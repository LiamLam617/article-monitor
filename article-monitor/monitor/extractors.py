"""
阅读数提取器 - 配置化版本：使用配置文件定义提取规则
集成防反爬功能：User-Agent 轮换、隐身模式、随机延迟
优化：预编译正则表达式，提升匹配速度
"""
import re
import logging
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from functools import lru_cache
from .config import (
    PLATFORM_EXTRACTORS,
    ANTI_SCRAPING_ENABLED,
    ANTI_SCRAPING_ROTATE_UA,
    ANTI_SCRAPING_RANDOM_DELAY,
    ANTI_SCRAPING_STEALTH_MODE,
    ANTI_SCRAPING_MIN_DELAY,
    ANTI_SCRAPING_MAX_DELAY
)
from .anti_scraping import (
    get_anti_scraping_manager,
    AntiScrapingManager
)

logger = logging.getLogger(__name__)

# 防反爬管理器实例
_anti_scraping_manager: Optional[AntiScrapingManager] = None


def _get_anti_scraping_manager() -> AntiScrapingManager:
    """获取防反爬管理器单例"""
    global _anti_scraping_manager
    if _anti_scraping_manager is None:
        _anti_scraping_manager = get_anti_scraping_manager(
            rotate_user_agent=ANTI_SCRAPING_ROTATE_UA,
            random_delay=ANTI_SCRAPING_RANDOM_DELAY,
            stealth_mode=ANTI_SCRAPING_STEALTH_MODE,
            min_delay=ANTI_SCRAPING_MIN_DELAY,
            max_delay=ANTI_SCRAPING_MAX_DELAY
        )
    return _anti_scraping_manager


def _get_browser_config() -> BrowserConfig:
    """获取浏览器配置（支持防反爬）
    
    优化：
    - 添加性能优化参数，减少资源消耗
    - 使用完整的 BrowserProfile 和 HTTP headers
    - 整合 AntiScrapingManager 的配置
    """
    # 基础性能优化参数（适用于所有配置）
    base_extra_args = [
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-gpu',  # 禁用 GPU 加速（headless 模式）
        '--disable-software-rasterizer',  # 禁用软件光栅化
        '--disable-extensions',  # 禁用扩展
        '--disable-plugins',  # 禁用插件
        '--disable-images',  # 禁用图片加载（提升速度）
    ]
    
    if ANTI_SCRAPING_ENABLED:
        manager = _get_anti_scraping_manager()
        profile = manager.get_browser_profile()
        # 获取完整的 HTTP 请求头（包含 Accept-Language、Sec-Ch-Ua、Referer 等）
        headers = manager.get_http_headers()
        
        # 整合 extra_args：合并基础参数和防反爬参数
        # 注意：window-size 已经在 viewport 中设置，不需要重复
        extra_args = base_extra_args + [
            '--disable-setuid-sandbox',  # 从 get_browser_config() 中添加
        ]
        
        return BrowserConfig(
            headless=True,
            viewport_width=profile.viewport_width,
            viewport_height=profile.viewport_height,
            user_agent=profile.user_agent,
            headers=headers,  # 添加完整的 HTTP 请求头，提升反检测能力
            verbose=False,
            extra_args=extra_args
        )
    else:
        # 默认配置（不启用防反爬）
        return BrowserConfig(
            headless=True,
            viewport_width=1280,
            viewport_height=800,
            verbose=False,
            extra_args=base_extra_args
        )

def get_browser_config() -> BrowserConfig:
    """获取浏览器配置（公开接口，供其他模块使用）"""
    return _get_browser_config()

def ensure_browser_config() -> BrowserConfig:
    """确保浏览器配置已初始化（公开接口，供其他模块使用）"""
    return _ensure_browser_config()


# 共享的浏览器配置（复用，避免重复创建）
# 注意：这里使用函数动态生成，支持防反爬
# 优化：对于防反爬模式，每次获取新配置以支持轮换；对于非防反爬模式，复用配置
_SHARED_BROWSER_CONFIG = None  # 延迟初始化（仅用于非防反爬模式）


