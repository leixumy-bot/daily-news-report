"""测试 processors/categories.py 分类体系。"""

from collections import Counter

from processors.categories import (
    ALL_CATEGORIES,
    RESEARCH,
    NEWS,
    normalize_category,
    normalize_type,
    select_for_summarize,
)


def test_normalize_category_basic():
    assert normalize_category("政策") == "政策"
    assert normalize_category("政策监管") == "政策"
    assert normalize_category("芯片") == "芯片"
    assert normalize_category("GPU") == "芯片"
    assert normalize_category("基础设施") == "基础设施"
    assert normalize_category("AI基础设施") == "基础设施"
    assert normalize_category("模型层") == "模型"
    assert normalize_category("应用") == "应用"
    assert normalize_category("能源") == "能源"
    assert normalize_category("安全事件") == "安全"


def test_normalize_category_unknown_falls_to_other():
    assert normalize_category("") == "其他"
    assert normalize_category(None) == "其他"
    assert normalize_category("无关话题") == "其他"


def test_normalize_type():
    assert normalize_type("研报") == RESEARCH
    assert normalize_type("高盛报告") == RESEARCH
    assert normalize_type("麦肯锡白皮书") == RESEARCH
    assert normalize_type("新闻") == NEWS
    assert normalize_type("") == NEWS


def test_select_for_summarize_caps_per_category():
    clusters = []
    for cat in ALL_CATEGORIES:
        for i in range(5):
            clusters.append(
                {"topic": f"{cat}-{i}", "priority": 5 - i, "category": cat, "type": "新闻"}
            )
    for i in range(4):
        clusters.append(
            {"topic": f"研报-{i}", "priority": 5, "category": "模型", "type": RESEARCH}
        )
    sel = select_for_summarize(clusters, cap=24)
    cnt = Counter(c["category"] for c in sel)
    assert len(sel) <= 24
    for cat in ALL_CATEGORIES:
        assert cnt[cat] <= 3
    assert sum(1 for c in sel if c["type"] == RESEARCH) <= 3
    assert all("_seq" in c for c in sel)


def test_select_for_summarize_overflow_unmarked():
    clusters = [
        {"topic": "A", "priority": 5, "category": "模型", "type": "新闻"},
        {"topic": "B", "priority": 4, "category": "模型", "type": "新闻"},
        {"topic": "C", "priority": 3, "category": "模型", "type": "新闻"},
        {"topic": "D", "priority": 2, "category": "模型", "type": "新闻"},
    ]
    sel = select_for_summarize(clusters)
    assert len(sel) == 3
    selected_topics = {c["topic"] for c in sel}
    assert "A" in selected_topics and "B" in selected_topics and "C" in selected_topics
    d = [c for c in clusters if c["topic"] == "D"][0]
    assert "_seq" not in d  # 溢出项不打 _seq
