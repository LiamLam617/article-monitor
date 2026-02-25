import json
import time
import importlib
import monitor.scheduler as scheduler_module
import monitor.database as database_module
import monitor.bitable_sync as bitable_sync_module

app_module = importlib.import_module("monitor.app")
app = app_module.app


def test_index_returns_200():
    """GET / returns 200."""
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_favicon_returns_204():
    """GET /favicon.ico returns 204 No Content."""
    client = app.test_client()
    resp = client.get("/favicon.ico")
    assert resp.status_code == 204


def test_get_articles_uses_envelope(monkeypatch):
    def fake_get_all_articles_with_latest_count():
        return [{"id": 1, "title": "T1", "site": "juejin", "url": "https://a1"}]

    monkeypatch.setattr(app_module, "get_all_articles_with_latest_count", fake_get_all_articles_with_latest_count)

    client = app.test_client()
    resp = client.get("/api/articles")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["data"], list)
    assert data["data"][0]["id"] == 1


def test_create_article_rejects_invalid_url():
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "not-a-valid-url"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "无效的URL格式" in data["error"]


def test_create_article_rejects_empty_url():
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "   "}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "URL不能为空"


def test_create_article_rejects_platform_not_allowed(monkeypatch):
    monkeypatch.setattr(app_module, "is_platform_allowed", lambda site: False)
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "https://juejin.cn/post/1"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "不在允许列表中" in data["error"]


def test_create_article_add_article_value_error_returns_400(monkeypatch):
    """create_article returns 400 when add_article raises ValueError."""
    async def fake_crawler():
        class C:
            async def __aexit__(self, *a):
                pass
        return C()
    async def fake_extract(url, crawler):
        return {"title": "T", "read_count": 0}
    import monitor.extractors as ext
    monkeypatch.setattr(ext, "create_shared_crawler", fake_crawler)
    monkeypatch.setattr(ext, "extract_article_info", fake_extract)
    def raise_val(url, title=None, site=None):
        raise ValueError("invalid")
    monkeypatch.setattr(app_module, "add_article", raise_val)
    monkeypatch.setattr(app_module, "add_read_count", lambda a, c: None)
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "https://juejin.cn/post/1"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "參數錯誤" in resp.get_json()["error"]


def test_create_article_add_article_exception_returns_500(monkeypatch):
    """create_article returns 500 when add_article raises generic Exception."""
    async def fake_crawler():
        class C:
            async def __aexit__(self, *a):
                pass
        return C()
    async def fake_extract(url, crawler):
        return {"title": "T", "read_count": 0}
    import monitor.extractors as ext
    monkeypatch.setattr(ext, "create_shared_crawler", fake_crawler)
    monkeypatch.setattr(ext, "extract_article_info", fake_extract)
    def raise_err(url, title=None, site=None):
        raise RuntimeError("db error")
    monkeypatch.setattr(app_module, "add_article", raise_err)
    monkeypatch.setattr(app_module, "add_read_count", lambda a, c: None)
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "https://juejin.cn/post/1"}),
        content_type="application/json",
    )
    assert resp.status_code == 500


