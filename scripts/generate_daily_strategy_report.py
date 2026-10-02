#!/usr/bin/env python3
"""Generate the scheduled A-share strategy PDF and email summary."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reports.a_share_strategy import generate_live_payload, load_fixture_payload
from src.reports.a_share_strategy_pdf import build_email_summary, render_strategy_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成A股每日策略 PDF")
    parser.add_argument("--output", type=Path, help="PDF输出路径")
    parser.add_argument("--summary", type=Path, help="邮件 Markdown 摘要路径")
    parser.add_argument("--payload-output", type=Path, help="保存结构化报告数据")
    parser.add_argument("--fixture", type=Path, help="使用已分析 JSON 数据（离线验收）")
    parser.add_argument("--date", help="报告日期，YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=5, choices=range(3, 7))
    parser.add_argument("--universe-limit", type=int)
    parser.add_argument("--workers", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_date = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    )
    date_token = report_date.strftime("%Y%m%d")
    output = args.output or ROOT / "output" / "pdf" / f"a_share_daily_strategy_{date_token}.pdf"
    summary = args.summary or output.with_suffix(".md")
    payload_output = args.payload_output or output.with_suffix(".json")

    if args.fixture:
        payload = load_fixture_payload(args.fixture, report_date=report_date, top_n=args.top_n)
    else:
        payload = generate_live_payload(
            report_date=report_date,
            universe_limit=args.universe_limit,
            workers=args.workers,
            top_n=args.top_n,
            report_dir=ROOT / "reports",
        )

    render_strategy_pdf(payload, output)
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(build_email_summary(payload), encoding="utf-8")
    payload_output.parent.mkdir(parents=True, exist_ok=True)
    payload_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"PDF_PATH={output.resolve()}")
    print(f"SUMMARY_PATH={summary.resolve()}")
    print(f"PAYLOAD_PATH={payload_output.resolve()}")
    print(f"EFFECTIVE_DATE={payload['effective_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
