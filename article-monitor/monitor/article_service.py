from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum
from typing import List, Dict, Optional
from urllib.parse import urlparse

from .config import (
    BATCH_PROCESS_SIZE,
    BATCH_PROCESS_CONCURRENCY,
    CRAWL_TIMEOUT,
    CRAWL_CONCURRENCY_PER_DOMAIN,
    CRAWL_MIN_DELAY_PER_DOMAIN,
    RESULT_RETRY_EXTRA_PASSES,
    is_platform_allowed,
    CRAWL_RETRY_DELAY,
    CRAWL_RETRY_BACKOFF,
    CRAWL_RETRY_MAX_DELAY,
    CRAWL_RETRY_JITTER,
    CRAWL_RETRY_SSL_DELAY,
    CRAWL_RETRY_NETWORK_MAX,
    CRAWL_RETRY_PARSE_MAX,
    CRAWL_RETRY_SSL_MAX,
)
from .task_manager import get_task_manager
from .browser_pool import get_browser_pool
from .extractors import extract_article_info, create_shared_crawler
from .database import add_articles_batch, add_read_counts_batch
from .retry_policy import RESULT_RETRYABLE_ERROR_CODES
from .url_utils import validate_and_normalize_url


logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """错误分类枚举"""

    NETWORK = "network"
    PARSE = "parse"
    SSL = "ssl"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


def _get_error_category(error: Exception) -> ErrorCategory:
    """智能错误分类"""
    error_str = str(error).lower()

    permanent_keywords = ["404", "not found", "403", "forbidden", "401", "unauthorized"]
    if any(keyword in error_str for keyword in permanent_keywords):
        return ErrorCategory.PERMANENT

    ssl_keywords = ["ssl", "certificate", "handshake", "tls", "cert"]
    if any(keyword in error_str for keyword in ssl_keywords):
        return ErrorCategory.SSL

    network_keywords = [
        "timeout",
        "connection",
        "network",
        "temporary",
        "503",
        "502",
        "504",
        "429",
        "econnrefused",
        "econnreset",
        "etimedout",
        "connection refused",
        "connection reset",
        "connection aborted",
        "name resolution",
        "dns",
    ]
    if any(keyword in error_str for keyword in network_keywords):
        return ErrorCategory.NETWORK

    parse_keywords = [
        "extract",
        "parse",
        "selector",
        "element not found",
        "no such element",
    ]
    if any(keyword in error_str for keyword in parse_keywords):
        return ErrorCategory.PARSE

    return ErrorCategory.UNKNOWN


def _calculate_retry_delay(error_category: ErrorCategory, attempt: int) -> float:
    """计算重试延迟"""
    if error_category == ErrorCategory.SSL:
        base_delay = CRAWL_RETRY_SSL_DELAY
    elif error_category == ErrorCategory.PARSE:
        base_delay = CRAWL_RETRY_DELAY * attempt
    else:
        base_delay = CRAWL_RETRY_DELAY * (CRAWL_RETRY_BACKOFF ** (attempt - 1))

    delay = min(base_delay, CRAWL_RETRY_MAX_DELAY)

    if CRAWL_RETRY_JITTER:
        jitter = random.uniform(-0.1 * delay, 0.1 * delay)
        delay = max(0.1, delay + jitter)

    return delay


def _get_max_retries_for_category(error_category: ErrorCategory) -> int:
    """根据错误类型获取最大重试次数"""
    if error_category in (ErrorCategory.NETWORK, ErrorCategory.UNKNOWN):
        return CRAWL_RETRY_NETWORK_MAX
    elif error_category == ErrorCategory.PARSE:
        return CRAWL_RETRY_PARSE_MAX
    elif error_category == ErrorCategory.SSL:
        return CRAWL_RETRY_SSL_MAX
    return 0


def _get_retry_priority(error_category: ErrorCategory) -> int:
    """获取重试优先级（数字越小优先级越高）"""
    priority_map = {
        ErrorCategory.NETWORK: 1,
        ErrorCategory.UNKNOWN: 1,
        ErrorCategory.PARSE: 2,
        ErrorCategory.SSL: 3,
        ErrorCategory.PERMANENT: 4,
    }
    return priority_map.get(error_category, 5)