def test_create_article_success(monkeypatch):
    """create_article success path with mocked extractors and DB."""
    async def fake_crawler():
        class C:
            async def __aexit__(self, *a):
                pass
        return C()

    async def fake_extract(url, crawler):
        return {"title": "Test Title", "read_count": 42}

    monkeypatch.setattr(app_module, "add_article", lambda url, title=None, site=None: 1)
    monkeypatch.setattr(app_module, "add_read_count", lambda aid, count: None)
    import monitor.extractors as extractors_module
    monkeypatch.setattr(extractors_module, "create_shared_crawler", fake_crawler)
    monkeypatch.setattr(extractors_module, "extract_article_info", fake_extract)
    client = app.test_client()
    resp = client.post(
        "/api/articles",
        data=json.dumps({"url": "https://juejin.cn/post/123"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["title"] == "Test Title"
    assert data["data"]["initial_count"] == 42


def test_batch_value_error_returns_400(monkeypatch):
    async def raise_value_error(urls):
        raise ValueError("bad")
    monkeypatch.setattr(app_module, "_process_urls_sync", raise_value_error)
    client = app.test_client()
    resp = client.post(
        "/api/articles/batch",
        data=json.dumps({"urls": ["https://juejin.cn/post/1"]}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "參數錯誤" in resp.get_json()["error"]


def test_batch_exception_returns_500(monkeypatch):
    async def raise_runtime(urls):
        raise RuntimeError("fail")
    monkeypatch.setattr(app_module, "_process_urls_sync", raise_runtime)
    client = app.test_client()
    resp = client.post(
        "/api/articles/batch",
        data=json.dumps({"urls": ["https://juejin.cn/post/1"]}),
        content_type="application/json",
    )
    assert resp.status_code == 500
    assert resp.get_json()["success"] is False


def test_settings_get_and_update(monkeypatch):
    # GET: 讀取設定
    monkeypatch.setattr(app_module, "get_setting", lambda key, default=None: "6")

    client = app.test_client()
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["crawl_interval_hours"] == 6

    # POST: 更新設定
    set_called = {}

    def fake_set_setting(key, value):
        set_called["key"] = key
        set_called["value"] = value
    monkeypatch.setattr(app_module, "set_setting", fake_set_setting)

    def fake_update_schedule():
        set_called["schedule_updated"] = True

    monkeypatch.setattr(scheduler_module, "update_schedule", fake_update_schedule)

    resp2 = client.post(
        "/api/settings",
        data=json.dumps({"crawl_interval_hours": 3}),
        content_type="application/json",
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2["success"] is True
    assert set_called["key"] == "crawl_interval_hours"
    assert set_called["value"] == 3
    assert set_called.get("schedule_updated") is True


def test_batch_empty_urls_returns_400():
    """POST /api/articles/batch with empty urls returns 400."""
    client = app.test_client()
    resp = client.post(
        "/api/articles/batch",
        data=json.dumps({"urls": []}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False


def test_batch_small_sync_success(monkeypatch):
    """POST /api/articles/batch with <=5 URLs uses sync path and returns results."""
    results = [{"success": True, "data": {"id": 1, "initial_count": 10}}]

    async def fake_sync(urls):
        return results

    monkeypatch.setattr(app_module, "_process_urls_sync", fake_sync)
    client = app.test_client()
    resp = client.post(
        "/api/articles/batch",
        data=json.dumps({"urls": ["https://juejin.cn/post/1"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "results" in data
    assert len(data["results"]) == 1


def test_batch_large_returns_task_id(monkeypatch):
    """POST /api/articles/batch with >5 URLs returns task_id."""
    class FakeTM:
        def submit_task(self, func, urls):
            return "fake-task-id-123"
    import monitor.task_manager as task_manager_module
    monkeypatch.setattr(task_manager_module, "get_task_manager", lambda: FakeTM())
    client = app.test_client()
    resp = client.post(
        "/api/articles/batch",
        data=json.dumps({"urls": ["https://a.com/1", "https://a.com/2", "https://a.com/3", "https://a.com/4", "https://a.com/5", "https://a.com/6"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data.get("task_id") == "fake-task-id-123"


def test_delete_article_success(monkeypatch):
    """DELETE /api/articles/<id> returns 200 when delete_article succeeds."""
    monkeypatch.setattr(app_module, "delete_article", lambda id: None)
    client = app.test_client()
    resp = client.delete("/api/articles/1")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_delete_article_handles_value_error(monkeypatch):
    """DELETE /api/articles/<id> returns 400 on ValueError."""
    def raise_value_error(article_id):
        raise ValueError("bad")
    monkeypatch.setattr(app_module, "delete_article", raise_value_error)
    client = app.test_client()
    resp = client.delete("/api/articles/999")
    assert resp.status_code == 400


def test_history_success(monkeypatch):
    """GET /api/articles/<id>/history returns 200 with data."""
    monkeypatch.setattr(app_module, "get_read_counts", lambda id, limit=100, start_date=None, end_date=None, group_by_hour=False: [{"count": 10, "timestamp": "2024-01-01 00:00:00"}])
    monkeypatch.setattr(database_module, "get_article_by_id", lambda id: {"id": id, "title": "T", "url": "https://u", "site": "juejin"})
    client = app.test_client()
    resp = client.get("/api/articles/1/history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data


def test_history_404_when_article_missing(monkeypatch):
    """GET /api/articles/<id>/history returns 404 when article not found."""
    monkeypatch.setattr(app_module, "get_read_counts", lambda id, limit=100, start_date=None, end_date=None, group_by_hour=False: [])
    monkeypatch.setattr(database_module, "get_article_by_id", lambda id: None)
    client = app.test_client()
    resp = client.get("/api/articles/99999/history")
    assert resp.status_code == 404


def test_history_exception_returns_500(monkeypatch):
    """GET /api/articles/<id>/history returns 500 when get_read_counts raises."""
    def raise_err(*a, **kw):
        raise RuntimeError("db error")
    monkeypatch.setattr(app_module, "get_read_counts", raise_err)
    client = app.test_client()
    resp = client.get("/api/articles/1/history")
    assert resp.status_code == 500


def test_manual_crawl_returns_200(monkeypatch):
    """POST /api/crawl returns 200 and starts crawl in thread."""
    import monitor.crawler as crawler_module
    monkeypatch.setattr(crawler_module, "crawl_all_sync", lambda: None)
    client = app.test_client()
    resp = client.post("/api/crawl")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_stop_crawl_returns_200(monkeypatch):
    """POST /api/crawl/stop returns 200."""
    import monitor.crawler as crawler_module
    monkeypatch.setattr(crawler_module, "stop_crawling", lambda: None)
    client = app.test_client()
    resp = client.post("/api/crawl/stop")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_get_statistics_returns_200():
    """GET /api/statistics returns 200 with date list."""
    client = app.test_client()
    resp = client.get("/api/statistics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data
    assert "dates" in data["data"]


def test_get_statistics_with_group_by_hour(monkeypatch):
    """GET /api/statistics?group_by_hour=true&start_date=2024-01-01&end_date=2024-01-01 returns hourly points."""
    client = app.test_client()
    resp = client.get("/api/statistics?group_by_hour=true&start_date=2024-01-01&end_date=2024-01-01")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["data"]["dates"]) == 24


def test_get_crawl_progress_returns_200(monkeypatch):
    """GET /api/crawl/progress returns 200 with progress data."""
    import monitor.crawler as crawler_module
    monkeypatch.setattr(crawler_module, "get_crawl_progress", lambda: {"is_running": False, "total": 0, "current": 0})
    client = app.test_client()
    resp = client.get("/api/crawl/progress")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data


def test_get_crawl_progress_exception_returns_500(monkeypatch):
    """GET /api/crawl/progress returns 500 when get_crawl_progress raises."""
    import monitor.crawler as crawler_module
    def raise_err():
        raise RuntimeError("err")
    monkeypatch.setattr(crawler_module, "get_crawl_progress", raise_err)
    client = app.test_client()
    resp = client.get("/api/crawl/progress")
    assert resp.status_code == 500


def test_get_task_status_200(monkeypatch):
    """GET /api/tasks/<id> returns 200 when task exists."""
    class FakeTM:
        def get_task(self, id):
            return {"id": id, "status": "completed"}
    import monitor.task_manager as task_manager_module
    monkeypatch.setattr(task_manager_module, "get_task_manager", lambda: FakeTM())
    client = app.test_client()
    resp = client.get("/api/tasks/some-id")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "completed"


def test_get_task_status_404(monkeypatch):
    """GET /api/tasks/<id> returns 404 when task does not exist."""
    class FakeTM:
        def get_task(self, id):
            return None
    import monitor.task_manager as task_manager_module
    monkeypatch.setattr(task_manager_module, "get_task_manager", lambda: FakeTM())
    client = app.test_client()
    resp = client.get("/api/tasks/nonexistent")
    assert resp.status_code == 404


def test_cancel_task_200(monkeypatch):
    """DELETE /api/tasks/<id> returns 200 when cancel succeeds."""
    class FakeTM:
        def cancel_task(self, id):
            return True
    import monitor.task_manager as task_manager_module
    monkeypatch.setattr(task_manager_module, "get_task_manager", lambda: FakeTM())
    client = app.test_client()
    resp = client.delete("/api/tasks/some-id")
    assert resp.status_code == 200


def test_cancel_task_400(monkeypatch):
    """DELETE /api/tasks/<id> returns 400 when cancel returns False."""
    class FakeTM:
        def cancel_task(self, id):
            return False
    import monitor.task_manager as task_manager_module
    monkeypatch.setattr(task_manager_module, "get_task_manager", lambda: FakeTM())
    client = app.test_client()
    resp = client.delete("/api/tasks/some-id")
    assert resp.status_code == 400


def test_get_failures_returns_200(monkeypatch):
    """GET /api/failures returns 200 with failures and stats."""
    monkeypatch.setattr(app_module, "get_all_failures", lambda limit=100, site=None: [])
    monkeypatch.setattr(app_module, "get_failure_stats", lambda: {"total": 0, "by_site": {}, "recent_24h": 0})
    client = app.test_client()
    resp = client.get("/api/failures")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data
    assert "failures" in data["data"]
    assert "stats" in data["data"]


def test_retry_failure_404(monkeypatch):
    """POST /api/failures/retry/<id> returns 404 when article not found."""
    monkeypatch.setattr(database_module, "get_article_by_id", lambda id: None)
    client = app.test_client()
    resp = client.post("/api/failures/retry/99999")
    assert resp.status_code == 404


def test_retry_failure_200(monkeypatch):
    """POST /api/failures/retry/<id> returns 200 and starts crawl."""
    monkeypatch.setattr(database_module, "get_article_by_id", lambda id: {"id": id})
    import monitor.crawler as crawler_module
    monkeypatch.setattr(crawler_module, "crawl_all_sync", lambda: None)
    client = app.test_client()
    resp = client.post("/api/failures/retry/1")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_export_csv_400_when_no_articles(monkeypatch):
    """POST /api/export/csv with no article_ids returns 400."""
    client = app.test_client()
    resp = client.post(
        "/api/export/csv",
        data=json.dumps({"article_ids": [], "start_date": "2024-01-01", "end_date": "2024-01-31"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_export_csv_200(monkeypatch):
    """POST /api/export/csv returns CSV response."""
    monkeypatch.setattr(app_module, "export_selected_articles_csv", lambda ids, start, end: (b"title,url\nA,https://a", "export.csv"))
    client = app.test_client()
    resp = client.post(
        "/api/export/csv",
        data=json.dumps({"article_ids": [1], "start_date": "2024-01-01", "end_date": "2024-01-31"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type or "csv" in resp.content_type.lower()


def test_export_all_csv_200(monkeypatch):
    """GET /api/export/all-csv returns CSV."""
    monkeypatch.setattr(app_module, "export_all_articles_csv", lambda start, end: (b"title,url\n", "all.csv"))
    client = app.test_client()
    resp = client.get("/api/export/all-csv")
    assert resp.status_code == 200


def test_get_settings_exception_returns_500(monkeypatch):
    """GET /api/settings returns 500 when get_setting raises."""
    def raise_err(key, default=None):
        raise RuntimeError("db error")
    monkeypatch.setattr(app_module, "get_setting", raise_err)
    client = app.test_client()
    resp = client.get("/api/settings")
    assert resp.status_code == 500


def test_export_csv_exception_returns_500(monkeypatch):
    """POST /api/export/csv returns 500 when export_selected_articles_csv raises."""
    def raise_err(ids, start, end):
        raise RuntimeError("export error")
    monkeypatch.setattr(app_module, "export_selected_articles_csv", raise_err)
    client = app.test_client()
    resp = client.post(
        "/api/export/csv",
        data=json.dumps({"article_ids": [1], "start_date": "2024-01-01", "end_date": "2024-01-31"}),
        content_type="application/json",
    )
    assert resp.status_code == 500


def test_export_all_csv_exception_returns_500(monkeypatch):
    """GET /api/export/all-csv returns 500 when export_all_articles_csv raises."""
    def raise_err(start, end):
        raise RuntimeError("export error")
    monkeypatch.setattr(app_module, "export_all_articles_csv", raise_err)
    client = app.test_client()
    resp = client.get("/api/export/all-csv")
    assert resp.status_code == 500


def test_health_returns_200(monkeypatch):
    """GET /api/monitor/health returns 200 with payload."""
    monkeypatch.setattr(app_module, "get_system_health_payload", lambda: {"system": {}, "platforms": [], "network": [], "timestamp": "2024-01-01"})
    client = app.test_client()
    resp = client.get("/api/monitor/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "data" in data


def test_settings_post_missing_interval_returns_400():
    client = app.test_client()
    resp = client.post(
        "/api/settings",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "crawl_interval_hours" in resp.get_json()["error"]


def test_settings_post_invalid_interval_returns_400():
    client = app.test_client()
    resp = client.post(
        "/api/settings",
        data=json.dumps({"crawl_interval_hours": 0}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_settings_post_non_numeric_returns_400():
    client = app.test_client()
    resp = client.post(
        "/api/settings",
        data=json.dumps({"crawl_interval_hours": "abc"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_bitable_sync_returns_202_with_task_id(monkeypatch):
    """POST /api/bitable/sync returns 202 Accepted with task_id and status_url (async)."""
    monkeypatch.setattr(app_module, "_last_bitable_sync_time", 0.0)
    client = app.test_client()
    resp = client.post(
        "/api/bitable/sync",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
    assert data["data"]["status"] == "pending"
    assert "status_url" in data
    assert data["status_url"] == f"/api/tasks/{data['data']['task_id']}"


def test_bitable_sync_success_shape(monkeypatch):
    """POST /api/bitable/sync returns 202 with task_id; result is polled via GET /api/tasks/<id>."""
    monkeypatch.setattr(app_module, "_last_bitable_sync_time", 0.0)
    client = app.test_client()
    resp = client.post(
        "/api/bitable/sync",
        data=json.dumps({"app_token": "tok", "table_id": "tbl"}),
        content_type="application/json",
    )
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
    assert data["data"]["status"] == "pending"
    assert data["status_url"].endswith(data["data"]["task_id"])


def test_bitable_sync_poll_task_until_completed(monkeypatch):
    """Submit Bitable sync, poll GET /api/tasks/<task_id> until completed; assert progress shape."""
    monkeypatch.setattr(app_module, "_last_bitable_sync_time", 0.0)
    fake_result = {
        "success": True,
        "processed": 5,
        "updated": 4,
        "failed": 1,
        "errors": [{"record_id": "rec1", "url": "https://x.com/1", "error": "timeout"}],
    }
    monkeypatch.setattr(
        bitable_sync_module,
        "sync_from_bitable",
        lambda **kw: fake_result,
    )
    client = app.test_client()
    resp = client.post(
        "/api/bitable/sync",
        data=json.dumps({"app_token": "t", "table_id": "t"}),
        content_type="application/json",
    )
    assert resp.status_code == 202
    task_id = resp.get_json()["data"]["task_id"]

    for _ in range(30):
        status_resp = client.get(f"/api/tasks/{task_id}")
        assert status_resp.status_code == 200
        data = status_resp.get_json()["data"]
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.15)

    assert data["status"] == "completed"
    progress = data["progress"]
    assert progress["success"] is True
    assert progress["processed"] == 5
    assert progress["updated"] == 4
    assert progress["failed"] == 1
    assert len(progress["errors"]) == 1
    assert progress["errors"][0]["record_id"] == "rec1"
    assert progress["errors"][0]["error"] == "timeout"

