"""Smoke tests for monitor.platform_rules (PLATFORM_EXTRACTORS structure)."""
from monitor.platform_rules import PLATFORM_EXTRACTORS


REQUIRED_KEYS = {"patterns", "parse_method"}


def test_platform_extractors_non_empty():
    """PLATFORM_EXTRACTORS is non-empty."""
    assert len(PLATFORM_EXTRACTORS) > 0


def test_platform_extractors_each_has_required_keys():
    """Each platform entry has at least 'patterns' and 'parse_method'."""
    for name, rules in PLATFORM_EXTRACTORS.items():
        assert isinstance(rules, dict), f"{name} should be a dict"
        for key in REQUIRED_KEYS:
            assert key in rules, f"{name} missing key {key}"
        assert isinstance(rules["patterns"], list), f"{name}.patterns should be list"
        assert len(rules["patterns"]) > 0, f"{name}.patterns should be non-empty"
        assert rules["parse_method"] in ("number", "number_with_suffix"), (
            f"{name}.parse_method should be 'number' or 'number_with_suffix'"
        )
