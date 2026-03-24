"""Unit and integration tests for Bitable sync (sync_from_bitable)."""
import asyncio
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


def test_sync_from_bitable_writeback_failure_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")
    monkeypatch.setattr(
        bitable_sync,
        "list_all_bitable_records",
        lambda *a, **k: [{"record_id": "r1", "fields": {"发布链接": "https://juejin.cn/post/1"}}],
    )
    monkeypatch.setattr(
        bitable_sync,
        "crawl_urls_for_results",
        lambda urls: asyncio.sleep(0, result=[{"url": urls[0], "success": True, "data": {"read_count": 11}}]),
    )

    def fake_batch_update(*args, **kwargs):
        raise RuntimeError("write back failed")

    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", fake_batch_update)

    with pytest.raises(RuntimeError, match="Bitable 批量更新失败"):
        bitable_sync.sync_from_bitable(app_token="tok", table_id="table_1")


def test_sync_from_multiple_bitable_sources_keeps_table_isolation(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")

    def fake_list_records(app_token, table_id):
        return [{"record_id": f"{table_id}-r1", "fields": {"发布链接": "https://juejin.cn/post/1"}}]

    crawled_urls = []

    async def fake_crawl(urls):
        crawled_urls.extend(urls)
        return [{"url": u, "success": True, "data": {"read_count": 10}} for u in urls]

    updates = {}

    def fake_batch_update(app_token, table_id, records, **kwargs):
        updates[table_id] = records

    monkeypatch.setattr(bitable_sync, "list_all_bitable_records", fake_list_records)
    monkeypatch.setattr(bitable_sync, "crawl_urls_for_results", fake_crawl)
    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", fake_batch_update)

    out = bitable_sync.sync_from_multiple_bitable_sources([
        {"app_token": "tok", "table_id": "table_1"},
        {"app_token": "tok", "table_id": "table_2"},
    ])

    assert out["success"] is True
    assert out["processed"] == 2
    assert len(crawled_urls) == 1
    assert "table_1" in updates
    assert "table_2" in updates
    assert len(out["tables"]) == 2


def test_sync_from_multiple_bitable_sources_handles_invalid_item():
    out = bitable_sync.sync_from_multiple_bitable_sources(
        [{"app_token": "tok"}],  # missing table_id
        max_concurrency=1,
    )

    assert out["success"] is False
    assert out["processed"] == 0
    assert len(out["tables"]) == 1
    assert out["tables"][0]["success"] is False
    assert "缺少 table_id" in out["tables"][0]["message"]


def test_sync_from_multiple_bitable_sources_rejects_non_dict_item():
    out = bitable_sync.sync_from_multiple_bitable_sources(
        [["not-a-dict"]],
        max_concurrency=1,
    )
    assert out["success"] is False
    assert len(out["tables"]) == 1
    assert out["tables"][0]["success"] is False
    assert "source 项必须是对象" in out["tables"][0]["message"]


def test_sync_from_multiple_bitable_sources_rejects_invalid_concurrency():
    out = bitable_sync.sync_from_multiple_bitable_sources(
        [{"app_token": "tok", "table_id": "tbl"}],
        max_concurrency=0,
    )
    assert out["success"] is False
    assert out["processed"] == 0
    assert "max_concurrency" in out["message"]


def test_sync_from_multiple_bitable_sources_partial_failure(monkeypatch):
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")
    monkeypatch.setattr(
        bitable_sync,
        "list_all_bitable_records",
        lambda *a, **k: [{"record_id": "r1", "fields": {"发布链接": "https://juejin.cn/post/1"}}],
    )
    monkeypatch.setattr(
        bitable_sync,
        "crawl_urls_for_results",
        lambda urls: asyncio.sleep(0, result=[{"url": urls[0], "success": True, "data": {"read_count": 11}}]),
    )

    def fake_batch_update(app_token, table_id, records, **kwargs):
        if table_id == "table_1":
            raise RuntimeError("write back failed")
        return None

    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", fake_batch_update)

    out = bitable_sync.sync_from_multiple_bitable_sources(
        [
            {"app_token": "tok", "table_id": "table_1"},
            {"app_token": "tok", "table_id": "table_2"},
        ]
    )

    assert out["success"] is False
    assert len(out["tables"]) == 2
    t1 = next(t for t in out["tables"] if t["table_id"] == "table_1")
    t2 = next(t for t in out["tables"] if t["table_id"] == "table_2")
    assert t1["success"] is False
    assert "write back failed" in t1["message"]
    assert t2["success"] is True


def test_sync_from_bitable_via_shared_pool_batches_requests(monkeypatch):
    captured_sources = []

    def fake_multi(sources, max_concurrency=1):
        assert max_concurrency >= 1
        captured_sources.extend(sources)
        return {
            "success": True,
            "processed": len(sources),
            "updated": len(sources),
            "failed": 0,
            "errors": [],
            "tables": [
                    {
                        "app_token": source["app_token"],
                        "success": True,
                        "processed": 1,
                        "updated": 1,
                        "failed": 0,
                        "errors": [],
                        "table_id": source["table_id"],
                    }
                    for source in sources
                ],
        }

    monkeypatch.setattr(bitable_sync._sync_service, "sync_multiple_tables", fake_multi)

    out1 = {}
    out2 = {}

    def run_one(out_holder, app_token, table_id):
        out_holder["result"] = bitable_sync.sync_from_bitable_via_shared_pool(
            {"app_token": app_token, "table_id": table_id}
        )

    import threading
    th1 = threading.Thread(target=run_one, args=(out1, "tok", "table_1"))
    th2 = threading.Thread(target=run_one, args=(out2, "tok", "table_2"))
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    assert len(captured_sources) == 2
    assert out1["result"]["table_id"] == "table_1"
    assert out2["result"]["table_id"] == "table_2"


def test_sync_from_bitable_via_shared_pool_matches_by_key_not_index(monkeypatch):
    """tables 返回顺序与 batch 请求顺序不一致时，仍按 app_token+table_id 正确分发。"""

    def fake_multi(sources, max_concurrency=1):
        assert max_concurrency >= 1
        rev = list(reversed(sources))
        return {
            "success": True,
            "processed": len(sources),
            "updated": len(sources),
            "failed": 0,
            "errors": [],
            "tables": [
                {
                    "app_token": s["app_token"],
                    "table_id": s["table_id"],
                    "success": True,
                    "processed": 1,
                    "updated": 1,
                    "failed": 0,
                    "errors": [],
                }
                for s in rev
            ],
        }

    monkeypatch.setattr(bitable_sync._sync_service, "sync_multiple_tables", fake_multi)

    out1 = {}
    out2 = {}

    def run_one(out_holder, app_token, table_id):
        out_holder["result"] = bitable_sync.sync_from_bitable_via_shared_pool(
            {"app_token": app_token, "table_id": table_id}
        )

    import threading
    th1 = threading.Thread(target=run_one, args=(out1, "tok", "table_1"))
    th2 = threading.Thread(target=run_one, args=(out2, "tok", "table_2"))
    th1.start()
    th2.start()
    th1.join()
    th2.join()

    assert out1["result"]["table_id"] == "table_1"
    assert out1["result"]["app_token"] == "tok"
    assert out2["result"]["table_id"] == "table_2"
    assert out2["result"]["app_token"] == "tok"


def test_sync_from_bitable_via_shared_pool_emits_progress_events(monkeypatch):
    events = []

    async def fake_crawl(urls, on_result=None):
        results = []
        for u in urls:
            payload = {"url": u, "success": True, "data": {"read_count": 1}}
            if on_result:
                on_result(payload)
            results.append(payload)
        return results

    monkeypatch.setattr(bitable_sync, "FEISHU_APP_ID", "id")
    monkeypatch.setattr(bitable_sync, "FEISHU_APP_SECRET", "sec")
    monkeypatch.setattr(
        bitable_sync,
        "list_all_bitable_records",
        lambda *a, **k: [{"record_id": "r1", "fields": {"发布链接": "https://juejin.cn/post/1"}}],
    )
    monkeypatch.setattr(bitable_sync, "crawl_urls_for_results", fake_crawl)
    monkeypatch.setattr(bitable_sync, "batch_update_bitable_records", lambda *a, **k: None)

    out = bitable_sync.sync_from_bitable_via_shared_pool(
        {"app_token": "tok", "table_id": "tbl_1"},
        progress_callback=lambda e: events.append(e),
    )

    assert out["success"] is True
    assert any(e.get("stage") == "crawling" for e in events)
    assert any(e.get("batch_url_progress", {}).get("processed") == 1 for e in events)
