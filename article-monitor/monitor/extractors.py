"""
阅读数提取器 - 配置化版本：使用配置文件定义提取规则
集成防反爬功能：User-Agent 轮换、隐身模式、随机延迟
"""
import re
import logging
from typing import Optional, Dict
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
import asyncio
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
    get_random_user_agent,
    get_random_viewport,
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
    """获取浏览器配置（支持防反爬）"""
    if ANTI_SCRAPING_ENABLED:
        manager = _get_anti_scraping_manager()
        profile = manager.get_browser_profile()
        
        return BrowserConfig(
            headless=True,
            viewport_width=profile.viewport_width,
            viewport_height=profile.viewport_height,
            user_agent=profile.user_agent,
            verbose=False,
            extra_args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
    else:
        # 默认配置（不启用防反爬）
        return BrowserConfig(
            headless=True,
            viewport_width=1280,
            viewport_height=800,
            verbose=False
        )


# 共享的浏览器配置（复用，避免重复创建）
# 注意：这里使用函数动态生成，支持防反爬
_SHARED_BROWSER_CONFIG = None  # 延迟初始化


def _ensure_browser_config() -> BrowserConfig:
    """确保浏览器配置已初始化"""
    global _SHARED_BROWSER_CONFIG
    if _SHARED_BROWSER_CONFIG is None:
        _SHARED_BROWSER_CONFIG = _get_browser_config()
    return _SHARED_BROWSER_CONFIG


# 默认的爬取配置
_DEFAULT_CRAWLER_CONFIG = CrawlerRunConfig(
    page_timeout=20000,  # 减少超时时间到20秒
    remove_overlay_elements=True,
    screenshot=False,  # 禁用截图以提升性能
    wait_for=None,  # 不等待特定元素，直接爬取
)


async def create_shared_crawler():
    """创建共享的浏览器实例（支持防反爬）"""
    # 每次创建时生成新的浏览器配置（如果启用了 UA 轮换）
    if ANTI_SCRAPING_ENABLED and ANTI_SCRAPING_ROTATE_UA:
        browser_config = _get_browser_config()
        logger.debug(f"🛡️ 创建防反爬浏览器实例")
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
    """
    try:
        # 执行人类化延迟（如果启用）
        if ANTI_SCRAPING_ENABLED and ANTI_SCRAPING_RANDOM_DELAY:
            manager = _get_anti_scraping_manager()
            await manager.human_delay()
        
        result = await crawler.arun(url, config=crawler_config)
        if not result.success:
            return None
        return result
    except Exception as e:
        logger.debug(f"爬取失败 {url}: {e}")
        return None

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


def _extract_title_from_html(html: str) -> Optional[str]:
    """从 HTML 中提取文章标题
    
    优先级：
    1. <title> 标签
    2. <h1> 标签
    3. og:title meta 标签
    """
    if not html:
        return None
    
    # 1. 尝试从 <title> 标签提取
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
        # 清理常见的网站后缀
        suffixes_to_remove = [
            r'\s*[-|_–—]\s*(掘金|CSDN|博客园|51CTO|SegmentFault|简书|电子发烧友|与非网|FreeBuf).*$',
            r'\s*[-|_–—]\s*.*博客.*$',
            r'\s*[-|_–—]\s*.*技术.*$',
        ]
        for suffix in suffixes_to_remove:
            title = re.sub(suffix, '', title, flags=re.IGNORECASE)
        if title:
            return title.strip()
    
    # 2. 尝试从 <h1> 标签提取
    h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.IGNORECASE | re.DOTALL)
    if h1_match:
        title = h1_match.group(1).strip()
        # 移除 HTML 标签
        title = re.sub(r'<[^>]+>', '', title)
        if title:
            return title.strip()
    
    # 3. 尝试从 og:title meta 标签提取
    og_match = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if og_match:
        return og_match.group(1).strip()
    
    # 反向匹配 og:title
    og_match2 = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']', html, re.IGNORECASE)
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
    wait_for = config.get('wait_for')
    timeout = config.get('timeout', 20000)
    parse_method = config.get('parse_method', 'number')
    delay_before_return = config.get('delay_before_return', 0)  # 额外延迟（毫秒）
    js_extract = config.get('js_extract', False)  # 是否使用 JavaScript 提取
    
    # 获取防反爬 JavaScript（隐身模式）
    stealth_js = ""
    if ANTI_SCRAPING_ENABLED and ANTI_SCRAPING_STEALTH_MODE:
        manager = _get_anti_scraping_manager()
        stealth_js = manager.get_stealth_js()
    
    # 对于 freebuf，使用 JavaScript 提取数字
    platform_js = ""
    if platform == 'freebuf' and config.get('js_extract', False):
        platform_js = """
        (() => {
            const reviewEl = document.querySelector('.review');
            if (!reviewEl) return null;
            const text = (reviewEl.textContent || reviewEl.innerText || '').trim();
            // 查找至少3位的数字（排除 SVG path 中的小数字）
            const numbers = text.match(/\\b([\\d,]{3,})\\b/g);
            if (numbers && numbers.length > 0) {
                // 选择最大的数字（最可能是阅读数）
                const maxNum = numbers.reduce((a, b) => {
                    const numA = parseInt(a.replace(/,/g, ''));
                    const numB = parseInt(b.replace(/,/g, ''));
                    return numA > numB ? a : b;
                });
                // 写入页面标题，方便后续提取
                document.title = 'READ_COUNT:' + maxNum;
                return maxNum;
            }
            return null;
        })();
        """
    
    # 合并 JavaScript 代码：先执行隐身脚本，再执行平台脚本
    combined_js = stealth_js
    if platform_js:
        combined_js = f"{stealth_js}\n{platform_js}" if stealth_js else platform_js
    
    crawler_config = CrawlerRunConfig(
        page_timeout=timeout,
        wait_for=wait_for,
        remove_overlay_elements=True,
        screenshot=False,
        js_code=combined_js if combined_js else None
    )
    
    # 使用共享浏览器或创建新实例
    if crawler:
        result = await _crawl_with_shared(url, crawler, crawler_config)
        if result is None:
            return (None, None)
    else:
        async with AsyncWebCrawler(config=_SHARED_BROWSER_CONFIG) as crawler_instance:
            result = await crawler_instance.arun(url, config=crawler_config)
            if not result.success:
                return (None, None)
    
    # 如果配置了额外延迟，等待 JavaScript 渲染
    if delay_before_return > 0:
        import asyncio
        await asyncio.sleep(delay_before_return / 1000.0)  # 转换为秒
    
    html = result.html
    markdown = result.markdown or ''
    
    # 提前提取文章标题
    article_title = _extract_title_from_html(html)
    
    # 对于 freebuf，如果配置了 JavaScript 提取，优先从标题中提取
    if platform == 'freebuf' and js_extract:
        # JavaScript 代码已经在爬取时执行，会将数字写入页面标题
        # 这里我们从 HTML 的 <title> 标签中提取
        title_match = re.search(r'<title[^>]*>READ_COUNT:([\d,]+)</title>', html, re.IGNORECASE)
        if title_match:
            count = _parse_number(title_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
        # 如果标题中没有，尝试从整个 HTML 中搜索
        title_match = re.search(r'READ_COUNT:([\d,]+)', html)
        if title_match:
            count = _parse_number(title_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
    
    # 对于 freebuf，如果配置了 JavaScript 提取，尝试其他方法
    if platform == 'freebuf' and js_code:
        try:
            # 尝试从 result 中获取 JavaScript 执行结果
            # 注意：crawl4ai 可能不直接返回 JS 结果，需要重新执行
            # 这里我们先用正则表达式，如果失败再考虑其他方法
            pass
        except:
            pass
    
    # 对于 freebuf，尝试从页面标题中提取（JavaScript 写入的）
    if platform == 'freebuf' and js_extract:
        # 先尝试从 <title> 标签中提取
        title_match = re.search(r'<title[^>]*>READ_COUNT:([\d,]+)</title>', html, re.IGNORECASE)
        if title_match:
            count = _parse_number(title_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
        # 如果标题中没有，尝试从整个 HTML 中搜索
        title_match = re.search(r'READ_COUNT:([\d,]+)', html)
        if title_match:
            count = _parse_number(title_match.group(1), parse_method)
            if count is not None and count > 0:
                return (count, article_title)
    
    # 对于 freebuf，尝试使用 JavaScript 直接从 DOM 提取
    if platform == 'freebuf' and hasattr(result, 'page') and result.page:
        try:
            # 使用 JavaScript 提取 .review 元素中的数字
            js_code = """
            () => {
                const reviewEl = document.querySelector('.review');
                if (!reviewEl) return null;
                const text = reviewEl.textContent || reviewEl.innerText;
                const match = text.match(/([\\d,]+)/);
                return match ? match[1] : null;
            }
            """
            # 注意：这里需要访问 page 对象，但 crawl4ai 可能不直接暴露
            # 先尝试从 HTML 提取，如果失败再考虑其他方法
        except:
            pass
    
    # 按优先级尝试每个模式
    for pattern in patterns:
        # 先在 HTML 中查找（使用 DOTALL 以匹配跨行内容）
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()  # 去除首尾空白
            count = _parse_number(text, parse_method)
            if count is not None and count > 0:  # 确保不是 0
                return (count, article_title)
        
        # 如果 HTML 中没找到，尝试在 markdown 中查找
        if markdown:
            match = re.search(pattern, markdown, re.IGNORECASE)
            if match:
                text = match.group(1)
                count = _parse_number(text, parse_method)
                if count is not None and count > 0:  # 确保不是 0
                    return (count, article_title)
    
    # 对于 freebuf，如果所有模式都失败，尝试使用 JavaScript 从 DOM 提取
    if platform == 'freebuf':
        # 如果 HTML 中没有找到数字，尝试使用 JavaScript 直接从 DOM 提取
        # 这需要重新访问页面，但可以获取渲染后的内容
        if crawler:
            try:
                # 使用 JavaScript 提取
                js_code = """
                () => {
                    const reviewEl = document.querySelector('.review');
                    if (!reviewEl) return null;
                    const text = reviewEl.textContent || reviewEl.innerText || '';
                    // 查找数字（排除 SVG path 中的数字）
                    const match = text.match(/\\s([\\d,]{3,})\\s/);
                    return match ? match[1] : null;
                }
                """
                js_config = CrawlerRunConfig(
                    page_timeout=timeout,
                    wait_for=wait_for,
                    remove_overlay_elements=True,
                    screenshot=False,
                    js_code=js_code
                )
                # 重新爬取页面，使用 JavaScript 提取数字
                js_result = await _crawl_with_shared(url, crawler, js_config)
                if js_result and js_result.success:
                    # 从标题中提取数字（JavaScript 写入的）
                    js_html = js_result.html
                    title_match = re.search(r'<title[^>]*>READ_COUNT:([\d,]+)</title>', js_html, re.IGNORECASE)
                    if title_match:
                        count = _parse_number(title_match.group(1), parse_method)
                        if count is not None and count > 0:
                            return (count, article_title)
                    # 如果标题中没有，尝试从整个 HTML 中搜索
                    title_match = re.search(r'READ_COUNT:([\d,]+)', js_html)
                    if title_match:
                        count = _parse_number(title_match.group(1), parse_method)
                        if count is not None and count > 0:
                            return (count, article_title)
                    # 尝试从 extracted_content 获取
                    if hasattr(js_result, 'extracted_content') and js_result.extracted_content:
                        try:
                            import json
                            js_data = json.loads(js_result.extracted_content)
                            if js_data:
                                count = _parse_number(js_data, parse_method)
                                if count is not None and count > 0:
                                    return (count, article_title)
                        except:
                            pass
                    # 如果 extracted_content 没有，从 HTML 中提取
                    js_html = js_result.html
                    review_section = re.search(r'class="review"[^>]*>.*?</span>', js_html, re.IGNORECASE | re.DOTALL)
                    if review_section:
                        section = review_section.group(0)
                        # 尝试匹配数字
                        num_match = re.search(r'</i>\s*([\d,]+)\s+</span>', section, re.IGNORECASE | re.DOTALL)
                        if num_match:
                            count = _parse_number(num_match.group(1), parse_method)
                            if count is not None and count > 0:
                                return (count, article_title)
            except:
                pass
        
        # 最后的备选方案：在整个 HTML 中搜索 .review 元素附近的数字
        review_section = re.search(r'class="review"[^>]*>.*?</span>', html, re.IGNORECASE | re.DOTALL)
        if review_section:
            section = review_section.group(0)
            # 优先查找 </i> 和 </span> 之间的数字（最可能的位置）
            patterns_to_try = [
                r'</i>\s*([\d,]+)\s+</span>',  # 数字后必须有空白字符
                r'</i>\s*([\d,]+)\s*</span>',  # 数字后可以有或没有空白字符
            ]
            
            for pattern in patterns_to_try:
                between_i_and_span = re.search(pattern, section, re.IGNORECASE | re.DOTALL)
                if between_i_and_span:
                    num_str = between_i_and_span.group(1)
                    count = _parse_number(num_str, parse_method)
                    if count is not None and count > 0:
                        return (count, article_title)
    
    return (None, article_title)


async def extract_article_info(url: str, crawler: Optional[AsyncWebCrawler] = None) -> Dict[str, any]:
    """提取文章信息（阅读数和标题）
    
    Args:
        url: 文章 URL
        crawler: 可选的共享浏览器实例
        
    Returns:
        包含 'read_count' 和 'title' 的字典
    """
    domain = urlparse(url).netloc.lower()
    
    # 根据域名匹配平台
    platform = None
    for site_domain, site_name in {
        'juejin.cn': 'juejin',
        'csdn.net': 'csdn',
        'cnblogs.com': 'cnblog',
        '51cto.com': '51cto',
        'segmentfault.com': 'segmentfault',
        'jianshu.com': 'jinshu',
        'elecfans.com': 'elecfans',
        'china.com': 'MBB',
        'eefocus.com': 'eefocus',
        'freebuf.com': 'freebuf'
    }.items():
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
