"""Stage 3: Format summaries and clusters into Feishu messages and KB docs.

七分类导航：消息1=五层蛋糕五层，消息2=政策+安全+其他+研报速览。
超长自动按分类边界切分为多条物理消息。
"""

import re
from typing import Any
from datetime import datetime, timezone, timedelta

from processors.categories import (
    ALL_CATEGORIES,
    CATEGORY_ORDER,
    CATEGORY_TITLES,
    OTHER,
    RESEARCH,
    RESEARCH_TITLE,
)

BJT = timezone(timedelta(hours=8))

FIVE_LAYER = ["能源", "芯片", "基础设施", "模型", "应用"]
POLICY_SECURITY = ["政策", "安全", OTHER]


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


# ── 分组 ──
def _group_by_category(
    summaries: list[dict], clusters: list[dict]
) -> tuple[dict[str, list], dict[str, list]]:
    """按分类分组精读（带 summary）与溢出（未精读）条目。

    返回 (summary_by_cat, overflow_by_cat)，键为 7 类 + 其他 + 研报。
    """
    summary_by_cat: dict[str, list] = {cat: [] for cat in ALL_CATEGORIES}
    summary_by_cat[RESEARCH] = []
    for s in summaries:
        if s.get("type") == RESEARCH:
            summary_by_cat[RESEARCH].append(s)
        else:
            cat = s.get("category") if s.get("category") in ALL_CATEGORIES else OTHER
            summary_by_cat[cat].append(s)

    overflow_by_cat: dict[str, list] = {cat: [] for cat in ALL_CATEGORIES}
    overflow_by_cat[RESEARCH] = []
    for c in clusters:
        if "_seq" in c:  # 已被选中精读，不算溢出
            continue
        if c.get("type") == RESEARCH:
            overflow_by_cat[RESEARCH].append(c)
        else:
            cat = c.get("category") if c.get("category") in ALL_CATEGORIES else OTHER
            overflow_by_cat[cat].append(c)

    return summary_by_cat, overflow_by_cat


def _one_liner(cluster: dict) -> str:
    """溢出项的「一句话」：优先 relevance，其次首条 snippet。"""
    rel = (cluster.get("relevance") or "").strip()
    if rel:
        return rel[:60]
    items = cluster.get("items") or []
    if items and isinstance(items[0], dict):
        return (items[0].get("snippet") or "")[:60]
    return ""


# ── 衍生链接兜底 ──
def _build_derivative_links(summary: dict, cluster: dict) -> str:
    """从簇内条目挑 1-2 条非主链接（防 LLM 幻觉，只接受真实条目 URL）。"""
    primary = summary.get("url") or ""
    items = cluster.get("items") or []
    seen: set[str] = set()
    picked = []
    for i in items:
        if not isinstance(i, dict) or not i.get("url") or i["url"] == primary:
            continue
        u = i["url"]
        if u in seen:
            continue
        seen.add(u)
        picked.append(i)
        if len(picked) >= 2:
            break
    if not picked:
        return ""
    parts = [f"[{(i.get('title') or '相关报道')[:30]}]({i['url']})" for i in picked]
    return "**衍生链接：** " + " · ".join(parts)


def _ensure_derivative_links(summary: dict, cluster: dict) -> dict:
    """summary_text 缺「衍生链接」行时自动补齐，返回新 summary。"""
    text = summary.get("summary_text", "")
    if "衍生链接" in text:
        return summary
    extra = _build_derivative_links(summary, cluster)
    if not extra:
        return summary
    lines = text.split("\n")
    out = []
    inserted = False
    for ln in lines:
        out.append(ln)
        if not inserted and ln.strip().startswith("**原文链接"):
            out.append("")
            out.append(extra)
            inserted = True
    if not inserted:
        out.append("")
        out.append(extra)
    s = dict(summary)
    s["summary_text"] = "\n".join(out)
    return s


# ── 分类渲染 ──
def build_section(
    key: str,
    full_entries: list[dict],
    overflow_entries: list[dict],
) -> str:
    """渲染单个分类 section；空分类输出占位。"""
    title = CATEGORY_TITLES.get(key, key)
    lines = [f"## {title}", ""]
    if not full_entries and not overflow_entries:
        lines.append("_今日暂无该类新闻_")
        return "\n".join(lines)
    for s in full_entries:
        lines.append(s.get("summary_text", ""))
        lines.append("")
        lines.append("---")
        lines.append("")
    for c in overflow_entries:
        lines.append(f"- **{c.get('topic', '')}** — {_one_liner(c)}")
        lines.append("")
    return "\n".join(lines)


def _build_research_section(entries: list[dict], overflow: list[dict]) -> str:
    """研报速览区：有内容才渲染，不占位。"""
    lines = [f"## {RESEARCH_TITLE}", ""]
    for s in entries:
        lines.append(s.get("summary_text", ""))
        lines.append("")
        lines.append("---")
        lines.append("")
    for c in overflow:
        lines.append(f"- **{c.get('topic', '')}** — {_one_liner(c)}")
        lines.append("")
    return "\n".join(lines)


# ── 字节切分器 ──
def _split_section(section: str, max_bytes: int) -> list[str]:
    """把超限 section 按段落边界（---）拆成子段。"""
    parts = re.split(r"\n---\s*\n", section)
    result: list[str] = []
    buf = ""

    def size(s: str) -> int:
        return len(s.encode("utf-8"))

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if buf and size(buf) + size(part) + 6 > max_bytes:
            result.append(buf)
            buf = ""
        if size(part) > max_bytes:
            while part:  # 单段落仍超限：硬切（极罕见）
                result.append(part[:max_bytes])
                part = part[max_bytes:]
        else:
            buf = (buf + "\n---\n" + part) if buf else part
    if buf:
        result.append(buf)
    return result


