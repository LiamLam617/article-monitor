"""
爬取任务 - 优化版本：并发爬取，复用浏览器实例，重试机制，防反爬
支持每域名并发限制与按站点交错调度，提高同一站点大量文章时的成功率
"""
import asyncio
import threading
import time
import logging
import random
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum
from uuid import uuid4
from .database import (
    get_all_articles, add_read_count, get_latest_read_count,
    get_latest_read_counts_batch, update_article_title, update_article_status
)
from .extractors import extract_article_info, create_shared_crawler
from urllib.parse import urlparse
from .config import (
    SUPPORTED_SITES, CRAWL_CONCURRENCY, CRAWL_DELAY,
    CRAWL_CONCURRENCY_PER_DOMAIN, CRAWL_INTERLEAVE_BY_SITE, CRAWL_MIN_DELAY_PER_DOMAIN,
    CRAWL_MAX_RETRIES, CRAWL_RETRY_DELAY, CRAWL_RETRY_BACKOFF,
    CRAWL_RETRY_MAX_DELAY, CRAWL_RETRY_JITTER,
    CRAWL_RETRY_NETWORK_MAX, CRAWL_RETRY_PARSE_MAX, CRAWL_RETRY_SSL_MAX, CRAWL_RETRY_SSL_DELAY,
    ANTI_SCRAPING_ENABLED, ANTI_SCRAPING_RANDOM_DELAY,
    ANTI_SCRAPING_MIN_DELAY, ANTI_SCRAPING_MAX_DELAY,
    is_platform_allowed
)
from .anti_scraping import get_anti_scraping_manager, reset_anti_scraping_manager
from .logging_context import bind_context_fields, set_log_context, reset_log_context

logger = logging.getLogger(__name__)


def _log_crawl_event(event: str, **fields):
    logger.info(event, extra=bind_context_fields({"event": event, **fields}))

# 全局进度状态（线程安全：使用锁保护）
_crawl_progress_lock = threading.Lock()
_crawl_progress = {
    'is_running': False,
    'total': 0,
    'current': 0,
    'success': 0,
    'failed': 0,
    'retried': 0,
    'current_url': None,
    'start_time': None,
    'end_time': None
}

# 全局停止信号（线程安全：使用锁保护）
_stop_signal_lock = threading.Lock()
_stop_signal = False

def stop_crawling():
    """停止爬取任务（线程安全）"""
    global _stop_signal
    with _stop_signal_lock:
        _stop_signal = True
    logger.info("🛑 收到停止信号，正在停止爬取...")

def get_crawl_progress():
    """获取爬取进度（线程安全）"""
    with _crawl_progress_lock:
        return _crawl_progress.copy()

def reset_crawl_progress():
    """重置爬取进度（线程安全）"""
    global _crawl_progress
    with _crawl_progress_lock:
        _crawl_progress = {
            'is_running': False,
            'total': 0,
            'current': 0,
            'success': 0,
            'failed': 0,
            'retried': 0,
            'current_url': None,
            'start_time': None,
            'end_time': None
        }


def _domain_from_article(article: dict) -> str:
    """从文章 URL 提取 netloc 作为域名 key（用于每域名限流）。"""
    url = article.get('url') or ''
    try:
        return urlparse(url).netloc.lower() or 'unknown'
    except Exception:
        return 'unknown'


# 每域名信号量注册表（lazy 创建，仅在单次 crawl 运行内使用，key=domain, value=Semaphore）
_domain_semaphores: Dict[str, asyncio.Semaphore] = {}
# 每事件循环一个 asyncio.Lock，避免「bound to a different event loop」（爬取在子线程的 loop 中运行）
_loop_locks_guard = threading.Lock()
_domain_semaphores_lock_by_loop: Dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
_domain_rate_limit_lock_by_loop: Dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}


