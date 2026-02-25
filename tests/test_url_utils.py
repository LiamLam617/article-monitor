import pytest

from monitor.url_utils import normalize_url, validate_url, validate_and_normalize_url
from monitor.config import SUPPORTED_SITES


def test_normalize_url_juejin_spost_to_post():
    original = "https://juejin.cn/spost/123456"
    normalized = normalize_url(original)
    assert "/post/" in normalized
    assert "/spost/" not in normalized


def test_normalize_url_other_unchanged():
    original = "https://example.com/path"
    assert normalize_url(original) == original


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://example.com", True),
        ("http://example.com/path", True),
        ("ftp://example.com", False),
        ("not-a-url", False),
        ("http://", False),
    ],
)
def test_validate_url(url, expected):
    assert validate_url(url) is expected


def test_validate_and_normalize_url_detects_supported_site():
    # 取一個已知支援的 domain，例如 juejin.cn
    # 尋找對應的 site_name 以避免硬編碼
    juejin_site_name = SUPPORTED_SITES.get("juejin.cn")
    assert juejin_site_name is not None

    url = "https://juejin.cn/post/123"
    is_valid, normalized, site = validate_and_normalize_url(url)

    assert is_valid is True
    assert normalized == url  # 已是標準格式，應不變
    assert site == juejin_site_name


def test_validate_and_normalize_url_empty_string():
    """Empty string returns invalid, original, None."""
    is_valid, normalized, site = validate_and_normalize_url("")
    assert is_valid is False
    assert normalized == ""
    assert site is None


def test_validate_and_normalize_url_unsupported_domain():
    """Valid http URL but unsupported domain returns valid, normalized URL, site None."""
    url = "https://example.com/page"
    is_valid, normalized, site = validate_and_normalize_url(url)
    assert is_valid is True
    assert normalized == url
    assert site is None


def test_validate_and_normalize_url_strips_whitespace():
    """Leading/trailing whitespace is stripped before validation."""
    url = "  https://juejin.cn/post/1  "
    is_valid, normalized, site = validate_and_normalize_url(url)
    assert is_valid is True
    assert normalized == "https://juejin.cn/post/1"
    assert site == "juejin"


def test_validate_url_value_error_path():
    """validate_url returns False for invalid input (e.g. non-string)."""
    # urlparse can accept None in some versions but may raise; ensure we don't assume True
    assert validate_url("") is False

