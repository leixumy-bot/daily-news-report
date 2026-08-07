#!/usr/bin/env python3
"""Seed seven-day dedup history from local report outputs into Feishu Base."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from output.feishu_base import _date_timestamp_bjt
from utils.history import fingerprint, normalize_text

BJT = timezone(timedelta(hours=8))
SECTION_NAMES = {
    "⚡ 能源", "🔩 芯片", "🏗️ 基础设施", "🧠 模型", "🎯 应用",
    "📜 政策", "🛡️ 安全", "📰 其他行业新闻", "📊 研报速览",
    "📖 精读摘要", "📋 附录：全部原文列表", "🔥 今日头条",
}


def _topic_heading(value: str) -> bool:
    return value.strip() not in SECTION_NAMES and not value.startswith("AI+Cloud 每日早报")


def parse_report(path: Path, date_str: str) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = []
    headings = list(re.finditer(r"^## (.+)$", text, re.M))
    for pos, match in enumerate(headings):
        topic = match.group(1).strip()
        if not _topic_heading(topic):
            continue
        end = headings[pos + 1].start() if pos + 1 < len(headings) else len(text)
        body = text[match.start():end].strip()
        link_match = re.search(r"\*\*原文链接：\*\*\s*\[([^\]]*)\]\(([^)]+)\)", body)
        source = link_match.group(1) if link_match else ""
        source_url = link_match.group(2) if link_match else ""
        rows.append({
            "topic": topic,
            "summary": body[:5000],
            "source": source,
            "source_url": source_url,
            "date": date_str,
        })

    # 溢出项目没有二级标题，保留其标题和一句话，作为已读历史基线。
    for match in re.finditer(r"^- \*\*(.+?)\*\* — (.+)$", text, re.M):
        rows.append({
            "topic": match.group(1).strip(),
            "summary": match.group(2).strip()[:500],
            "source": "",
            "source_url": "",
            "date": date_str,
        })
    return rows


def collect_rows(output_dir: Path, days: int) -> list[dict]:
    today = datetime.now(BJT).date()
    cutoff = today - timedelta(days=days - 1)
    rows = []
    for path in sorted(output_dir.glob("kb_doc_*.md")):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", path.name)
        if not m:
            continue
        date_str = m.group(1)
        try:
            date_value = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not cutoff <= date_value <= today:
            continue
        rows.extend(parse_report(path, date_str))

    unique = {}
    for row in rows:
        key = (row["date"], normalize_text(row["topic"]), row["source_url"])
        unique[key] = row
    return list(unique.values())


def build_rows(rows: list[dict]) -> tuple[list[str], list[list]]:
    fields = [
        "话题标题", "日期", "来源", "来源链接", "优先级", "精读摘要",
        "分类", "类型", "内容指纹", "主题指纹", "首次推送日期", "最后推送日期",
        "进展摘要", "状态", "记录来源",
    ]
    output = []
    for row in rows:
        topic = row["topic"]
        output.append([
            topic,
            _date_timestamp_bjt(row["date"]),
            row["source"],
            f"[{topic}]({row['source_url']})" if row["source_url"] else "",
            0,
            row["summary"],
            "",
            "",
            fingerprint(topic, row["summary"]),
            fingerprint(topic),
            _date_timestamp_bjt(row["date"]),
            _date_timestamp_bjt(row["date"]),
            "",
            "历史基线",
            "bootstrap_outputs",
        ])
    return fields, output


def main() -> int:
    parser = argparse.ArgumentParser(description="从本机日报产物补种近 N 天去重历史")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    token = __import__("os").environ.get("LARK_BASE_TOKEN", "")
    table_id = config.get("bitable", {}).get("table_id", "")
    rows = collect_rows(HERE / "outputs", args.days)
    fields, data = build_rows(rows)
    print(f"历史基线候选: {len(data)} 条")
    if args.dry_run:
        for row in data:
            print(f"  {row[1]} | {row[0][:80]}")
        return 0
    if not token:
        print("LARK_BASE_TOKEN 未设置", file=sys.stderr)
        return 1

    from subprocess import run
    for offset in range(0, len(data), 200):
        payload = json.dumps({"fields": fields, "rows": data[offset:offset + 200]}, ensure_ascii=False)
        result = run([
            "lark-cli", "base", "+record-batch-create",
            "--base-token", token, "--table-id", table_id, "--as", "user",
            "--json", payload, "--format", "json",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
