#!/usr/bin/env python3
"""Extract each sheet's name, used-range table, and embedded images.
One sheet = one page. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402

import openpyxl


def sheet_table_rows(ws) -> list[list[str]]:
    """The full used-range bounding box, blank interior rows/cells included
    as "" rather than skipped — a spacer row inside a sheet's data is a
    real row, not something to silently drop. Keeping the full rectangle
    also means this always matches `ws.max_row - ws.min_row + 1` /
    `ws.max_column - ws.min_column + 1`, which text_mode_grade.py's
    table_corruption check for xlsx relies on."""
    return [["" if cell is None else str(cell) for cell in row] for row in ws.iter_rows(values_only=True)]


def extract_sheet(ws, page_number: int, assets_dir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (body_elements, image_elements) for one sheet."""
    body_elements = [{"type": "heading", "level": 1, "text": ws.title}]

    rows = sheet_table_rows(ws)
    if rows:
        body_elements.append({"type": "table", "rows": rows})

    image_elements = []
    for idx, im in enumerate(ws._images, start=1):
        ext = getattr(im, "format", None) or "png"
        out_name = f"page{page_number}_bitmap{idx}.{ext}"
        (assets_dir / out_name).write_bytes(im._data())
        image_elements.append({"type": "image", "kind": "bitmap", "asset": f"assets/{out_name}", "caption": ""})

    return body_elements, image_elements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed sheet numbers")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    xlsx_path = paths.input_file(args.doc)
    if xlsx_path is None or xlsx_path.suffix != ".xlsx":
        print(f"error: input/{args.doc}.xlsx not found", file=sys.stderr)
        sys.exit(1)

    workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    assets_dir = paths.assets_dir(args.doc)
    assets_dir.mkdir(parents=True, exist_ok=True)

    for page_number in page_numbers:
        sheet_name = workbook.sheetnames[page_number - 1]
        ws = workbook[sheet_name]
        body_elements, image_elements = extract_sheet(ws, page_number, assets_dir)

        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "text"), page_number, body_elements)
        elements_lib.write_shard(paths.shard_path(args.doc, page_number, "image"), page_number, image_elements)

    print(f"extracted xlsx sheets {page_numbers}")


if __name__ == "__main__":
    main()
