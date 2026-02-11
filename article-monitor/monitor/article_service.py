import asyncio
import logging
from typing import List, Dict

from .config import BATCH_PROCESS_SIZE, BATCH_PROCESS_CONCURRENCY, is_platform_allowed
from .task_manager import get_task_manager
from .browser_pool import get_browser_pool
from .extractors import extract_article_info, create_shared_crawler
from .database import add_articles_batch, add_read_counts_batch
from .url_utils import validate_and_normalize_url


logger = logging.getLogger(__name__)


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


async def _process_batch(urls: List[str], browser_pool) -> List[dict]:
    """处理一批URL"""
    processed_results: List[dict] = [None] * len(urls)

    async def process_single_url(idx: int, url: str):
        normalized_url = url  # 初始化為原始 URL，作為異常情況的備用
        try:
            is_valid, normalized_url, site = validate_and_normalize_url(url)
            if not is_valid:
                return idx, {'url': url, 'success': False, 'error': '无效的URL格式（只支持 http/https）'}

            if not is_platform_allowed(site):
                return idx, {
                    'url': url,
                    'success': False,
                    'error': f'平台 "{site or "未知"}" 不在允许列表中，已跳过'
                }

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
                logger.warning(f"爬取失败 {url}: {e}")
                title = None
                count = None
            finally:
                if use_pool:
                    await browser_pool.release(crawler)
                else:
                    await crawler.__aexit__(None, None, None)

            return idx, {
                'url': normalized_url,
                'success': True,
                'data': {
                    'title': title,
                    'site': site,
                    'initial_count': count if count is not None else 0
                }
            }
        except Exception as e:
            return idx, {'url': normalized_url, 'success': False, 'error': str(e)}

    semaphore = asyncio.Semaphore(BATCH_PROCESS_CONCURRENCY)

    async def process_with_semaphore(idx: int, url: str):
        async with semaphore:
            return await process_single_url(idx, url)

    tasks = [process_with_semaphore(i, url) for i, url in enumerate(urls)]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(gathered):
        if isinstance(result, Exception):
            processed_results[i] = {'url': urls[i], 'success': False, 'error': str(result)}
        else:
            idx, payload = result
            processed_results[idx] = payload

    articles_to_add = []
    read_counts_to_add = []
    for item in processed_results:
        if item and item.get('success'):
            articles_to_add.append(
                (item.get('url'), item['data'].get('title'), item['data'].get('site'))
            )
            read_counts_to_add.append((item['data'].get('initial_count', 0),))

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
            article_idx += 1

    logger.info(f"批量插入成功: {len(articles_to_add)} 篇文章")

    return processed_results

