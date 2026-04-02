"""Unit tests for monitor.extractors (parse_read_count, get_browser_config, ensure_browser_config)."""
import types
import re
import pytest

import monitor.extractors as extractors_module
from monitor.extractors import parse_read_count, get_browser_config, ensure_browser_config
from monitor.logging_context import set_log_context, reset_log_context
from monitor.platform_rules import PLATFORM_EXTRACTORS


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1k", 1000),
        ("20k", 20000),
        ("1.5k", 1500),
        ("1,234", 1234),
        ("2.5m", 2500000),
        ("1w", 10000),
        ("10w", 100000),
        ("1000", 1000),
        (" 42 ", 42),
        ("1,234.5k", 1234500),
        ("", None),
        (None, None),
        ("abc", None),
        ("1.2.3", 1),  # regex matches "1.2", no suffix -> 1
    ],
)
def test_parse_read_count(text, expected):
    """parse_read_count handles k/m/w suffixes, commas, and invalid input."""
    assert parse_read_count(text) == expected


def test_get_browser_config_returns_config(monkeypatch):
    """get_browser_config returns a non-None BrowserConfig (no real browser)."""
    monkeypatch.setattr("monitor.extractors.ANTI_SCRAPING_ENABLED", False)
    config = get_browser_config()
    assert config is not None
    assert hasattr(config, "headless")
    assert config.headless is True


def test_ensure_browser_config_returns_config(monkeypatch):
    """ensure_browser_config returns a non-None config."""
    monkeypatch.setattr("monitor.extractors.ANTI_SCRAPING_ENABLED", False)
    config = ensure_browser_config()
    assert config is not None


def test_get_browser_config_with_anti_scraping_enabled(monkeypatch):
    """get_browser_config with ANTI_SCRAPING_ENABLED True uses manager profile and headers."""
    monkeypatch.setattr("monitor.extractors.ANTI_SCRAPING_ENABLED", True)
    from monitor.anti_scraping import BrowserProfile
    fake_profile = BrowserProfile(
        user_agent="Mozilla/5.0",
        accept_language="en",
        timezone_offset=0,
        viewport_width=800,
        viewport_height=600,
        platform="Win32",
        vendor="Google Inc.",
        referer=None,
    )
    class FakeManager:
        def get_browser_profile(self):
            return fake_profile
        def get_http_headers(self):
            return {"User-Agent": "Mozilla/5.0"}
    monkeypatch.setattr("monitor.extractors._get_anti_scraping_manager", lambda: FakeManager())
    config = get_browser_config()
    assert config is not None
    assert config.viewport_width == 800
    assert config.user_agent == "Mozilla/5.0"


def test_juejin_pattern_matches_views_count_from_meta_box():
    """Juejin rules should match views-count in author meta box."""
    html = """
    <div class="author-info-box">
      <div class="meta-box">
        <span class="views-count" data-v-61fb5e44="">47</span>
      </div>
    </div>
    """
    meta_box_pattern = PLATFORM_EXTRACTORS["juejin"]["patterns"][0]
    match = re.search(meta_box_pattern, html, re.IGNORECASE | re.DOTALL)
    assert match is not None
    assert match.group(1) == "47"


def test_juejin_pattern_matches_views_count_with_suffix():
    html = """
    <div class="author-info-box">
      <div class="meta-box">
        <span class="views-count">1.2k</span>
      </div>
    </div>
    """
    meta_box_pattern = PLATFORM_EXTRACTORS["juejin"]["patterns"][0]
    match = re.search(meta_box_pattern, html, re.IGNORECASE | re.DOTALL)
    assert match is not None
    assert match.group(1) == "1.2k"


def test_eet_china_pattern_matches_detail_view_num():
    html = '<span class="hidden-xs detail-view-num">154浏览</span>'
    pattern = PLATFORM_EXTRACTORS["eet_china"]["patterns"][0]
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    assert match is not None
    assert match.group(1) == "154"


@pytest.mark.asyncio
async def test_extract_with_config_full_logs_regex_match(caplog, monkeypatch):
    html = "READ:47"
    fake_result = types.SimpleNamespace(success=True, html=html, markdown="")

    async def fake_crawl(url, crawler, crawler_config):
        return fake_result

    monkeypatch.setattr(extractors_module, "_crawl_with_shared", fake_crawl)
    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)
    monkeypatch.setitem(
        extractors_module.PLATFORM_EXTRACTORS,
        "testregex",
        {
            "patterns": [r"READ:(\d+)"],
            "parse_method": "number",
            "js_extract": False,
        },
    )

    caplog.set_level("INFO", logger="monitor.extractors")
    token = set_log_context(crawl_id="trace-1", article_id=99, url="https://example.com/post/1", platform="testregex")
    try:
        count, _ = await extractors_module.extract_with_config_full(
            "https://example.com/post/1",
            "testregex",
            crawler=object(),
        )
    finally:
        reset_log_context(token)

    assert count == 47
    assert any(getattr(r, "event", "") == "extract.match" and getattr(r, "match_source", "") == "html" for r in caplog.records)
    assert any(getattr(r, "event", "") == "extract.parse_result" and getattr(r, "status", "") == "success" for r in caplog.records)
    assert any(
        getattr(r, "event", "") == "extract.parse_result"
        and getattr(r, "parsed_count", None) == 47
        and isinstance(getattr(r, "parsed_count", None), int)
        for r in caplog.records
    )
    assert any(
        getattr(r, "event", "") == "extract.start"
        and getattr(r, "crawl_id", "") == "trace-1"
        and getattr(r, "article_id", "") == 99
        and getattr(r, "platform", "") == "testregex"
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_extract_with_config_full_logs_parse_failure(caplog, monkeypatch):
    html = "VALUE:abc"
    fake_result = types.SimpleNamespace(success=True, html=html, markdown="")

    async def fake_crawl(url, crawler, crawler_config):
        return fake_result

    monkeypatch.setattr(extractors_module, "_crawl_with_shared", fake_crawl)
    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)
    monkeypatch.setitem(
        extractors_module.PLATFORM_EXTRACTORS,
        "testlog",
        {
            "patterns": [r"VALUE:([a-z]+)"],
            "parse_method": "number",
        },
    )

    caplog.set_level("INFO", logger="monitor.extractors")
    count, _ = await extractors_module.extract_with_config_full(
        "https://example.com/a",
        "testlog",
        crawler=object(),
    )

    assert count is None
    assert any(getattr(r, "event", "") == "extract.match" for r in caplog.records)
    assert any(getattr(r, "event", "") == "extract.parse_result" and getattr(r, "status", "") == "failed" for r in caplog.records)


