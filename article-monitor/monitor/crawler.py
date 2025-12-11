"""
爬取任务 - 优化版本：并发爬取，复用浏览器实例，重试机制，防反爬
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
from .database import (
    get_all_articles, add_read_count, get_latest_read_count, 
    update_article_title, update_article_status
)
from .extractors import extract_read_count, extract_article_info, create_shared_crawler
from urllib.parse import urlparse
from .config import (
    SUPPORTED_SITES, CRAWL_CONCURRENCY, CRAWL_DELAY, 
    CRAWL_MAX_RETRIES, CRAWL_RETRY_DELAY, CRAWL_RETRY_BACKOFF,
    ANTI_SCRAPING_ENABLED, ANTI_SCRAPING_RANDOM_DELAY,
    ANTI_SCRAPING_MIN_DELAY, ANTI_SCRAPING_MAX_DELAY
)
from .anti_scraping import get_anti_scraping_manager, reset_anti_scraping_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局进度状态
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

# 全局停止信号
_stop_signal = False

def stop_crawling():
    """停止爬取任务"""
    global _stop_signal
    _stop_signal = True
    logger.info("🛑 收到停止信号，正在停止爬取...")

def get_crawl_progress():
    """获取爬取进度"""
    return _crawl_progress.copy()

def reset_crawl_progress():
    """重置爬取进度"""
    global _crawl_progress
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

async def crawl_article_with_retry(article: dict, crawler=None, semaphore=None, max_retries: int = None) -> bool:
    """爬取单篇文章（带重试机制）
    
    Args:
        article: 文章信息字典
        crawler: 可选的共享浏览器实例
        semaphore: 可选的并发控制信号量
        max_retries: 最大重试次数，默认使用配置值
    """
    if max_retries is None:
        max_retries = CRAWL_MAX_RETRIES
    
    url = article['url']
    article_id = article['id']
    
    # 使用信号量控制并发
    if semaphore:
        async with semaphore:
            if _stop_signal:
                return False
            return await _crawl_with_retry(article, crawler, max_retries)
    else:
        if _stop_signal:
            return False
        return await _crawl_with_retry(article, crawler, max_retries)

async def _crawl_with_retry(article: dict, crawler=None, max_retries: int = 3) -> bool:
    """带重试机制的爬取逻辑（同时更新标题）"""
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
                if _stop_signal:
                    logger.info(f"🛑 任务已停止: {url}")
                    return False
                    
                global _crawl_progress
                _crawl_progress['retried'] += 1
            
            # 再次检查停止信号
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
                    return False
            
            # 检查是否需要更新（避免重复相同数据）
            latest = get_latest_read_count(article_id)
            if latest and latest['count'] == count:
                logger.debug(f"✓ 阅读数未变化: {url} ({count})")
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
                
                # 更新状态为失败（如果在最终失败前记录）
                # 注意：这里我们只在最后一次尝试失败后才标记为ERROR，或者不可重试错误时
                if not is_retryable or attempt >= max_retries:
                    update_article_status(article_id, 'ERROR', str(e))
                
                return False
    
    # 所有重试都失败
    final_error = str(last_error) if last_error else '未知错误'
    logger.error(f"❌ 爬取最终失败 {url}: {final_error[:100]}")
    update_article_status(article_id, 'ERROR', final_error)
    return False

async def crawl_article(article: dict, crawler=None, semaphore=None) -> bool:
    """爬取单篇文章（兼容旧接口）
    
    Args:
        article: 文章信息字典
        crawler: 可选的共享浏览器实例
        semaphore: 可选的并发控制信号量
    """
    return await crawl_article_with_retry(article, crawler, semaphore)

async def crawl_all_articles():
    """爬取所有文章 - 优化版本：并发爬取 + 重试机制"""
    global _crawl_progress, _stop_signal
    
    # 重置停止信号
    _stop_signal = False
    
    articles = get_all_articles()
    if not articles:
        logger.info("没有需要爬取的文章")
        reset_crawl_progress()
        return
    
    # 初始化进度
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
    
    # 注意：共享浏览器实例在并发场景下可能有问题
    # 每个任务使用独立实例更稳定，但性能稍差
    # 可以根据实际情况选择
    use_shared_crawler = False  # 暂时禁用共享实例，提高稳定性
    
    shared_crawler = None
    if use_shared_crawler:
        try:
            shared_crawler = await create_shared_crawler()
            logger.info("使用共享浏览器实例，提升性能")
        except Exception as e:
            logger.warning(f"无法创建共享浏览器实例，使用独立实例: {e}")
            shared_crawler = None
    
    # 创建爬取任务列表
    async def crawl_with_progress(article: dict, index: int):
        """带进度更新的爬取任务"""
        if _stop_signal:
            return False
            
        try:
            result = await crawl_article_with_retry(
                article, 
                crawler=shared_crawler, 
                semaphore=semaphore,
                max_retries=CRAWL_MAX_RETRIES
            )
            
            # 更新进度
            _crawl_progress['current'] = index + 1
            _crawl_progress['current_url'] = article['url']
            
            if result:
                _crawl_progress['success'] += 1
            else:
                _crawl_progress['failed'] += 1
            
            # 请求之间的延迟（避免过于频繁）
            # 如果启用了防反爬随机延迟，则由 extractors 模块处理
            # 这里只在未启用防反爬时使用固定延迟
            if not ANTI_SCRAPING_ENABLED and CRAWL_DELAY > 0:
                await asyncio.sleep(CRAWL_DELAY)
            
            return result
        except Exception as e:
            logger.error(f"任务异常 {article['url']}: {e}")
            _crawl_progress['failed'] += 1
            return False
    
    # 并发执行所有爬取任务
    tasks = [crawl_with_progress(article, i) for i, article in enumerate(articles)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理异常结果
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"任务异常 {articles[i]['url']}: {result}")
            _crawl_progress['failed'] += 1
    
    # 清理共享浏览器实例
    if shared_crawler:
        try:
            await shared_crawler.__aexit__(None, None, None)
        except:
            pass
    
    # 完成
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()
    
    _crawl_progress['is_running'] = False
    _crawl_progress['end_time'] = end_time.isoformat()
    _crawl_progress['current_url'] = None
    
    success_rate = (_crawl_progress['success'] / len(articles) * 100) if articles else 0
    logger.info(f"爬取完成: {_crawl_progress['success']}/{len(articles)} 成功 ({success_rate:.1f}%), "
                f"{_crawl_progress['failed']} 失败, {_crawl_progress['retried']} 次重试, "
                f"耗时 {elapsed:.2f} 秒")
    if elapsed > 0:
        logger.info(f"平均速度: {len(articles) / elapsed:.2f} 文章/秒")

def crawl_all_sync():
    """同步包装器"""
    try:
        asyncio.run(crawl_all_articles())
    except Exception as e:
        global _crawl_progress
        _crawl_progress['is_running'] = False
        _crawl_progress['end_time'] = datetime.now().isoformat()
        logger.error(f"爬取任务异常: {e}")
