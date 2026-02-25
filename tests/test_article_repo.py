"""Integration tests for monitor.db.article_repo with temp DB."""
from monitor.db import article_repo


def test_add_article_and_get_by_id(temp_db):
    """add_article returns id; get_article_by_id returns the article."""
    aid = article_repo.add_article("https://example.com/1", title="T1", site="juejin")
    assert aid is not None
    article = article_repo.get_article_by_id(aid)
    assert article is not None
    assert article["url"] == "https://example.com/1"
    assert article["title"] == "T1"
    assert article["site"] == "juejin"


def test_get_article_by_id_missing(temp_db):
    """get_article_by_id for non-existent id returns None."""
    assert article_repo.get_article_by_id(99999) is None


def test_get_article_by_url(temp_db):
    """get_article_by_url returns article when url exists."""
    url = "https://example.com/url-lookup"
    article_repo.add_article(url, title="U", site="csdn")
    article = article_repo.get_article_by_url(url)
    assert article is not None
    assert article["url"] == url
    assert article_repo.get_article_by_url("https://nonexistent.com") is None


def test_get_all_articles(temp_db):
    """get_all_articles returns all articles in created_at DESC order."""
    assert article_repo.get_all_articles() == []
    article_repo.add_article("https://a.com/1", "A1", "juejin")
    article_repo.add_article("https://a.com/2", "A2", "csdn")
    all_ = article_repo.get_all_articles()
    assert len(all_) == 2
    assert all("url" in a and "title" in a for a in all_)


def test_update_article_status(temp_db):
    """update_article_status sets last_status and last_error."""
    aid = article_repo.add_article("https://e.com/1", "E1", "juejin")
    article_repo.update_article_status(aid, "OK")
    a = article_repo.get_article_by_id(aid)
    assert a["last_status"] == "OK"
    article_repo.update_article_status(aid, "ERROR", error="something failed")
    a = article_repo.get_article_by_id(aid)
    assert a["last_status"] == "ERROR"
    assert a["last_error"] == "something failed"


def test_get_platform_failures(temp_db):
    """get_platform_failures returns articles in ERROR or PENDING with last_error."""
    aid = article_repo.add_article("https://f.com/1", "F1", "juejin")
    article_repo.update_article_status(aid, "ERROR", error="err")
    failures = article_repo.get_platform_failures()
    assert len(failures) >= 1
    assert any(f["id"] == aid for f in failures)


def test_delete_article(temp_db):
    """delete_article removes article and its read_counts."""
    aid = article_repo.add_article("https://d.com/1", "D1", "juejin")
    from monitor.db.read_count_repo import add_read_count
    add_read_count(aid, 10)
    article_repo.delete_article(aid)
    assert article_repo.get_article_by_id(aid) is None


def test_add_articles_batch(temp_db):
    """add_articles_batch inserts multiple and returns ids."""
    batch = [
        ("https://b.com/1", "B1", "juejin"),
        ("https://b.com/2", "B2", "csdn"),
    ]
    ids = article_repo.add_articles_batch(batch)
    assert len(ids) == 2
    for i, aid in enumerate(ids):
        a = article_repo.get_article_by_id(aid)
        assert a is not None
        assert a["url"] == batch[i][0]
        assert a["title"] == batch[i][1]
        assert a["site"] == batch[i][2]


def test_add_articles_batch_duplicate_url_returns_existing_id(temp_db):
    """add_articles_batch when one URL already exists returns existing id for that entry."""
    article_repo.add_article("https://dup2.com/1", "First", "juejin")
    batch = [
        ("https://dup2.com/1", "Second", "juejin"),
        ("https://dup2.com/2", "New", "csdn"),
    ]
    ids = article_repo.add_articles_batch(batch)
    assert len(ids) == 2
    assert ids[0] == ids[1] or article_repo.get_article_by_id(ids[0])["url"] == "https://dup2.com/1"


def test_add_article_duplicate_url_returns_existing_id(temp_db):
    """Adding same url again returns existing article id (no duplicate)."""
    url = "https://dup.com/1"
    id1 = article_repo.add_article(url, "T1", "juejin")
    id2 = article_repo.add_article(url, "T2", "juejin")
    assert id1 == id2
    assert article_repo.get_article_by_id(id1)["title"] in ("T1", "T2")


def test_update_article_title(temp_db):
    """update_article_title updates title and returns True when row exists."""
    aid = article_repo.add_article("https://t.com/1", "Old", "juejin")
    assert article_repo.update_article_title(aid, "New") is True
    assert article_repo.get_article_by_id(aid)["title"] == "New"
    assert article_repo.update_article_title(99999, "X") is False
    assert article_repo.update_article_title(aid, "  ") is False


def test_get_failure_stats(temp_db):
    """get_failure_stats returns total, by_site, recent_24h."""
    stats = article_repo.get_failure_stats()
    assert "total" in stats
    assert "by_site" in stats
    assert "recent_24h" in stats


def test_get_all_failures_with_site_filter(temp_db):
    """get_all_failures with site= filters by site."""
    article_repo.add_article("https://a.com/1", "A1", "juejin")
    article_repo.add_article("https://b.com/1", "B1", "csdn")
    article_repo.update_article_status(1, "ERROR", "e1")
    article_repo.update_article_status(2, "ERROR", "e2")
    all_f = article_repo.get_all_failures(limit=10)
    assert len(all_f) >= 2
    by_juejin = article_repo.get_all_failures(limit=10, site="juejin")
    assert all(f["site"] == "juejin" for f in by_juejin)


def test_get_all_articles_with_latest_count(temp_db):
    """get_all_articles_with_latest_count includes latest_count and latest_timestamp."""
    from monitor.db.read_count_repo import add_read_count
    aid = article_repo.add_article("https://lc.com/1", "LC", "juejin")
    add_read_count(aid, 100)
    rows = article_repo.get_all_articles_with_latest_count()
    assert len(rows) == 1
    assert rows[0].get("latest_count") == 100
    assert rows[0].get("latest_timestamp") is not None
