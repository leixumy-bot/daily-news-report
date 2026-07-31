"""七分类体系：黄仁勋五层蛋糕（能源/芯片/基础设施/模型/应用）+ 政策 + 安全 + 其他。

分类做导航维度，归不进去的行业新闻进「其他」；研报（投行/咨询机构报告）单独成区。
"""

CATEGORY_ORDER = ["能源", "芯片", "基础设施", "模型", "应用", "政策", "安全"]
OTHER = "其他"
ALL_CATEGORIES = CATEGORY_ORDER + [OTHER]

CATEGORY_TITLES = {
    "能源": "⚡ 能源",
    "芯片": "🔩 芯片",
    "基础设施": "🏗️ 基础设施",
    "模型": "🧠 模型",
    "应用": "🎯 应用",
    "政策": "📜 政策",
    "安全": "🛡️ 安全",
    "其他": "📰 其他行业新闻",
}

RESEARCH = "研报"
NEWS = "新闻"
RESEARCH_TITLE = "📊 研报速览"

MAX_PER_CATEGORY = 3
RESEARCH_MAX = 3
DEFAULT_SUMMARIZE_CAP = 24

# LLM 输出的自由分类文本 → 规范分类的别名映射（子串匹配）
_CATEGORY_ALIASES = {
    "能源": ["电力", "能耗", "供电", "核电", "绿电", "发电", "电网", "能源"],
    "芯片": ["GPU", "ASIC", "TPU", "HBM", "半导体", "制程", "晶圆", "光芯片", "芯片"],
    "基础设施": ["数据中心", "智算中心", "算力中心", "AI工厂", "云基础设施", "东数西算", "集群", "基础设施"],
    "模型": ["大模型", "LLM", "开源模型", "推理模型", "多模态模型", "训练", "微调", "基准", "模型"],
    "应用": ["Agent", "智能体", "具身智能", "机器人", "自动驾驶", "行业落地", "商业化", "应用"],
    "政策": ["监管", "备案", "审查", "法规", "条例", "办法", "立法", "规划", "发文", "出口管制", "数据要素", "数据出境", "政策", "治理"],
    "安全": ["泄露", "黑客", "漏洞", "网络攻击", "对抗样本", "deepfake", "深度伪造", "换脸", "诈骗", "虚假信息", "歧视", "偏见", "逃逸", "勒索", "事故", "安全"],
}

# 研报识别提示词（子串匹配）
_RESEARCH_HINTS = [
    "研报", "白皮书", "展望", "行业报告", "研究报告",
    "gartner", "麦肯锡", "高盛", "摩根士丹利", "瑞银", "中金", "中信", "美银",
]


def normalize_category(raw: str) -> str:
    """把 LLM 输出的分类自由文本归一到 8 个规范值，识别不了归「其他」。"""
    text = (raw or "").strip().lower()
    if not text:
        return OTHER
    for cat in ALL_CATEGORIES:
        if text == cat or text.startswith(cat) or cat.startswith(text):
            return cat
    for cat, words in _CATEGORY_ALIASES.items():
        for w in words:
            if w.lower() in text:
                return cat
    return OTHER


def normalize_type(raw: str) -> str:
    """判断条目是研报还是新闻。"""
    text = (raw or "").strip().lower()
    if not text:
        return NEWS
    if any(hint.lower() in text for hint in _RESEARCH_HINTS):
        return RESEARCH
    return NEWS


def select_for_summarize(
    clusters: list[dict], cap: int = DEFAULT_SUMMARIZE_CAP
) -> list[dict]:
    """按分类分组选择要精读的簇，给选中的簇打 _seq 索引。

    规则：每类最多 MAX_PER_CATEGORY 条（按 priority 降序），研报最多 RESEARCH_MAX 条，
    全局不超过 cap。未选中的簇不带 _seq，供 format 降级为「标题+一句话」。
    """
    for c in clusters:
        c.setdefault("category", normalize_category(c.get("category", "")))
        c.setdefault("type", normalize_type(c.get("type", "")))

    sorted_clusters = sorted(
        clusters, key=lambda c: c.get("priority", 0), reverse=True
    )

    news_by_cat: dict[str, list] = {cat: [] for cat in ALL_CATEGORIES}
    research: list[dict] = []
    for c in sorted_clusters:
        if c.get("type") == RESEARCH:
            research.append(c)
        else:
            cat = c["category"] if c["category"] in ALL_CATEGORIES else OTHER
            news_by_cat[cat].append(c)

    selected: list[dict] = []
    for cat in ALL_CATEGORIES:
        selected.extend(news_by_cat[cat][:MAX_PER_CATEGORY])
    selected.extend(research[:RESEARCH_MAX])

    if len(selected) > cap:
        selected = selected[:cap]

    for i, c in enumerate(selected):
        c["_seq"] = i
    return selected
