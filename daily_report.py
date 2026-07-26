#!/usr/bin/env python3
"""AI+Cloud 每日早报 — 主入口

采集→过滤→LLM去重聚类→LLM精读摘要→格式化→飞书推送

用法:
    python3 daily_report.py                    # 完整流程
    python3 daily_report.py --dry-run           # 采集+处理，不发飞书
    python3 daily_report.py --collect-only      # 只采集，不处理
    python3 daily_report.py --date 2026-07-24   # 补跑指定日期
    python3 daily_report.py --force             # 强制重跑今天
"""

import argparse
import json
import os
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# ── Config ──
def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Time ──
BJT = timezone(timedelta(hours=8))

def now_bjt() -> datetime:
    return datetime.now(BJT)

def date_bjt() -> str:
    return now_bjt().strftime("%Y-%m-%d")


# ── Mode detection ──
def is_ci() -> bool:
    """Detect if running in CI (GitHub Actions)."""
    return os.environ.get("CI") == "true"


# ── Logging ──
def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Keyword Filter ──
def keyword_filter(items: list, keywords: list[str]) -> list:
    """Keep items where title or body contains at least one keyword."""
    if not keywords:
        return items

    def matches(item) -> bool:
        text = (getattr(item, "title", "") + " " + getattr(item, "body", "")).lower()
        return any(kw.lower() in text for kw in keywords)

    filtered = [it for it in items if matches(it)]
    dropped = len(items) - len(filtered)
    if dropped:
        logging.getLogger("main").info(
            "Keyword filter: %d dropped, %d kept", dropped, len(filtered)
        )
    return filtered


# ── Parsing ──
def parse_args():
    p = argparse.ArgumentParser(
        description="AI+Cloud 每日早报 — 采集 → 处理 → 飞书推送"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and process only, skip Feishu output",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Force run even if already ran today",
    )
    p.add_argument(
        "--date",
        type=str,
        default="",
        help="Report date (YYYY-MM-DD). Defaults to today BJT",
    )
    p.add_argument(
        "--collect-only",
        action="store_true",
        help="Only run collectors, skip LLM processing and output",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging (debug level)",
    )
    return p.parse_args()


