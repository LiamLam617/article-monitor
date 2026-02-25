from typing import Any

from monitor import health_service


class DummyMem:
    def __init__(self):
        self.total = 100
        self.available = 40
        self.percent = 60.0


class DummyDisk:
    def __init__(self):
        self.total = 200
        self.free = 50
        self.percent = 75.0


def test_get_system_health_payload_structure(monkeypatch):
    # 模擬 psutil 系統資源
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda interval=None: 12.5)
    monkeypatch.setattr(health_service.psutil, "cpu_count", lambda: 8)
    monkeypatch.setattr(health_service.psutil, "virtual_memory", lambda: DummyMem())
    monkeypatch.setattr(health_service.psutil, "disk_usage", lambda path: DummyDisk())

    # 模擬平台健康與失敗資料
    monkeypatch.setattr(
        health_service,
        "get_platform_health",
        lambda: [{"site": "juejin", "last_update": "2024-01-01 00:00:00", "article_count": 1}],
    )
    monkeypatch.setattr(
        health_service,
        "get_platform_failures",
        lambda: [
            {
                "id": 1,
                "site": "juejin",
                "title": "T1",
                "url": "https://a1",
                "last_error": "error",
                "last_crawl_time": "2024-01-01 00:00:00",
            }
        ],
    )
    monkeypatch.setattr(health_service, "get_setting", lambda key, default=None: "6")

    # 網路狀態用固定回傳，避免真實連線
    monkeypatch.setattr(
        health_service,
        "_check_conn",
        lambda host, port=443: {"ok": True, "latency": 1},
    )

    payload: dict[str, Any] = health_service.get_system_health_payload()

    # 結構檢查
    assert "system" in payload
    assert "platforms" in payload
    assert "network" in payload
    assert "timestamp" in payload

    system = payload["system"]
    assert system["cpu"]["percent"] == 12.5
    assert system["cpu"]["count"] == 8

    platforms = payload["platforms"]
    assert len(platforms) == 1
    assert platforms[0]["site"] == "juejin"
    assert "status" in platforms[0]

    network = payload["network"]
    assert len(network) >= 1
    # 第一個目標應該是「互联网连通性」
    assert network[0]["name"] == "互联网连通性"


def test_health_platform_no_last_update(monkeypatch):
    """Platform with no last_update and article_count 0 gets status ok, 无文章."""
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda interval=None: 0)
    monkeypatch.setattr(health_service.psutil, "cpu_count", lambda: 1)
    monkeypatch.setattr(health_service.psutil, "virtual_memory", lambda: DummyMem())
    monkeypatch.setattr(health_service.psutil, "disk_usage", lambda path: DummyDisk())
    monkeypatch.setattr(
        health_service,
        "get_platform_health",
        lambda: [{"site": "x", "last_update": None, "article_count": 0}],
    )
    monkeypatch.setattr(health_service, "get_platform_failures", lambda: [])
    monkeypatch.setattr(health_service, "get_setting", lambda key, default=None: "6")
    monkeypatch.setattr(health_service, "_check_conn", lambda host, port=443: {"ok": True, "latency": 0})
    payload = health_service.get_system_health_payload()
    assert len(payload["platforms"]) == 1
    assert payload["platforms"][0]["status"] == "ok"
    assert "无文章" in payload["platforms"][0]["message"]


def test_health_platform_bad_date_format(monkeypatch):
    """Platform with unparseable last_update gets status unknown."""
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda interval=None: 0)
    monkeypatch.setattr(health_service.psutil, "cpu_count", lambda: 1)
    monkeypatch.setattr(health_service.psutil, "virtual_memory", lambda: DummyMem())
    monkeypatch.setattr(health_service.psutil, "disk_usage", lambda path: DummyDisk())
    monkeypatch.setattr(
        health_service,
        "get_platform_health",
        lambda: [{"site": "y", "last_update": "not-a-date", "article_count": 1}],
    )
    monkeypatch.setattr(health_service, "get_platform_failures", lambda: [])
    monkeypatch.setattr(health_service, "get_setting", lambda key, default=None: "6")
    monkeypatch.setattr(health_service, "_check_conn", lambda host, port=443: {"ok": True, "latency": 0})
    payload = health_service.get_system_health_payload()
    assert len(payload["platforms"]) == 1
    assert payload["platforms"][0]["status"] == "unknown"


def test_health_platform_delayed_update(monkeypatch):
    """Platform with last_update far in the past gets status error or warning."""
    from datetime import datetime, timedelta
    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda interval=None: 0)
    monkeypatch.setattr(health_service.psutil, "cpu_count", lambda: 1)
    monkeypatch.setattr(health_service.psutil, "virtual_memory", lambda: DummyMem())
    monkeypatch.setattr(health_service.psutil, "disk_usage", lambda path: DummyDisk())
    monkeypatch.setattr(
        health_service,
        "get_platform_health",
        lambda: [{"site": "z", "last_update": old_date, "article_count": 1}],
    )
    monkeypatch.setattr(health_service, "get_platform_failures", lambda: [])
    monkeypatch.setattr(health_service, "get_setting", lambda key, default=None: "6")
    monkeypatch.setattr(health_service, "_check_conn", lambda host, port=443: {"ok": True, "latency": 0})
    payload = health_service.get_system_health_payload()
    assert len(payload["platforms"]) == 1
    assert payload["platforms"][0]["status"] in ("error", "warning")
    assert "延迟" in payload["platforms"][0]["message"] or "小时" in payload["platforms"][0]["message"]


def test_health_platform_with_failures(monkeypatch):
    """Platform with failures gets warning message."""
    monkeypatch.setattr(health_service.psutil, "cpu_percent", lambda interval=None: 0)
    monkeypatch.setattr(health_service.psutil, "cpu_count", lambda: 1)
    monkeypatch.setattr(health_service.psutil, "virtual_memory", lambda: DummyMem())
    monkeypatch.setattr(health_service.psutil, "disk_usage", lambda path: DummyDisk())
    monkeypatch.setattr(
        health_service,
        "get_platform_health",
        lambda: [{"site": "juejin", "last_update": "2024-01-01 00:00:00", "article_count": 2}],
    )
    monkeypatch.setattr(
        health_service,
        "get_platform_failures",
        lambda: [{"id": 1, "site": "juejin", "title": "T", "url": "u", "last_error": "e", "last_crawl_time": "2024-01-01"}],
    )
    monkeypatch.setattr(health_service, "get_setting", lambda key, default=None: "6")
    monkeypatch.setattr(health_service, "_check_conn", lambda host, port=443: {"ok": True, "latency": 0})
    payload = health_service.get_system_health_payload()
    assert len(payload["platforms"]) == 1
    assert "失败" in payload["platforms"][0]["message"]

