"""Professional PDF renderer for the scheduled A-share strategy report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#101A2E")
BLUE = colors.HexColor("#356AE6")
CYAN = colors.HexColor("#35B8D0")
RED = colors.HexColor("#E65353")
GREEN = colors.HexColor("#16A085")
INK = colors.HexColor("#1D2939")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#E2E8F0")
PAPER = colors.HexColor("#F5F7FA")


def register_chinese_font() -> str:
    candidates = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    )
    for candidate in candidates:
        if not Path(candidate).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("AshareCN", candidate, subfontIndex=0))
            return "AshareCN"
        except Exception:
            continue
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=font_name, fontSize=29, leading=39, textColor=colors.white),
        "cover": ParagraphStyle("cover", fontName=font_name, fontSize=9.5, leading=16, textColor=colors.HexColor("#B9C4D8")),
        "h1": ParagraphStyle("h1", fontName=font_name, fontSize=19, leading=26, textColor=NAVY),
        "h2": ParagraphStyle("h2", fontName=font_name, fontSize=11.5, leading=17, textColor=NAVY),
        "body": ParagraphStyle("body", fontName=font_name, fontSize=8.5, leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", fontName=font_name, fontSize=7.1, leading=10.5, textColor=MUTED),
        "table": ParagraphStyle("table", fontName=font_name, fontSize=6.9, leading=9.4, textColor=INK),
        "thead": ParagraphStyle("thead", fontName=font_name, fontSize=6.8, leading=8.5, textColor=colors.white, alignment=1),
        "metric": ParagraphStyle("metric", fontName=font_name, fontSize=13, leading=17, textColor=NAVY, alignment=1),
    }


def _fmt_range(low: Any, high: Any) -> str:
    return f"{float(low):.2f} - {float(high):.2f}"


def render_strategy_pdf(payload: Mapping[str, Any], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font = register_chinese_font()
    styles = _styles(font)
    report_date = str(payload["report_date"])
    effective_date = str(payload["effective_date"])
    candidates = list(payload.get("candidates", []))

    def paragraph(text: Any, style: str = "body") -> Paragraph:
        return Paragraph(str(text), styles[style])

    def cover(canvas, _doc):
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#1D3155"))
        canvas.circle(width, height, 68 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#233B66"))
        canvas.circle(width - 8 * mm, 0, 46 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(2)
        canvas.line(17 * mm, height - 31 * mm, 49 * mm, height - 31 * mm)
        canvas.restoreState()

    def header(canvas, doc):
        width, height = A4
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(16 * mm, height - 14 * mm, width - 16 * mm, height - 14 * mm)
        canvas.setFont(font, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, height - 10.5 * mm, f"A股每日策略报告 | {report_date}")
        canvas.drawRightString(width - 16 * mm, 9 * mm, f"{doc.page:02d}")
        canvas.restoreState()

    def section(number: str, title: str, subtitle: str) -> list[Any]:
        return [
            Table(
                [[paragraph(number, "small"), paragraph(title, "h1")]],
                colWidths=[12 * mm, 160 * mm],
                style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]),
            ),
            paragraph(subtitle, "small"),
            Spacer(1, 4 * mm),
            Table([[""]], colWidths=[172 * mm], rowHeights=[2.5], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE)])),
            Spacer(1, 5 * mm),
        ]

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=20 * mm,
        bottomMargin=16 * mm,
        title=f"A股每日策略报告 {report_date}",
        author="daily_stock_analysis",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=frame, onPage=cover),
            PageTemplate(id="content", frames=frame, onPage=header),
        ]
    )

    scan_count = int(payload.get("scan_count", 0))
    story: list[Any] = [
        Spacer(1, 34 * mm),
        paragraph(f"DAILY A-SHARE PLAYBOOK / {report_date}", "cover"),
        Spacer(1, 8 * mm),
        paragraph("A股每日<br/>策略报告", "title"),
        Spacer(1, 7 * mm),
        paragraph("市场结构 · 行业轮动 · 候选股 · 交易边界", "cover"),
        Spacer(1, 22 * mm),
        Table(
            [
                [paragraph("数据口径", "cover"), paragraph(f"最新有效已完成交易日：{effective_date}。未把报告当日盘中数据当作收盘数据。", "cover")],
                [paragraph("扫描范围", "cover"), paragraph(f"有效扫描 {scan_count} 只高流动性行业代表及快照扩展标的；非全A股穷举。", "cover")],
                [paragraph("核心约束", "cover"), paragraph("只做分批计划；若开盘跳空超出区间，等待重新校准，不追高。", "cover")],
            ],
            colWidths=[31 * mm, 129 * mm],
            rowHeights=[18 * mm] * 3,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1B2B49")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#344765")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 27 * mm),
        paragraph(escape(str(payload.get("disclaimer", ""))), "cover"),
        NextPageTemplate("content"),
        PageBreak(),
    ]

    story += section("01", "市场与行业判断", "先确认行情实际截止日期，再观察风格与行业强弱")
    indices = list(payload.get("indices", []))[:4]
    if indices:
        metric_values = [paragraph(f'{float(item["close"]):.2f}', "metric") for item in indices]
        metric_labels = [paragraph(f'{escape(str(item["name"]))} {float(item["pct_change"]):+.2f}%', "small") for item in indices]
        story += [
            Table(
                [metric_values, metric_labels],
                colWidths=[172 * mm / len(indices)] * len(indices),
                rowHeights=[12 * mm, 8 * mm],
                style=TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
            ),
            Spacer(1, 7 * mm),
        ]
    industries = list(payload.get("industries", []))
    industry_rows = [[paragraph(value, "thead") for value in ("行业", "状态", "20日表现", "样本广度", "解读")]]
    for item in industries:
        state = str(item.get("state", ""))
        color = GREEN if state == "相对占优" else (CYAN if state == "中性轮动" else RED)
        interpretation = (
            "趋势与广度相对更好，仍需防范拥挤。"
            if state == "相对占优"
            else ("有轮动机会，但持续性需量能确认。" if state == "中性轮动" else "趋势偏弱，优先等待修复而非抢反弹。")
        )
        industry_rows.append(
            [
                paragraph(escape(str(item.get("industry", ""))), "table"),
                paragraph(f'<font color="{color.hexval()}"><b>{escape(state)}</b></font>', "table"),
                paragraph(f'{float(item.get("ret20", 0)):+.2f}%', "table"),
                paragraph(f'{int(item.get("positive_ratio", 0))}% / {int(item.get("sample_size", 0))}只', "table"),
                paragraph(interpretation, "table"),
            ]
        )
    story += [
        Table(
            industry_rows,
            colWidths=[29 * mm, 25 * mm, 23 * mm, 28 * mm, 67 * mm],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 6 * mm),
    ]
    context = str(payload.get("market_context") or "").strip()
    if context:
        story += [paragraph("政策、宏观与外围摘要", "h2"), paragraph(escape(context), "body"), Spacer(1, 4 * mm)]
    else:
        story += [paragraph("政策、宏观与外围校验", "h2"), paragraph("本次未获得可验证的市场复盘文本，不对政策和外盘作未经核实的推断。建议在开盘前复核权威入口与公司公告。", "body")]
    story.append(PageBreak())

    story += section("02", "候选与交易计划", "排名是观察优先级，不是买入指令；价格越过区间时不追价")
    headers = ("标的", "收盘", "买入区间", "第一止盈", "第二止盈", "失效位", "仓位")
    candidate_rows = [[paragraph(value, "thead") for value in headers]]
    for rank, stock in enumerate(candidates, start=1):
        plan = stock["plan"]
        candidate_rows.append(
            [
                paragraph(f'<font color="#356AE6"><b>{rank:02d}</b></font> {escape(str(stock["name"]))}<br/><font color="#667085">{stock["code"]} · {escape(str(stock.get("industry", "")))} · {escape(str(stock.get("state", "")))}</font>', "table"),
                paragraph(f'{float(stock["close"]):.2f}', "table"),
                paragraph(_fmt_range(plan["buy_low"], plan["buy_high"]), "table"),
                paragraph(_fmt_range(plan["target1_low"], plan["target1_high"]), "table"),
                paragraph(_fmt_range(plan["target2_low"], plan["target2_high"]), "table"),
                paragraph(f'{float(plan["stop"]):.2f}', "table"),
                paragraph(str(plan["position"]), "table"),
            ]
        )
    story += [
        Table(
            candidate_rows,
            colWidths=[40 * mm, 17 * mm, 27 * mm, 27 * mm, 27 * mm, 18 * mm, 16 * mm],
            rowHeights=[10 * mm] + [18 * mm] * len(candidates),
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        Spacer(1, 7 * mm),
        paragraph("组合执行原则", "h2"),
        paragraph("候选股不是同时买入清单。单只按建议仓位分两至三笔，初始总仓位建议不超过30%；触及第一止盈区可减仓约一半，余仓上移止损。", "body"),
        Spacer(1, 5 * mm),
        paragraph("跳空重新校准", "h2"),
        paragraph("若当日开盘较最新有效收盘高开3%以上，或直接高于买入上限，取消开盘买入；若低开跌破失效位，不因价格更低而拉低成本。", "body"),
        PageBreak(),
    ]

    story += section("03", "逐股逻辑与风险", "入选逻辑、失效位和仓位约束必须同时成立")
    for rank, stock in enumerate(candidates, start=1):
        plan = stock["plan"]
        signals = "、".join(escape(str(value)) for value in stock.get("signals", [])[:3]) or "无极端技术信号"
        block = Table(
            [
                [
                    paragraph(f'<font color="#356AE6">{rank:02d}</font> <b>{escape(str(stock["name"]))}</b>  <font color="#667085">{stock["code"]} · {escape(str(stock.get("state", "")))}</font>', "h2"),
                    paragraph(f'<b>计划买入</b> {_fmt_range(plan["buy_low"], plan["buy_high"])}<br/><b>止盈</b> {_fmt_range(plan["target1_low"], plan["target1_high"])} / {_fmt_range(plan["target2_low"], plan["target2_high"])}<br/><b>失效</b> {float(plan["stop"]):.2f}', "table"),
                ],
                [
                    paragraph(f'<b>逻辑：</b>{escape(str(plan["thesis"]))}<br/><b>技术：</b>评分 {int(stock.get("score", 0))}/100，RSI(14) {float(stock.get("rsi14", 0)):.1f}，MA20 {float(stock.get("ma20", 0)):.2f}，信号：{signals}。<br/><b>基本面关注：</b>{escape(str(plan["fundamental_focus"]))}。<br/><b>风险：</b>{escape(str(plan["risk"]))}。', "body"),
                    paragraph(f'<b>建议仓位</b><br/>{escape(str(plan["position"]))}<br/><font color="#E65353">分批执行</font>', "table"),
                ],
            ],
            colWidths=[124 * mm, 48 * mm],
            style=TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
        story += [block, Spacer(1, 3 * mm)]
    story.append(PageBreak())

    story += section("04", "执行清单与数据说明", "开盘前核对公告与外围，开盘后再确认价格和量能")
    checks = (
        ("盘前", "核对政策、公司公告、外盘指数、美元、原油、黄金和铜价。"),
        ("开盘", "记录跳空幅度；高开超出买入区间不追，低开跌破失效位不接。"),
        ("10:00后", "确认成交量与5日线；只有止跌和量能改善同时成立才加仓。"),
        ("止盈", "触及第一目标后分批兑现，余仓上移止损，不强求第二目标。"),
        ("复盘", "如果行业强度、公告或逻辑失效，即使未触及价格止损也应重新评估。"),
    )
    for label, text in checks:
        story += [
            Table(
                [[paragraph(f'<font color="#356AE6"><b>{label}</b></font>', "h2"), paragraph(text, "body")]],
                colWidths=[28 * mm, 144 * mm],
                rowHeights=[17 * mm],
                style=TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (0, 0), PAPER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6)]),
            ),
            Spacer(1, 3 * mm),
        ]
    source_links = " · ".join(
        f'<link href="{escape(str(item["url"]))}">{escape(str(item["label"]))}</link>'
        for item in payload.get("sources", [])
    )
    story += [
        Spacer(1, 4 * mm),
        paragraph("数据与来源", "h2"),
        paragraph(f"行情技术数据来自腾讯公开日K接口，有效日期为 {effective_date}。筛选先过滤ST/退市风险名称、数据不足和流动性明显不足标的；公司财务和监管风险仍需以最新公告复核。", "body"),
        Spacer(1, 3 * mm),
        paragraph(source_links, "small"),
        Spacer(1, 5 * mm),
        paragraph("免责声明", "h2"),
        paragraph(escape(str(payload.get("disclaimer", ""))) + " 技术评分不等于基本面质量，超卖不等于见底；请依据自身风险承受能力独立决策。", "body"),
    ]

    doc.build(story)
    return output_path


def build_email_summary(payload: Mapping[str, Any]) -> str:
    candidates: Sequence[Mapping[str, Any]] = payload.get("candidates", [])
    lines = [
        f'# A股每日策略报告 - {payload["report_date"]}',
        "",
        f'行情截止日：{payload["effective_date"]}（最新已完成交易日）。',
        f'有效扫描：{payload.get("scan_count", 0)} 只；候选：{len(candidates)} 只。',
        "",
        "## 前三候选",
        "",
    ]
    for index, stock in enumerate(candidates[:3], start=1):
        plan = stock["plan"]
        lines.append(
            f'{index}. {stock["name"]}({stock["code"]})：收盘 {float(stock["close"]):.2f}，'
            f'分批观察 {_fmt_range(plan["buy_low"], plan["buy_high"])}，'
            f'失效位 {float(plan["stop"]):.2f}。'
        )
    lines += [
        "",
        "若开盘跳空超出计划区间，不建议追高，应等待价格和量能重新确认。",
        "",
        "完整行业分析、买入/止盈区间、失效位与风险说明请见PDF附件。",
        "",
        "仅供研究参考，不构成个性化投资建议或收益承诺。",
    ]
    return "\n".join(lines)