async def _crawl_single_with_retry(
    url: str,
    browser_pool,
    domain_controller: _DomainThrottleController,
) -> Dict:
    """带重试机制的单URL爬取"""
    raw_url = url
    normalized_url = url
    attempt = 0

    try:
        is_valid, normalized_url, site = validate_and_normalize_url(url)
        if not is_valid:
            return {
                "url": raw_url,
                "success": False,
                "error": "无效的URL格式（只支持 http/https）",
                "error_code": "invalid_url",
            }

        if not is_platform_allowed(site or ""):
            return {
                "url": raw_url,
                "success": False,
                "error": f'平台 "{site or "未知"}" 不在允许列表中，已跳过',
                "error_code": "platform_not_allowed",
            }

        # 微信文章暂不支持
        if site and ("weixin" in site or "qq.com" in site):
            logger.info("跳过：微信文章正在开发中")
            return {
                "url": raw_url,
                "success": False,
                "error": "微信文章正在开发中",
                "error_code": "weixin_not_supported",
            }

        while True:
            try:
                crawler = await browser_pool.acquire()
                if not crawler:
                    crawler = await create_shared_crawler()
                    use_pool = False
                else:
                    use_pool = True

                try:
                    info = await extract_article_info(normalized_url, crawler)
                    title = info.get("title")
                    count = info.get("read_count")
                finally:
                    if use_pool:
                        await browser_pool.release(crawler)
                    else:
                        await crawler.__aexit__(None, None, None)

                if count is None:
                    return {
                        "url": raw_url,
                        "success": False,
                        "error": "无法提取阅读数",
                        "error_code": "parse_failed",
                    }
                logger.info("更新成功，阅读数: %s", count)
                return {
                    "url": normalized_url,
                    "success": True,
                    "data": {
                        "title": title,
                        "site": site,
                        "read_count": count,
                    },
                }
            except Exception as e:
                error_category = _get_error_category(e)

                if error_category == ErrorCategory.PERMANENT:
                    logger.error("永久性错误（不重试）")
                    return {
                        "url": raw_url,
                        "success": False,
                        "error": str(e)[:200],
                        "error_code": "crawl_failed",
                    }

                max_retries = _get_max_retries_for_category(error_category)
                if attempt >= max_retries:
                    logger.error("爬取失败: %s", error_category.value)
                    return {
                        "url": raw_url,
                        "success": False,
                        "error": str(e)[:200],
                        "error_code": "crawl_failed",
                    }

                attempt += 1
                delay = _calculate_retry_delay(error_category, attempt)
                logger.info("重试 %s/%s", attempt, max_retries)
                await asyncio.sleep(delay)

    except Exception as e:
        return {
            "url": normalized_url,
            "success": False,
            "error": str(e)[:200],
            "error_code": "crawl_failed",
        }


async def _crawl_batch_with_retry(
    urls: List[str],
    browser_pool,
    domain_controller: _DomainThrottleController,
    on_result=None,
) -> List[Optional[Dict]]:
    """带重试的批量爬取"""
    results: List[Optional[Dict]] = [None] * len(urls)

    semaphore = asyncio.Semaphore(BATCH_PROCESS_CONCURRENCY)

    async def process_with_semaphore(idx: int, url: str):
        async with semaphore:
            result = await _crawl_single_with_retry(
                url,
                browser_pool,
                domain_controller,
            )
            if on_result and result:
                try:
                    on_result(result)
                except Exception:
                    logger.debug("on_result callback failed", exc_info=True)
            return idx, result

    tasks = [
        asyncio.create_task(process_with_semaphore(i, url))
        for i, url in enumerate(urls)
    ]
    for completed in asyncio.as_completed(tasks):
        idx, result = await completed
        results[idx] = result

    return results


