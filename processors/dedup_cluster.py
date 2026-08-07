"""Stage 1: Deduplicate and cluster news items using LLM."""

import json
import logging
import re
import unicodedata
from typing import Any

from utils.llm import LLMClient, LLMError
from utils.validate import validate_clusters
from collectors.base import NewsItem

logger = logging.getLogger("dedup-cluster")

# 单次 LLM 聚类处理的条目上限：条目过多时 LLM 生成会超时/失败，需分批
BATCH_SIZE = 30


def normalize_topic_key(topic: str) -> str:
    """Normalize topic text for deterministic cross-batch deduplication."""
    text = unicodedata.normalize("NFKC", topic or "").lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text

SYSTEM_PROMPT = """你是 AI/Cloud 行业的专业新闻分析师。你的任务是对一组中文新闻条目进行去重和聚类。

规则：
1. 内容描述同一事件或话题的条目归为同一个话题簇
2. 优先标注原始来源（一手报道/官方公告），拒绝二手/三手转载
3. **严格过滤**：只保留最核心的 AI/Cloud 相关新闻。以下类别必须舍弃：
   - 招聘/大赛/榜单等推广内容
   - 公司简介/产品介绍页/引导注册页
   - 非 AI/Cloud 相关的行业新闻（房地产、汽车非智驾部分、消费等）
   - 内容过于陈旧的话题（系统学习、技术科普等）
4. 每个话题簇必须标注 category（分类）和 type（类型）：
   - **category** 从以下 8 个中选一个，这是本报告的核心导航维度：
     - 能源：电力/供配电/数据中心能耗/核电绿电
     - 芯片：GPU/ASIC/TPU/HBM/制程/晶圆/半导体/光芯片
     - 基础设施：数据中心/云基础设施/智算中心/网络/存储/集群/AI工厂
     - 模型：大模型发布/训练推理/开源模型/基准测试
     - 应用：AI应用/产品/Agent/具身智能/机器人/自动驾驶/行业落地/商业模式
     - 政策：**凡涉政府发文/监管/立法/规划/备案/处罚/标准制定，一律归政策，不进五层**
     - 安全：**只放风险事件**——数据泄露/黑客攻击/网络攻击/对抗样本/数据出境违规/合规风险，以及 deepfake/换脸诈骗/AI生成虚假信息/AI歧视偏见/AI自主决策事故；监管政策归政策
     - 其他：融资/产品发布/人事/生态合作等归不进上述类别的中性行业新闻
   - **type** 从「新闻」和「研报」中选：来源为高盛/摩根士丹利/瑞银/美银/中金/中信/麦肯锡/Gartner 等机构的研究报告、行业展望、白皮书归为「研报」，其余为「新闻」
5. 每个话题簇的 relevance 字段说明该话题对 AI/Cloud 销售和 GTM 从业者的价值
6. 根据与 AI/Cloud 行业的相关性评分（1-5 分），5 分表示今天最重要的消息
7. 优先选择真正有信息量的新闻，宁缺毋滥

你必须严格输出 JSON 格式，不要包含其他文本。"""


def build_user_message(items: list[NewsItem]) -> str:
    """Build user message with items as JSON."""
    truncated = [
        {
            "title": i.title[:150],
            "source": i.source,
            "url": i.url,
            "snippet": i.body[:80],
        }
        for i in items
    ]
    return f"请对以下 {len(items)} 条新闻进行去重和聚类：\n\n{json.dumps(truncated, ensure_ascii=False, indent=2)}\n\n返回 JSON：{{\"clusters\": [{{\"topic\": \"...\", \"priority\": 1-5, \"category\": \"能源|芯片|基础设施|模型|应用|政策|安全|其他\", \"type\": \"新闻|研报\", \"items\": [{{\"title\": \"...\", \"url\": \"...\", \"source\": \"...\", \"snippet\": \"...\"}}], \"relevance\": \"...\"}}]}}"


def run_dedup_cluster(
    llm: LLMClient, items: list[NewsItem]
) -> list[dict]:
    """Run LLM dedup + clustering. Returns list of clusters or empty list on failure.

    条目较多时分批聚类（每批 BATCH_SIZE 条），合并各批结果后按 topic 去重。
    """
    if not items:
        logger.warning("No items to cluster")
        return []

    logger.info("LLM Stage 1: dedup+cluster %d items...", len(items))
    batches = [items[i : i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    if len(batches) > 1:
        logger.info("  split into %d batches of <=%d", len(batches), BATCH_SIZE)

    all_clusters: list[dict] = []
    for i, batch in enumerate(batches):
        logger.info("  batch %d/%d (%d items)...", i + 1, len(batches), len(batch))
        clusters = _run_batch(llm, batch)
        if clusters:
            all_clusters.extend(clusters)

    # 跨批确定性去重：先按规范化 topic，再按相同首条 URL，保留 priority 高的。
    seen: set[str] = set()
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for c in sorted(all_clusters, key=lambda c: c.get("priority", 0), reverse=True):
        topic = normalize_topic_key(c.get("topic", ""))
        urls = {
            item.get("url", "")
            for item in c.get("items", [])
            if isinstance(item, dict) and item.get("url")
        }
        if topic and topic in seen:
            continue
        if urls and urls & seen_urls:
            continue
        if topic:
            seen.add(topic)
        seen_urls.update(urls)
        deduped.append(c)

    logger.info(
        "LLM Stage 1: %d clusters after %d batches (deduped from %d)",
        len(deduped), len(batches), len(all_clusters),
    )
    return deduped


def _run_batch(llm: LLMClient, items: list[NewsItem]) -> list[dict]:
    """对单批条目执行 LLM 去重聚类（含重试与降级）。"""
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
                            '输出格式: {"clusters": [{"topic": "标题", "priority": 1-5, "category": "能源|芯片|基础设施|模型|应用|政策|安全|其他", "type": "新闻|研报", "items": [{"title": "...", "url": "...", "source": "...", "snippet": "..."}], "relevance": "..."}]}\n'
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

    clusters = validate_clusters(parsed["clusters"])
    if not clusters:
        logger.warning("LLM Stage 1 returned invalid clusters, using fallback")
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
                "category": "其他",
                "type": "新闻",
                "items": [i.to_dict() for i in g],
                "relevance": "启发式分组（LLM 不可用时的降级）",
            }
        )

    logger.info(
        "Fallback grouping: %d clusters from %d items", len(result), len(items)
    )
    return result
