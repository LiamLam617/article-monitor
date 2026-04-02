"""Unit tests for monitor.logging_config."""
import json
import logging

from monitor.logging_config import setup_logging, JsonFormatter, TextWithExtrasFormatter, RedactionFilter


def _reset_root_logger():
    root = logging.getLogger()
    listener = getattr(root, "_article_monitor_queue_listener", None)
    if listener is not None:
        try:
            listener.stop()
        except Exception:
            pass
        setattr(root, "_article_monitor_queue_listener", None)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def test_setup_logging_uses_env_log_level(monkeypatch):
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_TO_FILE", "0")
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")

    _reset_root_logger()
    setup_logging(force=True)

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)


def test_setup_logging_writes_file_when_enabled(monkeypatch, tmp_path):
    log_file = tmp_path / "article-monitor.log"
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_LEVEL", "INFO")
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_TO_FILE", "1")
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_FILE", str(log_file))
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")

    _reset_root_logger()
    setup_logging(force=True)

    logger = logging.getLogger("monitor.logging-test")
    logger.info("hello logging file")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello logging file" in content


def test_setup_logging_writes_file_when_legacy_debug_log_path_set(monkeypatch, tmp_path):
    log_file = tmp_path / "legacy-debug.log"
    monkeypatch.delenv("ARTICLE_MONITOR_LOG_TO_FILE", raising=False)
    monkeypatch.delenv("ARTICLE_MONITOR_LOG_FILE", raising=False)
    monkeypatch.setenv("ARTICLE_MONITOR_DEBUG_LOG", str(log_file))
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")

    _reset_root_logger()
    setup_logging(force=True)

    logger = logging.getLogger("monitor.logging-legacy")
    logger.info("legacy file enabled")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "legacy file enabled" in content


def test_setup_logging_is_idempotent_without_force(monkeypatch):
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_TO_FILE", "0")
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")
    _reset_root_logger()

    setup_logging(force=True)
    first_count = len(logging.getLogger().handlers)
    setup_logging()
    second_count = len(logging.getLogger().handlers)

    assert first_count == second_count


def test_json_formatter_outputs_structured_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="monitor.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="extract.match",
        args=(),
        exc_info=None,
    )
    record.event = "extract.match"
    record.platform = "juejin"
    record.crawl_id = "abc-123"

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "extract.match"
    assert payload["event"] == "extract.match"
    assert payload["platform"] == "juejin"
    assert payload["crawl_id"] == "abc-123"
    assert payload["schema_version"] == "1.0"


def test_text_formatter_appends_extra_fields():
    formatter = TextWithExtrasFormatter("%(levelname)s %(name)s %(message)s")
    record = logging.LogRecord(
        name="monitor.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="extract.match",
        args=(),
        exc_info=None,
    )
    record.event = "extract.match"
    record.platform = "juejin"

    line = formatter.format(record)
    assert "extract.match" in line
    assert "event=extract.match" in line
    assert "platform=juejin" in line


def test_redaction_filter_masks_sensitive_keys_and_query_params():
    filt = RedactionFilter()
    record = logging.LogRecord(
        name="monitor.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request to https://example.com/?token=abc123",
        args=(),
        exc_info=None,
    )
    record.authorization = "Bearer SECRET"
    assert filt.filter(record) is True
    assert "token=***REDACTED***" in record.msg
    assert record.authorization == "***REDACTED***"
