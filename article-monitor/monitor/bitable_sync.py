"""
Bitable 同步编排：从飞书多维表格读取发布链接 → 爬取 → 写回总阅读量/失败原因。
列名可配置，v1 仅写总阅读量与失败原因；24h/72h 预留可写空或占位。
"""
import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

from .article_service import crawl_urls_for_results
from .config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_BITABLE_APP_TOKEN,
    FEISHU_BITABLE_TABLE_ID,
    FEISHU_BITABLE_FIELD_URL,
    FEISHU_BITABLE_FIELD_TOTAL_READ,
    FEISHU_BITABLE_FIELD_READ_24H,
    FEISHU_BITABLE_FIELD_READ_72H,
    FEISHU_BITABLE_FIELD_ERROR,
)
from .feishu_client import (
    list_all_bitable_records,
    batch_update_bitable_records,
    truncate_error_message,
)

logger = logging.getLogger(__name__)


def _empty_sync_result(message: str, *, success: bool = False) -> Dict[str, Any]:
    return {
        "success": success,
        "processed": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
        "message": message,
    }


def _normalize_source_item(source: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """标准化单个来源配置，返回 (normalized_source, error_message)。"""
    if not isinstance(source, dict):
        return None, "source 项必须是对象"
    app_token = (source.get("app_token") or FEISHU_BITABLE_APP_TOKEN or "").strip()
    table_id = (source.get("table_id") or "").strip()
    if not table_id:
        return None, "缺少 table_id"
    return {
        "app_token": app_token,
        "table_id": table_id,
        "field_url": source.get("field_url"),
        "field_total_read": source.get("field_total_read"),
        "field_read_24h": source.get("field_read_24h"),
        "field_read_72h": source.get("field_read_72h"),
        "field_error": source.get("field_error"),
    }, None


def _source_result_key_from_source(source: Any) -> Tuple[str, str]:
    """与请求 source 对齐的 (app_token, table_id)，用于共享池结果分发。"""
    if not isinstance(source, dict):
        return ("", "")
    app = (source.get("app_token") or FEISHU_BITABLE_APP_TOKEN or "").strip()
    tid = (source.get("table_id") or "").strip()
    return (app, tid)


def _source_result_key_from_table_row(tr: Dict[str, Any]) -> Tuple[str, str]:
    """从单表同步结果行取键；需与 sync 写入的 app_token/table_id 一致。"""
    app = (tr.get("app_token") or "").strip()
    tid = (tr.get("table_id") or "").strip()
    return (app, tid)


def _extract_url_from_field(value: Any) -> Optional[str]:
    """从 Bitable 字段原始值中提取 URL 字符串。"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s.startswith(("http://", "https://")) else None
    if isinstance(value, dict):
        return value.get("link") or value.get("text") or value.get("url")
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first.strip() if first.strip().startswith(("http://", "https://")) else None
        if isinstance(first, dict):
            return first.get("link") or first.get("text") or first.get("url")
    return None


def _build_column_config(
    field_url: Optional[str] = None,
    field_total_read: Optional[str] = None,
    field_read_24h: Optional[str] = None,
    field_read_72h: Optional[str] = None,
    field_error: Optional[str] = None,
) -> Dict[str, str]:
    """构建列名映射，未传则用 config 默认值。"""
    return {
        "url": field_url or FEISHU_BITABLE_FIELD_URL,
        "total_read": field_total_read or FEISHU_BITABLE_FIELD_TOTAL_READ,
        "read_24h": field_read_24h or FEISHU_BITABLE_FIELD_READ_24H,
        "read_72h": field_read_72h or FEISHU_BITABLE_FIELD_READ_72H,
        "error": field_error or FEISHU_BITABLE_FIELD_ERROR,
    }


class BitableSyncService:
    """Bitable 同步服务：聚合单表、多表同步与结果汇总逻辑。"""

    def __init__(self):
        self._shared_sync_lock = threading.Lock()
        self._shared_sync_pending: List[Dict[str, Any]] = []
        self._shared_sync_worker_running = False
        self._shared_sync_batch_wait_seconds = 0.8
        self._shared_sync_wait_timeout_seconds = 180

    def sync_single_table(
        self,
        app_token: Optional[str] = None,
        table_id: Optional[str] = None,
        *,
        field_url: Optional[str] = None,
        field_total_read: Optional[str] = None,
        field_read_24h: Optional[str] = None,
        field_read_72h: Optional[str] = None,
        field_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        app_token = (app_token or FEISHU_BITABLE_APP_TOKEN).strip()
        table_id = (table_id or FEISHU_BITABLE_TABLE_ID).strip()
        if not app_token or not table_id:
            return _empty_sync_result("未配置 FEISHU_BITABLE_APP_TOKEN 或 FEISHU_BITABLE_TABLE_ID")
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            return _empty_sync_result("未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

        out = self.sync_multiple_tables(
            [{
                "app_token": app_token,
                "table_id": table_id,
                "field_url": field_url,
                "field_total_read": field_total_read,
                "field_read_24h": field_read_24h,
                "field_read_72h": field_read_72h,
                "field_error": field_error,
            }],
            max_concurrency=1,
        )
        table_results = out.get("tables") or []
        if not table_results:
            return _empty_sync_result("同步结果为空")
        return table_results[0]

    def sync_multiple_tables(
        self,
        sources: List[Dict[str, Any]],
        *,
        max_concurrency: int = 3,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """集中提取多表 URL，统一爬取后按表回写，保证结果归属。"""
        invalid_out = self._validate_sync_input(sources, max_concurrency)
        if invalid_out is not None:
            return invalid_out

        table_jobs, table_results = self._collect_table_jobs_and_initial_results(sources)
        url_result_map = self._crawl_dedup_urls(table_jobs, progress_callback=progress_callback)

        for job in table_jobs:
            table_results.append(self._sync_single_job(job, url_result_map))

        return self._build_overall_result(table_results)

    @staticmethod
    def _validate_sync_input(
        sources: List[Dict[str, Any]],
        max_concurrency: int,
    ) -> Optional[Dict[str, Any]]:
        if max_concurrency < 1:
            out = _empty_sync_result("max_concurrency 必须 >= 1")
            out["tables"] = []
            return out
        if not isinstance(sources, list) or not sources:
            out = _empty_sync_result("sources 不能为空")
            out["tables"] = []
            return out
        return None

    def _collect_table_jobs_and_initial_results(
        self,
        sources: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        table_jobs: List[Dict[str, Any]] = []
        table_results: List[Dict[str, Any]] = []

        for raw_source in sources:
            normalized, source_error = _normalize_source_item(raw_source)
            raw_tid = ""
            raw_app = ""
            if isinstance(raw_source, dict):
                raw_tid = (raw_source.get("table_id") or "").strip()
                raw_app = (raw_source.get("app_token") or FEISHU_BITABLE_APP_TOKEN or "").strip()

            if source_error:
                table_results.append(
                    self._build_table_result_item(raw_app, raw_tid, success=False, message=source_error)
                )
                continue

            if not normalized.get("app_token"):
                table_results.append(
                    self._build_table_result_item("", normalized["table_id"], success=False, message="缺少 app_token")
                )
                continue

            job_or_error = self._build_job_from_source(normalized)
            if "message" in job_or_error:
                table_results.append(job_or_error)
            else:
                table_jobs.append(job_or_error)

        return table_jobs, table_results

    def _build_job_from_source(self, normalized: Dict[str, Any]) -> Dict[str, Any]:
        cols = _build_column_config(
            field_url=normalized.get("field_url"),
            field_total_read=normalized.get("field_total_read"),
            field_read_24h=normalized.get("field_read_24h"),
            field_read_72h=normalized.get("field_read_72h"),
            field_error=normalized.get("field_error"),
        )
        try:
            records = list_all_bitable_records(normalized["app_token"], normalized["table_id"])
        except Exception as exc:
            logger.exception("拉取 Bitable 记录失败: table_id=%s", normalized["table_id"])
            return self._build_table_result_item(
                normalized["app_token"],
                normalized["table_id"],
                success=False,
                message=str(exc),
            )

        rows: List[Tuple[str, str]] = []
        for rec in records:
            rid = rec.get("record_id") or rec.get("recordId")
            if not rid:
                continue
            raw = (rec.get("fields") or {}).get(cols["url"])
            url = _extract_url_from_field(raw)
            if url:
                rows.append((rid, url))

        return {"source": normalized, "cols": cols, "rows": rows}

    @staticmethod
    def _crawl_dedup_urls(table_jobs: List[Dict[str, Any]], progress_callback=None) -> Dict[str, Dict[str, Any]]:
        dedup_urls: List[str] = []
        seen_urls = set()
        for job in table_jobs:
            for _, url in job["rows"]:
                if url not in seen_urls:
                    seen_urls.add(url)
                    dedup_urls.append(url)

        url_result_map: Dict[str, Dict[str, Any]] = {}
        total_urls = len(dedup_urls)
        processed_urls = 0
        if progress_callback is not None:
            progress_callback({
                "stage": "crawling",
                "batch_url_progress": {"processed": 0, "total": total_urls},
            })
        if not dedup_urls:
            return url_result_map

        loop = asyncio.new_event_loop()
        try:
            def _on_crawl_result(payload: Dict[str, Any]):
                nonlocal processed_urls
                processed_urls += 1
                if progress_callback is not None:
                    progress_callback({
                        "stage": "crawling",
                        "batch_url_progress": {"processed": processed_urls, "total": total_urls},
                        "last_url": payload.get("url"),
                        "last_error": payload.get("error") if not payload.get("success") else None,
                    })

            crawl_results = loop.run_until_complete(crawl_urls_for_results(dedup_urls, on_result=_on_crawl_result))
        finally:
            loop.close()

        for url, result in zip(dedup_urls, crawl_results):
            url_result_map[url] = result
        return url_result_map

    def _sync_single_job(
        self,
        job: Dict[str, Any],
        url_result_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        source = job["source"]
        cols = job["cols"]
        rows = job["rows"]

        records_to_update, updated, failed, errors_list = self._build_updates_for_rows(rows, cols, url_result_map)

        table_item = self._build_table_result_item(
            source["app_token"],
            source["table_id"],
            success=True,
            processed=len(rows),
            updated=updated,
            failed=failed,
            errors=errors_list,
        )
        if not rows:
            table_item["message"] = "未找到有效发布链接"
            return table_item

        try:
            if records_to_update:
                batch_update_bitable_records(source["app_token"], source["table_id"], records_to_update)
            return table_item
        except Exception as exc:
            logger.exception("Bitable 批量写回失败: table_id=%s", source["table_id"])
            table_item["success"] = False
            table_item["message"] = f"Bitable 批量更新失败: {exc}"
            return table_item

    @staticmethod
    def _build_updates_for_rows(
        rows: List[Tuple[str, str]],
        cols: Dict[str, str],
        url_result_map: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], int, int, List[Dict[str, str]]]:
        updated = 0
        failed = 0
        errors_list: List[Dict[str, str]] = []
        records_to_update: List[Tuple[str, Dict[str, Any]]] = []

        for record_id, url in rows:
            crawl_result = url_result_map.get(url) or {
                "success": False,
                "url": url,
                "error": "未找到对应爬取结果",
            }
            fields_to_write: Dict[str, Any] = {}
            if crawl_result.get("success"):
                data = crawl_result.get("data") or {}
                total = data.get("read_count")
                if total is not None:
                    fields_to_write[cols["total_read"]] = total
                fields_to_write[cols["error"]] = ""
                updated += 1
            else:
                err_msg = crawl_result.get("error", "未知错误")
                fields_to_write[cols["error"]] = truncate_error_message(err_msg)
                failed += 1
                errors_list.append({
                    "record_id": record_id,
                    "url": crawl_result.get("url", url),
                    "error": err_msg,
                })
            if fields_to_write:
                records_to_update.append((record_id, fields_to_write))

        return records_to_update, updated, failed, errors_list

    @staticmethod
    def _build_table_result_item(
        app_token: str,
        table_id: str,
        *,
        success: bool,
        processed: int = 0,
        updated: int = 0,
        failed: int = 0,
        errors: Optional[List[Dict[str, str]]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        item = {
            "app_token": app_token,
            "table_id": table_id,
            "success": success,
            "processed": processed,
            "updated": updated,
            "failed": failed,
            "errors": errors or [],
        }
        if message:
            item["message"] = message
        return item

    @staticmethod
    def _build_overall_result(table_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        all_errors: List[Dict[str, Any]] = []
        total_processed = 0
        total_updated = 0
        total_failed = 0
        overall_success = True

        for item in table_results:
            total_processed += int(item.get("processed", 0))
            total_updated += int(item.get("updated", 0))
            total_failed += int(item.get("failed", 0))
            if not item.get("success", False):
                overall_success = False
            for err in item.get("errors", []):
                tagged_error = dict(err)
                tagged_error["table_id"] = item.get("table_id")
                all_errors.append(tagged_error)

        return {
            "success": overall_success,
            "processed": total_processed,
            "updated": total_updated,
            "failed": total_failed,
            "errors": all_errors,
            "tables": table_results,
        }

    def sync_via_shared_pool(self, source: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """将单表同步请求加入共享池，批次合并后统一爬取。"""
        done_event = threading.Event()
        request_item = {
            "source": dict(source or {}),
            "done": done_event,
            "result": None,
            "progress_callback": progress_callback,
        }

        with self._shared_sync_lock:
            self._shared_sync_pending.append(request_item)
            if not self._shared_sync_worker_running:
                self._shared_sync_worker_running = True
                worker = threading.Thread(target=self._shared_sync_worker_loop, daemon=True)
                worker.start()

        if not done_event.wait(timeout=self._shared_sync_wait_timeout_seconds):
            return _empty_sync_result("共享同步池等待超时")
        result = request_item.get("result")
        if isinstance(result, dict):
            return result
        return _empty_sync_result("共享同步池返回空结果")

    def _shared_sync_worker_loop(self):
        while True:
            time.sleep(self._shared_sync_batch_wait_seconds)
            with self._shared_sync_lock:
                if not self._shared_sync_pending:
                    self._shared_sync_worker_running = False
                    return
                batch = list(self._shared_sync_pending)
                self._shared_sync_pending.clear()

            sources = [item["source"] for item in batch]
            fallback_result = _empty_sync_result("未匹配到表同步结果")
            try:
                def _batch_progress(event: Dict[str, Any]):
                    for item in batch:
                        cb = item.get("progress_callback")
                        if cb is None:
                            continue
                        try:
                            cb(dict(event))
                        except Exception:
                            logger.warning("shared pool progress callback failed", exc_info=True)

                out = self.sync_multiple_tables(
                    sources,
                    max_concurrency=1,
                    progress_callback=_batch_progress,
                )
                table_results = out.get("tables") or []
            except Exception as exc:
                logger.exception("共享同步池批处理失败")
                table_results = []
                for s in sources:
                    app, tid = _source_result_key_from_source(s)
                    table_results.append({
                        "app_token": app,
                        "table_id": tid,
                        "success": False,
                        "processed": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                        "message": str(exc),
                    })
            finally:
                buckets: Dict[Tuple[str, str], deque] = defaultdict(deque)
                for tr in table_results:
                    buckets[_source_result_key_from_table_row(tr)].append(tr)
                for item in batch:
                    key = _source_result_key_from_source(item["source"])
                    q = buckets.get(key)
                    table_result = q.popleft() if q else fallback_result
                    item["result"] = dict(table_result)
                    item["done"].set()


_sync_service = BitableSyncService()


def sync_from_bitable(
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
    *,
    field_url: Optional[str] = None,
    field_total_read: Optional[str] = None,
    field_read_24h: Optional[str] = None,
    field_read_72h: Optional[str] = None,
    field_error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从 Bitable 拉取记录 → 爬取 URL → 写回总阅读量与失败原因（同步执行）。

    Returns:
        {
            "success": bool,
            "processed": int,
            "updated": int,
            "failed": int,
            "errors": [ {"record_id", "url", "error"}, ... ],
            "message": str (when success is False)
        }
    """
    out = _sync_service.sync_single_table(
        app_token=app_token,
        table_id=table_id,
        field_url=field_url,
        field_total_read=field_total_read,
        field_read_24h=field_read_24h,
        field_read_72h=field_read_72h,
        field_error=field_error,
    )
    # Backward compatibility: keep historical exception behavior on write-back failure.
    if not out.get("success", False) and str(out.get("message", "")).startswith("Bitable 批量更新失败"):
        raise RuntimeError(str(out.get("message")))
    return out


def sync_from_multiple_bitable_sources(
    sources: List[Dict[str, Any]],
    *,
    max_concurrency: int = 3,
) -> Dict[str, Any]:
    """多表同步入口。

    Note:
        `max_concurrency` is retained for API compatibility.
        Current implementation uses shared crawl path and does not apply per-table parallelism.
    """
    if max_concurrency != 1:
        logger.warning(
            "sync_from_multiple_bitable_sources: max_concurrency=%s currently kept for compatibility",
            max_concurrency,
        )
    return _sync_service.sync_multiple_tables(sources, max_concurrency=max_concurrency)


def sync_from_bitable_via_shared_pool(source: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
    return _sync_service.sync_via_shared_pool(source, progress_callback=progress_callback)
