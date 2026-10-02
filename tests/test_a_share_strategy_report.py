from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.reports.a_share_strategy import (
    UniverseItem,
    analyze_frame,
    build_payload,
    build_trade_plan,
    select_candidates,
)
from src.reports.a_share_strategy_pdf import render_strategy_pdf


def _frame(days: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2026-03-01", periods=days)
    close = np.linspace(20.0, 28.0, days) + np.sin(np.arange(days) / 5) * 0.3
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.1,
            "close": close,
            "high": close + 0.35,
            "low": close - 0.35,
            "volume": np.full(days, 400_000.0),
        }
    )


def _row(code: str, industry: str, score: int, *, name: str | None = None) -> dict:
    return {
        "code": code,
        "name": name or f"样本{code}",
        "industry": industry,
        "date": "2026-09-30",
        "close": 25.0,
        "ma20": 24.0,
        "rsi14": 55.0,
        "atr_14": 1.0,
        "support": 23.0,
        "resistance": 27.0,
        "ret_20d": 4.0,
        "volatility_20d": 10.0,
        "score": score,
        "signals": ["价格站上20/60日线"],
        "state": "趋势型",
        "liquidity_ok": True,
    }


def test_analyze_frame_and_trade_plan_have_ordered_prices():
    analyzed = analyze_frame(UniverseItem("600000", "浦发银行", "银行"), _frame())
    assert analyzed is not None
    plan = build_trade_plan(analyzed)
    assert plan["stop"] < plan["buy_low"] <= plan["buy_high"]
    assert plan["buy_high"] < plan["target1_low"] <= plan["target1_high"]
    assert plan["target1_high"] < plan["target2_low"] <= plan["target2_high"]
    assert "最新" in plan["fundamental_focus"]


def test_selection_filters_risk_names_and_limits_industry_concentration():
    rows = [
        _row("600001", "银行", 99, name="ST样本"),
        _row("600002", "银行", 98),
        _row("600003", "银行", 97),
        _row("600004", "银行", 96),
        _row("600005", "电力", 95),
        _row("600006", "医药", 94),
    ]
    selected = select_candidates(rows, top_n=5)
    assert all("ST" not in row["name"].upper() for row in selected)
    assert sum(row["industry"] == "银行" for row in selected) == 2
    assert len(selected) >= 3


def test_payload_uses_only_latest_completed_date_and_renders_pdf(tmp_path: Path):
    industries = ["银行", "电力", "医药", "汽车", "半导体"]
    rows = [
        _row(f"60000{index}", industry, 95 - index)
        for index, industry in enumerate(industries, start=1)
    ]
    stale = _row("600099", "银行", 100)
    stale["date"] = "2026-09-29"
    payload = build_payload(rows + [stale], report_date=date(2026, 10, 2))
    assert payload["effective_date"] == "2026-09-30"
    assert payload["scan_count"] == 5
    assert all(row["date"] == "2026-09-30" for row in payload["candidates"])

    output = tmp_path / "strategy.pdf"
    render_strategy_pdf(payload, output)
    assert output.is_file()
    assert output.stat().st_size > 10_000
