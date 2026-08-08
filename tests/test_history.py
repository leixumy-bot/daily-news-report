from utils.history import (
    build_semantic_pairs,
    content_fingerprint,
    deterministic_status,
    fingerprint,
    normalize_text,
)


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


def test_deterministic_duplicate_accepts_structured_url_field():
    cluster = {
        "topic": "新模型发布",
        "items": [{"title": "发布", "url": "https://example.com/news"}],
    }
    history = [{"话题标题": "另一种标题", "来源链接": {"link": "https://example.com/news"}}]
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
