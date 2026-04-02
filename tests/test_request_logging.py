import logging


def test_request_id_header_is_set_and_duration_logged(monkeypatch, caplog):
    # Import inside test so Flask app picks up test env.
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")
    from monitor.app import app

    caplog.set_level(logging.INFO)
    client = app.test_client()
    resp = client.get("/api/monitor/health")

    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")

    # Ensure lifecycle events are logged.
    messages = [r.getMessage() for r in caplog.records]
    assert "http.request.started" in messages
    assert "http.request.completed" in messages

    completed = [r for r in caplog.records if r.getMessage() == "http.request.completed"]
    assert completed
    record = completed[-1]
    assert hasattr(record, "duration_ms")
    assert record.duration_ms is None or record.duration_ms >= 0


def test_invalid_external_request_id_is_rejected(monkeypatch, caplog):
    monkeypatch.setenv("ARTICLE_MONITOR_LOG_QUEUE_ENABLED", "0")
    from monitor.app import app

    caplog.set_level(logging.INFO)
    client = app.test_client()
    # Werkzeug disallows raw newlines in header values; use a syntactically invalid id.
    resp = client.get("/api/monitor/health", headers={"X-Request-ID": "bad id"})

    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")

    completed = [r for r in caplog.records if r.getMessage() == "http.request.completed"]
    assert completed
    record = completed[-1]
    assert getattr(record, "request_id_source", None) == "client_rejected"

