from urllib.parse import urlparse
from typing import Optional

from .config import SUPPORTED_SITES
import logging

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """規範化 URL，修正已知平台的非標準格式"""
    # 掘金: spost -> post
    if 'juejin.cn' in url:
        url = url.replace('/spost/', '/post/')
    return url


def validate_url(url: str) -> bool:
    """驗證 URL 是否安全有效
    
    Args:
        url: 要驗證的 URL
        
    Returns:
        如果 URL 有效且安全，返回 True；否則返回 False
    """
    try:
        parsed = urlparse(url)
        # 只允許 http 和 https
        if parsed.scheme not in ('http', 'https'):
            return False
        # 檢查域名是否為空
        if not parsed.netloc:
            return False
        # 基本格式檢查通過
        return True
    except (ValueError, AttributeError):
        return False


def validate_and_normalize_url(url: str) -> tuple[bool, str, Optional[str]]:
    """驗證並規範化 URL，檢測平台
    
    Args:
        url: 原始 URL
        
    Returns:
        (is_valid, normalized_url, site) 元組
        - is_valid: URL 是否有效
        - normalized_url: 規範化後的 URL
        - site: 平台名稱（如果檢測到），否則為 None
    """
    url = normalize_url(url.strip())
    
    if not url:
        return False, url, None
    
    if not validate_url(url):
        return False, url, None
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        site = None
        for site_domain, site_name in SUPPORTED_SITES.items():
            if site_domain in domain:
                site = site_name
                break
        return True, url, site
    except (ValueError, AttributeError) as e:
        logger.debug(f"URL解析失败 {url}: {e}")
        return False, url, None