async def _merge_retry_passes(
    *,
    urls: List[str],
    all_results: List[Optional[Dict]],
    extra_passes: int,
    batch_size: int,
    browser_pool,
    domain_controller: _DomainThrottleController,
    on_result=None,
) -> List[Optional[Dict]]:
    """重试失败的文章（使用 crawler.py 相同的重试机制）

    收集失败的文章，按错误类型排序后集中重试。
    """
    current_results: List[Optional[Dict]] = list(all_results)

    for _pass in range(int(extra_passes)):
        # 收集可重试的失败项
        failed_items: List[tuple] = []
        for idx, result in enumerate(current_results):
            if not isinstance(result, dict):
                continue
            if result.get("success") is True:
                continue
            code = result.get("error_code")
            if code in RESULT_RETRYABLE_ERROR_CODES:
                url = result.get("url") or urls[idx]
                error_category = ErrorCategory.UNKNOWN
                if code == "crawl_timeout":
                    error_category = ErrorCategory.NETWORK
                elif code == "parse_failed":
                    error_category = ErrorCategory.PARSE
                failed_items.append((idx, url, error_category))

        if not failed_items:
            break

        # 按错误类型排序（优先级高的先重试）
        failed_items.sort(key=lambda x: _get_retry_priority(x[2]))

        failed_urls = [item[1] for item in failed_items]
        logger.info("开始集中重试 %s 篇文章", len(failed_urls))

        # 集中重试
        retry_results = await _crawl_batch_for_results(
            failed_urls,
            browser_pool,
            domain_controller,
            on_result=on_result,
        )

        # 更新结果
        for i, (original_idx, _url, _error_category) in enumerate(failed_items):
            if i < len(retry_results) and retry_results[i]:
                current_results[original_idx] = retry_results[i]

    return current_results


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
                self._semaphores[domain] = asyncio.Semaphore(
                    CRAWL_CONCURRENCY_PER_DOMAIN
                )
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
    results: List[Optional[Dict]] = []
    total = len(urls)

    browser_pool = get_browser_pool()

    batch_size = BATCH_PROCESS_SIZE
    for i in range(0, total, batch_size):
        batch_urls = urls[i : i + batch_size]
        batch_results = await _process_batch(batch_urls, browser_pool)
        results.extend(batch_results)

        task_manager.update_task_progress(
            task_id,
            {
                "processed": len(results),
                "total": total,
                "success": sum(1 for r in results if r and r.get("success")),
                "failed": sum(1 for r in results if not (r and r.get("success"))),
            },
        )

    task = task_manager.get_task(task_id)
    if task:
        task["results"] = results


async def _process_urls_sync(urls: List[str]):
    """同步处理URL列表（用于小批量）"""
    browser_pool = get_browser_pool()
    return await _process_batch(urls, browser_pool)


async def crawl_urls_for_results(
    urls: List[str], on_result=None
) -> List[Optional[Dict]]:
    """仅爬取 URL 列表并返回结构化结果，不写入数据库。

    供 Bitable 同步等仅需「爬取结果」的场景复用。

    使用两轮重试机制：
    - 第一轮：每篇文章带重试机制爬取
    - 第二轮：集中重试第一轮失败的文章

    Returns:
        与 urls 顺序对应的列表，每项为:
        - 成功: {"url", "success": True, "data": {"title", "site", "read_count"}}
        - 失败: {"url", "success": False, "error": str}
    """
    browser_pool = get_browser_pool()
    batch_size = BATCH_PROCESS_SIZE
    all_results: List[Optional[Dict]] = []
    domain_controller = _DomainThrottleController()
    logger.info("开始爬取 %s 篇文章", len(urls))

    # 第一轮：批量爬取（保留 crawl_single_url_for_result 作为单次爬取入口，便于测试/复用）
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i : i + batch_size]
        batch_results = await _crawl_batch_for_results(
            batch_urls,
            browser_pool,
            domain_controller,
            on_result=on_result,
        )
        all_results.extend(batch_results)

    # 第二轮：集中重试第一轮失败的文章
    all_results = await _merge_retry_passes(
        urls=urls,
        all_results=all_results,
        extra_passes=RESULT_RETRY_EXTRA_PASSES,
        batch_size=batch_size,
        browser_pool=browser_pool,
        domain_controller=domain_controller,
        on_result=on_result,
    )
    success_count = sum(1 for r in all_results if r and r.get("success"))
    logger.info("爬取完成: %s/%s 成功", success_count, len(urls))
    return all_results


