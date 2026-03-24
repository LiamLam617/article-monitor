import asyncio
import logging
import time
from typing import List, Dict
from urllib.parse import urlparse

from .config import (
    BATCH_PROCESS_SIZE,
    BATCH_PROCESS_CONCURRENCY,
    CRAWL_TIMEOUT,
    CRAWL_CONCURRENCY_PER_DOMAIN,
    CRAWL_MIN_DELAY_PER_DOMAIN,
    is_platform_allowed,
)
from .task_manager import get_task_manager
from .browser_pool import get_browser_pool
from .extractors import extract_article_info, create_shared_crawler
from .database import add_articles_batch, add_read_counts_batch
from .url_utils import validate_and_normalize_url


logger = logging.getLogger(__name__)


class _DomainThrottleController:
    """域名级并发与最小间隔控制，降低单站点突发请求。"""

    def __init__(self):
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._next_allowed_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _domain(url: str) -> str:
        try:
            return (urlparse(url).netloc or "unknown").lower()
        except Exception:
            return "unknown"

    async def get_semaphore(self, url: str):
        if CRAWL_CONCURRENCY_PER_DOMAIN <= 0:
            return None
        domain = self._domain(url)
        async with self._lock:
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(CRAWL_CONCURRENCY_PER_DOMAIN)
            return self._semaphores[domain]

    async def wait_turn(self, url: str):
        if CRAWL_MIN_DELAY_PER_DOMAIN <= 0:
            return
        domain = self._domain(url)
        sleep_time = 0.0
        async with self._lock:
            now = time.monotonic()
            next_allowed = self._next_allowed_time.get(domain, 0.0)
            scheduled = max(now, next_allowed)
            self._next_allowed_time[domain] = scheduled + CRAWL_MIN_DELAY_PER_DOMAIN
            sleep_time = scheduled - now
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    async def mark_done(self, url: str):
        """保留兼容接口：节流已在 wait_turn 里完成时间槽预留。"""
        return


async def _process_urls_async(task_id: str, urls: List[str]):
    """异步处理URL列表（用于任务队列）"""
    task_manager = get_task_manager()
    results: List[Dict] = []
    total = len(urls)

    browser_pool = get_browser_pool()

    batch_size = BATCH_PROCESS_SIZE
    for i in range(0, total, batch_size):
        batch_urls = urls[i:i + batch_size]
        batch_results = await _process_batch(batch_urls, browser_pool)
        results.extend(batch_results)

        task_manager.update_task_progress(task_id, {
            'processed': len(results),
            'total': total,
            'success': sum(1 for r in results if r.get('success')),
            'failed': sum(1 for r in results if not r.get('success'))
        })

    task = task_manager.get_task(task_id)
    if task:
        task['results'] = results


async def _process_urls_sync(urls: List[str]):
    """同步处理URL列表（用于小批量）"""
    browser_pool = get_browser_pool()
    return await _process_batch(urls, browser_pool)


async def crawl_urls_for_results(urls: List[str], on_result=None) -> List[Dict]:
    """仅爬取 URL 列表并返回结构化结果，不写入数据库。

    供 Bitable 同步等仅需「爬取结果」的场景复用。

    Returns:
        与 urls 顺序对应的列表，每项为:
        - 成功: {"url", "success": True, "data": {"title", "site", "read_count"}}
        - 失败: {"url", "success": False, "error": str}
    """
    browser_pool = get_browser_pool()
    batch_size = BATCH_PROCESS_SIZE
    all_results: List[Dict] = []
    domain_controller = _DomainThrottleController()
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i : i + batch_size]
        batch_results = await _crawl_batch_for_results(
            batch_urls,
            browser_pool,
            domain_controller,
            on_result=on_result,
        )
        all_results.extend(batch_results)
    return all_results


