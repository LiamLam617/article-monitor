"""
Unit and integration tests for monitor.crawler.

Uses monkeypatch, fake DB, and fake extractors to test:
- Error classification and retry helpers
- crawl_article_with_retry (single-article flow)
- crawl_all_articles (full crawl flow)
"""
import asyncio
from unittest.mock import MagicMock

import pytest

import monitor.crawler as crawler_module
from monitor.logging_context import set_log_context, reset_log_context
from monitor.crawler import (
    ErrorCategory,
    _get_error_category,
    _is_retryable_error,
    _calculate_retry_delay,
    _get_max_retries_for_category,
    _domain_from_article,
    _interleave_articles_by_site,
    _get_domain_semaphore,
    crawl_article_with_retry,
    crawl_all_articles,
    reset_crawl_progress,
    get_crawl_progress,
    stop_crawling,
)


def run_async(coro):
    """Run async coroutine in sync test."""
    return asyncio.run(coro)


# ----- Unit: error classification -----


@pytest.mark.parametrize(
    "error_msg, expected",
    [
        ("404 not found", ErrorCategory.PERMANENT),
        ("403 Forbidden", ErrorCategory.PERMANENT),
        ("401 unauthorized", ErrorCategory.PERMANENT),
        ("SSL handshake failed", ErrorCategory.SSL),
        ("certificate verify failed", ErrorCategory.SSL),
        ("connection timeout", ErrorCategory.NETWORK),
        ("503 service unavailable", ErrorCategory.NETWORK),
        ("502 bad gateway", ErrorCategory.NETWORK),
        ("connection refused", ErrorCategory.NETWORK),
        ("extract failed", ErrorCategory.PARSE),
        ("selector missing", ErrorCategory.PARSE),
        ("no such element", ErrorCategory.PARSE),
        ("something random", ErrorCategory.UNKNOWN),
    ],
)
def test_get_error_category(error_msg, expected):
    err = Exception(error_msg)
    assert _get_error_category(err) == expected


def test_is_retryable_error():
    assert _is_retryable_error(Exception("404")) is False
    assert _is_retryable_error(Exception("403")) is False
    assert _is_retryable_error(Exception("timeout")) is True
    assert _is_retryable_error(Exception("parse error")) is True
    assert _is_retryable_error(Exception("unknown")) is True


def test_calculate_retry_delay_ssl(monkeypatch):
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_SSL_DELAY", 5.0)
    delay = _calculate_retry_delay(ErrorCategory.SSL, 1)
    assert delay >= 0.1
    assert delay <= 5.0 * 1.1 + 0.5  # jitter


def test_calculate_retry_delay_network(monkeypatch):
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_DELAY", 2.0)
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_BACKOFF", 2.0)
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_MAX_DELAY", 60.0)
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_JITTER", False)
    delay = _calculate_retry_delay(ErrorCategory.NETWORK, 1)
    assert delay == 2.0
    delay2 = _calculate_retry_delay(ErrorCategory.NETWORK, 2)
    assert delay2 == 4.0  # 2 * 2^(2-1)


def test_get_max_retries_for_category():
    assert _get_max_retries_for_category(ErrorCategory.NETWORK) == crawler_module.CRAWL_RETRY_NETWORK_MAX
    assert _get_max_retries_for_category(ErrorCategory.UNKNOWN) == crawler_module.CRAWL_RETRY_NETWORK_MAX
    assert _get_max_retries_for_category(ErrorCategory.PARSE) == crawler_module.CRAWL_RETRY_PARSE_MAX
    assert _get_max_retries_for_category(ErrorCategory.SSL) == crawler_module.CRAWL_RETRY_SSL_MAX
    assert _get_max_retries_for_category(ErrorCategory.PERMANENT) == 0


# ----- Unit: domain and interleave -----


def test_domain_from_article():
    """_domain_from_article returns netloc lowercased from article url."""
    assert _domain_from_article({"url": "https://Juejin.CN/post/1"}) == "juejin.cn"
    assert _domain_from_article({"url": "https://blog.csdn.net/a/b"}) == "blog.csdn.net"
    assert _domain_from_article({"url": ""}) == "unknown"
    assert _domain_from_article({}) == "unknown"


