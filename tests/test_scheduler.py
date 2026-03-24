"""Unit tests for monitor.scheduler (get_interval_hours, start/update/stop)."""

import monitor.scheduler as scheduler_module
from monitor.scheduler import get_interval_hours, start_scheduler, update_schedule, stop_scheduler


def test_get_interval_hours_valid_from_db(monkeypatch):
    """get_interval_hours returns int when get_setting returns valid string."""
    monkeypatch.setattr(scheduler_module, "get_setting", lambda k, default=None: "4")
    assert get_interval_hours() == 4


def test_get_interval_hours_invalid_falls_back_to_default(monkeypatch):
    """get_interval_hours returns CRAWL_INTERVAL_HOURS when value is invalid."""
    monkeypatch.setattr(scheduler_module, "get_setting", lambda k, default=None: "not_a_number")
    default = scheduler_module.CRAWL_INTERVAL_HOURS
    assert get_interval_hours() == default


def test_get_interval_hours_default_when_missing(monkeypatch):
    """get_interval_hours uses default when get_setting returns default."""
    expected = scheduler_module.CRAWL_INTERVAL_HOURS
    monkeypatch.setattr(
        scheduler_module,
        "get_setting",
        lambda k, default=None: str(expected),
    )
    assert get_interval_hours() == expected


def test_start_scheduler_adds_job(monkeypatch):
    """start_scheduler adds a job and starts the scheduler."""
    add_job_calls = []
    start_calls = []
    monkeypatch.setattr(scheduler_module.scheduler, "add_job", lambda *a, **kw: add_job_calls.append((a, kw)))
    monkeypatch.setattr(scheduler_module.scheduler, "start", lambda: start_calls.append(1))
    monkeypatch.setattr(scheduler_module, "get_setting", lambda k, default=None: "6")
    monkeypatch.setattr(scheduler_module, "crawl_all_sync", lambda: None)
    start_scheduler()
    assert len(add_job_calls) == 1
    assert add_job_calls[0][1].get("id") == "crawl_job"
    assert len(start_calls) == 1


def test_update_schedule_reschedules_job(monkeypatch):
    """update_schedule calls reschedule_job."""
    reschedule_calls = []
    monkeypatch.setattr(scheduler_module.scheduler, "reschedule_job", lambda *a, **kw: reschedule_calls.append((a, kw)))
    monkeypatch.setattr(scheduler_module, "get_setting", lambda k, default=None: "3")
    update_schedule()
    assert len(reschedule_calls) == 1
    assert reschedule_calls[0][0][0] == "crawl_job"


def test_stop_scheduler_shuts_down(monkeypatch):
    """stop_scheduler calls scheduler.shutdown."""
    shutdown_calls = []
    monkeypatch.setattr(scheduler_module.scheduler, "shutdown", lambda: shutdown_calls.append(1))
    stop_scheduler()
    assert len(shutdown_calls) == 1