async def crawl_single_url_for_result(
    url: str,
    browser_pool=None,
    domain_controller: Optional[_DomainThrottleController] = None,
) -> Dict:
    """爬取单个 URL，返回统一结果结构，不写库。"""
    raw_url = url
    normalized_url = url
    try:
        is_valid, normalized_url, site = validate_and_normalize_url(url)
        if not is_valid:
            return {
                "url": raw_url,
                "success": False,
                "error": "无效的URL格式（只支持 http/https）",
                "error_code": "invalid_url",
            }

        if not is_platform_allowed(site or ""):
            return {
                "url": raw_url,
                "success": False,
                "error": f'平台 "{site or "未知"}" 不在允许列表中，已跳过',
                "error_code": "platform_not_allowed",
            }

        # 微信文章暂不支持
        if site and ("weixin" in site or "qq.com" in site):
            return {
                "url": raw_url,
                "success": False,
                "error": "微信文章正在开发中",
                "error_code": "weixin_not_supported",
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
                    title = info.get("title")
                    count = info.get("read_count")
                except Exception as e:
                    logger.warning("爬取失败")
                    title = None
                    count = None
                finally:
                    if use_pool:
                        await browser_pool.release(crawler)
                    else:
                        await crawler.__aexit__(None, None, None)
                    if domain_controller is not None:
                        await domain_controller.mark_done(normalized_url)

                if count is None:
                    return {
                        "url": raw_url,
                        "success": False,
                        "error": "无法提取阅读数",
                        "error_code": "parse_failed",
                    }
                logger.info(f"更新成功，閱讀數: {count}")
                return {
                    "url": normalized_url,
                    "success": True,
                    "data": {
                        "title": title,
                        "site": site,
                        "read_count": count,
                    },
                }
            except Exception as e:
                return {
                    "url": raw_url,
                    "success": False,
                    "error": str(e),
                    "error_code": "crawl_failed",
                }

        async def _crawl_with_domain_limit() -> Dict:
            if domain_sem is not None:
                async with domain_sem:
                    return await _crawl_once()
            return await _crawl_once()

        timeout_seconds = max(0.1, float(CRAWL_TIMEOUT))
        try:
            return await asyncio.wait_for(
                _crawl_with_domain_limit(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("爬取超时")
            return {
                "url": raw_url,
                "success": False,
                "error": f"爬取超时（>{timeout_seconds}秒）",
                "error_code": "crawl_timeout",
            }
    except Exception as e:
        return {
            "url": normalized_url,
            "success": False,
            "error": str(e),
            "error_code": "crawl_failed",
        }


async def _crawl_batch_for_results(
    urls: List[str],
    browser_pool,
    domain_controller: Optional[_DomainThrottleController] = None,
    on_result=None,
) -> List[Optional[dict]]:
    """爬取一批 URL，返回结果列表，不写库。"""
    processed_results: List[Optional[dict]] = [None] * len(urls)

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
                    "url": url,
                    "success": False,
                    "error": str(e),
                    "error_code": "crawl_failed",
                }

    tasks = [
        asyncio.create_task(process_with_semaphore(i, url))
        for i, url in enumerate(urls)
    ]
    for completed in asyncio.as_completed(tasks):
        idx, payload = await completed
        processed_results[idx] = payload
        if on_result is not None:
            try:
                on_result(payload)
            except Exception:
                logger.warning("on_result callback failed", exc_info=True)

    return processed_results


async def _process_batch(urls: List[str], browser_pool) -> List[Optional[dict]]:
    """处理一批URL：先爬取，再写入 SQLite。"""
    processed_results = await _crawl_batch_for_results(urls, browser_pool)

    articles_to_add = []
    read_counts_to_add = []
    for item in processed_results:
        if item and item.get("success"):
            articles_to_add.append(
                (item.get("url"), item["data"].get("title"), item["data"].get("site"))
            )
            read_counts_to_add.append((item["data"].get("read_count", 0),))

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
        if result and result.get("success") and article_idx < len(article_ids):
            result["data"]["id"] = article_ids[article_idx]
            result["data"]["initial_count"] = result["data"].get("read_count", 0)
            article_idx += 1

    logger.info("批量插入 %s 篇文章", len(articles_to_add))

    return processed_results
