"""Unit tests for monitor.config (is_platform_allowed and env-based config)."""
import pytest

import monitor.config as config_module


@pytest.mark.parametrize(
    "allowed_list, site, expected",
    [
        (["juejin", "csdn"], "juejin", True),
        (["juejin", "csdn"], "csdn", True),
        (["juejin", "csdn"], "cnblog", False),
        (["juejin"], "juejin", True),
        ([], "juejin", True),
        ([], "anything", True),
        (["juejin"], "", False),
        (["juejin"], None, False),
    ],
)
def test_is_platform_allowed(allowed_list, site, expected, monkeypatch):
    """is_platform_allowed respects ALLOWED_PLATFORMS list and empty/None site."""
    monkeypatch.setattr(config_module, "ALLOWED_PLATFORMS", allowed_list)
    assert config_module.is_platform_allowed(site) is expected


def test_is_platform_allowed_with_whitelist(monkeypatch):
    """With a fixed whitelist, only listed platforms are allowed."""
    monkeypatch.setattr(config_module, "ALLOWED_PLATFORMS", ["juejin", "csdn"])
    assert config_module.is_platform_allowed("juejin") is True
    assert config_module.is_platform_allowed("csdn") is True
    assert config_module.is_platform_allowed("unknown_platform_xyz") is False
