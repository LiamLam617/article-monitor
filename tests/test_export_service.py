import csv
from io import StringIO

from monitor import export_service


def _decode_csv(content: bytes):
    text = content.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(text)))
    if rows and rows[0]:
        rows[0][0] = rows[0][0].lstrip("\ufeff")
    return rows


def test_export_selected_articles_csv(monkeypatch):
    def fake_get_all_articles():
        return [
            {"id": 1, "title": "A1", "site": "juejin", "url": "https://a1"},
            {"id": 2, "title": "A2", "site": "csdn", "url": "https://a2"},
        ]

    def fake_get_read_counts(article_id, start_date=None, end_date=None):
        return [
            {"count": 10, "timestamp": "2024-01-01 00:00:00"},
            {"count": 20, "timestamp": "2024-01-02 00:00:00"},
        ]

    monkeypatch.setattr(export_service, "get_all_articles", fake_get_all_articles)
    monkeypatch.setattr(export_service, "get_read_counts", fake_get_read_counts)

    content, filename = export_service.export_selected_articles_csv([1], "2024-01-01", "2024-01-31")

    assert filename.startswith("article_data_")
    rows = _decode_csv(content)
    # header + 2 條紀錄
    assert rows[0] == ["文章标题", "网站", "URL", "阅读数", "记录时间"]
    assert len(rows) == 3


def test_export_all_articles_csv(monkeypatch):
    def fake_get_all_articles():
        return [
            {"id": 1, "title": "A1", "site": "juejin", "url": "https://a1"},
            {"id": 2, "title": "A2", "site": "csdn", "url": "https://a2"},
        ]

    def fake_get_read_counts(article_id, start_date=None, end_date=None):
        return [
            {"count": article_id * 10, "timestamp": "2024-01-01 00:00:00"},
        ]

    monkeypatch.setattr(export_service, "get_all_articles", fake_get_all_articles)
    monkeypatch.setattr(export_service, "get_read_counts", fake_get_read_counts)

    content, filename = export_service.export_all_articles_csv(None, None)

    assert filename.startswith("all_articles_")
    rows = _decode_csv(content)
    # header + 2 條紀錄
    assert rows[0] == ["文章标题", "网站", "URL", "阅读数", "记录时间"]
    assert len(rows) == 3