def _get_semaphores_lock_for_current_loop() -> asyncio.Lock:
    """返回当前事件循环对应的「信号量表」锁（懒创建，线程安全）。"""
    loop = asyncio.get_running_loop()
    with _loop_locks_guard:
        for closed_loop in [loop for loop in _domain_semaphores_lock_by_loop if loop.is_closed()]:
            _domain_semaphores_lock_by_loop.pop(closed_loop, None)
        if loop not in _domain_semaphores_lock_by_loop:
            _domain_semaphores_lock_by_loop[loop] = asyncio.Lock()
        return _domain_semaphores_lock_by_loop[loop]


def _get_rate_limit_lock_for_current_loop() -> asyncio.Lock:
    """返回当前事件循环对应的「每域名限速」锁（懒创建，线程安全）。"""
    loop = asyncio.get_running_loop()
    with _loop_locks_guard:
        for closed_loop in [loop for loop in _domain_rate_limit_lock_by_loop if loop.is_closed()]:
            _domain_rate_limit_lock_by_loop.pop(closed_loop, None)
        if loop not in _domain_rate_limit_lock_by_loop:
            _domain_rate_limit_lock_by_loop[loop] = asyncio.Lock()
        return _domain_rate_limit_lock_by_loop[loop]


async def _get_domain_semaphore(domain: str) -> Optional[asyncio.Semaphore]:
    """返回该域名的信号量；若 CRAWL_CONCURRENCY_PER_DOMAIN 为 0 则返回 None（不限制）。"""
    if CRAWL_CONCURRENCY_PER_DOMAIN <= 0:
        return None
    sem_lock = _get_semaphores_lock_for_current_loop()
    async with sem_lock:
        if domain not in _domain_semaphores:
            _domain_semaphores[domain] = asyncio.Semaphore(CRAWL_CONCURRENCY_PER_DOMAIN)
        return _domain_semaphores[domain]


def _reset_domain_semaphores():
    """清空每域名信号量表（在每次 crawl 开始时调用，避免跨次累积）。"""
    global _domain_semaphores
    _domain_semaphores = {}
    with _loop_locks_guard:
        for closed_loop in [loop for loop in _domain_semaphores_lock_by_loop if loop.is_closed()]:
            _domain_semaphores_lock_by_loop.pop(closed_loop, None)


# 每域名上次请求结束时间（用于 CRAWL_MIN_DELAY_PER_DOMAIN）
_domain_last_request_time: Dict[str, float] = {}


async def _wait_domain_rate_limit(domain: str) -> None:
    """若配置了 CRAWL_MIN_DELAY_PER_DOMAIN，则等待至满足最小间隔。"""
    if CRAWL_MIN_DELAY_PER_DOMAIN <= 0:
        return
    now = time.monotonic()
    rate_limit_lock = _get_rate_limit_lock_for_current_loop()
    async with rate_limit_lock:
        last = _domain_last_request_time.get(domain, 0)
        sleep_time = last + CRAWL_MIN_DELAY_PER_DOMAIN - now
    if sleep_time > 0:
        await asyncio.sleep(sleep_time)


async def _record_domain_request_done(domain: str) -> None:
    """记录该域名本次请求已结束（在 crawl 完成后调用）。"""
    if CRAWL_MIN_DELAY_PER_DOMAIN <= 0:
        return
    rate_limit_lock = _get_rate_limit_lock_for_current_loop()
    async with rate_limit_lock:
        _domain_last_request_time[domain] = time.monotonic()


def _reset_domain_rate_limit():
    """清空每域名请求时间（每次 crawl 开始时调用）。"""
    global _domain_last_request_time
    _domain_last_request_time = {}
    with _loop_locks_guard:
        for closed_loop in [loop for loop in _domain_rate_limit_lock_by_loop if loop.is_closed()]:
            _domain_rate_limit_lock_by_loop.pop(closed_loop, None)


