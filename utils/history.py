"""Seven-day report history and two-layer topic deduplication."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from output.feishu_base import _field_date_bjt, search_records

logger = logging.getLogger("history")
BJT = timezone(timedelta(hours=8))

DECISIONS = {"new_topic", "new_progress", "duplicate", "uncertain"}


def normalize_text(value: str) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text


def fingerprint(*values: str) -> str:
    payload = "|".join(normalize_text(v) for v in values if v)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def topic_fingerprint(cluster: dict) -> str:
    return fingerprint(cluster.get("topic", ""))


def content_fingerprint(cluster: dict) -> str:
    values = [cluster.get("topic", "")]
    for item in cluster.get("items", []):
        if isinstance(item, dict):
            values.extend([item.get("title", ""), item.get("snippet", ""), item.get("body", "")])
    return fingerprint(*values)


def load_recent_history(app_token: str, table_id: str, days: int = 7) -> list[dict]:
    """Read recent history rows. Missing credentials/API errors degrade to empty history."""
    if not app_token or not table_id:
        return []
    try:
        records = search_records(
            app_token,
            table_id,
            field_names=[
                "话题标题", "日期", "来源", "来源链接", "精读摘要", "内容指纹",
                "主题指纹", "首次推送日期", "进展摘要", "状态", "记录来源",
            ],
        )
    except Exception as exc:
        logger.warning("History read failed: %s", exc)
        return []

    cutoff = datetime.now(BJT).date() - timedelta(days=days)
    result = []
    for record in records:
        fields = record.get("fields", {})
        date_str = _field_date_bjt(fields.get("日期"))
        try:
            date_value = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if date_value < cutoff:
            continue
        row = dict(fields)
        row["record_id"] = record.get("record_id", "")
        row["date_str"] = date_str
        result.append(row)
    logger.info("Loaded %d history rows from the last %d days", len(result), days)
    return result


def _tokens(text: str) -> set[str]:
    normalized = normalize_text(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def similarity(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def deterministic_status(cluster: dict, history: list[dict]) -> str | None:
    """Return duplicate when URL/title/content is certainly already seen."""
    current_content = content_fingerprint(cluster)
    current_topic = topic_fingerprint(cluster)
    current_urls = {
        item.get("url", "")
        for item in cluster.get("items", [])
        if isinstance(item, dict) and item.get("url")
    }
    for row in history:
        if current_content and row.get("内容指纹") == current_content:
            return "duplicate"
        old_url = row.get("来源链接", "")
        if isinstance(old_url, dict):
            old_url = old_url.get("link") or old_url.get("url") or old_url.get("text") or ""
        elif isinstance(old_url, list):
            old_url = " ".join(
                str(item.get("link") or item.get("url") or item.get("text") or "")
                if isinstance(item, dict) else str(item)
                for item in old_url
            )
        elif not isinstance(old_url, str):
            old_url = str(old_url or "")
        link_match = re.search(r"\]\((https?://[^)]+)\)", old_url or "")
        old_url = link_match.group(1) if link_match else old_url
        if old_url and old_url in current_urls:
            return "duplicate"
    return None


def build_semantic_pairs(clusters: list[dict], history: list[dict], threshold: float = 0.18) -> list[dict]:
    pairs = []
    for current_index, cluster in enumerate(clusters):
        topic = cluster.get("topic", "")
        for history_index, row in enumerate(history):
            score = similarity(topic, row.get("话题标题", ""))
            if score >= threshold:
                pairs.append({
                    "current_index": current_index,
                    "history_index": history_index,
                    "score": round(score, 3),
                })
    pairs.sort(key=lambda pair: pair["score"], reverse=True)
    return pairs[:120]


def filter_clusters_by_history(llm: Any, clusters: list[dict], history: list[dict]) -> list[dict]:
    """Filter old topics and annotate genuine progress for the summarizer."""
    if not history or not clusters:
        return clusters

    kept = []
    for cluster in clusters:
        status = deterministic_status(cluster, history)
        if status == "duplicate":
            logger.info("Skip deterministic duplicate: %s", cluster.get("topic", ""))
            continue
        kept.append(cluster)

    pairs = build_semantic_pairs(kept, history)
    if not pairs:
        return kept

    prompt_items = []
    for local_index, cluster in enumerate(kept):
        prompt_items.append({"index": local_index, "topic": cluster.get("topic", "")})
    prompt_history = [
        {"index": i, "topic": row.get("话题标题", ""), "date": row.get("date_str", ""), "progress": row.get("进展摘要", "")}
        for i, row in enumerate(history)
    ]
    prompt = (
        "请判断当前日报候选与近7天历史主题的关系。\n"
        "duplicate=同一事件且没有明确新进展；new_progress=同一事件但有明确新版本/数据/公告/结果；"
        "new_topic=新主题；uncertain=无法确认。换来源、换标题或换一种解读不算新进展。\n"
        "只输出 JSON：{\"decisions\":[{\"current_index\":0,\"decision\":\"...\",\"history_index\":0,\"progress_summary\":\"...\"}]}\n\n"
        f"当前候选：{json.dumps(prompt_items, ensure_ascii=False)}\n"
        f"历史主题：{json.dumps(prompt_history, ensure_ascii=False)}\n"
        f"可能相似配对：{json.dumps(pairs, ensure_ascii=False)}"
    )
    try:
        parsed = llm.extract_json(llm.messages_create(
            system="你是严格的新闻事件去重审校员。不要补充输入中没有的事实。",
            messages=[{"role": "user", "content": prompt}],
        ))
    except Exception as exc:
        logger.warning("Semantic history dedup failed: %s", exc)
        parsed = None

    decisions = {}
    if parsed and isinstance(parsed.get("decisions"), list):
        for item in parsed["decisions"]:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("current_index"))
            except (TypeError, ValueError):
                continue
            decision = item.get("decision", "uncertain")
            if decision not in DECISIONS:
                decision = "uncertain"
            decisions[idx] = item

    candidate_indexes = {pair["current_index"] for pair in pairs}
    result = []
    for local_index, cluster in enumerate(kept):
        decision = decisions.get(local_index)
        if local_index in candidate_indexes and (
            not decision or decision.get("decision") in {"duplicate", "uncertain"}
        ):
            status = decision.get("decision", "uncertain") if decision else "uncertain"
            logger.info("Skip %s history candidate: %s", status, cluster.get("topic", ""))
            continue
        if decision and decision.get("decision") == "new_progress":
            cluster = dict(cluster)
            cluster["history_note"] = (decision.get("progress_summary") or "").strip()[:500]
            try:
                history_index = int(decision.get("history_index"))
            except (TypeError, ValueError):
                history_index = -1
            if 0 <= history_index < len(history):
                cluster["history_first_date"] = (
                    _field_date_bjt(history[history_index].get("首次推送日期"))
                    or history[history_index].get("date_str", "")
                )
        result.append(cluster)
    return result
