import asyncio
import time
from typing import List

import monitor.article_service as article_service


class DummyCrawler:
    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyBrowserPool:
    def __init__(self):
        self.acquired: List[DummyCrawler] = []

    async def acquire(self):
        crawler = DummyCrawler()
        self.acquired.append(crawler)
        return crawler

    async def release(self, crawler):
        return None


def run(coro):
    """Helper to run async functions in tests without pytest-asyncio."""
    return asyncio.run(coro)


def test_process_urls_sync_success(monkeypatch):
    dummy_pool = DummyBrowserPool()

    async def fake_extract_article_info(url, crawler):
        return {"title": f"title-{url}", "read_count": 42}

    async def fake_create_shared_crawler():
        return DummyCrawler()

    def fake_validate_and_normalize(url: str):
        return True, url.strip(), "juejin"

    def fake_is_platform_allowed(site: str) -> bool:
        return True

    def fake_add_articles_batch(articles):
        # 回傳連續 id
        return list(range(1, len(articles) + 1))

    created_read_counts = []

    def fake_add_read_counts_batch(records):
        created_read_counts.extend(records)

    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract_article_info)
    monkeypatch.setattr(article_service, "create_shared_crawler", fake_create_shared_crawler)
    monkeypatch.setattr(article_service, "validate_and_normalize_url", fake_validate_and_normalize)
    monkeypatch.setattr(article_service, "is_platform_allowed", fake_is_platform_allowed)
    monkeypatch.setattr(article_service, "add_articles_batch", fake_add_articles_batch)
    monkeypatch.setattr(article_service, "add_read_counts_batch", fake_add_read_counts_batch)

    urls = ["https://example.com/1", "https://example.com/2"]
    results = run(article_service._process_urls_sync(urls))

    assert len(results) == 2
    for idx, r in enumerate(results):
        assert r["success"] is True
        assert r["data"]["id"] == idx + 1
        assert r["data"]["initial_count"] == 42

    # 確認有寫入對應數量的閱讀數
    assert len(created_read_counts) == 2


def test_process_urls_async_updates_task_results(monkeypatch):
    class DummyTaskManager:
        def __init__(self):
            self.tasks = {}
            self.progress_updates = []

        def update_task_progress(self, task_id, progress):
            self.progress_updates.append((task_id, progress))

        def get_task(self, task_id):
            return self.tasks.get(task_id)

    dummy_task_manager = DummyTaskManager()
    task_id = "task-1"
    dummy_task_manager.tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "progress": {},
        "results": None,
    }

    # 重用前一個測試的行為，但簡化為總是成功
    monkeypatch.setattr(article_service, "get_task_manager", lambda: dummy_task_manager)
    async def fake_process_batch(urls, browser_pool):
        return [{"url": u, "success": True, "data": {"id": i + 1}} for i, u in enumerate(urls)]

    monkeypatch.setattr(article_service, "_process_batch", fake_process_batch)
    monkeypatch.setattr(article_service, "get_browser_pool", lambda: DummyBrowserPool())

    urls = ["https://example.com/1", "https://example.com/2", "https://example.com/3"]

    run(article_service._process_urls_async(task_id, urls))

    # 任務結果應該已被寫回 task 物件
    task = dummy_task_manager.get_task(task_id)
    assert task is not None
    assert task["results"] is not None
    assert len(task["results"]) == len(urls)


def test_crawl_urls_for_results_return_structure(monkeypatch):
    """crawl_urls_for_results 返回结构含 url/success/data.read_count 或 error，不写库。"""
    dummy_pool = DummyBrowserPool()
    async def fake_extract(url, crawler):
        return {"title": "t", "read_count": 10}
    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
    monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
    monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)

    urls = ["https://juejin.cn/post/1"]
    results = run(article_service.crawl_urls_for_results(urls))
    assert len(results) == 1
    r = results[0]
    assert "url" in r
    assert r["success"] is True
    assert "data" in r
    assert r["data"]["read_count"] == 10
    assert "initial_count" not in r["data"]  # crawl_urls_for_results 只返回 read_count


def test_crawl_single_url_for_result_invalid_url(monkeypatch):
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (False, u, None))
    result = run(article_service.crawl_single_url_for_result("bad-url"))
    assert result["success"] is False
    assert "无效的URL格式" in result["error"]


