"""Integration tests for monitor.db.read_count_repo with temp DB."""
from monitor.db import article_repo
from monitor.db import read_count_repo


def test_add_read_count_and_get_read_counts(temp_db):
    """add_read_count then get_read_counts returns the record."""
    aid = article_repo.add_article("https://r.com/1", "R1", "juejin")
    read_count_repo.add_read_count(aid, 42)
    rows = read_count_repo.get_read_counts(aid)
    assert len(rows) == 1
    assert rows[0]["count"] == 42
    assert "timestamp" in rows[0]


def test_get_read_counts_with_dates(temp_db):
    """get_read_counts with start_date/end_date filters."""
    aid = article_repo.add_article("https://d.com/1", "D1", "juejin")
    read_count_repo.add_read_count(aid, 10)
    rows = read_count_repo.get_read_counts(aid, start_date="2020-01-01", end_date="2030-12-31")
    assert len(rows) >= 1
    rows_empty = read_count_repo.get_read_counts(aid, start_date="2010-01-01", end_date="2010-01-02")
    assert len(rows_empty) == 0


def test_get_latest_read_count(temp_db):
    """get_latest_read_count returns most recent record."""
    aid = article_repo.add_article("https://l.com/1", "L1", "juejin")
    assert read_count_repo.get_latest_read_count(aid) is None
    read_count_repo.add_read_count(aid, 1)
    read_count_repo.add_read_count(aid, 2)
    latest = read_count_repo.get_latest_read_count(aid)
    assert latest is not None
    assert latest["count"] == 2


def test_add_read_counts_batch(temp_db):
    """add_read_counts_batch inserts multiple records."""
    aid = article_repo.add_article("https://b.com/1", "B1", "juejin")
    records = [(aid, 10), (aid, 20)]
    read_count_repo.add_read_counts_batch(records)
    rows = read_count_repo.get_read_counts(aid, limit=10)
    assert len(rows) == 2
    counts = {r["count"] for r in rows}
    assert 10 in counts and 20 in counts


def test_add_read_counts_batch_empty(temp_db):
    """add_read_counts_batch with empty list does nothing."""
    read_count_repo.add_read_counts_batch([])
    # no exception


def test_get_latest_read_counts_batch(temp_db):
    """get_latest_read_counts_batch returns latest per article."""
    a1 = article_repo.add_article("https://lb.com/1", "LB1", "juejin")
    a2 = article_repo.add_article("https://lb.com/2", "LB2", "csdn")
    read_count_repo.add_read_count(a1, 100)
    read_count_repo.add_read_count(a1, 200)
    read_count_repo.add_read_count(a2, 50)
    result = read_count_repo.get_latest_read_counts_batch([a1, a2])
    assert result[a1]["count"] == 200
    assert result[a2]["count"] == 50


def test_get_latest_read_counts_batch_empty(temp_db):
    """get_latest_read_counts_batch with empty list returns {}."""
    assert read_count_repo.get_latest_read_counts_batch([]) == {}


def test_get_platform_health(temp_db):
    """get_platform_health returns per-site last_update and article_count."""
    a1 = article_repo.add_article("https://h.com/1", "H1", "juejin")
    article_repo.add_article("https://h.com/2", "H2", "juejin")
    read_count_repo.add_read_count(a1, 1)
    health = read_count_repo.get_platform_health()
    assert isinstance(health, list)
    sites = [h["site"] for h in health]
    assert "juejin" in sites


def test_get_aggregated_read_counts(temp_db):
    """get_aggregated_read_counts returns aggregated by date/site."""
    aid = article_repo.add_article("https://ag.com/1", "AG1", "juejin")
    read_count_repo.add_read_count(aid, 10)
    rows = read_count_repo.get_aggregated_read_counts(days=30)
    assert isinstance(rows, list)


def test_get_all_read_counts_summary(temp_db):
    """get_all_read_counts_summary returns summary by date."""
    aid = article_repo.add_article("https://s.com/1", "S1", "juejin")
    read_count_repo.add_read_count(aid, 5)
    rows = read_count_repo.get_all_read_counts_summary(days=7)
    assert isinstance(rows, list)


def test_get_read_counts_group_by_hour(temp_db):
    """get_read_counts with group_by_hour and start_date uses hourly aggregation."""
    aid = article_repo.add_article("https://g.com/1", "G1", "juejin")
    read_count_repo.add_read_count(aid, 1)
    rows = read_count_repo.get_read_counts(aid, group_by_hour=True, start_date="2020-01-01")
    assert isinstance(rows, list)


def test_delete_read_count_by_timestamp(temp_db):
    """delete_read_count_by_timestamp removes matching row."""
    aid = article_repo.add_article("https://del.com/1", "Del", "juejin")
    read_count_repo.add_read_count(aid, 1)
    rows = read_count_repo.get_read_counts(aid, limit=1)
    assert len(rows) == 1
    ts = rows[0]["timestamp"]
    n = read_count_repo.delete_read_count_by_timestamp(aid, ts)
    assert n == 1
    assert len(read_count_repo.get_read_counts(aid)) == 0


def test_clear_cache(temp_db):
    """clear_cache with before_date or days deletes old records."""
    aid = article_repo.add_article("https://c.com/1", "C1", "juejin")
    read_count_repo.add_read_count(aid, 1)
    n = read_count_repo.clear_cache(before_date="2010-01-01")
    assert n >= 0
    n2 = read_count_repo.clear_cache(days=9999)
    assert n2 >= 0
    assert read_count_repo.clear_cache() == 0
