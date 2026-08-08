"""测试 processors/format.py 消息组装与切分。"""

from processors.categories import RESEARCH
from processors.format import (
    build_kb_document,
    build_messages,
    build_section,
    split_markdown_by_bytes,
)


def _size(s: str) -> int:
    return len(s.encode("utf-8"))


def _fixture():
    clusters = []
    summaries = []
    seq = 0
    for cat in ["能源", "芯片", "基础设施", "模型", "应用", "政策", "其他"]:
        clusters.append(
            {"topic": f"{cat}新闻A", "priority": 4, "category": cat, "type": "新闻", "relevance": "对GTM有价值"}
        )
        summaries.append(
            {
                "topic": f"{cat}新闻A", "priority": 4, "category": cat, "type": "新闻", "_seq": seq,
                "url": f"https://{cat}.com/a",
                "summary_text": f"## {cat}新闻A\n\n正文。\n\n**原文链接：** [来源](https://{cat}.com/a)\n**对 AI/Cloud GTM 的启示：** 关注",
            }
        )
        seq += 1
        clusters.append(
            {"topic": f"{cat}溢出B", "priority": 3, "category": cat, "type": "新闻", "relevance": "次要"}
        )
    clusters.append({"topic": "高盛AI研报", "priority": 5, "category": "模型", "type": RESEARCH, "relevance": "研报"})
    summaries.append(
        {
            "topic": "高盛AI研报", "priority": 5, "category": "模型", "type": RESEARCH, "_seq": seq,
            "url": "https://goldmansachs.com/r",
            "summary_text": "## 高盛AI研报\n\n观点。\n\n**原文链接：** [高盛](https://goldmansachs.com/r)\n**对 AI/Cloud GTM 的启示：** 资本开支",
        }
    )
    return summaries, clusters


def test_build_section_empty_placeholder():
    section = build_section("安全", [], [])
    assert "## 🛡️ 安全" in section
    assert "今日暂无该类新闻" in section


def test_build_messages_structure():
    summaries, clusters = _fixture()
    msgs = build_messages(summaries, clusters, max_bytes=100000)
    f5 = "".join(msgs["five_layer"])
    ps = "".join(msgs["policy_security"])
    assert "## ⚡ 能源" in f5 and "## 🎯 应用" in f5
    assert "## 🛡️ 安全" in ps and "## 📰 其他行业新闻" in ps
    assert "## 📊 研报速览" in ps
    assert "## ⚡ 能源" not in ps  # 五层只在消息1


def test_build_messages_research_hidden_when_empty():
    summaries, clusters = _fixture()
    summaries = [s for s in summaries if s.get("type") != RESEARCH]
    clusters = [c for c in clusters if c.get("type") != RESEARCH]
    msgs = build_messages(summaries, clusters, max_bytes=100000)
    assert "研报速览" not in "".join(msgs["policy_security"])


def test_split_markdown_by_bytes_multiple_chunks():
    big = "**" + "x" * 500 + "**"
    chunks = split_markdown_by_bytes([f"## A\n\n{big}\n\n## B\n\n{big}"], 200)
    assert len(chunks) >= 2
    for c in chunks:
        assert _size(c) <= 300


def test_split_markdown_by_bytes_empty():
    assert split_markdown_by_bytes([], 200) == []
    assert split_markdown_by_bytes(["x"], 0) == ["x"]


def test_split_markdown_by_bytes_respects_utf8_limit_and_preserves_content():
    source = "中" * 1000
    chunks = split_markdown_by_bytes([source], 100)
    assert all(_size(chunk) <= 100 for chunk in chunks)
    body = "".join(
        chunk.replace("_（第 ", "\n_（第 ").split("# 📖 续读\n\n", 1)[-1]
        for chunk in chunks
    )
    assert body == source


def test_build_messages_uses_report_date():
    msgs = build_messages([], [], max_bytes=100000, date_str="2026-01-02")
    assert "2026年01月02日" in msgs["five_layer"][0]


def test_build_kb_document():
    summaries, clusters = _fixture()
    kb = build_kb_document(summaries, clusters, "2026-07-31")
    assert "## ⚡ 能源" in kb
    assert "## 📊 研报速览" in kb
    assert "## 🛡️ 安全" in kb
