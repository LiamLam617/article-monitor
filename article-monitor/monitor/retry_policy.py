"""
Retry policy primitives shared across modules.

This module is intentionally small: it centralizes the meaning of
\"retryable result error_code\" used by result-based retry loops
(e.g. `crawl_urls_for_results`).

Non-retryable examples (by design):
- invalid_url
- platform_not_allowed
"""

from __future__ import annotations


# Result-style error codes eligible for retry passes.
# Keep this list small and conservative: only transient / potentially recoverable failures.
RESULT_RETRYABLE_ERROR_CODES = frozenset(
    {
        "crawl_timeout",
        "crawl_failed",
        "parse_failed",
    }
)

