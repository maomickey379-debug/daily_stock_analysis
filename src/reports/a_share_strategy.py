"""Deterministic A-share screening used by the scheduled PDF report.

The scanner deliberately separates data collection from report rendering so the
same analysis can be tested with fixtures when market endpoints are unavailable.
It never treats an in-progress trading day as a completed daily bar.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TENCENT_KLINE_URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
    "param={symbol},day,,,{bars},qfq"
)


# A liquid, sector-diversified fallback universe. A live full-market snapshot is
# used to extend it when available, so this is not a historical watchlist.
DEFAULT_UNIVERSE: tuple[tuple[str, str, str], ...] = (
    ("600036", "招商银行", "银行"),
    ("601398", "工商银行", "银行"),
    ("000001", "平安银行", "银行"),
    ("601318", "中国平安", "保险"),
    ("601601", "中国太保", "保险"),
    ("600030", "中信证券", "券商"),
    ("300059", "东方财富", "券商"),
    ("600519", "贵州茅台", "白酒"),
    ("000858", "五粮液", "白酒"),
    ("000568", "泸州老窖", "白酒"),
    ("603288", "海天味业", "食品饮料"),
    ("600887", "伊利股份", "食品饮料"),
    ("600276", "恒瑞医药", "医药"),
    ("000538", "云南白药", "中药"),
    ("300760", "迈瑞医疗", "医疗器械"),
    ("300122", "智飞生物", "生物医药"),
    ("600900", "长江电力", "电力"),
    ("600025", "华能水电", "电力"),
    ("601985", "中国核电", "电力"),
    ("601088", "中国神华", "煤炭"),
    ("601225", "陕西煤业", "煤炭"),
    ("601898", "中煤能源", "煤炭"),
    ("600028", "中国石化", "石油石化"),
    ("601857", "中国石油", "石油石化"),
    ("601899", "紫金矿业", "有色金属"),
    ("600547", "山东黄金", "黄金"),
    ("000630", "铜陵有色", "有色金属"),
    ("603993", "洛阳钼业", "有色金属"),
    ("600019", "宝钢股份", "钢铁"),
    ("600585", "海螺水泥", "建材"),
    ("600048", "保利发展", "地产"),
    ("000333", "美的集团", "家电"),
    ("000651", "格力电器", "家电"),
    ("600690", "海尔智家", "家电"),
    ("002594", "比亚迪", "汽车"),
    ("601633", "长城汽车", "汽车"),
    ("600104", "上汽集团", "汽车"),
    ("300750", "宁德时代", "电池"),
    ("002466", "天齐锂业", "锂电"),
    ("601012", "隆基绿能", "光伏"),
    ("300274", "阳光电源", "光伏"),
    ("002202", "金风科技", "风电"),
    ("601138", "工业富联", "AI硬件"),
    ("000725", "京东方A", "面板"),
    ("002475", "立讯精密", "消费电子"),
    ("002371", "北方华创", "半导体"),
    ("603501", "豪威集团", "半导体"),
    ("688981", "中芯国际", "半导体"),
    ("000063", "中兴通讯", "通信设备"),
    ("300308", "中际旭创", "光通信"),
    ("000977", "浪潮信息", "服务器"),
    ("603019", "中科曙光", "计算机"),
    ("688111", "金山办公", "软件"),
    ("300502", "新易盛", "光通信"),
    ("600941", "中国移动", "通信运营"),
    ("601728", "中国电信", "通信运营"),
    ("002230", "科大讯飞", "AI应用"),
    ("300418", "昆仑万维", "互联网"),
    ("600031", "三一重工", "工程机械"),
    ("000425", "徐工机械", "工程机械"),
    ("300124", "汇川技术", "工业自动化"),
    ("600760", "中航沈飞", "国防军工"),
    ("002025", "航天电器", "国防军工"),
    ("000768", "中航西飞", "国防军工"),
    ("601919", "中远海控", "航运"),
    ("601006", "大秦铁路", "铁路"),
    ("600009", "上海机场", "机场"),
    ("601888", "中国中免", "零售"),
    ("300498", "温氏股份", "农牧"),
    ("002714", "牧原股份", "农牧"),
    ("600309", "万华化学", "化工"),
    ("002648", "卫星化学", "化工"),
    ("601668", "中国建筑", "建筑"),
    ("601111", "中国国航", "航空"),
    ("600018", "上港集团", "港口"),
)

INDEX_UNIVERSE: tuple[tuple[str, str], ...] = (
    ("000001", "上证指数"),
    ("399001", "深证成指"),
    ("399006", "创业板指"),
    ("000300", "沪深300"),
)

INDUSTRY_FUNDAMENTAL_FOCUS: dict[str, str] = {
    "银行": "关注净息差、资产质量与信贷投放，需核对最新财报及监管指标",
    "保险": "关注新业务价值、投资收益和偿付能力，需核对最新财报",
    "券商": "关注成交活跃度、投行业务与自营波动，需核对最新公告",
    "白酒": "关注渠道库存、批价和现金流，需核对最新经营数据",
    "食品饮料": "关注终端需求、成本与渠道库存，需核对最新财报",
    "医药": "关注产品放量、研发进展与集采影响，需核对公司公告",
    "中药": "关注产品提价、渠道动销与原料成本，需核对最新财报",
    "医疗器械": "关注订单、海外需求与集采影响，需核对最新公告",
    "生物医药": "关注研发管线、商业化进度与现金消耗，需核对公司公告",
    "电力": "关注来水/利用小时、电价和资本开支，需核对经营公告",
    "煤炭": "关注煤价、长协比例和股东回报，需核对产销公告",
    "石油石化": "关注油价、炼化价差和资本开支，需核对经营数据",
    "有色金属": "关注金属价格、产量和项目进度，需核对产销公告",
    "黄金": "关注金价、矿产金产量与成本，需核对产销公告",
    "汽车": "关注销量、产品周期和单车盈利，需核对月度产销公告",
    "电池": "关注出货、材料成本和海外扩产，需核对最新财报与公告",
    "光伏": "关注组件价格、开工率与现金流，需核对最新经营数据",
    "半导体": "关注下游景气、产能利用率和研发投入，需核对最新财报",
    "AI硬件": "关注订单兑现、客户集中度和资本开支周期，需核对最新公告",
    "光通信": "关注订单兑现、产品迭代与估值消化，需核对最新公告",
    "通信设备": "关注运营商资本开支、订单与海外风险，需核对公司公告",
    "通信运营": "关注ARPU、云业务与资本开支，需核对最新运营数据",
    "国防军工": "关注订单节奏、合同负债和交付，需核对最新财报",
    "农牧": "关注产品价格、成本与产能变化，需核对月度经营公告",
    "化工": "关注产品价差、开工率与新增产能，需核对经营数据",
}


@dataclass(frozen=True)
class UniverseItem:
    code: str
    name: str
    industry: str


def _stock_symbol(code: str) -> str:
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


def _index_symbol(code: str) -> str:
    return ("sh" if code.startswith("000") else "sz") + code


def _http_json(url: str, *, timeout: float = 12, retries: int = 2) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # Network errors are handled by provider fallback.
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"腾讯行情请求失败: {last_error}")


def _parse_kline_rows(payload: Mapping[str, Any], symbol: str) -> pd.DataFrame:
    node = payload.get("data", {}).get(symbol, {})
    rows = node.get("qfqday") or node.get("day") or []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            parsed.append(
                {
                    "date": pd.Timestamp(row[0]),
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (TypeError, ValueError):
            continue
    return pd.DataFrame(parsed).sort_values("date").reset_index(drop=True) if parsed else pd.DataFrame()


def fetch_completed_kline(
    code: str,
    *,
    as_of: date,
    bars: int = 260,
    is_index: bool = False,
    timeout: float = 12,
) -> pd.DataFrame:
    """Fetch daily bars and remove the current/incomplete trading date."""
    symbol = _index_symbol(code) if is_index else _stock_symbol(code)
    payload = _http_json(
        TENCENT_KLINE_URL.format(symbol=symbol, bars=bars), timeout=timeout
    )
    frame = _parse_kline_rows(payload, symbol)
    if frame.empty:
        return frame
    return frame[frame["date"].dt.date < as_of].reset_index(drop=True)


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    relative = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + relative))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def analyze_frame(item: UniverseItem, frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty or len(frame) < 80:
        return None
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]
    latest = frame.iloc[-1]
    previous = frame.iloc[-2]

    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_bar = 2 * (dif - dea)
    rsi14 = _rsi(close, 14)
    std20 = close.rolling(20).std()
    boll_upper = ma20 + 2 * std20
    boll_lower = ma20 - 2 * std20
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr14 = tr.rolling(14).mean()

    current = float(latest["close"])
    avg_amount_proxy = float((close.tail(20) * volume.tail(20) * 100).mean())
    ret5 = (current / float(close.iloc[-6]) - 1) * 100
    ret20 = (current / float(close.iloc[-21]) - 1) * 100
    ret60 = (current / float(close.iloc[-61]) - 1) * 100
    volatility = float(close.pct_change().tail(20).std() * math.sqrt(20) * 100)
    support = float(low.tail(20).min())
    resistance = float(high.tail(20).max())
    bias20 = (current / float(ma20.iloc[-1]) - 1) * 100

    score = 50.0
    signals: list[str] = []
    if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
        score += 18
        signals.append("均线多头排列")
    elif current > ma20.iloc[-1] > ma60.iloc[-1]:
        score += 10
        signals.append("价格站上20/60日线")
    elif current < ma20.iloc[-1]:
        score -= 6

    if dif.iloc[-1] > dea.iloc[-1] and macd_bar.iloc[-1] > macd_bar.iloc[-2]:
        score += 8
        signals.append("MACD动能改善")
    elif dif.iloc[-1] < dea.iloc[-1]:
        score -= 5

    rsi_value = _safe_float(rsi14.iloc[-1], 50)
    if 42 <= rsi_value <= 68:
        score += 6
    elif rsi_value < 30:
        score += 2
        signals.append("RSI超卖（仍需止跌确认）")
    elif rsi_value > 76:
        score -= 10
        signals.append("RSI偏热")

    if -4 <= bias20 <= 5:
        score += 8
        signals.append("接近20日均线")
    elif bias20 > 12:
        score -= 12
        signals.append("偏离20日线较大")
    elif bias20 < -12:
        score -= 4
        signals.append("趋势尚未修复")

    if ret20 > 3:
        score += min(ret20, 15) * 0.45
    elif ret20 < -12:
        score -= 6
    if ret5 > 10:
        score -= 8
        signals.append("近5日涨幅较大，追高风险")
    if volatility > 18:
        score -= 6
    if avg_amount_proxy >= 300_000_000:
        score += 5
    elif avg_amount_proxy < 50_000_000:
        score -= 20

    band_width = float(boll_upper.iloc[-1] - boll_lower.iloc[-1])
    boll_position = (
        (current - float(boll_lower.iloc[-1])) / band_width if band_width > 0 else 0.5
    )
    if 0.2 <= boll_position <= 0.75:
        score += 4
    elif boll_position > 1.0:
        score -= 6

    state = "趋势型" if current > ma20.iloc[-1] > ma60.iloc[-1] else "等待确认"
    if rsi_value < 32:
        state = "超跌观察"

    return {
        "code": item.code,
        "name": item.name,
        "industry": item.industry,
        "date": latest["date"].date().isoformat(),
        "close": round(current, 2),
        "open": round(float(latest["open"]), 2),
        "high": round(float(latest["high"]), 2),
        "low": round(float(latest["low"]), 2),
        "pct_change": round((current / float(previous["close"]) - 1) * 100, 2),
        "ma5": round(float(ma5.iloc[-1]), 2),
        "ma10": round(float(ma10.iloc[-1]), 2),
        "ma20": round(float(ma20.iloc[-1]), 2),
        "ma60": round(float(ma60.iloc[-1]), 2),
        "rsi14": round(rsi_value, 2),
        "macd_dif": round(float(dif.iloc[-1]), 4),
        "macd_dea": round(float(dea.iloc[-1]), 4),
        "macd_bar": round(float(macd_bar.iloc[-1]), 4),
        "boll_upper": round(float(boll_upper.iloc[-1]), 2),
        "boll_lower": round(float(boll_lower.iloc[-1]), 2),
        "boll_position": round(float(boll_position), 3),
        "ret_5d": round(float(ret5), 2),
        "ret_20d": round(float(ret20), 2),
        "ret_60d": round(float(ret60), 2),
        "bias_20": round(float(bias20), 2),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "atr_14": round(float(atr14.iloc[-1]), 2),
        "volatility_20d": round(volatility, 2),
        "avg_amount_proxy": round(avg_amount_proxy, 2),
        "score": int(max(0, min(100, round(score)))),
        "signals": signals,
        "state": state,
        "liquidity_ok": avg_amount_proxy >= 50_000_000,
    }


def _valid_stock_name(name: str) -> bool:
    upper = str(name or "").upper()
    return not any(marker in upper for marker in ("ST", "退", "退市"))


def load_universe(*, limit: int = 120) -> list[UniverseItem]:
    """Return a broad universe, extending the curated list with a live snapshot."""
    known = {code: UniverseItem(code, name, industry) for code, name, industry in DEFAULT_UNIVERSE}
    try:
        import efinance as ef

        snapshot = ef.stock.get_realtime_quotes("沪深A股", timeout=10)
        if not snapshot.empty:
            snapshot = snapshot.copy()
            snapshot["总市值"] = pd.to_numeric(snapshot.get("总市值"), errors="coerce")
            snapshot["成交额"] = pd.to_numeric(snapshot.get("成交额"), errors="coerce")
            snapshot = snapshot.sort_values(["总市值", "成交额"], ascending=False)
            for _, row in snapshot.head(max(limit * 3, 200)).iterrows():
                code = str(row.get("股票代码", "")).zfill(6)
                name = str(row.get("股票名称", "")).strip()
                if len(code) != 6 or not code.isdigit() or not _valid_stock_name(name):
                    continue
                known.setdefault(code, UniverseItem(code, name, "其他高流动性标的"))
                if len(known) >= limit:
                    break
    except Exception:
        # The curated universe is the deterministic fallback for blocked/flaky snapshots.
        pass
    return list(known.values())[:limit]


def _scan_item(item: UniverseItem, as_of: date) -> dict[str, Any] | None:
    if not _valid_stock_name(item.name):
        return None
    frame = fetch_completed_kline(item.code, as_of=as_of)
    return analyze_frame(item, frame)


def scan_market(
    *,
    as_of: date | None = None,
    universe_limit: int = 120,
    workers: int = 12,
) -> tuple[list[dict[str, Any]], list[str]]:
    as_of = as_of or datetime.now(SHANGHAI_TZ).date()
    universe = load_universe(limit=universe_limit)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 20))) as executor:
        futures = {executor.submit(_scan_item, item, as_of): item for item in universe}
        for future in as_completed(futures):
            item = futures[future]
            try:
                value = future.result()
                if value and value.get("liquidity_ok"):
                    results.append(value)
            except Exception as exc:
                errors.append(f"{item.code}: {type(exc).__name__}")
    results.sort(key=lambda row: (row.get("score", 0), row.get("avg_amount_proxy", 0)), reverse=True)
    return results, errors


def select_candidates(rows: Sequence[Mapping[str, Any]], *, top_n: int = 5) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    industry_counts: dict[str, int] = {}
    for raw in sorted(rows, key=lambda row: _safe_float(row.get("score")), reverse=True):
        row = dict(raw)
        if not _valid_stock_name(str(row.get("name", ""))) or not row.get("liquidity_ok", True):
            continue
        industry = str(row.get("industry") or "其他")
        if industry_counts.get(industry, 0) >= 2:
            continue
        selected.append(row)
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        if len(selected) >= max(3, min(top_n, 6)):
            break
    return selected


def build_trade_plan(row: Mapping[str, Any]) -> dict[str, Any]:
    close = _safe_float(row.get("close"))
    atr = max(_safe_float(row.get("atr_14")), close * 0.015)
    support = _safe_float(row.get("support"), close - atr)
    resistance = _safe_float(row.get("resistance"), close + atr * 2)
    buy_low = max(support, close - atr * 0.65)
    buy_high = max(buy_low + close * 0.002, close + atr * 0.10)
    stop = min(buy_low - atr * 0.65, support - atr * 0.25)
    risk = max(buy_high - stop, atr * 0.8)
    target1_low = max(resistance, buy_high + risk * 1.35)
    target1_high = target1_low + atr * 0.45
    target2_low = max(target1_high + close * 0.003, buy_high + risk * 2.25)
    target2_high = target2_low + atr * 0.65
    volatility = _safe_float(row.get("volatility_20d"), 12)
    position = "5% - 7%" if volatility <= 9 else ("3% - 5%" if volatility <= 15 else "2% - 3%")
    signals = [str(value) for value in row.get("signals", [])][:3]
    state = str(row.get("state") or "等待确认")
    thesis = "、".join(signals) if signals else "价格与均线、量能处于可跟踪区间"
    risk_text = (
        "超卖不等于见底，需等待放量止跌"
        if state == "超跌观察"
        else "跌破支撑或量价背离时逻辑失效"
    )
    industry = str(row.get("industry") or "其他")
    fundamental_focus = INDUSTRY_FUNDAMENTAL_FOCUS.get(
        industry,
        "关注盈利质量、现金流、估值与监管事项，需核对最新财报和公司公告",
    )
    return {
        "buy_low": round(buy_low, 2),
        "buy_high": round(buy_high, 2),
        "target1_low": round(target1_low, 2),
        "target1_high": round(target1_high, 2),
        "target2_low": round(target2_low, 2),
        "target2_high": round(target2_high, 2),
        "stop": round(max(0.01, stop), 2),
        "position": position,
        "thesis": thesis,
        "fundamental_focus": fundamental_focus,
        "risk": risk_text,
        "gap_rule": (
            "若开盘较最新有效收盘高开3%以上或超出买入上限，"
            "不追价；等待回踩区间并重新核对量能。"
        ),
    }


def summarize_industries(rows: Sequence[Mapping[str, Any]], *, limit: int = 6) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("industry") or "其他"), []).append(row)
    summaries: list[dict[str, Any]] = []
    for industry, members in groups.items():
        returns = [_safe_float(member.get("ret_20d")) for member in members]
        scores = [_safe_float(member.get("score")) for member in members]
        positive_ratio = sum(value > 0 for value in returns) / max(1, len(returns))
        strength = mean(returns) * 0.65 + positive_ratio * 12 + median(scores) * 0.15
        state = "相对占优" if strength >= 14 else ("中性轮动" if strength >= 8 else "偏弱观察")
        summaries.append(
            {
                "industry": industry,
                "state": state,
                "ret20": round(mean(returns), 2),
                "positive_ratio": round(positive_ratio * 100),
                "sample_size": len(members),
                "strength": strength,
            }
        )
    summaries.sort(key=lambda value: value["strength"], reverse=True)
    return summaries[:limit]


def fetch_indices(*, as_of: date) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for code, name in INDEX_UNIVERSE:
        try:
            frame = fetch_completed_kline(code, as_of=as_of, is_index=True, bars=40)
            if len(frame) < 2:
                continue
            latest, previous = frame.iloc[-1], frame.iloc[-2]
            close = float(latest["close"])
            output.append(
                {
                    "code": code,
                    "name": name,
                    "date": latest["date"].date().isoformat(),
                    "close": round(close, 2),
                    "pct_change": round((close / float(previous["close"]) - 1) * 100, 2),
                }
            )
        except Exception:
            continue
    return output


def _latest_market_context(report_dir: Path) -> str:
    candidates = sorted(report_dir.glob("market_review_*.md"), reverse=True)
    if not candidates:
        return ""
    text = candidates[0].read_text(encoding="utf-8", errors="replace")
    compact = " ".join(line.strip("# -*\t") for line in text.splitlines() if line.strip())
    return compact[:1400]


def build_payload(
    rows: Sequence[Mapping[str, Any]],
    *,
    report_date: date,
    indices: Sequence[Mapping[str, Any]] | None = None,
    scan_errors: Sequence[str] | None = None,
    market_context: str = "",
    top_n: int = 5,
) -> dict[str, Any]:
    valid_rows = [dict(row) for row in rows if row.get("close") and row.get("date")]
    if len(valid_rows) < 3:
        raise ValueError("有效候选不足3只，无法生成策略报告")
    effective_date = max(str(row["date"]) for row in valid_rows)
    valid_rows = [row for row in valid_rows if str(row["date"]) == effective_date]
    if len(valid_rows) < 3:
        raise ValueError("最新有效交易日的候选不足3只")
    candidates = select_candidates(valid_rows, top_n=top_n)
    if len(candidates) < 3:
        raise ValueError("风险和流动性过滤后候选不足3只")
    for candidate in candidates:
        candidate["plan"] = build_trade_plan(candidate)
    industries = summarize_industries(valid_rows)
    return {
        "report_date": report_date.isoformat(),
        "effective_date": effective_date,
        "scan_count": len(valid_rows),
        "scan_error_count": len(scan_errors or []),
        "indices": list(indices or []),
        "industries": industries,
        "candidates": candidates,
        "market_context": market_context,
        "sources": [
            {"label": "上交所交易日历", "url": "https://www.sse.com.cn/services/tradingservice/tradingcalendar/"},
            {"label": "中国人民银行", "url": "https://www.pbc.gov.cn/"},
            {"label": "国家统计局", "url": "https://www.stats.gov.cn/"},
            {"label": "中国证监会", "url": "https://www.csrc.gov.cn/"},
        ],
        "disclaimer": "仅供研究参考，不构成个性化投资建议或收益承诺。",
    }


def generate_live_payload(
    *,
    report_date: date | None = None,
    universe_limit: int | None = None,
    workers: int | None = None,
    top_n: int = 5,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    report_date = report_date or datetime.now(SHANGHAI_TZ).date()
    universe_limit = universe_limit or int(os.getenv("A_SHARE_REPORT_UNIVERSE_LIMIT", "120"))
    workers = workers or int(os.getenv("A_SHARE_REPORT_WORKERS", "12"))
    rows, errors = scan_market(
        as_of=report_date,
        universe_limit=universe_limit,
        workers=workers,
    )
    indices = fetch_indices(as_of=report_date)
    context = _latest_market_context(report_dir or Path("reports"))
    return build_payload(
        rows,
        report_date=report_date,
        indices=indices,
        scan_errors=errors,
        market_context=context,
        top_n=top_n,
    )


def load_fixture_payload(
    path: Path,
    *,
    report_date: date,
    top_n: int = 5,
) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("rows", raw) if isinstance(raw, dict) else raw
    indices = raw.get("indices", []) if isinstance(raw, dict) else []
    return build_payload(rows, report_date=report_date, indices=indices, top_n=top_n)
