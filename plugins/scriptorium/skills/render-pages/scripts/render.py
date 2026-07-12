#!/usr/bin/env python3
"""Render pages to PNG. PDF pages rasterize directly; other formats that
have no native page-image representation (pptx) are first converted to PDF
via LibreOffice, then rasterized the same way. See SKILL.md."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import paths  # noqa: E402

import fitz  # PyMuPDF


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    if not spec:
        return list(range(1, page_count + 1))
    return [int(p) for p in spec.split(",") if p.strip()]


def convert_pptx_to_pdf(pptx_path: Path, doc: str) -> Path:
    """Slide-for-slide PDF via LibreOffice headless, cached so a retry
    doesn't re-convert. soffice names its output <stem>.pdf, and doc names
    already match the input file's stem, so the output lands at
    work/<doc>/<doc>.pdf."""
    work_dir = paths.work_dir(doc)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = work_dir / f"{doc}.pdf"
    if out_pdf.exists() and out_pdf.stat().st_mtime >= pptx_path.stat().st_mtime:
        return out_pdf

    result = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(pptx_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not out_pdf.exists():
        print(f"error: soffice pptx->pdf conversion failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return out_pdf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default=None, help="comma-separated 1-indexed page numbers, default all")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--force", action="store_true", help="re-render even if the PNG already exists")
    args = parser.parse_args()

    input_path = paths.input_file(args.doc)
    if input_path is None:
        print(f"error: no input file found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)

    input_format = paths.detect_input_format(args.doc)
    if input_format == "pdf":
        pdf_path = input_path
    elif input_format == "pptx":
        pdf_path = convert_pptx_to_pdf(input_path, args.doc)
    else:
        print(f"error: render-pages has no rasterization path for format {input_format!r}", file=sys.stderr)
        sys.exit(1)

    document = fitz.open(pdf_path)
    page_numbers = parse_pages(args.pages, document.page_count)

    out_dir = paths.pages_dir(args.doc)
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered = []
    for n in page_numbers:
        out_path = paths.page_png(args.doc, n)
        if out_path.exists() and not args.force:
            rendered.append(str(out_path))
            continue
        page = document[n - 1]
        zoom = args.dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(out_path)
        rendered.append(str(out_path))
    document.close()

    for path in rendered:
        print(path)


if __name__ == "__main__":
    main()