# ════════════════════════════════════════
# Main
# ════════════════════════════════════════
def main():
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("main")

    # ── Load config ──
    config_path = HERE / "config.json"
    if not config_path.exists():
        logger.error("config.json not found at %s", config_path)
        sys.exit(1)
    config = load_config(config_path)

    report_date = args.date or date_bjt()
    report_title = f"AI+Cloud早报_{report_date.replace('-', '')}"

    logger.info("=" * 50)
    logger.info("AI+Cloud 每日早报 — %s", report_date)
    logger.info("args: dry_run=%s, force=%s, collect_only=%s",
                args.dry_run, args.force, args.collect_only)
    logger.info("=" * 50)

    # ── 1. COLLECT ──
    logger.info("[1/5] 开始采集...")
    from collectors.rss import RSSCollector
    from collectors.web_search import WebSearchCollector
    from collectors.podcast_search import PodcastCollector
    from collectors.xhs_collector import XiaohongshuCollector
    from collectors.wechat_collector import WechatCollector

    src_cfg = config.get("sources", {})

    collectors = []

    # RSS
    for rss_cfg in src_cfg.get("rss", []):
        collectors.append(
            RSSCollector(rss_cfg["name"], rss_cfg["url"], rss_cfg.get("max_items", 20))
        )

    # Web search
    ws_cfg = src_cfg.get("web_search", {})
    if ws_cfg.get("enabled", True):
        collectors.append(
            WebSearchCollector(
                ws_cfg.get("queries", []),
                ws_cfg.get("max_results_per_query", 5),
            )
        )

    # Podcast
    pc_cfg = src_cfg.get("podcast", {})
    if pc_cfg.get("enabled", True):
        collectors.append(
            PodcastCollector(
                pc_cfg.get("sources", []),
                pc_cfg.get("max_results_per_source", 3),
            )
        )

    # Xiaohongshu (requires local MCP server — skip in CI)
    if not is_ci():
        try:
            collectors.append(XiaohongshuCollector())
            logger.info("Added Xiaohongshu collector")
        except Exception as e:
            logger.warning("Failed to init Xiaohongshu collector: %s", e)
    else:
        logger.info("CI mode: skipping Xiaohongshu collector")

    # WeChat (DDGS search only, works in both modes)
    collectors.append(WechatCollector())

    all_items: list = []
    errors: list[str] = []

    # Define timeouts per collector type (seconds)
    COLLECTOR_TIMEOUTS = {
        "RSSCollector": 20,
        "WebSearchCollector": 60,
        "PodcastCollector": 30,
        "XiaohongshuCollector": 25,
        "WechatCollector": 30,
    }

    for col in collectors:
        col_type = col.__class__.__name__
        timeout = COLLECTOR_TIMEOUTS.get(col_type, 30)
        items, err = col.safe_collect(timeout=timeout)
        all_items.extend(items)
        if err:
            errors.append(err)

    logger.info("Collected %d items from %d collectors", len(all_items), len(collectors))
    if errors:
        for e in errors:
            logger.warning("Collector error: %s", e)

    # ── 2. KEYWORD FILTER ──
    logger.info("[2/5] 关键词过滤...")
    keywords = config.get("keywords", {}).get("include", [])
    relevant = keyword_filter(all_items, keywords)

    if not relevant:
        logger.warning("No relevant items after keyword filter")
        # Send notification about empty result
        if not args.dry_run:
            _send_empty_notification(config)
        return

    # ── 2.5 Collect-only mode ──
    if args.collect_only:
        print(json.dumps(
            [{"source": i.source, "title": i.title[:80]} for i in relevant],
            ensure_ascii=False, indent=2,
        ))
        logger.info("Collect only mode — %d items shown above", len(relevant))
        return

    # ── 3. LLM STAGE 1: DEDUP + CLUSTER ──
    logger.info("[3/5] LLM 去重+聚类...")
    from utils.llm import LLMClient
    from processors.dedup_cluster import run_dedup_cluster

    llm = LLMClient(config.get("llm", {}))
    clusters = run_dedup_cluster(llm, relevant)

    if not clusters:
        logger.warning("No clusters generated — cannot proceed")
        if not args.dry_run:
            _send_error_notification(config, "未识别出任何话题簇")
        return

    # Log clusters
    for c in clusters:
        logger.info("  cluster: [%d] %s", c.get("priority", 0), c.get("topic", "?"))

    # Keep only top 12 clusters by priority (covers more than 10 in case some fail)
    clusters.sort(key=lambda c: c.get("priority", 0), reverse=True)
    clusters_for_summary = clusters[:12]

    # ── 4. LLM STAGE 2: SUMMARIZE ──
    logger.info("[4/5] LLM 精读摘要 (%d clusters)...", len(clusters_for_summary))
    from processors.summarize import summarize_clusters

    summaries = summarize_clusters(llm, clusters_for_summary)

    if not summaries:
        logger.warning("No summaries generated")
        if not args.dry_run:
            _send_error_notification(config, "摘要生成失败")
        return

    for s in summaries:
        logger.info("  summary: [%d] %s (%s)",
                    s.get("priority", 0), s.get("topic", "?"), s.get("source", ""))

    # ── 5. FORMAT + OUTPUT ──
    logger.info("[5/5] 格式化 + 飞书输出...")
    from processors.format import (
        build_curated_message,
        build_appendix_message,
        build_kb_document,
    )

    # Format curated message (Message 1)
    group_msg = build_curated_message(
        summaries=summaries,
        user_name=config.get("feishu", {}).get("user_name", ""),
        user_open_id=config.get("feishu", {}).get("user_open_id", ""),
    )

    # Format appendix message (Message 2)
    appendix_msg = build_appendix_message(
        all_items=all_items,
        date_str=report_date,
    )

    kb_doc = build_kb_document(
        summaries=summaries,
        all_items=all_items,
        date_str=report_date,
    )

    # Save locally
    output_dir = HERE / "outputs"
    output_dir.mkdir(exist_ok=True)
    (output_dir / f"curated_{report_date}.md").write_text(group_msg, encoding="utf-8")
    (output_dir / f"appendix_{report_date}.md").write_text(appendix_msg, encoding="utf-8")
    (output_dir / f"kb_doc_{report_date}.md").write_text(kb_doc, encoding="utf-8")
    logger.info("Outputs saved to %s", output_dir)

    if args.dry_run:
        logger.info("DRY RUN — skipping Feishu output")
        print("\n" + "=" * 50)
        print("📖 CURATED MESSAGE PREVIEW:")
        print("=" * 50)
        print(group_msg[:1000])
        print("\n... (truncated)")
        print(f"\n📋 附录共 {len(all_items)} 条来源")
        print("\nFull output saved to outputs/ directory")
        return

    # ── Send to Feishu ──
    feishu_cfg = config.get("feishu", {})

    ok = False
    doc_url = ""

    if is_ci():
        # CI mode: use direct REST API (no lark-cli needed)
        logger.info("CI mode: using REST API...")
        from output.feishu_api import FeishuAPI

        try:
            feishu = FeishuAPI()

            # Message 1: Curated summaries
            ok = feishu.send_group_message(
                chat_id=feishu_cfg.get("chat_id", ""),
                markdown_content=group_msg,
            )
            if ok:
                logger.info("✅ Curated message sent")
            else:
                logger.error("❌ Curated message failed")

            # Message 2: Appendix with all source links
            appendix_ok = feishu.send_group_message(
                chat_id=feishu_cfg.get("chat_id", ""),
                markdown_content=appendix_msg,
            )
            if appendix_ok:
                logger.info("✅ Appendix message sent")
            else:
                logger.warning("⚠️ Appendix message failed")

        except ValueError as e:
            logger.error("REST API init failed: %s", e)
            logger.warning(
                "请在 GitHub 仓库 Settings → Secrets 中添加变量:\n"
                "  LARK_APP_ID: cli_aaea66281c78dd11\n"
                "  LARK_APP_SECRET: (从 open.feishu.cn 获取)\n"
                "  ANTHROPIC_AUTH_TOKEN: (从 settings.json 获取)"
            )
    else:
        # Local mode: use lark-cli
        # Step A: Send group message
        logger.info("Sending group message...")
        from output.feishu_send import send_group_message

        ok, err = send_group_message(
            markdown=group_msg,
            chat_id=feishu_cfg.get("chat_id", ""),
            as_bot=feishu_cfg.get("bot_as", "bot"),
        )

    if ok:
        logger.info("✅ Group message sent")
    else:
        logger.error("❌ Group message failed: %s", err if 'err' in dir() else "see above")

    # Step B: Create KB doc (local mode only, needs user identity)
    if not is_ci():
        logger.info("Creating KB doc...")
        from output.feishu_kb import create_kb_doc

        doc_result, doc_err = create_kb_doc(
            markdown_content=kb_doc,
            title=report_title,
            as_user=feishu_cfg.get("user_as", "user"),
            wiki_space_id=feishu_cfg.get("wiki_space_id", "my_library"),
        )

        if doc_result:
            data = doc_result.get("data", {})
            doc_data = data.get("document", {})
            doc_url = doc_data.get("url", data.get("url", ""))
            logger.info("✅ KB doc created: %s", doc_url)
        else:
            logger.error("❌ KB doc creation failed: %s", doc_err)
            if doc_err and "auth" in doc_err.lower():
                logger.warning(
                    "⚠️  user 身份认证可能已过期，请运行: "
                    "lark-cli auth login --domain wiki --no-wait --json"
                )
    else:
        logger.info("CI mode: skipping KB doc creation (requires local user auth)")

    # If group message succeeded and we have a doc URL, send follow-up
    if ok and doc_url:
            followup = (
                f"📄 **完整日报已存档**：[{report_title}]({doc_url})\n"
                f"可在知识库中查看全文（含全部原文链接）"
            )
            send_group_message(
                markdown=followup,
                chat_id=feishu_cfg.get("chat_id", ""),
                as_bot=feishu_cfg.get("bot_as", "bot"),
            )
    # ── Summary ──
    print()
    print("=" * 50)
    print(f"📊 日报完成: {report_date}")
    print(f"   采集: {len(all_items)} 条 → 过滤后 {len(relevant)} 条")
    print(f"   聚类: {len(clusters)} 个话题簇")
    print(f"   精读: {len(summaries)} 条摘要")
    print(f"   群消息: {'✅ 已发送' if ok else '❌ 失败'}")
    print(f"   知识库: {'✅ 已创建' if doc_url else '❌ 失败或跳过'}")
    if errors:
        print(f"   ⚠️  采集告警: {len(errors)} 个")
        for e in errors:
            print(f"       - {e}")
    print("=" * 50)