def _interleave_articles_by_site(articles: List[dict]) -> List[dict]:
    """按站点 round-robin 打散文章顺序，使并发更均匀分布在多站点。"""
    if not articles:
        return articles
    groups = defaultdict(list)
    for a in articles:
        key = _domain_from_article(a)
        groups[key].append(a)
    keys = list(groups.keys())
    interleaved = []
    idx = 0
    while any(groups[k] for k in keys):
        k = keys[idx % len(keys)]
        if groups[k]:
            interleaved.append(groups[k].pop(0))
        idx += 1
    return interleaved


class ErrorCategory(Enum):
    """错误分类枚举"""
    NETWORK = 'network'  # 网络错误（可重试）
    PARSE = 'parse'  # 解析错误（可重试，但重试次数较少）
    SSL = 'ssl'  # SSL/证书错误（可重试，需要更长延迟）
    PERMANENT = 'permanent'  # 永久性错误（不重试）
    UNKNOWN = 'unknown'  # 未知错误（默认可重试）

# 重试优先级映射（数字越小优先级越高）
RETRY_PRIORITY_MAP = {
    ErrorCategory.NETWORK: 1,
    ErrorCategory.UNKNOWN: 1,
    ErrorCategory.PARSE: 2,
    ErrorCategory.SSL: 3,
    ErrorCategory.PERMANENT: 4
}

def _get_error_category(error: Exception) -> ErrorCategory:
    """智能错误分类
    
    Args:
        error: 异常对象
        
    Returns:
        ErrorCategory: 错误分类
    """
    error_str = str(error).lower()
    
    # 永久性错误（不重试）
    permanent_keywords = ['404', 'not found', '403', 'forbidden', '401', 'unauthorized']
    if any(keyword in error_str for keyword in permanent_keywords):
        return ErrorCategory.PERMANENT
    
    # SSL/证书错误
    ssl_keywords = ['ssl', 'certificate', 'handshake', 'tls', 'cert']
    if any(keyword in error_str for keyword in ssl_keywords):
        return ErrorCategory.SSL
    
    # 网络错误（可重试）
    network_keywords = [
        'timeout', 'connection', 'network', 'temporary',
        '503', '502', '504', '429',  # HTTP错误码
        'econnrefused', 'econnreset', 'etimedout',
        'connection refused', 'connection reset', 'connection aborted',
        'name resolution', 'dns', 'no route to host'
    ]
    if any(keyword in error_str for keyword in network_keywords):
        return ErrorCategory.NETWORK
    
    # 解析错误（提取失败、页面结构变化）
    parse_keywords = ['extract', 'parse', 'selector', 'element not found', 'no such element']
    if any(keyword in error_str for keyword in parse_keywords):
        return ErrorCategory.PARSE
    
    # 默认：未知错误，视为网络错误（可重试）
    return ErrorCategory.UNKNOWN

def _is_retryable_error(error: Exception) -> bool:
    """判断错误是否可重试（保持向后兼容）"""
    category = _get_error_category(error)
    return category != ErrorCategory.PERMANENT

async def crawl_article_with_retry(article: dict, crawler=None, semaphore=None, max_retries: int = None, skip_retry: bool = False) -> bool:
    """爬取单篇文章（带重试机制）
    
    Args:
        article: 文章信息字典
        crawler: 可选的共享浏览器实例
        semaphore: 可选的并发控制信号量
        max_retries: 最大重试次数，默认使用配置值
        skip_retry: 是否跳过重试（用于第一轮爬取，只尝试一次）
    """
    if max_retries is None:
        max_retries = CRAWL_MAX_RETRIES
    
    url = article['url']
    article_id = article['id']
    site = article.get('site')
    
    # 检查平台是否在白名单中（双重保险）
    if not is_platform_allowed(site):
        logger.info(f"⏭️  跳过非白名单平台文章: {url} (平台: {site})")
        return False
    
    # 检查停止信号（线程安全）
    with _stop_signal_lock:
        if _stop_signal:
            return False
    
    # 使用信号量控制并发（优化：消除重复代码）
    async def _do_crawl():
        return await _crawl_with_retry(
            article, crawler, 
            max_retries if not skip_retry else 0,
            mark_error_on_fail=not skip_retry
        )
    
    if semaphore:
        async with semaphore:
            # 再次检查停止信号（在获取信号量后）
            with _stop_signal_lock:
                if _stop_signal:
                    return False
            return await _do_crawl()
    else:
        return await _do_crawl()

