"""Integration tests for monitor.db.connection with temp DB."""

from monitor.db.connection import get_db, init_db


def test_init_db_creates_tables_and_settings(temp_db):
    """With temp_db, init_db() creates articles, read_counts, settings and default row."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "articles" in tables
    assert "read_counts" in tables
    assert "settings" in tables

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", ("crawl_interval_hours",))
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] is not None


def test_get_db_returns_connection_with_wal(temp_db):
    """get_db() applies optimizations; journal_mode is WAL."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0].upper()
    conn.close()
    assert mode == "WAL"


def test_init_db_idempotent(temp_db):
    """Calling init_db() again does not fail."""
    init_db()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM articles")
    conn.close()
