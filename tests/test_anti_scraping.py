"""Unit tests for monitor.anti_scraping (manager, profile, headers)."""
import pytest

from monitor.anti_scraping import (
    get_anti_scraping_manager,
    reset_anti_scraping_manager,
    AntiScrapingManager,
    BrowserProfile,
)


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset the global manager so each test gets a fresh one when calling get_anti_scraping_manager."""
    yield
    reset_anti_scraping_manager()


def test_get_anti_scraping_manager_returns_manager():
    """get_anti_scraping_manager returns an AntiScrapingManager instance."""
    manager = get_anti_scraping_manager()
    assert isinstance(manager, AntiScrapingManager)


def test_get_anti_scraping_manager_singleton():
    """get_anti_scraping_manager returns the same instance on second call."""
    a = get_anti_scraping_manager()
    b = get_anti_scraping_manager()
    assert a is b


def test_get_browser_profile_has_viewport_and_ua():
    """Manager get_browser_profile returns profile with viewport and user_agent."""
    manager = get_anti_scraping_manager()
    profile = manager.get_browser_profile()
    assert isinstance(profile, BrowserProfile)
    assert profile.viewport_width > 0
    assert profile.viewport_height > 0
    assert profile.user_agent
    assert "Mozilla" in profile.user_agent


def test_get_http_headers_returns_dict_with_user_agent():
    """Manager get_http_headers returns dict with User-Agent and expected keys."""
    manager = get_anti_scraping_manager()
    headers = manager.get_http_headers()
    assert isinstance(headers, dict)
    assert "User-Agent" in headers
    assert headers["User-Agent"]
    assert "Accept" in headers or "Accept-Language" in headers