def _calculate_retry_delay(error_category: ErrorCategory, attempt: int) -> float:
    """计算重试延迟（根据错误类型和尝试次数）
    
    Args:
        error_category: 错误分类
        attempt: 当前尝试次数（从1开始）
        
    Returns:
        float: 延迟时间（秒）
    """
    if error_category == ErrorCategory.SSL:
        # SSL错误：固定长延迟
        base_delay = CRAWL_RETRY_SSL_DELAY
    elif error_category == ErrorCategory.PARSE:
        # 解析错误：线性退避
        base_delay = CRAWL_RETRY_DELAY * attempt
    else:
        # 网络错误和未知错误：指数退避
        base_delay = CRAWL_RETRY_DELAY * (CRAWL_RETRY_BACKOFF ** (attempt - 1))
    
    # 应用最大延迟上限
    delay = min(base_delay, CRAWL_RETRY_MAX_DELAY)
    
    # 添加抖动（jitter）避免雷群效应
    if CRAWL_RETRY_JITTER:
        jitter = random.uniform(-0.1 * delay, 0.1 * delay)
        delay = max(0.1, delay + jitter)  # 确保延迟不为负
    
    return delay

def _get_max_retries_for_category(error_category: ErrorCategory) -> int:
    """根据错误类型获取最大重试次数
    
    Args:
        error_category: 错误分类
        
    Returns:
        int: 最大重试次数
    """
    if error_category == ErrorCategory.NETWORK or error_category == ErrorCategory.UNKNOWN:
        return CRAWL_RETRY_NETWORK_MAX
    elif error_category == ErrorCategory.PARSE:
        return CRAWL_RETRY_PARSE_MAX
    elif error_category == ErrorCategory.SSL:
        return CRAWL_RETRY_SSL_MAX
    else:  # PERMANENT
        return 0

