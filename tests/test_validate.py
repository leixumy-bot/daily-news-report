"""测试 utils/validate.py：LLM 输出结构校验与清洗。"""

from utils.validate import validate_clusters
from utils.llm import LLMClient
from processors.dedup_cluster import _run_batch, _fallback_grouping
from collectors.base import NewsItem


class _FakeLLM:
    """返回预设 raw 文本的假 LLM，供 _run_batch 测试。"""

    def __init__(self, raw: str):
        self.raw = raw

    def messages_create(self, system, messages):
        return self.raw

    def extract_json(self, text: str):
        # 复用真实 LLMClient.extract_json 的解析逻辑（含 markdown fence 剥离）
        return LLMClient.extract_json(self, text)


def test_run_batch_invalid_structure_uses_fallback():
    """JSON 能解析但结构全坏（缺字段/非 dict 项）→ 走 fallback 而非空结果。"""
    items = [NewsItem(source="rss", title="英伟达发布新芯片", url="https://x.com", body="正文")]
    # 解析出的 clusters 是坏结构：字符串项、priority 非法、topic 空、无 items
    raw = '{"clusters": [{"topic": "", "priority": "高", "items": ["纯字符串"]}, "不是dict"]}'
    llm = _FakeLLM(raw)
    out = _run_batch(llm, items)
    # fallback 分组至少保留原始条目
    assert out and out[0]["items"][0]["title"] == "英伟达发布新芯片"


def test_run_batch_valid_structure_preserved():
    """清洗后结构正确的簇原样保留（priority/category 归一）。"""
    items = [NewsItem(source="rss", title="标题", url="", body="")]
    raw = '{"clusters": [{"topic": "英伟达新芯片", "priority": "9", "category": "芯片", "type": "新闻", "items": [{"title": "英伟达新芯片", "url": "https://x.com"}]}]}'
    llm = _FakeLLM(raw)
    out = _run_batch(llm, items)
    assert out[0]["topic"] == "英伟达新芯片"
    assert out[0]["priority"] == 5  # "9" clamp 到 5
    assert out[0]["category"] == "芯片"


def test_string_priority_clamped_to_range():
    """字符串优先级转 int 并 clamp 到 [1,5]。"""
    out = validate_clusters([{"topic": "A", "priority": "9", "items": []}])
    assert out[0]["priority"] == 5

    out = validate_clusters([{"topic": "A", "priority": "0", "items": []}])
    assert out[0]["priority"] == 1


def test_invalid_priority_defaults_to_3():
    """非法优先级（非数字）回退到默认 3。"""
    out = validate_clusters([{"topic": "A", "priority": "高", "items": []}])
    assert out[0]["priority"] == 3

    out = validate_clusters([{"topic": "A", "priority": True, "items": []}])
    assert out[0]["priority"] == 3


def test_missing_topic_falls_back_to_first_item_title():
    """缺 topic 用首条 item 的 title 兜底。"""
    out = validate_clusters([{"topic": "", "priority": 5, "items": [{"title": "英伟达新芯片"}]}])
    assert out[0]["topic"] == "英伟达新芯片"


def test_empty_topic_and_no_items_dropped():
    """缺 topic 且无 items → 丢弃该簇。"""
    out = validate_clusters([{"topic": "", "priority": 5, "items": []}])
    assert out == []


def test_invalid_category_falls_to_other():
    """非法 category 归"其他"。"""
    out = validate_clusters([{"topic": "A", "priority": 3, "category": "无头新闻", "items": []}])
    assert out[0]["category"] == "其他"


def test_valid_category_preserved():
    """合法 category/type 保留。"""
    out = validate_clusters([{"topic": "A", "priority": 4, "category": "芯片", "type": "研报", "items": []}])
    assert out[0]["category"] == "芯片"
    assert out[0]["type"] == "研报"


def test_string_items_filtered():
    """items 里的字符串/无 title 项被过滤，只留 dict 且含 title 的。"""
    out = validate_clusters([
        {"topic": "A", "priority": 3, "items": [
            "纯字符串",
            {"title": "有效标题", "url": "https://x.com"},
            {"url": "https://no-title.com"},
        ]}
    ])
    assert len(out[0]["items"]) == 1
    assert out[0]["items"][0]["title"] == "有效标题"


def test_non_list_input_returns_empty():
    """非列表输入返回空列表（调用方据此走 fallback）。"""
    assert validate_clusters(None) == []
    assert validate_clusters("not a list") == []
    assert validate_clusters({}) == []


def test_relevance_truncated():
    """relevance 截断到 300 字符。"""
    out = validate_clusters([{"topic": "A", "priority": 3, "relevance": "x" * 500, "items": []}])
    assert len(out[0]["relevance"]) == 300
