"""Feishu Base (多维表格) writer — store curated summaries as records.

Reuses FeishuAPI for tenant token management.
"""

import json
import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger("feishu-base")

FEISHU_BASE = "https://open.feishu.cn/open-apis"


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
) -> set[str]:
    """Fetch existing topic titles for a given date to avoid duplicates."""
    url = (
        f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    )
    # date filter: exact match on 日期 field
    payload = {
        "field_names": ["话题标题"],
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "日期",
                    "operator": "is",
                    "value": date_str,
                }
            ],
        },
    }
    try:
        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        if resp.status_code != 200:
            logger.warning("Failed to search existing records: HTTP %d", resp.status_code)
            return set()
        data = resp.json()
        if data.get("code") != 0:
            logger.warning("Search records error: %s", data.get("msg", ""))
            return set()
        items = data.get("data", {}).get("items", [])
        existing = set()
        for item in items:
            fields = item.get("fields", {})
            topic = fields.get("话题标题", "")
            if topic:
                existing.add(topic)
        return existing
    except requests.RequestException as e:
        logger.warning("Search records request failed: %s", e)
        return set()


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
    existing = _existing_records(app_token, table_id, date_str)
    if existing:
        logger.info("Found %d existing topics for %s in Base", len(existing), date_str)

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

        # Skip if already recorded for this date
        if topic in existing:
            logger.info("  ⏭️  Skipped (already exists): %s", topic)
            skipped_count += 1
            continue

        # Format 来源链接 as markdown-style URL for the url text field
        source_link = f"[{topic}]({source_url})" if source_url else ""

        record = {
            "fields": {
                "话题标题": topic,
                "日期": int(time.mktime(time.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S"))),
                "优先级": priority,
                "精读摘要": summary_text,
                "来源": source,
                "来源链接": source_link,
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