async def _crawl_with_retry(article: dict, crawler=None, max_retries: int = 3, mark_error_on_fail: bool = True) -> bool:
    """带重试机制的爬取逻辑（同时更新标题）
    
    Args:
        article: 文章信息字典
        crawler: 可选的浏览器实例
        max_retries: 最大重试次数
        mark_error_on_fail: 失败时是否立即标记为ERROR（第一轮不标记，第二轮标记）
    """
    url = article['url']
    article_id = article['id']
    current_title = article.get('title', '')
    context_token = set_log_context(article_id=article_id, url=url, platform=article.get('site'))
    
    last_error = None
    last_error_category = None
    try:
        for attempt in range(max_retries + 1):  # 0到max_retries，共max_retries+1次尝试
            try:
                # 如果不是第一次尝试，等待后重试
                if attempt > 0 and last_error_category:
                    # 根据错误类型计算延迟
                    delay = _calculate_retry_delay(last_error_category, attempt)
                    logger.info(f"🔄 重试 {attempt}/{max_retries}: {url} (错误类型: {last_error_category.value}, 等待 {delay:.1f}秒)")
                    await asyncio.sleep(delay)

                    # 再次检查停止信号（在睡眠期间可能收到了停止信号）
                    with _stop_signal_lock:
                        if _stop_signal:
                            logger.info(f"🛑 任务已停止: {url}")
                            return False

                    with _crawl_progress_lock:
                        _crawl_progress['retried'] += 1

                # 再次检查停止信号
                with _stop_signal_lock:
                    if _stop_signal:
                        return False

                # 执行爬取（同时获取阅读数和标题）
                info = await extract_article_info(url, crawler)
                count = info.get('read_count')
                new_title = info.get('title')
                _log_crawl_event(
                    "crawl.extract_result",
                    article_id=article_id,
                    url=url,
                    attempt=attempt + 1,
                    read_count=count,
                    status="success" if count is not None else "parse_failed",
                )

                # 更新文章标题（如果有新标题且与当前标题不同）
                if new_title and new_title != current_title:
                    if update_article_title(article_id, new_title):
                        logger.info(f"📝 更新标题: {new_title[:30]}...")

                if count is None:
                    # 提取失败视为解析错误
                    parse_error = Exception('无法提取阅读数')
                    last_error_category = ErrorCategory.PARSE
                    category_max_retries = _get_max_retries_for_category(last_error_category)
                    effective_max_retries = min(max_retries, category_max_retries)

                    if attempt <= effective_max_retries:
                        logger.info(f"⚠️  提取失败（解析错误），将重试: {url} (尝试 {attempt + 1}/{effective_max_retries + 1})")
                        last_error = parse_error
                        continue
                    logger.warning(f"❌ 无法提取阅读数: {url} (已重试 {effective_max_retries} 次)")
                    # 提取失败时不标记ERROR（等待集中重试）
                    if mark_error_on_fail:
                        update_article_status(article_id, 'ERROR', '无法提取阅读数')
                    return False

                # 检查是否需要更新（避免重复相同数据）
                # 优先使用预加载的最新阅读数，避免数据库查询
                latest_count = article.get('_latest_count')
                if latest_count is None:
                    # 如果预加载失败，回退到数据库查询
                    latest = get_latest_read_count(article_id)
                    latest_count = latest['count'] if latest else None

                if latest_count is not None and latest_count == count:
                    logger.debug(f"✓ 阅读数未变化: {url} ({count})")
                    # 即使未变化，也更新状态为成功（表示爬取正常）
                    update_article_status(article_id, 'OK')
                    return True

                # 保存阅读数
                add_read_count(article_id, count)

                # 更新状态为成功
                update_article_status(article_id, 'OK')

                if attempt > 0:
                    logger.info(f"✅ 重试成功: {url} -> {count} (尝试 {attempt + 1} 次)")
                else:
                    logger.info(f"✅ 更新成功: {url} -> {count}")
                return True

            except Exception as e:
                last_error = e
                last_error_category = _get_error_category(e)

                # 快速失败：永久性错误立即失败，不重试
                if last_error_category == ErrorCategory.PERMANENT:
                    error_msg = str(e)[:100]
                    logger.error(f"❌ 永久性错误（不重试）{url}: {error_msg}")
                    if mark_error_on_fail:
                        update_article_status(article_id, 'ERROR', error_msg)
                    return False

                # 根据错误类型获取最大重试次数
                category_max_retries = _get_max_retries_for_category(last_error_category)
                effective_max_retries = min(max_retries, category_max_retries)

                # 判断是否可重试
                is_retryable = _is_retryable_error(e)

                if is_retryable and attempt <= effective_max_retries:
                    logger.warning(f"⚠️  可重试错误 [{last_error_category.value}] (尝试 {attempt + 1}/{effective_max_retries + 1}): {url} - {str(e)[:100]}")
                    continue

                # 不可重试或已达到最大重试次数
                error_msg = str(e)[:100]
                if last_error_category == ErrorCategory.NETWORK:
                    logger.error(f"⏱️  网络错误 {url}: {error_msg} (已重试 {attempt} 次)")
                elif last_error_category == ErrorCategory.PARSE:
                    logger.error(f"🔍 解析错误 {url}: {error_msg} (已重试 {attempt} 次)")
                elif last_error_category == ErrorCategory.SSL:
                    logger.error(f"🔒 SSL错误 {url}: {error_msg} (已重试 {attempt} 次)")
                else:
                    logger.error(f"❌ 爬取失败 {url}: {error_msg} (已重试 {attempt} 次)")

                # 更新状态为失败（根据参数决定是否标记）
                # 第一轮不标记ERROR（等待集中重试），第二轮才标记
                if mark_error_on_fail and (not is_retryable or attempt >= effective_max_retries):
                    update_article_status(article_id, 'ERROR', str(e))

                return False

        # 所有重试都失败
        final_error = str(last_error) if last_error else '未知错误'
        logger.error(f"❌ 爬取最终失败 {url}: {final_error[:100]}")
        if mark_error_on_fail:
            update_article_status(article_id, 'ERROR', final_error)
        return False
    finally:
        reset_log_context(context_token)


