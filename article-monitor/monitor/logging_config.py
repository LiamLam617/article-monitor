"""Application logging configuration."""
import atexit
import json
import logging
import os
import queue
import re
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from .logging_context import get_log_context

_STANDARD_LOG_RECORD_FIELDS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "thread",
    "threadName", "taskName",
}

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|authorization|cookie|api[_-]?key|set-cookie)",
    re.IGNORECASE,
)
_URL_SENSITIVE_QUERY_PATTERN = re.compile(
    r"([?&])(token|key|secret|code|password|auth)=([^&\s]+)",
    re.IGNORECASE,
)
_CONTROL_CHAR_PATTERN = re.compile(r"[\r\n\t\x00]")
_MANAGED_HANDLER_ATTR = "_article_monitor_handler"
_QUEUE_LISTENER_ATTR = "_article_monitor_queue_listener"
_QUEUE_ATTR = "_article_monitor_log_queue"
_QUEUE_MAXSIZE_ATTR = "_article_monitor_log_queue_maxsize"
_SCHEMA_VERSION = "1.0"

_dropped_events = 0
_redaction_error_count = 0

def _is_truthy(value: str) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _parse_log_level(raw_level: str) -> int:
    level_name = (raw_level or "INFO").strip().upper()
    return getattr(logging, level_name, logging.INFO)


class JsonFormatter(logging.Formatter):
    """Single-line JSON formatter for machine-parsable logs."""

    def format(self, record: logging.LogRecord) -> str:
        context = get_log_context()
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "schema_version": _SCHEMA_VERSION,
        }
        payload.update(context)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextWithExtrasFormatter(logging.Formatter):
    """Text formatter that appends custom LogRecord extras as key=value."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = []
        context = get_log_context()
        if context:
            for key, value in sorted(context.items()):
                extras.append(f"{key}={_safe_text_value(value)}")
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS:
                extras.append(f"{key}={_safe_text_value(value)}")
        if extras:
            return f"{base} | {' '.join(extras)}"
        return base


class RedactionFilter(logging.Filter):
    """Redact sensitive values and sanitize control chars."""

    def filter(self, record: logging.LogRecord) -> bool:
        global _redaction_error_count
        try:
            if isinstance(record.msg, str):
                record.msg = _sanitize_and_redact_text(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(_sanitize_value(arg) for arg in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: _sanitize_value(v) for k, v in record.args.items()}

            for key, value in list(record.__dict__.items()):
                if key in _STANDARD_LOG_RECORD_FIELDS:
                    continue
                if _SENSITIVE_KEY_PATTERN.search(key):
                    record.__dict__[key] = "***REDACTED***"
                else:
                    record.__dict__[key] = _sanitize_value(value)
            return True
        except Exception:
            _redaction_error_count += 1
            # fail-safe: never output the original payload on redaction error
            record.msg = "[redaction_error] log payload sanitized"
            record.args = ()
            safe = {}
            for key in list(record.__dict__.keys()):
                if key in _STANDARD_LOG_RECORD_FIELDS:
                    continue
                safe[key] = "***REDACTED***"
            record.__dict__.update(safe)
            record.redaction_error = True
            return True


class ContextFilter(logging.Filter):
    """Inject correlation context fields into LogRecord attributes."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            context = get_log_context()
            for key, value in context.items():
                if key not in record.__dict__:
                    record.__dict__[key] = value
        except Exception:
            # Never block logs if context injection fails.
            record.context_injection_error = True
        return True


class NonBlockingQueueHandler(QueueHandler):
    """QueueHandler that drops log records when queue is full."""

    def enqueue(self, record: logging.LogRecord) -> None:
        global _dropped_events
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            _dropped_events += 1


def _create_formatter(log_format: str) -> logging.Formatter:
    if log_format == "json":
        return JsonFormatter()
    return TextWithExtrasFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )


def _safe_text_value(value: Any) -> str:
    return _sanitize_and_redact_text(str(value))


def _sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    return _sanitize_and_redact_text(str(value))


def _sanitize_and_redact_text(text: str) -> str:
    value = _URL_SENSITIVE_QUERY_PATTERN.sub(r"\1\2=***REDACTED***", text)
    value = _CONTROL_CHAR_PATTERN.sub(" ", value)
    return value


