"""Unit tests for monitor.task_manager (submit_task, get_task, TaskStatus)."""
import asyncio
import time

import pytest

from monitor.task_manager import (
    get_task_manager,
    TaskManager,
    TaskStatus,
)


def test_task_status_enum_values():
    """TaskStatus has expected values."""
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.CANCELLED.value == "cancelled"


def test_get_task_manager_singleton():
    """get_task_manager returns the same instance."""
    a = get_task_manager()
    b = get_task_manager()
    assert a is b


def test_submit_task_returns_task_id():
    """submit_task returns a non-empty task_id."""

    async def noop(task_id, x):
        pass

    manager = get_task_manager()
    task_id = manager.submit_task(noop, "arg")
    assert task_id
    assert isinstance(task_id, str)
    assert len(task_id) > 0


def test_get_task_returns_status_and_eventually_completed():
    """After submitting a no-op task, get_task shows status and eventually COMPLETED."""

    async def quick_noop(task_id):
        await asyncio.sleep(0.05)

    manager = get_task_manager()
    task_id = manager.submit_task(quick_noop)
    info = manager.get_task(task_id)
    assert info is not None
    assert info["id"] == task_id
    assert info["status"] in ("pending", "running", "completed")

    # Poll until completed or timeout
    for _ in range(50):
        info = manager.get_task(task_id)
        if info and info["status"] == "completed":
            break
        time.sleep(0.1)
    assert info is not None
    assert info["status"] == "completed"


def test_get_task_nonexistent_returns_none():
    """get_task for non-existent task_id returns None."""
    manager = get_task_manager()
    assert manager.get_task("nonexistent-task-id-12345") is None
