"""
Shared pytest fixtures for article-monitor tests.

- temp_db: Use a temporary SQLite database path and init_db(); patches
  monitor.config.DATABASE_PATH and monitor.db.connection.DATABASE_PATH so
  all DB access in the test uses the temp file. Cleanup after yield.
- task_manager_reset: Clears the TaskManager singleton so the next
  get_task_manager() creates a new instance (for tests that need isolation).
"""
import os
import pytest


@pytest.fixture
def temp_db(monkeypatch):
    """Use a temporary SQLite database for the test; init_db() is called."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        monkeypatch.setattr("monitor.config.DATABASE_PATH", path)
        monkeypatch.setattr("monitor.db.connection.DATABASE_PATH", path)
        from monitor.db.connection import init_db
        init_db()
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def task_manager_reset(monkeypatch):
    """Clear the TaskManager singleton so next get_task_manager() is fresh."""
    import monitor.task_manager as task_manager_module
    with task_manager_module.TaskManager._lock:
        task_manager_module.TaskManager._instance = None
    yield
    with task_manager_module.TaskManager._lock:
        task_manager_module.TaskManager._instance = None