def _add_chunk_headers(chunks: list[str]) -> list[str]:
    """给后续物理段加序号头，保证每段以 # 标题开头（供 post 提取标题）。"""
    n = len(chunks)
    if n <= 1:
        return chunks
    out = []
    for i, c in enumerate(chunks):
        if i == 0:
            out.append(c)
        else:
            out.append(f"_（第 {i + 1}/{n} 段）_\n\n# 📖 续读\n\n{c}")
    return out


def split_markdown_by_bytes(sections: list[str], max_bytes: int) -> list[str]:
    """按字节切分 markdown section 列表（每 section 为原子单元）。

    单个 section 超限时在内部按段落递归切分。返回物理消息列表。
    """
    if max_bytes <= 0 or not sections:
        return sections

    chunks: list[str] = []
    current = ""

    def size(s: str) -> int:
        return len(s.encode("utf-8"))

    def emit_and_reset():
        nonlocal current
        if current.strip():
            chunks.append(current)
            current = ""

    for section in sections:
        ssize = size(section)
        if current and size(current) + ssize + 1 > max_bytes:
            emit_and_reset()
        if ssize <= max_bytes:
            current = (current + "\n" + section).strip() if current else section
        else:
            for sub in _split_section(section, max_bytes):
                if current and size(current) + size(sub) + 1 > max_bytes:
                    emit_and_reset()
                current = (current + "\n" + sub).strip() if current else sub
    emit_and_reset()
    return _add_chunk_headers(chunks)


# ── 消息组装 ──
def build_messages(
    summaries: list[dict],
    clusters: list[dict],
    max_bytes: int = 28000,
    user_name: str = "徐磊",
    user_open_id: str = "",
) -> dict[str, list[str]]:
    """组装两条逻辑消息：消息1=五层，消息2=政策+安全+其他+研报。

    返回 {"five_layer": [chunk...], "policy_security": [chunk...]}。
    """
    # 衍生链接兜底（需簇内真实条目）
    cluster_by_seq = {c.get("_seq"): c for c in clusters if c.get("_seq") is not None}
    summaries = [
        _ensure_derivative_links(s, cluster_by_seq.get(s.get("_seq"), {}))
        for s in summaries
    ]
    summary_by_cat, overflow_by_cat = _group_by_category(summaries, clusters)

    # 消息1：五层（空类占位）
    msg1_lines = []
    if user_open_id:
        msg1_lines.append(f'<at user_id="{user_open_id}">{user_name}</at>')
        msg1_lines.append("")
    msg1_lines.append(f"# 🤖 AI+Cloud 每日早报 · {today_bjt_cn()}")
    msg1_lines.append("")
    msg1_header = "\n".join(msg1_lines)
    five_sections = [
        build_section(cat, summary_by_cat[cat], overflow_by_cat[cat])
        for cat in FIVE_LAYER
    ]
    five_chunks = split_markdown_by_bytes([msg1_header] + five_sections, max_bytes)

    # 消息2：政策+安全+其他+研报（研报空则整块隐藏）
    msg2_header = f"# 📋 政策与安全板块 · {today_bjt_cn()}\n\n"
    policy_sections = [
        build_section(cat, summary_by_cat[cat], overflow_by_cat[cat])
        for cat in POLICY_SECURITY
    ]
    if summary_by_cat[RESEARCH] or overflow_by_cat[RESEARCH]:
        policy_sections.append(
            _build_research_section(summary_by_cat[RESEARCH], overflow_by_cat[RESEARCH])
        )
    policy_chunks = split_markdown_by_bytes([msg2_header] + policy_sections, max_bytes)

    return {"five_layer": five_chunks, "policy_security": policy_chunks}


def build_kb_document(
    summaries: list[dict],
    clusters: list[dict],
    date_str: str,
    max_bytes: int = 0,
) -> str:
    """按七分类组织知识库整篇存档，链接随每条精读归档。"""
    cluster_by_seq = {c.get("_seq"): c for c in clusters if c.get("_seq") is not None}
    summaries = [
        _ensure_derivative_links(s, cluster_by_seq.get(s.get("_seq"), {}))
        for s in summaries
    ]
    summary_by_cat, overflow_by_cat = _group_by_category(summaries, clusters)

    lines = [f"# AI+Cloud 每日早报 · {date_str}", ""]
    lines.append("---")
    lines.append("")
    for cat in FIVE_LAYER + POLICY_SECURITY:
        lines.append(build_section(cat, summary_by_cat[cat], overflow_by_cat[cat]))
        lines.append("")
        lines.append("---")
        lines.append("")
    if summary_by_cat[RESEARCH] or overflow_by_cat[RESEARCH]:
        lines.append(_build_research_section(summary_by_cat[RESEARCH], overflow_by_cat[RESEARCH]))
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append(f"_由 AI+Cloud News Digest 自动生成 · {date_str}_")
    return "\n".join(lines)


def build_summary_for_message(summaries: list[dict]) -> str:
    """Build a short summary for the beginning."""
    topics = [s["topic"] for s in summaries[:5]]
    parts = "、".join(topics)
    if len(summaries) > 5:
        parts += f" 等共 {len(summaries)} 个话题"
    return f"今日精读：{parts}"
