"""Unit tests for Feishu Bitable client (lark_oapi SDK: list, update)."""
from unittest.mock import MagicMock, patch

import pytest

import monitor.feishu_client as feishu_client


def test_truncate_error_message():
    assert feishu_client.truncate_error_message("short") == "short"
    long_msg = "x" * 300
    out = feishu_client.truncate_error_message(long_msg, max_len=200)
    assert len(out) == 200
    assert out.endswith("...")


def test_list_bitable_records_success(monkeypatch):
    """list_bitable_records 使用 SDK 成功返回一页。"""
    fake_data = MagicMock()
    fake_data.items = [
        MagicMock(record_id="rec1", fields={"发布链接": "https://a.com/1"}),
    ]
    fake_data.has_more = False
    fake_data.page_token = None
    fake_resp = MagicMock()
    fake_resp.success.return_value = True
    fake_resp.data = fake_data

    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.list.return_value = fake_resp

    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)

    items, next_token = feishu_client.list_bitable_records(
        "app_tok", "tbl_id", app_id="id", app_secret="sec"
    )
    assert len(items) == 1
    assert items[0]["record_id"] == "rec1"
    assert next_token is None


def test_list_bitable_records_pagination(monkeypatch):
    """list_all_bitable_records 自动分页。"""
    call_count = [0]

    def list_resp(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            data = MagicMock()
            data.items = [MagicMock(record_id="rec1", fields={})]
            data.has_more = True
            data.page_token = "pt1"
        else:
            data = MagicMock()
            data.items = [MagicMock(record_id="rec2", fields={})]
            data.has_more = False
            data.page_token = None
        r = MagicMock()
        r.success.return_value = True
        r.data = data
        return r

    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.list.side_effect = list_resp

    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)

    all_items = feishu_client.list_all_bitable_records(
        "app_tok", "tbl_id", app_id="id", app_secret="sec", page_size=1
    )
    assert len(all_items) == 2
    assert all_items[0]["record_id"] == "rec1"
    assert all_items[1]["record_id"] == "rec2"


def test_list_bitable_records_no_credentials():
    feishu_client._client = None
    with pytest.raises(ValueError, match="未配置"):
        feishu_client.list_bitable_records(
            "app_tok", "tbl_id", app_id="", app_secret="sec"
        )


def test_list_bitable_records_api_error(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.success.return_value = False
    fake_resp.msg = "permission denied"
    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.list.return_value = fake_resp
    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)
    with pytest.raises(RuntimeError, match="Bitable 拉取记录失败"):
        feishu_client.list_bitable_records(
            "app_tok", "tbl_id", app_id="id", app_secret="sec"
        )


def test_update_bitable_record_success(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.success.return_value = True
    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.update.return_value = fake_resp
    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)

    feishu_client.update_bitable_record(
        "app_tok", "tbl_id", "rec1", {"总阅读量": 100},
        app_id="id", app_secret="sec",
    )
    fake_client.bitable.v1.app_table_record.update.assert_called_once()
    call_args = fake_client.bitable.v1.app_table_record.update.call_args[0][0]
    assert call_args.request_body.fields == {"总阅读量": 100}


def test_batch_update_bitable_records_success(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.success.return_value = True
    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.batch_update.return_value = fake_resp
    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)

    feishu_client.batch_update_bitable_records(
        "app_tok", "tbl_id",
        [("rec1", {"总阅读量": 10}), ("rec2", {"总阅读量": 20})],
        app_id="id", app_secret="sec",
    )
    fake_client.bitable.v1.app_table_record.batch_update.assert_called_once()
    call_req = fake_client.bitable.v1.app_table_record.batch_update.call_args[0][0]
    recs = call_req.request_body.records
    assert len(recs) == 2
    assert recs[0].record_id == "rec1" and recs[0].fields == {"总阅读量": 10}
    assert recs[1].record_id == "rec2" and recs[1].fields == {"总阅读量": 20}


def test_update_bitable_record_api_error(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.success.return_value = False
    fake_resp.msg = "record not found"
    fake_client = MagicMock()
    fake_client.bitable.v1.app_table_record.update.return_value = fake_resp
    monkeypatch.setattr(feishu_client, "_client", None)
    monkeypatch.setattr(feishu_client, "_get_client", lambda *a, **k: fake_client)
    with pytest.raises(RuntimeError, match="Bitable 更新记录失败"):
        feishu_client.update_bitable_record(
            "app_tok", "tbl_id", "rec1", {"总阅读量": 100},
            app_id="id", app_secret="sec",
        )
