"""
飞书 Open API 客户端：使用官方 lark_oapi SDK 实现鉴权与 Bitable 拉取/更新。
不依赖 SQLite，tenant_access_token 由 SDK 内部根据 app_id/app_secret 获取并缓存。

API 文档参考：
- 自建应用获取 tenant_access_token: https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
- 记录数据结构: https://open.feishu.cn/document/docs/bitable-v1/app-table-record/bitable-record-data-structure-overview
- 记录筛选: https://open.feishu.cn/document/docs/bitable-v1/app-table-record/record-filter-guide
- 查询记录: https://open.feishu.cn/document/docs/bitable-v1/app-table-record/search
- 批量获取: https://open.feishu.cn/document/docs/bitable-v1/app-table-record/batch_get
- 批量更新: https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_update
- SDK: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/python--sdk/preparations-before-development
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import lark_oapi as lark  # type: ignore[import-untyped]
from lark_oapi.api.bitable.v1 import (  # type: ignore[import-untyped]
    BatchUpdateAppTableRecordRequest,
    BatchUpdateAppTableRecordRequestBody,
    ListAppTableRecordRequest,
    UpdateAppTableRecordRequest,
)
from lark_oapi.api.bitable.v1.model.app_table_record import AppTableRecord  # type: ignore[import-untyped]

from .config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN,
)

logger = logging.getLogger(__name__)

# 单次批量更新最大条数（飞书限制，见 batch_update 文档）
BATCH_UPDATE_PAGE_SIZE = 500

# 单例 Client（SDK 内部管理 tenant_access_token 缓存）
_client: Optional[lark.Client] = None


def _get_client(app_id: Optional[str] = None, app_secret: Optional[str] = None) -> lark.Client:
    """获取或创建 lark Client，用于调用飞书 API。"""
    global _client
    app_id = app_id or FEISHU_APP_ID
    app_secret = app_secret or FEISHU_APP_SECRET
    if not app_id or not app_secret:
        raise ValueError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
    if _client is None:
        _client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
    return _client


def _record_item_to_dict(item: Any) -> Dict[str, Any]:
    """将 SDK 返回的 record 转为 dict，统一 record_id 与 fields。"""
    if isinstance(item, dict):
        d = dict(item)
    else:
        d = {
            "record_id": getattr(item, "record_id", None) or getattr(item, "recordId", None),
            "fields": getattr(item, "fields", None) or {},
        }
    if "record_id" not in d and "recordId" in d:
        d["record_id"] = d["recordId"]
    return d


def list_bitable_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    page_token: Optional[str] = None,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    拉取 Bitable 表记录（单页）。

    Returns:
        (items, next_page_token)
        items: [ {"record_id": str, "fields": {...} }, ... ]
        next_page_token: 下一页 token，无更多时为 None
    """
    client = _get_client(app_id, app_secret)
    builder = (
        ListAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .page_size(page_size)
    )
    if page_token:
        builder = builder.page_token(page_token)
    req = builder.build()
    resp = client.bitable.v1.app_table_record.list(req)
    if not resp.success():
        logger.error(
            "client.bitable.v1.app_table_record.list failed, code=%s, msg=%s",
            resp.code, resp.msg,
        )
        raise RuntimeError(f"Bitable 拉取记录失败: {resp.msg}")
    data = resp.data
    items_raw = getattr(data, "items", None) or []
    items = [_record_item_to_dict(i) for i in items_raw]
    has_more = getattr(data, "has_more", False)
    next_token = getattr(data, "page_token", None) if has_more else None
    return items, next_token


def list_all_bitable_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """拉取 Bitable 表全部记录（自动分页）。"""
    all_items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        items, page_token = list_bitable_records(
            app_token,
            table_id,
            page_size=page_size,
            page_token=page_token,
            app_id=app_id,
            app_secret=app_secret,
        )
        all_items.extend(items)
        if not page_token:
            break
    return all_items


def update_bitable_record(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: Dict[str, Any],
    *,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
) -> None:
    """更新 Bitable 单条记录。"""
    client = _get_client(app_id, app_secret)
    body = AppTableRecord.builder().fields(fields).build()
    req = (
        UpdateAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .record_id(record_id)
        .request_body(body)
        .build()
    )
    resp = client.bitable.v1.app_table_record.update(req)
    if not resp.success():
        logger.error(
            "client.bitable.v1.app_table_record.update failed, code=%s, msg=%s",
            resp.code, resp.msg,
        )
        raise RuntimeError(f"Bitable 更新记录失败: {resp.msg}")


def batch_update_bitable_records(
    app_token: str,
    table_id: str,
    records: List[Tuple[str, Dict[str, Any]]],
    *,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    page_size: int = BATCH_UPDATE_PAGE_SIZE,
) -> None:
    """
    批量更新 Bitable 记录（按 page_size 分片请求）。

    Args:
        app_token: 多维表格 app_token
        table_id: 数据表 table_id
        records: [(record_id, fields), ...]
        page_size: 单次请求最大条数，默认 500（飞书 batch_update 限制）
    """
    if not records:
        return
    client = _get_client(app_id, app_secret)
    for i in range(0, len(records), page_size):
        chunk = records[i : i + page_size]
        app_records = [
            AppTableRecord.builder().record_id(rid).fields(fields).build()
            for rid, fields in chunk
        ]
        body = BatchUpdateAppTableRecordRequestBody.builder().records(app_records).build()
        req = (
            BatchUpdateAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .request_body(body)
            .build()
        )
        resp = client.bitable.v1.app_table_record.batch_update(req)
        if not resp.success():
            logger.error(
                "client.bitable.v1.app_table_record.batch_update failed, code=%s, msg=%s",
                resp.code, resp.msg,
            )
            msg = f"Bitable 批量更新记录失败: {resp.msg}"
            if resp.code == 91403:
                msg += "（91403 Forbidden：请确认飞书应用已获得该多维表格的「可编辑」权限，并在应用后台开通 bitable:app 写权限）"
            raise RuntimeError(msg)


def truncate_error_message(message: str, max_len: Optional[int] = None) -> str:
    """截断错误信息，避免写回 Bitable 时过长。"""
    max_len = max_len or FEISHU_BITABLE_ERROR_MESSAGE_MAX_LEN
    if len(message) <= max_len:
        return message
    return message[: max_len - 3] + "..."
