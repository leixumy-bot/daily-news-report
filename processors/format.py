"""Stage 3: Format summaries and appendix into Feishu messages and KB docs."""

from typing import Any
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))


def _get(item, key: str, default="") -> str:
    """Safely get attribute from dict or dataclass/object."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def today_bjt() -> str:
    return datetime.now(BJT).strftime("%Y-%m-%d")


def today_bjt_cn() -> str:
    """Chinese date format."""
    return datetime.now(BJT).strftime("%Y年%m月%d日")


def build_group_message(
    summaries: list[dict],
    all_items: list,
    appendix_url: str = "",
    user_name: str = "徐磊",
    user_open_id: str = "",
    max_curated: int = 10,
) -> str:
    """Build Feishu markdown for group chat message.

    Capped at max_curated summaries in the curated section;
    lower-priority topics go to a 'other notable' list.
    """
    lines = []

    # @mention user
    if user_open_id:
        lines.append(f'<at user_id="{user_open_id}">{user_name}</at>')
    lines.append("")

    # Title
    lines.append(f"# 🤖 AI+Cloud 每日早报 · {today_bjt_cn()}")
    lines.append("")

    # Separate into curated (top N by priority) and rest
    curated = summaries[:max_curated]
    rest = summaries[max_curated:]

    # 🔥 今日头条 (priority >= 4, max 3)
    highlights = [s for s in curated if s.get("priority", 0) >= 4]
    if highlights:
        lines.append("## 🔥 今日头条")
        lines.append("")
        for s in highlights[:3]:
            lines.append(f"**{s['topic']}**")
            lines.append("")
            # Extract a concise insight from the summary
            text = s.get("summary_text", "")
            # Find the GTM启示 line if it exists
            insight = ""
            for line in text.split("\n"):
                if "GTM" in line or "启示" in line:
                    insight = line.strip()
                    break
            if not insight:
                # Use first meaningful line after heading
                parts = text.split("\n\n")
                for p in parts[1:]:
                    stripped = p.strip().strip("-").strip()
                    if len(stripped) > 20 and stripped[0].isalpha():
                        insight = stripped[:150]
                        break
            if insight:
                lines.append(insight)
            lines.append(f"> 来源：{s.get('source', '')} | 相关度：{'⭐' * s.get('priority', 3)}")
            lines.append("")

    # 📖 精读版 (top N curated)
    lines.append("---")
    lines.append(f"## 📖 精读版（共 {len(curated)} 篇）")
    lines.append("")
    for s in curated:
        lines.append(s.get("summary_text", ""))
        lines.append("")
        lines.append("---")
        lines.append("")

    # Remaining topics as list
    if rest:
        lines.append("## 📌 其他值得关注")
        lines.append("")
        for s in rest:
            lines.append(f"- **{s['topic']}** — 来源：{s.get('source', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer with appendix link
    lines.append("## 📋 附录")
    lines.append("")
    lines.append(f"当日共采集 **{len(all_items)}** 条来源")
    if appendix_url:
        lines.append(f"📄 **[查看完整日报（含全部原文链接）]({appendix_url})**")
    lines.append("")
    lines.append("---")
    lines.append(f"_由 AI+Cloud News Digest 自动生成 · {today_bjt_cn()} · 仅供行业参考_")

    return "\n".join(lines)


def build_kb_document(
    summaries: list[dict],
    all_items: list,
    date_str: str,
) -> str:
    """Build full markdown for knowledge base document."""
    lines = []

    lines.append(f"# AI+Cloud 每日早报 · {date_str}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 📖 精读摘要
    lines.append("## 📖 精读摘要")
    lines.append("")
    for s in summaries:
        lines.append(s.get("summary_text", ""))
        lines.append("")
        lines.append("---")
        lines.append("")

    # 📋 附录：全部原文列表
    lines.append("## 📋 附录：全部原文列表")
    lines.append("")
    lines.append(f"共 {len(all_items)} 条来源")
    lines.append("")

    # Group by source
    by_source: dict[str, list] = {}
    for item in all_items:
        src = _get(item, "source", "unknown")
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(item)

    for source_name in sorted(by_source.keys()):
        lines.append(f"### {source_name}")
        lines.append("")
        for item in by_source[source_name]:
            title = _get(item, "title", "")
            url = _get(item, "url", "")
            body = _get(item, "body", "")
            if url:
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")
            if body:
                lines.append(f"  - {body[:150]}")
        lines.append("")

    lines.append("---")
    lines.append(f"_由 AI+Cloud News Digest 自动生成 · {date_str}_")

    return "\n".join(lines)


def build_summary_for_message(summaries: list[dict]) -> str:
    """Build a short summary for the beginning."""
    topics = [s["topic"] for s in summaries[:5]]
    parts = "、".join(topics)
    if len(summaries) > 5:
        parts += f" 等共 {len(summaries)} 个话题"
    return f"今日精读：{parts}"
