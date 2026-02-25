"""Unit and integration tests for Bitable sync (sync_from_bitable)."""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

import monitor.bitable_sync as bitable_sync


def test_extract_url_from_field():
    assert bitable_sync._extract_url_from_field("https://a.com") == "https://a.com"
    assert bitable_sync._extract_url_from_field("  https://b.com  ") == "https://b.com"
    assert bitable_sync._extract_url_from_field("not-a-url") is None
    assert bitable_sync._extract_url_from_field(None) is None
    assert bitable_sync._extract_url_from_field({"link": "https://c.com"}) == "https://c.com"
    assert bitable_sync._extract_url_from_field([{"link": "https://d.com"}]) == "https://d.com"


def test_build_column_config():
    cols = bitable_sync._build_column_config()
    assert "url" in cols
    assert "total_read" in cols
    assert "error" in cols
    cols2 = bitable_sync._build_column_config(field_url="链接")
    assert cols2["url"] == "链接"


def test_sync_from_bitable_missing_config():
    out = bitable_sync.sync_from_bitable(app_token="", table_id="tbl")
    assert out["success"] is False
    assert "未配置" in out.get("message", "")

    out2 = bitable_sync.sync_from_bitable(app_token="tok", table_id="tbl")
    # Depends on FEISHU_APP_ID/SECRET in env; if not set, returns failure
    if not bitable_sync.FEISHU_APP_ID or not bitable_sync.FEISHU_APP_SECRET:
        assert out2["success"] is False
        assert "未配置" in out2.get("message", "")


def test_sync_from_bitable_no_records(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")
    monkeypatch.setattr(
        bitable_sync,
        "list_all_bitable_records",
        lambda *a, **k: [],
    )
    out = bitable_sync.sync_from_bitable(app_token="tok", table_id="tbl")
    assert out["success"] is True
    assert out["processed"] == 0
    assert out["updated"] == 0
    assert "未找到有效" in out.get("message", "")


async def _fake_crawl_success(urls):
    return [
        {"url": u, "success": True, "data": {"read_count": 100 + i, "title": None, "site": "juejin"}}
        for i, u in enumerate(urls)
    ]


def test_sync_from_bitable_crawl_and_write_back(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")

    records = [
        {"record_id": "rec1", "fields": {"发布链接": "https://juejin.cn/post/1"}},
        {"record_id": "rec2", "fields": {"发布链接": "https://juejin.cn/post/2"}},
    ]
    monkeypatch.setattr(
        bitable_sync,
        "list_all_bitable_records",
        lambda *a, **k: records,
    )

    updates = []

    def capture_batch_update(app_token, table_id, records, **kwargs):
        for record_id, fields in records:
            updates.append({"record_id": record_id, "fields": dict(fields)})

    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", capture_batch_update)
    monkeypatch.setattr(
        bitable_sync,
        "crawl_urls_for_results",
        _fake_crawl_success,
    )

    out = bitable_sync.sync_from_bitable(app_token="tok", table_id="tbl")
    assert out["success"] is True
    assert out["processed"] == 2
    assert out["updated"] == 2
    assert out["failed"] == 0
    assert len(updates) == 2
    assert updates[0]["fields"].get("总阅读量") == 100
    assert updates[0]["fields"].get("失败原因") == ""
    assert updates[1]["fields"].get("总阅读量") == 101


async def _fake_crawl_mixed(urls):
    return [
        {"url": urls[0], "success": True, "data": {"read_count": 50, "title": None, "site": "juejin"}},
        {"url": urls[1], "success": False, "error": "平台不允许"},
    ]


def test_sync_from_bitable_crawl_failure_writes_error(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")
    records = [
        {"record_id": "r1", "fields": {"发布链接": "https://juejin.cn/p/1"}},
        {"record_id": "r2", "fields": {"发布链接": "https://other.com/p/2"}},
    ]
    monkeypatch.setattr(bitable_sync, "list_all_bitable_records", lambda *a, **k: records)
    updates = []

    def capture_batch_update(app_token, table_id, records, **kwargs):
        for record_id, fields in records:
            updates.append({"record_id": record_id, "fields": dict(fields)})

    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", capture_batch_update)
    monkeypatch.setattr(bitable_sync, "crawl_urls_for_results", _fake_crawl_mixed)

    out = bitable_sync.sync_from_bitable(app_token="tok", table_id="tbl")
    assert out["success"] is True
    assert out["processed"] == 2
    assert out["updated"] == 1
    assert out["failed"] == 1
    assert len(out["errors"]) == 1
    assert out["errors"][0]["record_id"] == "r2"
    assert "平台不允许" in out["errors"][0]["error"]
    assert len(updates) == 2
    err_fields = next(u["fields"] for u in updates if u["record_id"] == "r2")
    assert "失败原因" in err_fields
    assert "平台不允许" in err_fields["失败原因"]
