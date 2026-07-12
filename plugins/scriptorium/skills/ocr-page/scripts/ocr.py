#!/usr/bin/env python3
"""OCR rendered page PNGs with a pluggable local backend. See SKILL.md."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402
import tesseract as tesseract_lib  # noqa: E402

from PIL import Image
import pytesseract

_found = tesseract_lib.find_tesseract()
if _found:
    pytesseract.pytesseract.tesseract_cmd = _found


def ocr_tesseract(image_path: Path, lang: str, tessdata_dir: str | None = None) -> tuple[list[dict], float]:
    image = Image.open(image_path)
    config = f'--tessdata-dir "{tessdata_dir}"' if tessdata_dir else ""
    data = pytesseract.image_to_data(image, lang=lang, config=config, output_type=pytesseract.Output.DICT)

    paragraphs: dict[tuple[int, int, int], list[str]] = {}
    confidences = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = int(data["conf"][i]) if str(data["conf"][i]).lstrip("-").isdigit() else -1
        if conf >= 0:
            confidences.append(conf)
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        paragraphs.setdefault(key, []).append(word)

    page_elements = [
        {"type": "paragraph", "text": " ".join(words)}
        for words in paragraphs.values()
        if words
    ]
    avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return page_elements, round(avg_conf, 3)


BACKENDS = {"tesseract": ocr_tesseract}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers")
    parser.add_argument("--backend", default="tesseract", choices=list(BACKENDS))
    parser.add_argument("--lang", default="eng", help='tesseract language code(s), "+"-joined for multiple (e.g. "eng+deu")')
    parser.add_argument("--tessdata-dir", default=None, help="override tessdata directory (e.g. a user-writable fallback ensure_language.py downloaded packs into)")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    backend_fn = BACKENDS[args.backend]

    for page_number in page_numbers:
        image_path = paths.page_png(args.doc, page_number)
        if not image_path.exists():
            print(f"error: {image_path} not found — run render-pages first", file=sys.stderr)
            sys.exit(1)
        page_elements, confidence = backend_fn(image_path, args.lang, args.tessdata_dir)
        shard_path = paths.shard_path(args.doc, page_number, "ocr")
        elements_lib.write_shard(shard_path, page_number, page_elements, ocr_confidence=confidence)
        print(f"page {page_number}: confidence={confidence} elements={len(page_elements)}")


if __name__ == "__main__":
    main()
