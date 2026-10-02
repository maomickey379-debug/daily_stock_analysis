#!/usr/bin/env python3
"""Render and validate every page of a generated PDF report."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐页渲染并验收 PDF")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--render-dir", required=True, type=Path)
    parser.add_argument("--min-pages", type=int, default=4)
    return parser.parse_args()


def verify_pdf(pdf_path: Path, render_dir: Path, *, min_pages: int = 4) -> list[Path]:
    if not pdf_path.is_file() or pdf_path.stat().st_size < 10_000:
        raise ValueError("PDF 不存在或文件过小")
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) < min_pages:
        raise ValueError(f"PDF 页数不足: {len(reader.pages)} < {min_pages}")
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    for marker in ("A股", "买入区间", "失效", "免责声明"):
        if marker not in extracted:
            raise ValueError(f"PDF 缺少关键内容: {marker}")

    renderer = shutil.which("pdftoppm")
    if not renderer:
        raise RuntimeError("未找到 pdftoppm，无法逐页渲染验收")
    render_dir.mkdir(parents=True, exist_ok=True)
    prefix = render_dir / "page"
    subprocess.run(
        [renderer, "-png", "-r", "144", str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = sorted(render_dir.glob("page-*.png"))
    if len(pages) != len(reader.pages):
        raise ValueError("渲染页数与 PDF 页数不一致")

    for page_index, page in enumerate(pages, start=1):
        with Image.open(page).convert("RGB") as image:
            width, height = image.size
            if width < 900 or height < 1200:
                raise ValueError(f"{page.name} 渲染分辨率过低")
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            minimum_mean = 15 if page_index == 1 else 35
            if stat.mean[0] < minimum_mean:
                raise ValueError(f"{page.name} 整页过黑，可能存在黑块")
            histogram = gray.histogram()
            dark_ratio = sum(histogram[:12]) / (width * height)
            maximum_dark_ratio = 0.85 if page_index == 1 else 0.55
            if dark_ratio > maximum_dark_ratio:
                raise ValueError(f"{page.name} 深色像素比例异常")
            edge = max(3, min(width, height) // 250)
            edge_regions = (
                gray.crop((0, 0, width, edge)),
                gray.crop((0, height - edge, width, height)),
                gray.crop((0, 0, edge, height)),
                gray.crop((width - edge, 0, width, height)),
            )
            if page_index > 1 and any(
                ImageStat.Stat(region).mean[0] < 20 for region in edge_regions
            ):
                raise ValueError(f"{page.name} 页边缘疑似裁切或黑块")
    return pages


def main() -> int:
    args = parse_args()
    pages = verify_pdf(args.pdf, args.render_dir, min_pages=args.min_pages)
    print(f"PDF_OK={args.pdf.resolve()}")
    print(f"PAGE_COUNT={len(pages)}")
    print(f"RENDER_DIR={args.render_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