async def crawl_all_articles():
    """爬取所有文章 - 优化版本：并发爬取 + 重试机制"""
    global _crawl_progress, _stop_signal

    # 重置停止信号（线程安全）
    with _stop_signal_lock:
        _stop_signal = False
    context_token = set_log_context(crawl_id=str(uuid4()))

    try:
        articles = get_all_articles()
        if not articles:
            logger.info("没有需要爬取的文章")
            reset_crawl_progress()
            return

        # 过滤：只爬取白名单中的平台
        filtered_articles = []
        skipped_count = 0
        for article in articles:
            site = article.get('site')
            if is_platform_allowed(site):
                filtered_articles.append(article)
            else:
                skipped_count += 1
                logger.info(f"⏭️  跳过非白名单平台: {article.get('url')} (平台: {site})")

        if skipped_count > 0:
            logger.info(f"⏭️  已跳过 {skipped_count} 篇非白名单平台文章")

        if not filtered_articles:
            logger.info("没有需要爬取的文章（所有文章都不在白名单中）")
            reset_crawl_progress()
            return

        articles = filtered_articles

        # 批量获取最新阅读数（优化：避免在爬取循环中逐个查询）
        article_ids = [a['id'] for a in articles]
        latest_counts = get_latest_read_counts_batch(article_ids)

        # 将最新阅读数添加到文章字典中，避免在爬取时重复查询
        for article in articles:
            latest = latest_counts.get(article['id'])
            article['_latest_count'] = latest['count'] if latest else None

        # 按站点交错调度（round-robin），使并发更均匀分布在多站点
        if CRAWL_INTERLEAVE_BY_SITE:
            articles = _interleave_articles_by_site(articles)
            logger.info("已按站点交错排序文章")

        # 每域名状态在本次爬取内使用，开始时重置
        _reset_domain_semaphores()
        _reset_domain_rate_limit()

        # 初始化进度（线程安全）
        with _crawl_progress_lock:
            _crawl_progress['is_running'] = True
            _crawl_progress['total'] = len(articles)
            _crawl_progress['current'] = 0
            _crawl_progress['success'] = 0
            _crawl_progress['failed'] = 0
            _crawl_progress['retried'] = 0
            _crawl_progress['start_time'] = datetime.now().isoformat()
            _crawl_progress['end_time'] = None

        # 记录防反爬状态
        if ANTI_SCRAPING_ENABLED:
            logger.info(f"🛡️ 防反爬已启用: UA轮换, 隐身模式, 随机延迟({ANTI_SCRAPING_MIN_DELAY}-{ANTI_SCRAPING_MAX_DELAY}秒)")
            # 重置防反爬管理器，确保每次爬取使用新的配置
            reset_anti_scraping_manager()

        logger.info(f"开始爬取 {len(articles)} 篇文章（并发数: {CRAWL_CONCURRENCY}, 最大重试: {CRAWL_MAX_RETRIES}）")
        start_time = datetime.now()

        # 创建并发控制信号量
        semaphore = asyncio.Semaphore(CRAWL_CONCURRENCY)

        # 优化：使用独立浏览器实例（更稳定，避免并发冲突）
        use_shared_crawler = False

        shared_crawler = None
        if use_shared_crawler:
            try:
                shared_crawler = await create_shared_crawler()
                logger.info("使用共享浏览器实例，提升性能")
            except Exception as e:
                logger.warning(f"无法创建共享浏览器实例，使用独立实例: {e}")
                shared_crawler = None

        # 第一轮爬取：只尝试一次，不重试（快速失败，收集需要重试的文章）
        failed_articles_lock = threading.Lock()  # 保护失败文章列表的锁
        failed_articles = []

        async def crawl_with_progress(article: dict, index: int):
            """带进度更新的爬取任务（第一轮：只尝试一次）；含每域名限流与信号量。"""
            with _stop_signal_lock:
                if _stop_signal:
                    return False

            domain = _domain_from_article(article)
            await _wait_domain_rate_limit(domain)
            domain_sem = await _get_domain_semaphore(domain)

            try:
                if domain_sem is not None:
                    async with domain_sem:
                        result = await crawl_article_with_retry(
                            article,
                            crawler=shared_crawler,
                            semaphore=semaphore,
                            max_retries=CRAWL_MAX_RETRIES,
                            skip_retry=True,
                        )
                else:
                    result = await crawl_article_with_retry(
                        article,
                        crawler=shared_crawler,
                        semaphore=semaphore,
                        max_retries=CRAWL_MAX_RETRIES,
                        skip_retry=True,
                    )

                # 更新进度（线程安全）
                with _crawl_progress_lock:
                    _crawl_progress['current'] = index + 1
                    _crawl_progress['current_url'] = article['url']
                    if result:
                        _crawl_progress['success'] += 1
                    else:
                        _crawl_progress['failed'] += 1

                if not result:
                    with failed_articles_lock:
                        failed_articles.append(article)

                if not ANTI_SCRAPING_ENABLED and CRAWL_DELAY > 0 and result:
                    await asyncio.sleep(CRAWL_DELAY)

                return result
            except Exception as e:
                logger.error(f"任务异常 {article['url']}: {e}")
                with failed_articles_lock:
                    failed_articles.append(article)
                with _crawl_progress_lock:
                    _crawl_progress['failed'] += 1
                return False
            finally:
                await _record_domain_request_done(domain)

        # 并发执行所有爬取任务（第一轮）
        tasks = [crawl_with_progress(article, i) for i, article in enumerate(articles)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果（线程安全）
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"任务异常 {articles[i]['url']}: {result}")
                with failed_articles_lock:
                    if articles[i] not in failed_articles:
                        failed_articles.append(articles[i])
                with _crawl_progress_lock:
                    _crawl_progress['failed'] += 1

        # 清理共享浏览器实例（第一轮结束）
        if shared_crawler:
            try:
                await shared_crawler.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"清理共享浏览器实例时出错: {e}")
                # 尝试强制清理
                try:
                    if hasattr(shared_crawler, 'browser') and shared_crawler.browser:
                        await shared_crawler.browser.close()
                except Exception as e2:
                    logger.debug(f"强制清理浏览器实例失败: {e2}")

        # 第二轮：集中重试所有失败的文章（复用浏览器实例）
        # 优化：按错误类型排序，优先重试成功率高的错误
        def _get_retry_priority(article: dict) -> int:
            """获取重试优先级（数字越小优先级越高）"""
            last_error = article.get('last_error', '')
            if not last_error:
                return 2  # 未知错误，中等优先级

            # 创建临时异常对象用于分类
            try:
                temp_error = Exception(last_error)
                category = _get_error_category(temp_error)
                return RETRY_PRIORITY_MAP.get(category, 2)
            except Exception:
                return 2

        # 按优先级排序失败文章
        failed_articles.sort(key=_get_retry_priority)

        with _stop_signal_lock:
            should_retry = not _stop_signal and len(failed_articles) > 0

        if should_retry:
            logger.info(f"🔄 开始集中重试 {len(failed_articles)} 篇失败文章（复用浏览器实例）")

            # 使用浏览器池进行集中重试
            from .browser_pool import get_browser_pool
            browser_pool = get_browser_pool()

            # 批量重试（使用浏览器池）
            retry_semaphore = asyncio.Semaphore(CRAWL_CONCURRENCY)
            retry_start_time = datetime.now()

            async def retry_with_pool(article: dict, index: int):
                """使用浏览器池重试失败的文章；含每域名限流与信号量。"""
                with _stop_signal_lock:
                    if _stop_signal:
                        return False

                domain = _domain_from_article(article)
                domain_sem = await _get_domain_semaphore(domain)

                try:
                    if domain_sem is not None:
                        async with domain_sem:
                            await _wait_domain_rate_limit(domain)
                            return await _do_retry_with_pool(article, index)
                    await _wait_domain_rate_limit(domain)
                    return await _do_retry_with_pool(article, index)
                finally:
                    await _record_domain_request_done(domain)

            async def _do_retry_with_pool(article: dict, index: int) -> bool:
                """实际执行重试（获取浏览器、调用 _crawl_with_retry、更新进度）。"""
                try:
                    crawler = await browser_pool.acquire()
                    use_pool = True
                    if not crawler:
                        crawler = await create_shared_crawler()
                        use_pool = False
                    try:
                        result = await _crawl_with_retry(article, crawler, CRAWL_MAX_RETRIES, mark_error_on_fail=True)
                        with _crawl_progress_lock:
                            _crawl_progress['current'] = len(articles) + index + 1
                            _crawl_progress['current_url'] = article['url']
                            if result:
                                _crawl_progress['success'] += 1
                                _crawl_progress['failed'] -= 1
                                _crawl_progress['retried'] += 1
                            else:
                                _crawl_progress['retried'] += 1
                        if not result:
                            update_article_status(article['id'], 'ERROR', '集中重试后仍然失败')
                        return result
                    finally:
                        if use_pool:
                            await browser_pool.release(crawler)
                        else:
                            await crawler.__aexit__(None, None, None)
                except Exception as e:
                    logger.error(f"重试异常 {article['url']}: {e}")
                    update_article_status(article['id'], 'ERROR', str(e))
                    with _crawl_progress_lock:
                        _crawl_progress['retried'] += 1
                    return False

            # 并发重试所有失败的文章
            retry_tasks = []
            for i, article in enumerate(failed_articles):
                async def retry_with_semaphore(article, index):
                    async with retry_semaphore:
                        return await retry_with_pool(article, index)
                retry_tasks.append(retry_with_semaphore(article, i))

            retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)

            retry_elapsed = (datetime.now() - retry_start_time).total_seconds()
            retry_success = sum(1 for r in retry_results if r is True)
            logger.info(f"🔄 集中重试完成: {retry_success}/{len(failed_articles)} 成功, 耗时 {retry_elapsed:.2f} 秒")

        # 完成（线程安全）
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()

        with _crawl_progress_lock:
            _crawl_progress['is_running'] = False
            _crawl_progress['end_time'] = end_time.isoformat()
            _crawl_progress['current_url'] = None
            success_count = _crawl_progress['success']
            failed_count = _crawl_progress['failed']
            retried_count = _crawl_progress['retried']

        success_rate = (success_count / len(articles) * 100) if articles else 0
        logger.info(f"爬取完成: {success_count}/{len(articles)} 成功 ({success_rate:.1f}%), "
                    f"{failed_count} 失败, {retried_count} 次重试, "
                    f"耗时 {elapsed:.2f} 秒")
        if elapsed > 0:
            logger.info(f"平均速度: {len(articles) / elapsed:.2f} 文章/秒")
    finally:
        reset_log_context(context_token)

def crawl_all_sync():
    """同步包装器；若已有爬取在運行則跳過（防定時任務疊加）"""
    progress = get_crawl_progress()
    if progress.get('is_running'):
        logger.info("爬取已在進行中，跳過本次定時觸發")
        return
    try:
        asyncio.run(crawl_all_articles())
    except Exception as e:
        with _crawl_progress_lock:
            _crawl_progress['is_running'] = False
            _crawl_progress['end_time'] = datetime.now().isoformat()
        logger.error(f"爬取任务异常: {e}")