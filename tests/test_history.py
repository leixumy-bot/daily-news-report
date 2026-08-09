from utils.history import (
    build_semantic_pairs,
    content_fingerprint,
    deterministic_status,
    fingerprint,
    normalize_text,
)
from output.feishu_base import _date_timestamp_bjt, _field_date_bjt


def test_normalize_and_fingerprint_are_stable():
    assert normalize_text("OpenAI GPT-5.6！ https://example.com") == "openaigpt56"
    assert fingerprint("A", "B") == fingerprint("a", "b")


def test_deterministic_duplicate_by_url():
    cluster = {
        "topic": "新模型发布",
        "items": [{"title": "发布", "url": "https://example.com/news"}],
    }
    history = [{"话题标题": "另一种标题", "来源链接": "https://example.com/news"}]
    assert deterministic_status(cluster, history) == "duplicate"


def test_topic_fingerprint_is_not_alone_a_duplicate():
    cluster = {
        "topic": "同一事件",
        "items": [{"title": "标题", "url": "https://example.com/a"}],
    }
    history = [{"话题标题": "同一事件", "主题指纹": fingerprint("同一事件")}]
    assert deterministic_status(cluster, history) is None


def test_semantic_candidate_is_created_for_similar_topics():
    clusters = [{"topic": "OpenAI 发布新模型", "items": []}]
    history = [{"话题标题": "OpenAI 新模型发布", "date_str": "2026-08-05"}]
    pairs = build_semantic_pairs(clusters, history, threshold=0.1)
    assert pairs and pairs[0]["current_index"] == 0


def test_date_timestamp_bjt_is_int_and_roundtrips():
    """Base 日期字段必须是时间戳（字符串会被拒），且能 roundtrip 回同一天。"""
    ts = _date_timestamp_bjt("2026-08-09")
    assert isinstance(ts, int)
    assert _field_date_bjt(ts) == "2026-08-09"
