from pathlib import Path


WORKFLOW = Path(".github/workflows/00-daily-analysis.yml")


def test_daily_strategy_workflow_contract():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cron: '30 1 * * *'" in text
    assert "timezone:" not in text.split("workflow_dispatch:", 1)[0]
    assert "default: 'strategy-pdf'" in text
    assert "python scripts/generate_daily_strategy_report.py" in text
    assert "python scripts/verify_pdf_report.py" in text
    assert "python scripts/send_report_email.py" in text
    assert "--message-file" in text
    assert "output/pdf/" in text
