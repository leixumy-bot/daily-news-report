"""测试跨批语义合并与摘要指纹生成。"""

import json

from utils.llm import LLMClient
from processors.dedup_cluster import _semantic_merge_clusters
from processors.summarize import summarize_clusters


class _FakeLLM:
    """返回预设 raw 文本的假 LLM。"""

    def __init__(self, raw: str):
        self.raw = raw

    def messages_create(self, system, messages):
        return self.raw

    def extract_json(self, text: str):
        # 复用真实 LLMClient.extract_json 的解析逻辑（含 markdown fence 剥离）
        return LLMClient.extract_json(self, text)


class _BoomLLM:
    """LLM 调用抛异常，用于验证安全降级。"""

    def messages_create(self, system, messages):
        raise RuntimeError("boom")

    def extract_json(self, text):
        return None


def _cluster(topic, priority, items):
    return {"topic": topic, "priority": priority, "category": "模型",
            "type": "新闻", "items": items}


def test_semantic_merge_combines_duplicate_clusters():
    """同一事件、标题措辞不同 → LLM 判 duplicate → 合并 items、删除被合并簇。"""
    llm = _FakeLLM(json.dumps({"merges": [{"keep_index": 0, "drop_index": 1, "merge": True}]}))
    clusters = [
        _cluster("OpenAI 发布新模型 GPT-5", 5, [{"title": "A", "url": "https://a.com/1"}]),
        _cluster("OpenAI 推出 GPT-5 新模型", 3, [{"title": "B", "url": "https://b.com/2"}]),
    ]
    out = _semantic_merge_clusters(llm, clusters)
    assert len(out) == 1
    assert len(out[0]["items"]) == 2
    assert out[0]["topic"] == "OpenAI 发布新模型 GPT-5"  # 保留高优先级簇


def test_semantic_merge_keeps_distinct_clusters():
    """不同事件（LLM 判 merge=false）→ 全部保留。"""
    llm = _FakeLLM(json.dumps({"merges": [{"keep_index": 0, "drop_index": 1, "merge": False}]}))
    clusters = [
        _cluster("OpenAI 发布新模型", 5, [{"title": "A", "url": "https://a.com/1"}]),
        _cluster("英伟达发布新芯片", 4, [{"title": "B", "url": "https://b.com/2"}]),
    ]
    out = _semantic_merge_clusters(llm, clusters)
    assert len(out) == 2


def test_semantic_merge_safe_on_llm_failure():
    """LLM 异常 → 不合并，原样返回（安全降级）。"""
    clusters = [
        _cluster("OpenAI 发布新模型 GPT-5", 5, [{"title": "A", "url": "https://a.com/1"}]),
        _cluster("OpenAI 推出 GPT-5 新模型", 3, [{"title": "B", "url": "https://b.com/2"}]),
    ]
    out = _semantic_merge_clusters(_BoomLLM(), clusters)
    assert len(out) == 2


def test_semantic_merge_no_pairs_keeps_all():
    """无相似候选对 → 原样返回，不调 LLM。"""
    clusters = [
        _cluster("OpenAI 发布新模型", 5, [{"title": "A", "url": "https://a.com/1"}]),
        _cluster("英伟达发布新芯片", 4, [{"title": "B", "url": "https://b.com/2"}]),
    ]
    # 不相干主题不应产生相似对（即便 LLM 会误判，也不该被调用）
    out = _semantic_merge_clusters(_BoomLLM(), clusters)
    assert len(out) == 2


def test_summary_includes_fingerprints():
    """每条摘要都生成内容指纹/主题指纹，供 Base 写入后跨天去重比对。"""
    cluster = _cluster(
        "OpenAI 发布新模型",
        5,
        [{"title": "OpenAI GPT-5 发布", "url": "https://a.com/1", "source": "RSS", "snippet": "..."}],
    )
    raw = "## OpenAI 发布新模型\n\n摘要正文"
    out = summarize_clusters(_FakeLLM(raw), [cluster])
    assert out[0]["content_fingerprint"]
    assert out[0]["topic_fingerprint"]
