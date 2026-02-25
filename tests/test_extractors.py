"""Unit tests for monitor.extractors (parse_read_count, get_browser_config, ensure_browser_config)."""
import pytest

from monitor.extractors import parse_read_count, get_browser_config, ensure_browser_config


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
