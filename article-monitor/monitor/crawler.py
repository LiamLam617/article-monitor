"""
爬取任务 - 优化版本：并发爬取，复用浏览器实例，重试机制，防反爬
"""
import asyncio
import threading
import logging
from datetime import datetime
from typing import List, Dict, Optional
from .database import (
    get_all_articles, add_read_count, get_latest_read_count,
    get_latest_read_counts_batch, update_article_title, update_article_status
)
from .extractors import extract_read_count, extract_article_info, create_shared_crawler
from urllib.parse import urlparse
from .config import (
    SUPPORTED_SITES, CRAWL_CONCURRENCY, CRAWL_DELAY, 
    CRAWL_MAX_RETRIES, CRAWL_RETRY_DELAY, CRAWL_RETRY_BACKOFF,
    ANTI_SCRAPING_ENABLED, ANTI_SCRAPING_RANDOM_DELAY,
    ANTI_SCRAPING_MIN_DELAY, ANTI_SCRAPING_MAX_DELAY,
    is_platform_allowed
)
from .anti_scraping import get_anti_scraping_manager, reset_anti_scraping_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def _is_retryable_error(error: Exception) -> bool:
    """判断错误是否可重试"""
    error_str = str(error).lower()
    retryable_keywords = [
        'timeout', 'connection', 'network', 'temporary',
        '503', '502', '504', '429',  # HTTP错误码
        'econnrefused', 'econnreset', 'etimedout',
        'ssl', 'certificate', 'handshake'
    ]
    return any(keyword in error_str for keyword in retryable_keywords)

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
        logger.debug(f"⏭️  跳过非白名单平台文章: {url} (平台: {site})")
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
    
    last_error = None
    
    for attempt in range(max_retries + 1):  # 0到max_retries，共max_retries+1次尝试
        try:
            # 如果不是第一次尝试，等待后重试
            if attempt > 0:
                # 指数退避：延迟时间 = 基础延迟 * (退避倍数 ^ 尝试次数)
                delay = CRAWL_RETRY_DELAY * (CRAWL_RETRY_BACKOFF ** (attempt - 1))
                logger.info(f"🔄 重试 {attempt}/{max_retries}: {url} (等待 {delay:.1f}秒)")
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
            
            # 更新文章标题（如果有新标题且与当前标题不同）
            if new_title and new_title != current_title:
                if update_article_title(article_id, new_title):
                    logger.info(f"📝 更新标题: {new_title[:30]}...")
            
            if count is None:
                # 如果提取失败，判断是否应该重试
                if attempt < max_retries:
                    logger.debug(f"⚠️  提取失败，将重试: {url} (尝试 {attempt + 1}/{max_retries + 1})")
                    continue
                else:
                    logger.warning(f"❌ 无法提取阅读数: {url} (已重试 {max_retries} 次)")
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
            error_str = str(e).lower()
            
            # 判断是否可重试
            is_retryable = _is_retryable_error(e)
            
            if is_retryable and attempt < max_retries:
                logger.warning(f"⚠️  可重试错误 (尝试 {attempt + 1}/{max_retries + 1}): {url} - {str(e)[:100]}")
                continue
            else:
                # 不可重试或已达到最大重试次数
                error_msg = str(e)[:100]
                if 'timeout' in error_str or 'connection' in error_str:
                    logger.error(f"⏱️  网络错误 {url}: {error_msg} (已重试 {attempt} 次)")
                else:
                    logger.error(f"❌ 爬取失败 {url}: {error_msg} (已重试 {attempt} 次)")
                
                # 更新状态为失败（根据参数决定是否标记）
                # 第一轮不标记ERROR（等待集中重试），第二轮才标记
                if mark_error_on_fail and (not is_retryable or attempt >= max_retries):
                    update_article_status(article_id, 'ERROR', str(e))
                
                return False
    
    # 所有重试都失败
    final_error = str(last_error) if last_error else '未知错误'
    logger.error(f"❌ 爬取最终失败 {url}: {final_error[:100]}")
    if mark_error_on_fail:
        update_article_status(article_id, 'ERROR', final_error)
    return False


async def crawl_all_articles():
    """爬取所有文章 - 优化版本：并发爬取 + 重试机制"""
    global _crawl_progress, _stop_signal
    
    # 重置停止信号（线程安全）
    with _stop_signal_lock:
        _stop_signal = False
    
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
            logger.debug(f"⏭️  跳过非白名单平台: {article.get('url')} (平台: {site})")
    
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
        """带进度更新的爬取任务（第一轮：只尝试一次）"""
        with _stop_signal_lock:
            if _stop_signal:
                return False
            
        try:
            # 第一轮：只尝试一次，不重试（skip_retry=True）
            result = await crawl_article_with_retry(
                article, 
                crawler=shared_crawler, 
                semaphore=semaphore,
                max_retries=CRAWL_MAX_RETRIES,
                skip_retry=True  # 第一轮不重试
            )
            
            # 更新进度（线程安全）
            with _crawl_progress_lock:
                _crawl_progress['current'] = index + 1
                _crawl_progress['current_url'] = article['url']
                
                if result:
                    _crawl_progress['success'] += 1
                else:
                    _crawl_progress['failed'] += 1
            
            # 收集失败的文章（线程安全）
            if not result:
                with failed_articles_lock:
                    failed_articles.append(article)
            
            # 请求之间的延迟（避免过于频繁）
            # 注意：如果启用了防反爬随机延迟，则由 extractors 模块在每次爬取时处理
            # 这里只在未启用防反爬时使用固定延迟
            # 优化：如果爬取失败，不延迟（快速失败）
            if not ANTI_SCRAPING_ENABLED and CRAWL_DELAY > 0 and result:
                await asyncio.sleep(CRAWL_DELAY)
            
            return result
        except Exception as e:
            logger.error(f"任务异常 {article['url']}: {e}")
            # 收集失败的文章（线程安全）
            with failed_articles_lock:
                failed_articles.append(article)
            with _crawl_progress_lock:
                _crawl_progress['failed'] += 1
            return False
    
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
            logger.debug(f"清理共享浏览器实例时出错: {e}")
    
    # 第二轮：集中重试所有失败的文章（复用浏览器实例）
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
            """使用浏览器池重试失败的文章"""
            with _stop_signal_lock:
                if _stop_signal:
                    return False
            
            try:
                # 从浏览器池获取实例
                crawler = await browser_pool.acquire()
                use_pool = True
                
                if not crawler:
                    # 如果池已满，创建独立实例
                    crawler = await create_shared_crawler()
                    use_pool = False
                
                try:
                    # 执行重试（这次允许重试，并标记错误）
                    result = await _crawl_with_retry(article, crawler, CRAWL_MAX_RETRIES, mark_error_on_fail=True)
                    
                    # 更新进度（线程安全）
                    with _crawl_progress_lock:
                        _crawl_progress['current'] = len(articles) + index + 1
                        _crawl_progress['current_url'] = article['url']
                        
                        if result:
                            _crawl_progress['success'] += 1
                            _crawl_progress['failed'] -= 1  # 从失败数中减去
                            _crawl_progress['retried'] += 1
                        else:
                            _crawl_progress['retried'] += 1
                    
                    # 重试后仍然失败，确保标记为 ERROR（双重保险）
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
                # 重试异常时也标记为 ERROR
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

def crawl_all_sync():
    """同步包装器"""
    try:
        asyncio.run(crawl_all_articles())
    except Exception as e:
        with _crawl_progress_lock:
            _crawl_progress['is_running'] = False
            _crawl_progress['end_time'] = datetime.now().isoformat()
        logger.error(f"爬取任务异常: {e}")