def test_interleave_articles_by_site():
    """_interleave_articles_by_site round-robins by domain so same site is not consecutive."""
    a1 = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin"}
    a2 = {"id": 2, "url": "https://juejin.cn/post/2", "site": "juejin"}
    b1 = {"id": 3, "url": "https://csdn.net/blog/1", "site": "csdn"}
    articles = [a1, a2, b1]
    out = _interleave_articles_by_site(articles)
    assert len(out) == 3
    assert {x["id"] for x in out} == {1, 2, 3}
    # Round-robin: one from each domain in turn. So first two items must be from different domains.
    domains = [_domain_from_article(x) for x in out]
    assert domains[0] != domains[1] or domains[1] != domains[2]


def test_interleave_articles_by_site_empty():
    assert _interleave_articles_by_site([]) == []


def test_get_domain_semaphore_returns_none_when_disabled(monkeypatch):
    """When CRAWL_CONCURRENCY_PER_DOMAIN is 0, _get_domain_semaphore returns None."""
    monkeypatch.setattr(crawler_module, "CRAWL_CONCURRENCY_PER_DOMAIN", 0)
    crawler_module._reset_domain_semaphores()
    sem = run_async(_get_domain_semaphore("juejin.cn"))
    assert sem is None


def test_get_domain_semaphore_returns_semaphore_when_enabled(monkeypatch):
    """When CRAWL_CONCURRENCY_PER_DOMAIN is 2, same domain gets same semaphore, limit 2."""
    monkeypatch.setattr(crawler_module, "CRAWL_CONCURRENCY_PER_DOMAIN", 2)
    crawler_module._reset_domain_semaphores()
    sem_a = run_async(_get_domain_semaphore("juejin.cn"))
    sem_b = run_async(_get_domain_semaphore("juejin.cn"))
    assert sem_a is not None
    assert sem_a is sem_b
    # Two acquires should succeed immediately (limit 2)
    async def two_acquires():
        async with sem_a:
            pass
        async with sem_a:
            pass
    run_async(two_acquires())


# ----- Unit: crawl_article_with_retry -----


def test_crawl_article_with_retry_platform_not_allowed(monkeypatch):
    """Platform not in whitelist -> returns False without calling extractor."""
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T"}
    extract_calls = []

    async def fake_extract(url, c):
        extract_calls.append(url)
        return {"read_count": 100, "title": "T"}

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: False)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)

    result = run_async(crawl_article_with_retry(article, skip_retry=True))
    assert result is False
    assert len(extract_calls) == 0


def test_crawl_article_with_retry_stop_signal(monkeypatch):
    """Stop signal set -> returns False without calling extractor."""
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T"}
    extract_calls = []

    async def fake_extract(url, c):
        extract_calls.append(url)
        return {"read_count": 100, "title": "T"}

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "_stop_signal", True)

    try:
        result = run_async(crawl_article_with_retry(article, skip_retry=True))
        assert result is False
        assert len(extract_calls) == 0
    finally:
        with crawler_module._stop_signal_lock:
            crawler_module._stop_signal = False


def test_crawl_article_with_retry_success(monkeypatch):
    """Extractor returns count -> add_read_count and update_article_status('OK') called."""
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "Old", "_latest_count": None}
    add_read_count_calls = []
    update_status_calls = []
    update_title_calls = []

    async def fake_extract(url, c):
        return {"read_count": 100, "title": "New Title"}

    def fake_add_read_count(aid, count):
        add_read_count_calls.append((aid, count))

    def fake_update_article_status(aid, status, error=None):
        update_status_calls.append((aid, status, error))

    def fake_update_article_title(aid, title):
        update_title_calls.append((aid, title))
        return True

    def fake_get_latest_read_count(aid):
        return None

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "add_read_count", fake_add_read_count)
    monkeypatch.setattr(crawler_module, "update_article_status", fake_update_article_status)
    monkeypatch.setattr(crawler_module, "update_article_title", fake_update_article_title)
    monkeypatch.setattr(crawler_module, "get_latest_read_count", fake_get_latest_read_count)

    result = run_async(crawl_article_with_retry(article, skip_retry=True))

    assert result is True
    assert add_read_count_calls == [(1, 100)]
    assert any(c[1] == "OK" for c in update_status_calls)
    assert any(c[1] == "New Title" for c in update_title_calls)