def _ensure_browser_config() -> BrowserConfig:
    """确保浏览器配置已初始化
    
    优化：对于防反爬模式，每次获取新配置以支持轮换和指纹一致性
    对于非防反爬模式，复用配置以提升性能
    """
    global _SHARED_BROWSER_CONFIG
    # 如果启用防反爬，每次都获取新配置（支持轮换）
    if ANTI_SCRAPING_ENABLED:
        return _get_browser_config()
    # 非防反爬模式，复用配置
    if _SHARED_BROWSER_CONFIG is None:
        _SHARED_BROWSER_CONFIG = _get_browser_config()
    return _SHARED_BROWSER_CONFIG


async def create_shared_crawler():
    """创建共享的浏览器实例（支持防反爬）
    
    优化：优先从浏览器池获取，如果池已满则创建独立实例
    """
    from .browser_pool import get_browser_pool
    browser_pool = get_browser_pool()
    
    # 尝试从池中获取
    crawler = await browser_pool.acquire()
    if crawler:
        return crawler
    
    # 池已满，创建独立实例
    if ANTI_SCRAPING_ENABLED and ANTI_SCRAPING_ROTATE_UA:
        browser_config = _get_browser_config()
        logger.debug(f"🛡️ 创建防反爬浏览器实例（独立）")
    else:
        browser_config = _ensure_browser_config()
    
    crawler = AsyncWebCrawler(config=browser_config)
    await crawler.__aenter__()
    return crawler

def parse_read_count(text: str) -> Optional[int]:
    """从文本中提取数字，处理 k/m/w 后缀和逗号分隔符
    
    支持的格式：
    - 纯数字: "1000" -> 1000
    - 带逗号: "1,234" -> 1234
    - k后缀: "1k" -> 1000, "20k" -> 20000, "1.5k" -> 1500
    - m后缀: "1m" -> 1000000, "2.5m" -> 2500000
    - w后缀: "1w" -> 10000, "10w" -> 100000
    - 混合: "1,234.5k" -> 1234500
    
    示例：
        parse_read_count("1k") -> 1000
        parse_read_count("20k") -> 20000
        parse_read_count("1.5k") -> 1500
    """
    if not text:
        return None
    
    # 移除所有空格
    text = text.strip().replace(' ', '')
    
    # 匹配数字（支持小数点、逗号）和k/m/w后缀
    # 模式说明：
    #   [\d,]+         匹配数字和逗号（整数部分）
    #   (?:\.[\d,]+)?  匹配可选的小数部分（包含小数点）
    #   ([kmwKMW]?)    匹配可选的后缀（k/m/w，大小写不敏感）
    match = re.search(r'([\d,]+(?:\.[\d,]+)?)([kmwKMW]?)', text)
    if not match:
        return None
    
    number_str = match.group(1)
    suffix = match.group(2).lower()
    
    # 移除所有逗号，转换为浮点数
    number_str = number_str.replace(',', '')
    
    try:
        number = float(number_str)
    except ValueError:
        return None
    
    # 后缀倍数映射
    multipliers = {
        'k': 1000,      # 千: 1k = 1000, 20k = 20000
        'm': 1000000,   # 百万: 1m = 1000000
        'w': 10000      # 万（中文）: 1w = 10000
    }
    multiplier = multipliers.get(suffix, 1)
    
    # 计算最终结果并转换为整数
    result = int(number * multiplier)
    return result

async def _crawl_with_shared(url: str, crawler: AsyncWebCrawler, crawler_config: CrawlerRunConfig):
    """使用共享浏览器实例爬取页面（内部函数）
    
    集成防反爬功能：人类化延迟
    优化：区分不同类型的错误，提供更详细的日志
    """
    try:
        # 执行人类化延迟（如果启用）
        if ANTI_SCRAPING_ENABLED and ANTI_SCRAPING_RANDOM_DELAY:
            manager = _get_anti_scraping_manager()
            await manager.human_delay()
        
        result = await crawler.arun(url, config=crawler_config)
        if not result.success:
            # 记录失败原因（如果 result 有错误信息）
            error_msg = getattr(result, 'error', '未知错误')
            logger.debug(f"爬取失败 {url}: {error_msg}")
            return None
        return result
    except asyncio.TimeoutError as e:
        logger.warning(f"⏱️ 爬取超时 {url}: {e}")
        return None
    except ConnectionError as e:
        logger.warning(f"🔌 连接错误 {url}: {e}")
        return None
    except Exception as e:
        # 根据错误类型分类记录
        error_str = str(e).lower()
        if 'timeout' in error_str or 'timed out' in error_str:
            logger.warning(f"⏱️ 超时错误 {url}: {e}")
        elif 'connection' in error_str or 'network' in error_str:
            logger.warning(f"🔌 网络错误 {url}: {e}")
        elif 'ssl' in error_str or 'certificate' in error_str:
            logger.warning(f"🔒 SSL错误 {url}: {e}")
        else:
            logger.warning(f"⚠️ 爬取失败 {url}: {e}")
        return None

