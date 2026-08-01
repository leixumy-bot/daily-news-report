"""LLM 结构化输出校验与清洗。

Stage 1 去重聚类、Stage 2 摘要的输出仅做 JSON 语法解析（extract_json），
无法保证 priority/category/type/items 的结构正确。这里在解析后做字段级
清洗，把坏数据修复或丢弃，避免穿透到排序与多维表格写入。
"""

from processors.categories import normalize_category, normalize_type

# priority 合法范围
PRIORITY_MIN = 1
PRIORITY_MAX = 5
PRIORITY_DEFAULT = 3


def _normalize_priority(raw) -> int:
    """priority 转 int 并 clamp 到 [1,5]，非法值回退到默认 3。

    修复：LLM 返回字符串优先级（如 "5"、"高"）导致排序错乱、
    多维表格数字字段拒绝写入。
    """
    if isinstance(raw, bool):  # True/False 不是合法优先级
        return PRIORITY_DEFAULT
    if isinstance(raw, (int, float)):
        value = int(raw)
    elif isinstance(raw, str):
        try:
            value = int(float(raw.strip()))
        except (ValueError, TypeError):
            return PRIORITY_DEFAULT
    else:
        return PRIORITY_DEFAULT
    return max(PRIORITY_MIN, min(PRIORITY_MAX, value))


def _clean_item(item) -> dict | None:
    """清洗单条 items 项：只保留含 title 的 dict，丢弃字符串/空项。"""
    if not isinstance(item, dict):
        return None
    title = (item.get("title") or "").strip()
    if not title:
        return None
    cleaned = {k: item.get(k, "") for k in ("title", "url", "source", "snippet", "body")}
    cleaned["title"] = title
    return cleaned


def validate_clusters(raw_clusters) -> list[dict]:
    """逐簇清洗 LLM 聚类输出。

    返回清洗后的簇列表；全部非法则返回空列表（调用方据此走 fallback）。
    """
    if not isinstance(raw_clusters, list):
        return []

    cleaned: list[dict] = []
    for c in raw_clusters:
        if not isinstance(c, dict):
            continue

        # topic：非空字符串；空则用首条 item 的 title 兜底，仍空 → 丢弃
        topic = (c.get("topic") or "").strip()
        items = [_clean_item(i) for i in (c.get("items") or [])]
        items = [i for i in items if i is not None]
        if not topic:
            if items:
                topic = items[0]["title"]
            else:
                continue
        topic = topic[:200]

        cleaned.append(
            {
                "topic": topic,
                "priority": _normalize_priority(c.get("priority")),
                "category": normalize_category(c.get("category", "")),
                "type": normalize_type(c.get("type", "")),
                "items": items,
                "relevance": (c.get("relevance") or "").strip()[:300],
            }
        )
    return cleaned