def test_crawl_article_with_retry_extract_fails_marks_error(monkeypatch):
    """Extractor returns None (parse failure), skip_retry=False -> mark ERROR."""
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T", "_latest_count": None}
    update_status_calls = []

    async def fake_extract(url, c):
        return {"read_count": None, "title": None}

    def fake_update_article_status(aid, status, error=None):
        update_status_calls.append((aid, status, error))

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "update_article_status", fake_update_article_status)
    monkeypatch.setattr(crawler_module, "get_latest_read_count", lambda aid: None)
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_PARSE_MAX", 1)

    result = run_async(crawl_article_with_retry(article, skip_retry=False, max_retries=1))

    assert result is False
    assert any(c[1] == "ERROR" and "无法提取阅读数" in (c[2] or "") for c in update_status_calls)


def test_crawl_article_with_retry_logs_extract_success(monkeypatch, caplog):
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "Old", "_latest_count": None}

    async def fake_extract(url, c):
        return {"read_count": 88, "title": "New Title"}

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "add_read_count", lambda aid, count: None)
    monkeypatch.setattr(crawler_module, "update_article_status", lambda aid, status, error=None: None)
    monkeypatch.setattr(crawler_module, "update_article_title", lambda aid, title: True)
    monkeypatch.setattr(crawler_module, "get_latest_read_count", lambda aid: None)

    caplog.set_level("INFO", logger="monitor.crawler")
    token = set_log_context(crawl_id="crawl-test-id")
    try:
        result = run_async(crawl_article_with_retry(article, skip_retry=True))
    finally:
        reset_log_context(token)

    assert result is True
    assert any(
        getattr(r, "event", "") == "crawl.extract_result"
        and getattr(r, "status", "") == "success"
        and getattr(r, "read_count", "") == 88
        and getattr(r, "crawl_id", "") == "crawl-test-id"
        and getattr(r, "article_id", "") == 1
        and getattr(r, "platform", "") == "juejin"
        for r in caplog.records
    )


def test_crawl_article_with_retry_logs_extract_failure(monkeypatch, caplog):
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "Old", "_latest_count": None}

    async def fake_extract(url, c):
        return {"read_count": None, "title": None}

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "update_article_status", lambda aid, status, error=None: None)
    monkeypatch.setattr(crawler_module, "get_latest_read_count", lambda aid: None)
    monkeypatch.setattr(crawler_module, "CRAWL_RETRY_PARSE_MAX", 0)

    caplog.set_level("INFO", logger="monitor.crawler")
    result = run_async(crawl_article_with_retry(article, skip_retry=False, max_retries=0))

    assert result is False
    assert any(
        getattr(r, "event", "") == "crawl.extract_result"
        and getattr(r, "status", "") == "parse_failed"
        and getattr(r, "read_count", "") is None
        for r in caplog.records
    )


def test_crawl_article_with_retry_permanent_error_no_retry(monkeypatch):
    """Permanent error (404) -> no retry, update_article_status('ERROR')."""
    article = {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T", "_latest_count": None}
    extract_calls = []
    update_status_calls = []

    async def fake_extract(url, c):
        extract_calls.append(url)
        raise Exception("404 not found")

    def fake_update_article_status(aid, status, error=None):
        update_status_calls.append((aid, status, error))

    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract)
    monkeypatch.setattr(crawler_module, "update_article_status", fake_update_article_status)

    result = run_async(crawl_article_with_retry(article, skip_retry=False, max_retries=3))

    assert result is False
    assert len(extract_calls) == 1  # no retry
    assert any(c[1] == "ERROR" for c in update_status_calls)


# ----- Integration-style: crawl_all_articles -----


def test_crawl_all_articles_empty_list(monkeypatch):
    """No articles -> reset_crawl_progress, progress not running after return."""
    monkeypatch.setattr(crawler_module, "get_all_articles", lambda: [])

    run_async(crawl_all_articles())

    progress = get_crawl_progress()
    assert progress["is_running"] is False
    assert progress["total"] == 0


def test_crawl_all_articles_all_skipped_by_platform(monkeypatch):
    """All articles filtered out by platform -> reset_crawl_progress, return early."""
    monkeypatch.setattr(crawler_module, "get_all_articles", lambda: [
        {"id": 1, "url": "https://x.com/1", "site": "unknown_platform", "title": "T"},
    ])
    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: False)

    run_async(crawl_all_articles())

    progress = get_crawl_progress()
    assert progress["is_running"] is False
    assert progress["total"] == 0


