"""Feishu Base (多维表格) writer — store curated summaries as records.

Reuses FeishuAPI for tenant token management.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

logger = logging.getLogger("feishu-base")

FEISHU_BASE = "https://open.feishu.cn/open-apis"
BJT = timezone(timedelta(hours=8))


def _date_timestamp_bjt(date_str: str) -> int:
    """Return the canonical cell value for a Base datetime field.

    多维表格日期字段接受秒级时间戳，不接受 "YYYY-MM-DD HH:MM:SS" 字符串
    （v4.0 曾改为字符串导致 DatetimeFieldConvFail、历史记录全部写不进去）。
    用 BJT 0 点的时间戳，避免 CI（UTC）与本地时区差异导致跨天偏移。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=BJT)
    return int(dt.timestamp())


def _field_date_bjt(value) -> str:
    """把多维表格日期字段值（秒/毫秒时间戳或字符串）转成 BJT YYYY-MM-DD。"""
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e12 else value  # 毫秒→秒
        return datetime.fromtimestamp(ts, tz=BJT).strftime("%Y-%m-%d")
    if isinstance(value, str):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
        if m:
            return m.group(1)
    return ""


def search_records(
    app_token: str,
    table_id: str,
    field_names: list[str] | None = None,
    page_size: int = 500,
) -> list[dict]:
    """分页拉取全部记录，每条保留 record_id。返回 [{"record_id":..., "fields":{...}}]。"""
    url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    all_records: list[dict] = []
    page_token = ""
    while True:
        payload: dict = {"page_size": page_size}
        if field_names:
            payload["field_names"] = field_names
        if page_token:
            payload["page_token"] = page_token
        try:
            resp = requests.post(url, headers=_headers(), json=payload, timeout=20)
        except requests.RequestException as e:
            logger.warning("Search records request failed: %s", e)
            break
        if resp.status_code != 200 or resp.json().get("code") != 0:
            logger.warning("Search records error: HTTP %d %s",
                           resp.status_code, resp.text[:200])
            break
        data = resp.json().get("data", {})
        all_records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break
    return all_records


def batch_update_records(
    app_token: str,
    table_id: str,
    records: list[dict],
    batch_size: int = 100,
) -> dict:
    """批量更新记录。records: [{"record_id":..., "fields":{...}}]。返回汇总。"""
    url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    success = 0
    failed: list[dict] = []
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        try:
            resp = requests.post(url, headers=_headers(), json={"records": batch}, timeout=20)
        except requests.RequestException as e:
            logger.error("batch_update request failed: %s", e)
            failed.extend(batch)
            continue
        if resp.status_code != 200:
            logger.error("batch_update HTTP %d %s", resp.status_code, resp.text[:200])
            failed.extend(batch)
            continue
        data = resp.json()
        if data.get("code") != 0:
            logger.error("batch_update error: %s", data.get("msg", ""))
            failed.extend(batch)
            continue
        success += len(batch)
        logger.info("batch_update: %d records ok", len(batch))
    return {"success": success, "failed": failed}


def _get_token() -> str:
    """Get tenant access token using bot credentials."""
    app_id = os.environ.get("LARK_APP_ID", "")
    app_secret = os.environ.get("LARK_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError("LARK_APP_ID and LARK_APP_SECRET must be set")

    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("tenant_access_token", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def _existing_records(
    app_token: str, table_id: str, date_str: str
) -> tuple[set[str], set[str]]:
    """拉取指定日期的记录，返回 (话题标题集合, 内容指纹集合)。

    日期按字段值（秒/毫秒时间戳）解析成 BJT 日期比对，修复字符串匹配失效问题。
    """
    records = search_records(app_token, table_id, field_names=["话题标题", "日期", "内容指纹"])
    topics: set[str] = set()
    content_fingerprints: set[str] = set()
    for r in records:
        fields = r.get("fields", {})
        if _field_date_bjt(fields.get("日期")) != date_str:
            continue
        topic = fields.get("话题标题", "")
        if topic:
            topics.add(topic)
        content_fp = fields.get("内容指纹", "")
        if content_fp:
            content_fingerprints.add(content_fp)
    return topics, content_fingerprints


def save_summaries_to_base(
    summaries: list[dict],
    date_str: str,
    app_token: str = "",
    table_id: str = "",
) -> bool:
    """Save curated summaries as records in the Feishu Base (多维表格).

    Each summary becomes one record with fields: 日期, 话题标题, 优先级, 精读摘要, 来源, 来源链接.
    Skips topics already recorded for this date (idempotent).
    """
    app_token = app_token or os.environ.get("LARK_BASE_TOKEN", "")
    table_id = table_id or os.environ.get("LARK_BASE_TABLE_ID", "tblwj7BApfF5hC3A")

    if not app_token:
        logger.warning("LARK_BASE_TOKEN not set — skipping Base write")
        return False

    # Check existing records for today
    existing_topics, existing_content_fingerprints = _existing_records(app_token, table_id, date_str)
    if existing_topics:
        logger.info("Found %d existing topics for %s in Base", len(existing_topics), date_str)

    headers = _headers()
    url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records"

    success_count = 0
    skipped_count = 0

    for s in summaries:
        topic = s.get("topic", "")
        priority = s.get("priority", 3)
        summary_text = s.get("summary_text", "")
        source = s.get("source", "")
        source_url = s.get("url", "")
        category = s.get("category", "其他")
        item_type = s.get("type", "新闻")

        content_fp = s.get("content_fingerprint", "")
        # 完全相同内容跳过；同主题但有新进展允许新增一条记录。
        if content_fp and content_fp in existing_content_fingerprints:
            logger.info("  ⏭️  Skipped (same content): %s", topic)
            skipped_count += 1
            continue
        if not content_fp and topic in existing_topics:
            logger.info("  ⏭️  Skipped (legacy topic): %s", topic)
            skipped_count += 1
            continue

        # Format 来源链接 as markdown-style URL for the url text field
        source_link = f"[{topic}]({source_url})" if source_url else ""

        record = {
            "fields": {
                "话题标题": topic,
                "日期": _date_timestamp_bjt(date_str),
                "优先级": priority,
                "精读摘要": summary_text,
                "来源": source,
                "来源链接": source_link,
                "分类": category,
                "类型": item_type,
                "内容指纹": s.get("content_fingerprint", ""),
                "主题指纹": s.get("topic_fingerprint", ""),
                "首次推送日期": _date_timestamp_bjt(s.get("first_push_date") or date_str),
                "最后推送日期": _date_timestamp_bjt(date_str),
                "进展摘要": s.get("history_note", ""),
                "状态": "正常",
                "记录来源": "daily_report",
            }
        }

        try:
            resp = requests.post(url, headers=headers, json=record, timeout=15)
            if resp.status_code != 200:
                logger.error(
                    "Failed to insert record for '%s': HTTP %d %s",
                    topic, resp.status_code, resp.text[:200],
                )
                continue
            data = resp.json()
            if data.get("code") != 0:
                logger.error(
                    "Failed to insert record for '%s': %s",
                    topic, data.get("msg", ""),
                )
                continue
            logger.info("  ✅ Inserted: %s (priority=%d)", topic, priority)
            success_count += 1
        except requests.RequestException as e:
            logger.error("Request failed for '%s': %s", topic, e)
            continue

    logger.info(
        "Base write done: %d inserted, %d skipped (already existed)",
        success_count, skipped_count,
    )
    return success_count > 0 or skipped_count > 0
