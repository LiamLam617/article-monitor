"""
Bitable 同步编排：从飞书多维表格读取发布链接 → 爬取 → 写回总阅读量/失败原因。
列名可配置，v1 仅写总阅读量与失败原因；24h/72h 预留可写空或占位。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

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
    app_token = (app_token or FEISHU_BITABLE_APP_TOKEN).strip()
    table_id = (table_id or FEISHU_BITABLE_TABLE_ID).strip()
    if not app_token or not table_id:
        return {
            "success": False,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
            "message": "未配置 FEISHU_BITABLE_APP_TOKEN 或 FEISHU_BITABLE_TABLE_ID",
        }
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return {
            "success": False,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
            "message": "未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET",
        }

    cols = _build_column_config(
        field_url=field_url,
        field_total_read=field_total_read,
        field_read_24h=field_read_24h,
        field_read_72h=field_read_72h,
        field_error=field_error,
    )

    try:
        records = list_all_bitable_records(app_token, table_id)
    except Exception as e:
        logger.exception("拉取 Bitable 记录失败")
        return {
            "success": False,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
            "message": str(e),
        }

    # 构建 (record_id, url) 列表，跳过无有效 URL 的记录
    rows: List[tuple] = []
    for rec in records:
        rid = rec.get("record_id") or rec.get("recordId")
        if not rid:
            continue
        raw = (rec.get("fields") or {}).get(cols["url"])
        url = _extract_url_from_field(raw)
        if url:
            rows.append((rid, url))

    if not rows:
        return {
            "success": True,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "errors": [],
            "message": "未找到有效发布链接",
        }

    record_ids = [r[0] for r in rows]
    urls = [r[1] for r in rows]

    # 异步爬取
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(crawl_urls_for_results(urls))
    finally:
        loop.close()

    updated = 0
    failed = 0
    errors_list: List[Dict[str, str]] = []
    records_to_update: List[tuple] = []  # [(record_id, fields), ...]

    for i, (record_id, crawl_result) in enumerate(zip(record_ids, results)):
        if i >= len(results):
            break
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
                "url": crawl_result.get("url", urls[i] if i < len(urls) else ""),
                "error": err_msg,
            })
        if fields_to_write:
            records_to_update.append((record_id, fields_to_write))

    if records_to_update:
        try:
            batch_update_bitable_records(app_token, table_id, records_to_update)
        except Exception as e:
            logger.exception("Bitable 批量写回失败")
            raise RuntimeError(f"Bitable 批量更新失败: {e}") from e

    return {
        "success": True,
        "processed": len(rows),
        "updated": updated,
        "failed": failed,
        "errors": errors_list,
    }