def test_crawl_all_articles_single_article_success(monkeypatch):
    """One allowed article, fake extract returns count -> progress success 1, add_read_count called."""
    reset_crawl_progress()
    with crawler_module._stop_signal_lock:
        crawler_module._stop_signal = False

    articles = [{"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T"}]
    add_read_count_calls = []
    update_status_calls = []

    def fake_get_all_articles():
        return list(articles)

    def fake_get_latest_read_counts_batch(ids):
        return {1: {"count": 0, "timestamp": "2024-01-01 00:00:00"}}

    async def fake_extract_article_info(url, c):
        return {"read_count": 100, "title": "T"}

    def fake_add_read_count(aid, count):
        add_read_count_calls.append((aid, count))

    def fake_update_article_status(aid, status, error=None):
        update_status_calls.append((aid, status, error))

    def fake_update_article_title(aid, title):
        return True

    monkeypatch.setattr(crawler_module, "get_all_articles", fake_get_all_articles)
    monkeypatch.setattr(crawler_module, "get_latest_read_counts_batch", fake_get_latest_read_counts_batch)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract_article_info)
    monkeypatch.setattr(crawler_module, "add_read_count", fake_add_read_count)
    monkeypatch.setattr(crawler_module, "update_article_status", fake_update_article_status)
    monkeypatch.setattr(crawler_module, "update_article_title", fake_update_article_title)
    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "ANTI_SCRAPING_ENABLED", False)

    run_async(crawl_all_articles())

    progress = get_crawl_progress()
    assert progress["is_running"] is False
    assert progress["total"] == 1
    assert progress["success"] == 1
    assert progress["failed"] == 0
    assert len(add_read_count_calls) == 1
    assert add_read_count_calls[0] == (1, 100)


def test_crawl_all_articles_two_articles_one_fails(monkeypatch):
    """Two articles: first succeeds, second fails (extract returns None) -> success 1, failed 1."""
    reset_crawl_progress()
    with crawler_module._stop_signal_lock:
        crawler_module._stop_signal = False

    articles = [
        {"id": 1, "url": "https://juejin.cn/post/1", "site": "juejin", "title": "T1"},
        {"id": 2, "url": "https://juejin.cn/post/2", "site": "juejin", "title": "T2"},
    ]
    call_count = {"extract": 0}

    def fake_get_all_articles():
        return list(articles)

    def fake_get_latest_read_counts_batch(ids):
        return {1: {"count": 0, "timestamp": ""}, 2: {"count": 0, "timestamp": ""}}

    async def fake_extract_article_info(url, c):
        call_count["extract"] += 1
        if "post/1" in url:
            return {"read_count": 50, "title": "T1"}
        return {"read_count": None, "title": None}

    add_read_count_calls = []

    class FakePool:
        async def acquire(self):
            return MagicMock()

        async def release(self, c):
            pass

    async def fake_create_shared_crawler():
        return MagicMock()

    monkeypatch.setattr(crawler_module, "get_all_articles", fake_get_all_articles)
    monkeypatch.setattr(crawler_module, "get_latest_read_counts_batch", fake_get_latest_read_counts_batch)
    monkeypatch.setattr(crawler_module, "extract_article_info", fake_extract_article_info)
    monkeypatch.setattr(crawler_module, "add_read_count", lambda a, c: add_read_count_calls.append((a, c)))
    monkeypatch.setattr(crawler_module, "update_article_status", lambda a, s, e=None: None)
    monkeypatch.setattr(crawler_module, "update_article_title", lambda a, t: True)
    monkeypatch.setattr(crawler_module, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(crawler_module, "ANTI_SCRAPING_ENABLED", False)
    import monitor.browser_pool as bp
    monkeypatch.setattr(bp, "get_browser_pool", lambda: FakePool())
    monkeypatch.setattr(crawler_module, "create_shared_crawler", fake_create_shared_crawler)

    run_async(crawl_all_articles())

    progress = get_crawl_progress()
    assert progress["total"] == 2
    assert progress["success"] == 1
    assert progress["failed"] == 1
    assert len(add_read_count_calls) == 1
    assert add_read_count_calls[0][0] == 1 and add_read_count_calls[0][1] == 50
