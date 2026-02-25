"""Unit tests for monitor.browser_pool (get_browser_pool, acquire, release)."""
import asyncio

import pytest

from monitor.browser_pool import get_browser_pool, BrowserPool


class FakeCrawler:
    """Fake AsyncWebCrawler that supports async context manager and passes _is_crawler_valid."""

    def __init__(self):
        self.browser = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def mock_create_crawler(monkeypatch):
    """Mock _create_crawler to return a FakeCrawler without starting a real browser."""

    async def fake_create_crawler(self):
        crawler = FakeCrawler()
        await crawler.__aenter__()
        return crawler

    monkeypatch.setattr(BrowserPool, "_create_crawler", fake_create_crawler)


def _run(coro):
    return asyncio.run(coro)


def test_get_browser_pool_singleton():
    """get_browser_pool returns the same instance."""
    a = get_browser_pool()
    b = get_browser_pool()
    assert a is b


def test_acquire_returns_crawler(mock_create_crawler):
    """acquire returns a crawler instance when pool can create one."""
    pool = get_browser_pool()
    crawler = _run(pool.acquire())
    assert crawler is not None
    assert isinstance(crawler, FakeCrawler)


def test_release_returns_crawler_to_pool(mock_create_crawler):
    """release puts crawler back so next acquire can reuse (if valid)."""
    pool = get_browser_pool()
    c1 = _run(pool.acquire())
    assert c1 is not None
    _run(pool.release(c1))
    c2 = _run(pool.acquire())
    assert c2 is not None
