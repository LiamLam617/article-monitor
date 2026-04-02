"""Shared structured logging context for request/crawl traces."""
from contextvars import ContextVar, Token, copy_context
from typing import Any, Callable, Dict, Optional

_crawl_context_var: ContextVar[Dict[str, Any]] = ContextVar("crawl_context", default={})


def get_log_context() -> Dict[str, Any]:
    """Return a shallow copy of current logging context."""
    return dict(_crawl_context_var.get())


def set_log_context(**fields: Any) -> Token:
    """Set context fields for current execution scope and return token."""
    current = _crawl_context_var.get()
    merged = dict(current)
    for key, value in fields.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return _crawl_context_var.set(merged)


def reset_log_context(token: Token) -> None:
    """Restore context to previous state using token."""
    _crawl_context_var.reset(token)


def bind_context_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Merge explicit fields with contextual correlation fields.

    Note: Prefer calling this only in small logging helpers (not throughout business logic),
    so tests/caplog can still inspect LogRecord attributes without requiring logging setup.
    """
    merged = get_log_context()
    merged.update(fields)
    return merged


def run_with_current_log_context(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run callable in copied context (safe for new thread boundaries)."""
    ctx = copy_context()
    return ctx.run(func, *args, **kwargs)


def current_log_context_or_none() -> Optional[Dict[str, Any]]:
    """Return current context dict, or None when context is empty."""
    current = get_log_context()
    if not current:
        return None
    return current
