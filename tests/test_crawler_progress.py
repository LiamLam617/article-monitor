from monitor import crawler


def test_crawl_progress_reset_and_get():
    # 先重置，再讀取
    crawler.reset_crawl_progress()
    progress = crawler.get_crawl_progress()

    assert progress["is_running"] is False
    assert progress["total"] == 0
    assert progress["current"] == 0
    assert progress["success"] == 0
    assert progress["failed"] == 0
    assert progress["retried"] == 0
    assert progress["current_url"] is None


def test_stop_crawling_sets_stop_signal():
    # 無法直接讀取 stop flag，但可以至少呼叫保證不拋錯
    # 後續若有 API 使用 stop_crawling，可在整合測試中確認行為。
    crawler.stop_crawling()

