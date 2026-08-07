"""Stage 2: Generate curated summaries for each cluster using LLM."""

import json
import logging
from typing import Any

from utils.llm import LLMClient, LLMError

logger = logging.getLogger("summarize")

SYSTEM_PROMPT = """你是一位 AI/Cloud 行业分析师，为一位从通信行业转型到 AI/Cloud 销售和 GTM 岗位的从业者撰写每日早报精读摘要。

写作要求：
1. 每条摘要 200-300 字中文，语言精炼、有洞察力
2. 对重要话题提供多视角分析（如：技术视角 vs 商业视角 vs 政策/行业视角）
3. 每个摘要末尾用一两句话说明「对 AI/Cloud GTM 的启示」
4. 严格基于提供的原始内容撰写，不要添加未提及的信息
5. 保持客观，避免夸大或主观判断

输出格式：
## {话题标题}

{摘要正文}

**原文链接：** [{来源名}]({原文 URL})
**衍生链接：** [{标题1}]({url1}) · [{标题2}]({url2})
**对 AI/Cloud GTM 的启示：** {启示内容}

约束：衍生链接只能从提供的原始条目 URL 中选取，最多 2 条，禁止编造链接。"""


def summarize_clusters(
    llm: LLMClient, clusters: list[dict]
) -> list[dict]:
    """Generate a summary for each cluster. Returns list of summary dicts.

    Each summary dict: {topic, priority, summary_text, source, url, relevance}
    """
    if not clusters:
        return []

    summaries: list[dict] = []

    for i, cluster in enumerate(clusters):
        try:
            topic = cluster.get("topic", "未命名话题")
            priority = cluster.get("priority", 3)
            relevance = cluster.get("relevance", "")
            history_note = cluster.get("history_note", "")
            items = cluster.get("items", [])

            # Build items text
            lines = []
            for item in items:
                # Handle both dict items and plain strings (from LLM output)
                if isinstance(item, str):
                    title = item
                    source = ""
                    url = ""
                    body = ""
                else:
                    title = item.get("title", "")
                    source = item.get("source", "")
                    url = item.get("url", "")
                    body = item.get("body", "") or item.get("snippet", "")
                lines.append(f"- **{title}**")
                lines.append(f"  来源：{source} | 链接：{url}")
                if body:
                    lines.append(f"  摘要：{body[:200]}")
                lines.append("")

            items_text = "\n".join(lines)

            # Pick primary source for attribution
            primary_source = ""
            primary_url = ""
            if items:
                if isinstance(items[0], str):
                    primary_source = ""
                    primary_url = ""
                else:
                    primary_source = items[0].get("source", "")
                    primary_url = items[0].get("url", "")

            user_msg = f"""请为以下话题撰写精读摘要：

话题：{topic}
相关度评分：{priority}/5
原始条目（请基于这些内容撰写）：
{items_text}

近7天历史对照得到的新增进展（为空表示新主题）：
{history_note or '无'}

如果存在新增进展，请把摘要重点放在新增变化，旧背景只用一句话交代。

请按指定格式输出。"""

            try:
                logger.info(
                    "LLM Stage 2: summarizing cluster %d/%d '%s' (priority %d)",
                    i + 1,
                    len(clusters),
                    topic,
                    priority,
                )
                raw = llm.messages_create(
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
            except LLMError as e:
                logger.error(
                    "LLM Stage 2 failed for cluster '%s': %s", topic, e
                )
                # Fallback: use first item title as summary
                if items:
                    first_title = items[0] if isinstance(items[0], str) else items[0].get("title", "")
                else:
                    first_title = ""
                raw = f"""## {topic}

{first_title}

**原文链接：** [{primary_source}]({primary_url})
**对 AI/Cloud GTM 的启示：** {relevance}"""

            summaries.append(
                {
                    "topic": topic,
                    "priority": priority,
                    "category": cluster.get("category", "其他"),
                    "type": cluster.get("type", "新闻"),
                    "_seq": cluster.get("_seq"),
                    "summary_text": raw,
                    "source": primary_source,
                    "url": primary_url,
                    "relevance": relevance,
                    "history_note": history_note,
                    "history_first_date": cluster.get("history_first_date", ""),
                }
            )
        except Exception as e:
            logger.error("Cluster %d skipped due to error: %s", i, e, exc_info=True)
            continue

    # Sort by priority descending
    summaries.sort(key=lambda s: s.get("priority", 0), reverse=True)
    logger.info(
        "LLM Stage 2: generated %d summaries", len(summaries)
    )
    return summaries