@pytest.mark.asyncio
async def test_extract_with_config_full_extracts_juejin_from_meta_box_only(monkeypatch):
    html = """
    <div class="author-info-box">
      <div class="meta-box">
        <span class="views-count" data-v-61fb5e44="" data-cursor-element-id="cursor-el-1">49</span>
      </div>
    </div>
    """
    fake_result = types.SimpleNamespace(success=True, html=html, markdown="")

    async def fake_crawl(url, crawler, crawler_config):
        return fake_result

    monkeypatch.setattr(extractors_module, "_crawl_with_shared", fake_crawl)
    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)

    count, _ = await extractors_module.extract_with_config_full(
        "https://juejin.cn/post/1",
        "juejin",
        crawler=object(),
    )

    assert count == 49


@pytest.mark.asyncio
async def test_extract_with_config_full_blocked_then_tor_retry_uses_proxy_config(monkeypatch):
    # First attempt returns a captcha/blocked page; second attempt (Tor) succeeds.
    blocked_html = "<html><body>访问验证</body></html>"
    ok_html = """
    <div class="author-info-box">
      <div class="meta-box">
        <span class="views-count">49</span>
      </div>
    </div>
    """

    class FakeResult:
        def __init__(self, html: str):
            self.success = True
            self.html = html
            self.markdown = ""

    calls = []

    async def fake_arun(url, config):
        # Record whether proxy_config is set
        calls.append(getattr(config, "proxy_config", None))
        if len(calls) == 1:
            return FakeResult(blocked_html)
        return FakeResult(ok_html)

    class FakeCrawler:
        arun = staticmethod(fake_arun)

    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)
    monkeypatch.setattr(extractors_module, "TOR_ENABLED", True)
    monkeypatch.setattr(extractors_module, "TOR_SOCKS5_URL", "socks5://127.0.0.1:9050")
    monkeypatch.setattr(extractors_module, "TOR_ON_BLOCKED_ONLY", True)
    monkeypatch.setattr(extractors_module, "TOR_BLOCKED_RETRY_MAX", 1)

    count, _ = await extractors_module.extract_with_config_full(
        "https://juejin.cn/post/1",
        "juejin",
        crawler=FakeCrawler(),
    )

    assert count == 49
    assert calls[0] is None
    proxy_cfg = calls[1]
    # crawl4ai may normalize proxy_config into a ProxyConfig object
    if isinstance(proxy_cfg, str):
        assert proxy_cfg == "socks5://127.0.0.1:9050"
    else:
        assert getattr(proxy_cfg, "server", None) == "socks5://127.0.0.1:9050"


@pytest.mark.asyncio
async def test_extract_with_config_full_extracts_eet_china_view_count(monkeypatch):
    html = '<span class="hidden-xs detail-view-num">154浏览</span>'
    fake_result = types.SimpleNamespace(success=True, html=html, markdown="")

    async def fake_crawl(url, crawler, crawler_config):
        return fake_result

    monkeypatch.setattr(extractors_module, "_crawl_with_shared", fake_crawl)
    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)

    count, _ = await extractors_module.extract_with_config_full(
        "https://www.eet-china.com/mp/a480306.html",
        "eet_china",
        crawler=object(),
    )

    assert count == 154


def test_eet_china_pattern_does_not_match_unrelated_browse_text():
    html = '<div class="sidebar"><span>999浏览</span></div>'
    pattern = PLATFORM_EXTRACTORS["eet_china"]["patterns"][0]
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    assert match is None


@pytest.mark.asyncio
async def test_extract_article_info_routes_eet_china_before_china_domain(monkeypatch):
    html = '<span class="hidden-xs detail-view-num">154浏览</span>'
    fake_result = types.SimpleNamespace(success=True, html=html, markdown="")

    async def fake_crawl(url, crawler, crawler_config):
        return fake_result

    monkeypatch.setattr(extractors_module, "_crawl_with_shared", fake_crawl)
    monkeypatch.setattr(extractors_module, "ANTI_SCRAPING_ENABLED", False)

    result = await extractors_module.extract_article_info(
        "https://www.eet-china.com/mp/a480306.html",
        crawler=object(),
    )

    assert result["read_count"] == 154
