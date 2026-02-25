"""Integration tests for monitor.db.settings_repo with temp DB."""
import pytest

from monitor.db.settings_repo import get_setting, set_setting


def test_get_setting_missing_returns_default(temp_db):
    """get_setting for a key that does not exist returns default."""
    assert get_setting("nonexistent_key", "default_value") == "default_value"
    assert get_setting("another_missing", None) is None


def test_set_setting_then_get(temp_db):
    """set_setting then get_setting returns the value."""
    set_setting("test_key", "test_value")
    assert get_setting("test_key") == "test_value"


def test_set_setting_overwrites(temp_db):
    """set_setting overwrites existing value (INSERT OR REPLACE)."""
    set_setting("overwrite_key", "first")
    assert get_setting("overwrite_key") == "first"
    set_setting("overwrite_key", "second")
    assert get_setting("overwrite_key") == "second"


def test_get_setting_crawl_interval_exists_after_init(temp_db):
    """After init_db, crawl_interval_hours exists (from conftest temp_db)."""
    value = get_setting("crawl_interval_hours")
    assert value is not None