def _cleanup_managed_handlers(root_logger: logging.Logger) -> None:
    for handler in list(root_logger.handlers):
        if getattr(handler, _MANAGED_HANDLER_ATTR, False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def _stop_queue_listener_if_running(root_logger: logging.Logger) -> None:
    listener = getattr(root_logger, _QUEUE_LISTENER_ATTR, None)
    if listener is not None:
        try:
            listener.stop()
        except Exception:
            pass
        setattr(root_logger, _QUEUE_LISTENER_ATTR, None)

    if hasattr(root_logger, _QUEUE_ATTR):
        setattr(root_logger, _QUEUE_ATTR, None)
    if hasattr(root_logger, _QUEUE_MAXSIZE_ATTR):
        setattr(root_logger, _QUEUE_MAXSIZE_ATTR, None)


def get_logging_stats() -> Dict[str, Any]:
    """Return lightweight logging health stats for monitoring."""
    root = logging.getLogger()
    q = getattr(root, _QUEUE_ATTR, None)
    maxsize = getattr(root, _QUEUE_MAXSIZE_ATTR, None)
    queue_depth: Optional[int] = None
    if q is not None:
        try:
            queue_depth = q.qsize()
        except Exception:
            queue_depth = None
    return {
        "schema_version": _SCHEMA_VERSION,
        "queue_depth": queue_depth,
        "queue_maxsize": maxsize,
        "dropped_events": _dropped_events,
        "redaction_error_count": _redaction_error_count,
    }


def setup_logging(force: bool = False) -> logging.Logger:
    """Configure root logger for the application."""
    root_logger = logging.getLogger()
    has_managed = any(getattr(h, _MANAGED_HANDLER_ATTR, False) for h in root_logger.handlers)
    if has_managed and not force:
        return root_logger

    _stop_queue_listener_if_running(root_logger)
    if force:
        _cleanup_managed_handlers(root_logger)
    elif has_managed:
        return root_logger

    log_level = _parse_log_level(os.getenv("ARTICLE_MONITOR_LOG_LEVEL", "INFO"))
    root_logger.setLevel(log_level)
    root_logger.propagate = False

    console_format = (os.getenv("ARTICLE_MONITOR_LOG_FORMAT_CONSOLE", "text") or "text").strip().lower()
    file_format = (os.getenv("ARTICLE_MONITOR_LOG_FORMAT_FILE", "json") or "json").strip().lower()
    if console_format not in ("text", "json"):
        console_format = "text"
    if file_format not in ("text", "json"):
        file_format = "json"

    legacy_debug_log_path = (os.getenv("ARTICLE_MONITOR_DEBUG_LOG") or "").strip()
    log_to_file = _is_truthy(os.getenv("ARTICLE_MONITOR_LOG_TO_FILE", "0")) or bool(legacy_debug_log_path)

    context_filter = ContextFilter()
    redaction_filter = RedactionFilter()
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(_create_formatter(console_format))
    stream_handler.addFilter(context_filter)
    stream_handler.addFilter(redaction_filter)
    setattr(stream_handler, _MANAGED_HANDLER_ATTR, True)

    downstream_handlers = [stream_handler]
    if log_to_file:
        file_path = os.getenv("ARTICLE_MONITOR_LOG_FILE", "").strip() or legacy_debug_log_path
        if not file_path:
            project_root = Path(__file__).resolve().parents[1]
            file_path = str(project_root / "logs" / "article-monitor.log")
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        max_bytes = max(1024, int(os.getenv("ARTICLE_MONITOR_LOG_MAX_BYTES", str(50 * 1024 * 1024))))
        backup_count = max(1, int(os.getenv("ARTICLE_MONITOR_LOG_BACKUP_COUNT", "10")))
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(_create_formatter(file_format))
        file_handler.addFilter(context_filter)
        file_handler.addFilter(redaction_filter)
        setattr(file_handler, _MANAGED_HANDLER_ATTR, True)
        downstream_handlers.append(file_handler)

    queue_handler: logging.Handler
    queue_enabled = _is_truthy(os.getenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "1"))
    if queue_enabled:
        maxsize = max(100, int(os.getenv("ARTICLE_MONITOR_LOG_QUEUE_MAXSIZE", "10000")))
        log_queue: queue.Queue = queue.Queue(maxsize=maxsize)
        queue_handler = NonBlockingQueueHandler(log_queue)
        queue_handler.setLevel(log_level)
        queue_handler.addFilter(context_filter)
        setattr(queue_handler, _MANAGED_HANDLER_ATTR, True)
        listener = QueueListener(log_queue, *downstream_handlers, respect_handler_level=True)
        listener.start()
        setattr(root_logger, _QUEUE_LISTENER_ATTR, listener)
        setattr(root_logger, _QUEUE_ATTR, log_queue)
        setattr(root_logger, _QUEUE_MAXSIZE_ATTR, maxsize)
        atexit.register(_stop_queue_listener_if_running, root_logger)
        root_logger.addHandler(queue_handler)
        return root_logger

    # Queue disabled: attach downstream handlers directly (synchronous emit).
    for handler in downstream_handlers:
        root_logger.addHandler(handler)

    return root_logger