@lru_cache(maxsize=None)  # 无界缓存，因为模式数量有限且固定
def _compile_pattern(pattern: str) -> re.Pattern:
    """编译正则表达式（缓存编译结果，提升性能）"""
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)

def _parse_number(text: str, method: str = 'number') -> Optional[int]:
    """根据指定方法解析数字
    
    Args:
        text: 要解析的文本
        method: 解析方法
            - 'number': 仅提取纯数字（不支持k/m/w后缀）
            - 'number_with_suffix': 支持k/m/w后缀（如 1k=1000, 20k=20000）
    
    Returns:
        解析后的整数，失败返回 None
    """
    if not text:
        return None
    
    if method == 'number_with_suffix':
        # 使用 parse_read_count 处理带后缀的数字
        # 注意：parse_read_count 内部会处理空格和逗号
        return parse_read_count(text)
    else:
        # 仅提取纯数字（不支持后缀）
        # 移除空格和逗号，然后提取第一个数字
        text = text.strip().replace(' ', '').replace(',', '')
        match = re.search(r'(\d+)', text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None


# 预编译标题提取的正则表达式（优化性能）
_TITLE_PATTERNS = {
    'title': re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE),
    'h1': re.compile(r'<h1[^>]*>([^<]+)</h1>', re.IGNORECASE | re.DOTALL),
    'og_title1': re.compile(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', re.IGNORECASE),
    'og_title2': re.compile(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', re.IGNORECASE),
}
_TITLE_SUFFIX_PATTERNS = [
    re.compile(r'\s*[-|_–—]\s*(掘金|CSDN|博客园|51CTO|SegmentFault|简书|电子发烧友|与非网).*$', re.IGNORECASE),
    re.compile(r'\s*[-|_–—]\s*.*博客.*$', re.IGNORECASE),
    re.compile(r'\s*[-|_–—]\s*.*技术.*$', re.IGNORECASE),
]
_HTML_TAG_PATTERN = re.compile(r'<[^>]+>')

def _extract_title_from_html(html: str) -> Optional[str]:
    """从 HTML 中提取文章标题（优化：使用预编译正则表达式）
    
    优先级：
    1. <title> 标签
    2. <h1> 标签
    3. og:title meta 标签
    """
    if not html:
        return None
    
    # 1. 尝试从 <title> 标签提取
    title_match = _TITLE_PATTERNS['title'].search(html)
    if title_match:
        title = title_match.group(1).strip()
        # 清理常见的网站后缀（使用预编译正则）
        for suffix_pattern in _TITLE_SUFFIX_PATTERNS:
            title = suffix_pattern.sub('', title)
        if title:
            return title.strip()
    
    # 2. 尝试从 <h1> 标签提取
    h1_match = _TITLE_PATTERNS['h1'].search(html)
    if h1_match:
        title = h1_match.group(1).strip()
        # 移除 HTML 标签
        title = _HTML_TAG_PATTERN.sub('', title)
        if title:
            return title.strip()
    
    # 3. 尝试从 og:title meta 标签提取
    og_match = _TITLE_PATTERNS['og_title1'].search(html)
    if og_match:
        return og_match.group(1).strip()
    
    # 反向匹配 og:title
    og_match2 = _TITLE_PATTERNS['og_title2'].search(html)
    if og_match2:
        return og_match2.group(1).strip()
    
    return None


async def extract_with_config(url: str, platform: str, crawler: Optional[AsyncWebCrawler] = None) -> Optional[int]:
    """使用配置文件提取阅读数
    
    Args:
        url: 目标URL
        platform: 平台标识（如 'juejin', 'csdn'）
        crawler: 可选的共享浏览器实例
    
    Returns:
        阅读数，失败返回 None
    """
    if platform not in PLATFORM_EXTRACTORS:
        return None
    
    # 调用完整版本，只返回阅读数
    read_count, _ = await extract_with_config_full(url, platform, crawler)
    return read_count


async def extract_with_config_full(url: str, platform: str, crawler: Optional[AsyncWebCrawler] = None) -> tuple:
    """使用配置文件提取阅读数和标题
    
    Args:
        url: 目标URL
        platform: 平台标识（如 'juejin', 'csdn'）
        crawler: 可选的共享浏览器实例
    
    Returns:
        (阅读数, 标题) 元组，失败时对应值为 None
    """
    if platform not in PLATFORM_EXTRACTORS:
        return (None, None)
    
    config = PLATFORM_EXTRACTORS[platform]
    patterns = config.get('patterns', [])
    # 预编译正则表达式（提升性能）
    # HTML 使用 DOTALL 模式（支持跨行匹配），markdown 不使用
    compiled_patterns_html = [_compile_pattern(p) for p in patterns]
    compiled_patterns_markdown = [re.compile(p, re.IGNORECASE) for p in patterns]
    wait_for = config.get('wait_for')
    timeout = config.get('timeout', 20000)
    parse_method = config.get('parse_method', 'number')
    delay_before_return = config.get('delay_before_return', 0)  # 额外延迟（毫秒）
    js_extract = config.get('js_extract', False)  # 是否使用 JavaScript 提取
    
    # 获取防反爬配置（如果启用）
    base_crawler_config = {}
    js_parts = []
    
    if ANTI_SCRAPING_ENABLED:
        manager = _get_anti_scraping_manager()
        # 获取基础防反爬配置
        base_crawler_config = manager.get_crawler_config(
            timeout=timeout,
            wait_for=wait_for
        )
        # 如果防反爬配置中有 js_code，添加到 js_parts
        if base_crawler_config.get('js_code'):
            js_parts.append(base_crawler_config['js_code'])
            # 移除 js_code，稍后合并所有 JS 代码
            base_crawler_config.pop('js_code', None)
    
    # 平台特定的 JavaScript 提取逻辑
    if js_extract and platform == 'sohu':
        # 搜狐：wait_for 已确保数字加载完成，这里直接提取并注入标记
        platform_js = """
        (() => {
            const pvEl = document.querySelector('em[data-role="pv"]');
            if (pvEl) {
                const text = pvEl.textContent.trim();
                if (/^\\d+$/.test(text)) {
                    // 在 HTML 中注入明确的标记，确保能被正则提取
                    const marker = document.createElement('script');
                    marker.type = 'text/plain';
                    marker.id = 'sohu-pv-marker';
                    marker.textContent = 'SOHU_PV_COUNT:' + text;
                    document.head.appendChild(marker);
                    console.log('Sohu PV injected:', text);
                    return text;
                }
            }
            return null;
        })();
        """
        js_parts.append(platform_js)
    
    # 合并 JavaScript 代码：先执行隐身脚本，再执行平台脚本
    combined_js = '\n'.join(js_parts) if js_parts else None
    
    # 创建爬取配置（整合防反爬配置和平台特定配置）
    crawler_config = CrawlerRunConfig(
        page_timeout=timeout,
        wait_for=wait_for,
        remove_overlay_elements=base_crawler_config.get('remove_overlay_elements', True),  # 移除弹窗和遮罩层
        screenshot=base_crawler_config.get('screenshot', False),  # 禁用截图以提升性能
        js_code=combined_js if combined_js else None
    )
    
    # 使用共享浏览器或创建新实例
    if crawler:
        # 使用传入的共享浏览器实例
        result = await _crawl_with_shared(url, crawler, crawler_config)
        if result is None:
            return (None, None)
    else:
        # 没有传入 crawler，尝试从浏览器池获取或创建临时实例
        from .browser_pool import get_browser_pool
        browser_pool = get_browser_pool()
        
        # 尝试从池中获取
        pool_crawler = await browser_pool.acquire()
        if pool_crawler:
            try:
                result = await _crawl_with_shared(url, pool_crawler, crawler_config)
                if result is None:
                    return (None, None)
            finally:
                # 确保释放回池中
                await browser_pool.release(pool_crawler)
        else:
            # 池已满，创建临时实例（使用上下文管理器确保正确清理）
            browser_config = _ensure_browser_config()
            async with AsyncWebCrawler(config=browser_config) as temp_crawler:
                result = await temp_crawler.arun(url, config=crawler_config)
                if not result.success:
                    return (None, None)
    
    # 如果配置了额外延迟，等待 JavaScript 渲染
    if delay_before_return > 0:
        await asyncio.sleep(delay_before_return / 1000.0)  # 转换为秒
    
    html = result.html
    markdown = result.markdown or ''
    
    # 检测验证码（部分网站的反爬机制）
    captcha_indicators = ['访问验证', '请按住滑块', '拖动到最右边', '滑块验证', 'CAPTCHA_DETECTED']
    for indicator in captcha_indicators:
        if indicator in html:
            logger.warning(f"🔒 检测到验证码，无法提取: {url}")
            return (None, None)
    
    # 提前提取文章标题
    article_title = _extract_title_from_html(html)
    
    # 如果配置了 JavaScript 提取，优先从标记中提取（支持 sohu 等）
    if js_extract:
        # 方法1: 从 READ_COUNT 标记提取
        title_match = re.search(r'READ_COUNT:([\d,]+)', html)
        if title_match:
            count = _parse_number(title_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
        
        # 方法2: 从 SOHU_READ_COUNT 标记提取（搜狐专用，支持 HTML 注释格式）
        sohu_match = re.search(r'SOHU_READ_COUNT:([\d,]+)', html)
        if sohu_match:
            count = _parse_number(sohu_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
        
        # 方法3: 从 SOHU_PV_COUNT 标记提取（搜狐专用）
        sohu_pv_match = re.search(r'SOHU_PV_COUNT:(\d+)', html)
        if sohu_pv_match:
            count = _parse_number(sohu_pv_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
    
    # 按优先级尝试每个模式（使用预编译的正则表达式）
    for i, compiled_pattern_html in enumerate(compiled_patterns_html):
        # 先在 HTML 中查找
        match = compiled_pattern_html.search(html)
        if match:
            text = match.group(1).strip()  # 去除首尾空白
            count = _parse_number(text, parse_method)
            if count is not None and count > 0:  # 确保不是 0
                return (count, article_title)
        
        # 如果 HTML 中没找到，尝试在 markdown 中查找（使用对应的预编译模式）
        if markdown:
            compiled_pattern_md = compiled_patterns_markdown[i]
            match = compiled_pattern_md.search(markdown)
            if match:
                text = match.group(1)
                count = _parse_number(text, parse_method)
                if count is not None and count > 0:  # 确保不是 0
                    return (count, article_title)
    
    # 如果所有模式都失败，返回 None
    return (None, article_title)


async def extract_article_info(url: str, crawler: Optional[AsyncWebCrawler] = None) -> Dict[str, Any]:
    """提取文章信息（阅读数和标题）
    
    Args:
        url: 文章 URL
        crawler: 可选的共享浏览器实例
        
    Returns:
        包含 'read_count' 和 'title' 的字典
    """
    from .config import SUPPORTED_SITES
    
    domain = urlparse(url).netloc.lower()
    
    # 根据域名匹配平台（使用配置文件中的映射）
    platform = None
    for site_domain, site_name in SUPPORTED_SITES.items():
        if site_domain in domain:
            platform = site_name
            break
    
    result = {'read_count': None, 'title': None}
    
    if platform and platform in PLATFORM_EXTRACTORS:
        result['read_count'], result['title'] = await extract_with_config_full(url, platform, crawler)
    elif 'generic' in PLATFORM_EXTRACTORS:
        result['read_count'], result['title'] = await extract_with_config_full(url, 'generic', crawler)
    
    return result


async def extract_read_count(url: str, crawler: Optional[AsyncWebCrawler] = None) -> Optional[int]:
    """根据URL自动选择提取器（仅返回阅读数）"""
    info = await extract_article_info(url, crawler)
    return info.get('read_count')
