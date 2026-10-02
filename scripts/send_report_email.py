#!/usr/bin/env python3
"""Send a generated PDF report through the project's configured SMTP channel."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notification_sender.email_sender import EmailSender


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="发送股票分析 PDF 报告邮件")
    parser.add_argument("--pdf", required=True, help="待发送 PDF 文件路径")
    parser.add_argument("--to", action="append", dest="receivers", help="收件地址；可重复传入")
    parser.add_argument("--subject", help="邮件主题")
    parser.add_argument("--message-file", type=Path, help="从 UTF-8 文件读取邮件正文")
    parser.add_argument(
        "--message",
        default="今日A股分析报告已生成，核心结论与完整交易计划请见附件。\n\n仅供研究参考，不构成投资建议。",
        help="邮件正文（支持 Markdown）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    message = args.message
    if args.message_file:
        if not args.message_file.is_file():
            print(f"邮件正文文件不存在: {args.message_file}", file=sys.stderr)
            return 2
        message = args.message_file.read_text(encoding="utf-8")
    configured_receivers = [
        value.strip()
        for value in os.getenv("EMAIL_RECEIVERS", "").split(",")
        if value.strip()
    ]
    email_config = SimpleNamespace(
        email_sender=os.getenv("EMAIL_SENDER", "").strip(),
        email_sender_name=os.getenv(
            "EMAIL_SENDER_NAME", "daily_stock_analysis股票分析助手"
        ).strip(),
        email_password=os.getenv("EMAIL_PASSWORD", "").strip(),
        email_receivers=configured_receivers,
        stock_email_groups=[],
    )
    sender = EmailSender(email_config)
    sent = sender.send_email_with_pdf_attachment(
        content=message,
        pdf_path=args.pdf,
        subject=args.subject,
        receivers=args.receivers,
    )
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
