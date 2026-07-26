"""Stage 1: Deduplicate and cluster news items using LLM."""

import json
import logging
from typing import Any

from utils.llm import LLMClient, LLMError
from collectors.base import NewsItem

logger = logging.getLogger("dedup-cluster")

SYSTEM_PROMPT = """你是 AI/Cloud 行业的专业新闻分析师。你的任务是对一组中文新闻条目进行去重和聚类。

规则：
1. 内容描述同一事件或话题的条目归为同一个话题簇
2. 优先标注原始来源（一手报道/官方公告），拒绝二手/三手转载
3. **严格过滤**：只保留最核心的 AI/Cloud 相关新闻。以下类别必须舍弃：
   - 招聘/大赛/榜单/调研报告等推广内容
   - 公司简介/产品介绍页/引导注册页
   - 非 AI/Cloud 相关的行业新闻（房地产、汽车非智驾部分、消费等）
   - 内容过于陈旧的话题（系统学习、技术科普等）
4. 每个话题簇的 relevance 字段说明该话题对 AI/Cloud 销售和 GTM 从业者的价值
5. 根据与 AI/Cloud 行业的相关性评分（1-5 分），5 分表示今天最重要的消息
6. 优先选择真正有信息量的新闻，宁缺毋滥

你必须严格输出 JSON 格式，不要包含其他文本。"""


def build_user_message(items: list[NewsItem]) -> str:
    """Build user message with items as JSON."""
    truncated = [
        {
            "title": i.title[:150],
            "source": i.source,
            "url": i.url,
            "snippet": i.body[:200],
        }
        for i in items
    ]
    return f"请对以下 {len(items)} 条新闻进行去重和聚类：\n\n{json.dumps(truncated, ensure_ascii=False, indent=2)}\n\n返回 JSON：{{\"clusters\": [{{\"topic\": \"...\", \"priority\": 1-5, \"items\": [{{\"title\": \"...\", \"url\": \"...\", \"source\": \"...\", \"snippet\": \"...\"}}], \"relevance\": \"...\"}}]}}"


def run_dedup_cluster(
    llm: LLMClient, items: list[NewsItem]
) -> list[dict]:
    """Run LLM dedup + clustering. Returns list of clusters or empty list on failure."""
    if not items:
        logger.warning("No items to cluster")
        return []

    logger.info("LLM Stage 1: dedup+cluster %d items...", len(items))

    try:
        raw = llm.messages_create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(items)}],
        )
    except LLMError as e:
        logger.error("LLM Stage 1 failed: %s", e)
        return _fallback_grouping(items)

    # If first attempt fails, retry once with stricter prompt + original data
    parsed = llm.extract_json(raw)
    if not parsed or "clusters" not in parsed:
        logger.warning(
            "LLM Stage 1 JSON parse failed (raw len=%d), retrying...",
            len(raw),
        )
        logger.debug("Raw first 500: %s", raw[:500])
        try:
            raw2 = llm.messages_create(
                system="你只输出合法的 JSON 对象，不要包含任何其他文字。",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "请严格按照以下 JSON 格式对新闻条目进行去重和聚类，只保留 AI/Cloud 相关条目：\n\n"
                            f"{build_user_message(items)}\n\n"
                            '输出格式: {"clusters": [{"topic": "标题", "priority": 1-5, "items": [{"title": "...", "url": "...", "source": "...", "snippet": "..."}], "relevance": "..."}]}\n'
                            "只输出 JSON，不要任何其他文字。"
                        ),
                    }
                ],
            )
            parsed = llm.extract_json(raw2)
        except Exception:
            parsed = None

    if not parsed or "clusters" not in parsed:
        logger.warning(
            "LLM Stage 1 retry failed too, using fallback grouping"
        )
        return _fallback_grouping(items)

    clusters = parsed["clusters"]
    if not isinstance(clusters, list) or len(clusters) == 0:
        logger.warning("LLM Stage 1 returned empty clusters, using fallback")
        return _fallback_grouping(items)

    logger.info(
        "LLM Stage 1: %d clusters (priorities: %s)",
        len(clusters),
        [c.get("priority", "?") for c in clusters],
    )
    return clusters


def _fallback_grouping(items: list[NewsItem]) -> list[dict]:
    """Simple title-based grouping fallback when LLM fails."""
    from collections import Counter

    # Extract common keywords from titles
    all_words = []
    for item in items:
        words = item.title.replace(":", " ").replace("：", " ").split()
        all_words.extend(w for w in words if len(w) >= 2)

    common = {w for w, _ in Counter(all_words).most_common(5)}

    groups: list[list[NewsItem]] = []
    used = set()
    for i, item in enumerate(items):
        if i in used:
            continue
        group = [item]
        used.add(i)
        words = set(item.title)
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            j_words = set(items[j].title)
            overlap = words & j_words
            if len(overlap) >= 2:
                group.append(items[j])
                used.add(j)
        groups.append(group)

    result = []
    for g in groups:
        result.append(
            {
                "topic": g[0].title[:40],
                "priority": 3,
                "items": [i.to_dict() for i in g],
                "relevance": "启发式分组（LLM 不可用时的降级）",
            }
        )

    logger.info(
        "Fallback grouping: %d clusters from %d items", len(result), len(items)
    )
    return result