def _send_empty_notification(config: dict):
    """Send notification when no relevant news found."""
    from output.feishu_send import send_group_message

    msg = (
        f"<at user_id=\"{config['feishu']['user_open_id']}\">"
        f"{config['feishu']['user_name']}</at>\n\n"
        f"# 🤖 AI+Cloud 每日早报 · {date_bjt()}\n\n"
        f"今日未采集到与 AI/Cloud 直接相关的新闻。\n"
        f"来源正常运行中，请明天再查看。\n\n"
        f"_由 AI+Cloud News Digest 自动生成_"
    )
    send_group_message(
        markdown=msg,
        chat_id=config["feishu"]["chat_id"],
        as_bot=config["feishu"]["bot_as"],
    )


def _send_error_notification(config: dict, error_msg: str):
    """Send notification when processing fails."""
    from output.feishu_send import send_group_message

    msg = (
        f"<at user_id=\"{config['feishu']['user_open_id']}\">"
        f"{config['feishu']['user_name']}</at>\n\n"
        f"# ⚠️ AI+Cloud 早报处理异常\n\n"
        f"日期：{date_bjt()}\n"
        f"错误：{error_msg}\n\n"
        f"请检查日志或重试。"
    )
    send_group_message(
        markdown=msg,
        chat_id=config["feishu"]["chat_id"],
        as_bot=config["feishu"]["bot_as"],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.getLogger("main").exception("Fatal error — 日报流程未捕获异常")
        # Send failure notification to Feishu (best effort)
        try:
            config_path = HERE / "config.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                feishu_cfg = config.get("feishu", {})
                if feishu_cfg.get("chat_id"):
                    from output.feishu_api import FeishuAPI
                    api = FeishuAPI()
                    date_str = date_bjt()
                    msg = (
                        f"# ⚠️ AI+Cloud 早报生成失败\n\n"
                        f"日期：{date_str}\n"
                        f"错误：{e}\n\n"
                        f"请检查 GitHub Actions 日志排查原因。"
                    )
                    api.send_group_message(
                        chat_id=feishu_cfg["chat_id"],
                        markdown_content=msg,
                    )
        except Exception:
            pass
        sys.exit(1)
