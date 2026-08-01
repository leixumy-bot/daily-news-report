#!/usr/bin/env python3
"""历史多维表格记录分类回填：LLM 批量重分类 + batch_update。

只 update 不 delete，绝不删除任何历史数据。
用法:
    python3 backfill_base.py --dry-run     # 只打印重分类计划，不写 API
    python3 backfill_base.py               # 真实回填
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from output.feishu_base import search_records, batch_update_records
from utils.llm import LLMClient
from processors.categories import normalize_category, normalize_type

logger = logging.getLogger("backfill")

SYSTEM_PROMPT = """你是 AI/Cloud 行业的新闻分类分析师，为历史新闻记录补充分类和类型。

分类从以下 8 个中选一个：
- 能源：电力/供配电/数据中心能耗/核电绿电
- 芯片：GPU/ASIC/TPU/HBM/制程/晶圆/半导体/光芯片
- 基础设施：数据中心/云基础设施/智算中心/网络/存储/集群/AI工厂
- 模型：大模型发布/训练推理/开源模型/基准测试
- 应用：AI应用/产品/Agent/具身智能/机器人/自动驾驶/行业落地
- 政策：政府发文/监管/立法/规划/备案/处罚/标准制定
- 安全：风险事件——数据泄露/黑客攻击/网络攻击/深度伪造/换脸诈骗/AI生成虚假信息/AI歧视偏见/AI自主决策事故
- 其他：融资/产品发布/人事/生态合作等中性行业新闻

类型：研报（高盛/摩根士丹利/瑞银/美银/中金/中信/麦肯锡/Gartner 等机构的研究报告、白皮书、展望）或 新闻。

严格输出 JSON，不要其他文字：{"items": [{"index": 0, "topic": "原样", "category": "8选1", "type": "新闻或研报"}]}"""


def build_user_message(records: list[dict]) -> str:
    items = []
    for idx, r in enumerate(records):
        fields = r.get("fields", {})
        items.append({
            "index": idx,
            "topic": (fields.get("话题标题") or "")[:100],
            "summary": (fields.get("精读摘要") or "")[:200],
        })
    return (
        f"请为以下 {len(items)} 条历史新闻记录判断分类和类型，index 必须原样返回：\n\n"
        f"{json.dumps(items, ensure_ascii=False, indent=2)}\n\n"
        '返回 JSON：{"items": [{"index": 0, "topic": "...", "category": "...", "type": "..."}]}'
    )


def run_backfill(
    llm: LLMClient,
    records: list[dict],
    batch_size: int,
    update_batch_size: int,
    app_token: str,
    table_id: str,
    dry_run: bool,
) -> dict:
    """按批回填。返回 {total, planned, updated, failed}。"""
    total = len(records)
    planned = 0
    updated = 0
    failed = 0

    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        raw = llm.messages_create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(batch)}],
        )
        parsed = llm.extract_json(raw)
        items = parsed.get("items") if parsed and isinstance(parsed.get("items"), list) else []
        by_index = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                idx = int(it.get("index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = it

        updates = []
        for idx, r in enumerate(batch):
            topic = (r.get("fields", {}).get("话题标题") or "").strip()
            it = by_index.get(idx)
            if not it:
                logger.warning("  ⚠️ 未匹配 index %d: %s", idx, topic[:40])
                failed += 1
                continue
            cat = normalize_category(it.get("category", ""))
            typ = normalize_type(it.get("type", ""))
            planned += 1
            if dry_run:
                print(f"  [计划] {topic[:50]} → 分类={cat} / 类型={typ}")
                continue
            updates.append({
                "record_id": r.get("record_id"),
                "fields": {"分类": cat, "类型": typ},
            })

        if updates and not dry_run:
            res = batch_update_records(app_token, table_id, updates, update_batch_size)
            updated += res["success"]
            failed += len(res["failed"])
            time.sleep(0.5)  # 防限流

    return {"total": total, "planned": planned, "updated": updated, "failed": failed}


def main():
    p = argparse.ArgumentParser(description="历史多维表格记录分类回填")
    p.add_argument("--dry-run", action="store_true", help="只打印重分类计划，不写 API")
    p.add_argument("--batch-size", type=int, default=0, help="LLM 每批记录数（默认取 config）")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    bitable = config.get("bitable", {})
    app_token = os.environ.get("LARK_BASE_TOKEN", "")
    table_id = bitable.get("table_id", "")
    if not app_token:
        logger.error("LARK_BASE_TOKEN 环境变量未设置")
        sys.exit(1)

    batch_size = args.batch_size or bitable.get("backfill_batch_size", 20)
    update_batch_size = bitable.get("update_batch_size", 100)

    # 拉全表，筛出未分类的记录
    logger.info("拉取全部记录...")
    records = search_records(app_token, table_id, field_names=["话题标题", "精读摘要", "分类", "类型"])
    pending = [r for r in records if not (r.get("fields", {}).get("分类") or "").strip()]
    logger.info("总记录 %d 条，待回填 %d 条", len(records), len(pending))
    if not pending:
        print("✓ 无需回填")
        return

    llm = LLMClient(config.get("llm", {}))
    res = run_backfill(llm, pending, batch_size, update_batch_size, app_token, table_id, args.dry_run)
    print()
    print("=" * 50)
    print(f"回填汇总: 待回填 {res['total']} 条")
    print(f"  已分类计划: {res['planned']}")
    print(f"  已更新: {res['updated']}")
    print(f"  失败: {res['failed']}")
    print(f"  模式: {'DRY-RUN（未写 API）' if args.dry_run else '已写入'}")
    print("=" * 50)
    if res["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