def test_crawl_single_url_for_result_success(monkeypatch):
    dummy_pool = DummyBrowserPool()

    async def fake_extract(url, crawler):
        return {"title": "ok", "read_count": 7}

    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
    monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
    monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)

    result = run(article_service.crawl_single_url_for_result("https://juejin.cn/post/1"))
    assert result["success"] is True
    assert result["data"]["title"] == "ok"
    assert result["data"]["read_count"] == 7
    assert result["data"]["site"] == "juejin"


def test_crawl_urls_for_results_respects_domain_min_delay(monkeypatch):
    dummy_pool = DummyBrowserPool()
    call_times = []

    async def fake_extract(url, crawler):
        call_times.append(time.monotonic())
        return {"title": "t", "read_count": 10}

    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
    monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
    monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(article_service, "CRAWL_CONCURRENCY_PER_DOMAIN", 1)
    monkeypatch.setattr(article_service, "CRAWL_MIN_DELAY_PER_DOMAIN", 0.05)

    urls = [
        "https://juejin.cn/post/1",
        "https://juejin.cn/post/2",
    ]
    results = run(article_service.crawl_urls_for_results(urls))

    assert len(results) == 2
    assert results[0]["success"] is True
    assert results[1]["success"] is True
    assert len(call_times) == 2
    assert (call_times[1] - call_times[0]) >= 0.045


def test_crawl_urls_for_results_respects_domain_min_delay_with_concurrency(monkeypatch):
    dummy_pool = DummyBrowserPool()
    call_times = []

    async def fake_extract(url, crawler):
        call_times.append(time.monotonic())
        return {"title": "t", "read_count": 10}

    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
    monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
    monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(article_service, "CRAWL_CONCURRENCY_PER_DOMAIN", 3)
    monkeypatch.setattr(article_service, "CRAWL_MIN_DELAY_PER_DOMAIN", 0.03)
    monkeypatch.setattr(article_service, "BATCH_PROCESS_CONCURRENCY", 3)

    urls = [
        "https://juejin.cn/post/1",
        "https://juejin.cn/post/2",
        "https://juejin.cn/post/3",
    ]
    results = run(article_service.crawl_urls_for_results(urls))

    assert len(results) == 3
    assert all(r["success"] is True for r in results)
    assert len(call_times) == 3
    ordered = sorted(call_times)
    # Windows timer granularity can be coarse; assert overall spread instead of per-step equality.
    assert (ordered[-1] - ordered[0]) >= 0.04


def test_crawl_single_url_for_result_timeout_returns_failure(monkeypatch):
    dummy_pool = DummyBrowserPool()

    async def fake_extract(url, crawler):
        await asyncio.sleep(1.2)
        return {"title": "late", "read_count": 1}

    monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
    monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
    monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
    monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
    monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)
    monkeypatch.setattr(article_service, "CRAWL_TIMEOUT", 1)

    result = run(article_service.crawl_single_url_for_result("https://juejin.cn/post/timeout"))
    assert result["success"] is False
    assert result["error_code"] == "crawl_timeout"
    assert "超时" in result["error"]


def test_crawl_single_url_timeout_includes_domain_semaphore_wait(monkeypatch):
    dummy_pool = DummyBrowserPool()

    async def fake_extract(url, crawler):
        return {"title": "ok", "read_count": 9}

    async def run_case():
        monkeypatch.setattr(article_service, "get_browser_pool", lambda: dummy_pool)
        monkeypatch.setattr(article_service, "extract_article_info", fake_extract)
        monkeypatch.setattr(article_service, "create_shared_crawler", lambda: DummyCrawler())
        monkeypatch.setattr(article_service, "validate_and_normalize_url", lambda u: (True, u, "juejin"))
        monkeypatch.setattr(article_service, "is_platform_allowed", lambda s: True)
        monkeypatch.setattr(article_service, "CRAWL_TIMEOUT", 0.2)
        monkeypatch.setattr(article_service, "CRAWL_CONCURRENCY_PER_DOMAIN", 1)
        monkeypatch.setattr(article_service, "CRAWL_MIN_DELAY_PER_DOMAIN", 0)

        controller = article_service._DomainThrottleController()
        sem = await controller.get_semaphore("https://juejin.cn/post/lock")
        await sem.acquire()
        try:
            return await article_service.crawl_single_url_for_result(
                "https://juejin.cn/post/wait",
                browser_pool=dummy_pool,
                domain_controller=controller,
            )
        finally:
            sem.release()

    result = run(run_case())
    assert result["success"] is False
    assert result["error_code"] == "crawl_timeout"