async def crawl_single_url_for_result(
    url: str,
    browser_pool=None,
    domain_controller: _DomainThrottleController = None,
) -> Dict:
    """爬取单个 URL，返回统一结果结构，不写库。"""
    raw_url = url
    normalized_url = url
    try:
        is_valid, normalized_url, site = validate_and_normalize_url(url)
        if not is_valid:
            return {
                'url': raw_url,
                'success': False,
                'error': '无效的URL格式（只支持 http/https）',
                'error_code': 'invalid_url',
            }

        if not is_platform_allowed(site):
            return {
                'url': raw_url,
                'success': False,
                'error': f'平台 "{site or "未知"}" 不在允许列表中，已跳过',
                'error_code': 'platform_not_allowed',
            }

        if browser_pool is None:
            browser_pool = get_browser_pool()

        domain_sem = None
        if domain_controller is not None:
            domain_sem = await domain_controller.get_semaphore(normalized_url)

        async def _crawl_once() -> Dict:
            if domain_controller is not None:
                await domain_controller.wait_turn(normalized_url)

            try:
                crawler = await browser_pool.acquire()
                if not crawler:
                    crawler = await create_shared_crawler()
                    use_pool = False
                else:
                    use_pool = True

                try:
                    info = await extract_article_info(normalized_url, crawler)
                    title = info.get('title')
                    count = info.get('read_count')
                except Exception as e:
                    logger.warning(f"爬取失败 {raw_url}: {e}")
                    title = None
                    count = None
                finally:
                    if use_pool:
                        await browser_pool.release(crawler)
                    else:
                        await crawler.__aexit__(None, None, None)
                    if domain_controller is not None:
                        await domain_controller.mark_done(normalized_url)

                read_count = count if count is not None else 0
                return {
                    'url': normalized_url,
                    'success': True,
                    'data': {
                        'title': title,
                        'site': site,
                        'read_count': read_count,
                    },
                }
            except Exception as e:
                return {'url': raw_url, 'success': False, 'error': str(e), 'error_code': 'crawl_failed'}

        async def _crawl_with_domain_limit() -> Dict:
            if domain_sem is not None:
                async with domain_sem:
                    return await _crawl_once()
            return await _crawl_once()

        timeout_seconds = max(0.1, float(CRAWL_TIMEOUT))
        try:
            return await asyncio.wait_for(_crawl_with_domain_limit(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("爬取超时 %s (timeout=%ss)", raw_url, timeout_seconds)
            return {
                'url': raw_url,
                'success': False,
                'error': f'爬取超时（>{timeout_seconds}秒）',
                'error_code': 'crawl_timeout',
            }
    except Exception as e:
        return {'url': normalized_url, 'success': False, 'error': str(e), 'error_code': 'crawl_failed'}


async def _crawl_batch_for_results(
    urls: List[str],
    browser_pool,
    domain_controller: _DomainThrottleController = None,
    on_result=None,
) -> List[dict]:
    """爬取一批 URL，返回结果列表，不写库。"""
    processed_results: List[dict] = [None] * len(urls)

    async def process_single_url(idx: int, url: str):
        result = await crawl_single_url_for_result(
            url,
            browser_pool=browser_pool,
            domain_controller=domain_controller,
        )
        return idx, result

    semaphore = asyncio.Semaphore(BATCH_PROCESS_CONCURRENCY)

    async def process_with_semaphore(idx: int, url: str):
        async with semaphore:
            try:
                return await process_single_url(idx, url)
            except Exception as e:
                return idx, {
                    'url': url,
                    'success': False,
                    'error': str(e),
                    'error_code': 'crawl_failed',
                }

    tasks = [asyncio.create_task(process_with_semaphore(i, url)) for i, url in enumerate(urls)]
    for completed in asyncio.as_completed(tasks):
        idx, payload = await completed
        processed_results[idx] = payload
        if on_result is not None:
            try:
                on_result(payload)
            except Exception:
                logger.warning("on_result callback failed", exc_info=True)

    return processed_results


async def _process_batch(urls: List[str], browser_pool) -> List[dict]:
    """处理一批URL：先爬取，再写入 SQLite。"""
    processed_results = await _crawl_batch_for_results(urls, browser_pool)

    articles_to_add = []
    read_counts_to_add = []
    for item in processed_results:
        if item and item.get('success'):
            articles_to_add.append(
                (item.get('url'), item['data'].get('title'), item['data'].get('site'))
            )
            read_counts_to_add.append((item['data'].get('read_count', 0),))

    if not articles_to_add:
        return processed_results

    article_ids = add_articles_batch(articles_to_add)

    if len(article_ids) != len(articles_to_add):
        error_msg = f"批量插入失败: 返回 {len(article_ids)} 个ID, 期望 {len(articles_to_add)} 个"
        logger.error(error_msg)
        raise ValueError(error_msg)

    if None in article_ids:
        error_msg = "批量插入包含失败项（None值）"
        logger.error(error_msg)
        raise ValueError(error_msg)

    if len(read_counts_to_add) != len(articles_to_add):
        error_msg = (
            f"阅读数记录数量不匹配: read_counts_to_add={len(read_counts_to_add)}, "
            f"articles_to_add={len(articles_to_add)}"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    read_count_records = []
    for article_id, count_tuple in zip(article_ids, read_counts_to_add):
        if article_id is not None and count_tuple:
            read_count_records.append((article_id, count_tuple[0]))

    if read_count_records:
        add_read_counts_batch(read_count_records)

    article_idx = 0
    for result in processed_results:
        if result.get('success') and article_idx < len(article_ids):
            result['data']['id'] = article_ids[article_idx]
            result['data']['initial_count'] = result['data'].get('read_count', 0)
            article_idx += 1

    logger.info(f"批量插入成功: {len(articles_to_add)} 篇文章")

    return processed_results

