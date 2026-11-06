"""Pre-analysis of a PDF, before any extraction: which detection scopes
will find something in it, and which known quirks it has, each with the
measure the pipeline applies. Written to triage.json["pre_analysis"] by
triage.py. See README.md.

A quirk is only listed here once a measure exists for it; a new kind of
problem found on a real document (a `findings.py` folder) gets a detector
here and a measure in the script that handles it.
"""

import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import figures as figures_lib  # noqa: E402
import furniture as furniture_lib  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "extract_text_for_triage",
    Path(__file__).resolve().parents[2]
    / "extract-text"
    / "scripts"
    / "extract_text.py",
)
extract_text = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_text)

# Common function words per tesseract language; a word two languages share
# ("de", "la") is dropped below, so a hit names one language.
_STOPWORDS = {
    "deu": "und der die das nicht mit für auf ist wird sie den von zu ein eine dem des bei oder auch",
    "eng": "the and of to is for with that this are on be from by it as an or not",
    "fra": "le les et des est pour dans une que sur avec pas du au ce qui sont",
    "spa": "el los las y que en para con una por es del se al lo como",
    "ita": "il che di e per con una non sono della gli nel alla dei",
    "nld": "het een en van is dat met voor niet op zijn ook aan bij of",
}
_counts = Counter(w for words in _STOPWORDS.values() for w in words.split())
STOPWORDS = {
    lang: {w for w in words.split() if _counts[w] == 1}
    for lang, words in _STOPWORDS.items()
}
# A language counts when it has this share of all stopword hits, and enough
# hits to be more than a quoted name or a stray English word.
LANGUAGE_MIN_SHARE = 0.15
LANGUAGE_MIN_HITS = 20

MEASURES = {
    "layout_table": "read as body text (headings, paragraphs in reading order), not as a table: extract-text",
    "heading_in_block": "the accent-coloured heading line is split off as its own heading: extract-text",
    "side_margin_text": "removed as page furniture: extract-text, merge",
    "garbled_text_layer": "extracted by OCR instead of the text layer: triage tier",
    "text_language": "OCR language for scanned pages and bitmap labels: ensure_language.py --extra",
}


def text_languages(document) -> list[str]:
    """Tesseract codes of the languages the text layer is written in."""
    hits = Counter()
    for page in document:
        for word in re.findall(r"[^\W\d_]+", page.get_text().lower()):
            for lang, words in STOPWORDS.items():
                if word in words:
                    hits[lang] += 1
    total = sum(hits.values())
    return sorted(
        lang
        for lang, n in hits.items()
        if n >= LANGUAGE_MIN_HITS and n / total >= LANGUAGE_MIN_SHARE
    )


def _has_heading_in_block(page, body_size: float) -> bool:
    blocks, _ = extract_text.extract_page_text_blocks(page, body_size)
    return any(
        len(b["lines"]) > 1
        and b["lines"][0].get("accent")
        and not any(ln.get("accent") for ln in b["lines"][1:])
        for b in blocks
    )


def _has_side_margin_text(page) -> bool:
    return any(
        furniture_lib.is_side_margin_line(line["dir"], line["bbox"], page.rect.width)
        for block in page.get_text("dict")["blocks"]
        if block["type"] == 0
        for line in block["lines"]
    )


def analyze(
    document,
    pdf_path: Path,
    pages: list[dict],
    furniture: dict,
    toc_entries: list,
    body_size: float,
) -> dict:
    """{"scopes": what the detectors will find, "quirks": [{name, pages, measure}]}."""
    text_pages = [
        p["page_number"]
        for p in pages
        if p["tier"] == "text" and p.get("role") != "toc"
    ]
    found: dict[str, list[int]] = {name: [] for name in MEASURES}
    data_table_pages = []
    for n in text_pages:
        page = document[n - 1]
        rect = furniture_lib.page_content_rect(
            furniture, page.rect.width, page.rect.height
        )
        tables = figures_lib.page_tables(
            pdf_path,
            n,
            furniture.get("frame_tables", []),
            rect,
            exclude_regions=figures_lib.bitmap_panels(page),
        )
        if any(figures_lib.is_layout_table(t) for t in tables):
            found["layout_table"].append(n)
        if any(
            not figures_lib.is_layout_table(t) and t["filled_cells"] for t in tables
        ):
            data_table_pages.append(n)
        if _has_heading_in_block(page, body_size):
            found["heading_in_block"].append(n)
        if _has_side_margin_text(page):
            found["side_margin_text"].append(n)
    furniture_xrefs = set(furniture.get("image_xrefs", []))
    bitmap_pages = [
        n for n in range(1, document.page_count + 1)
        if any(img[0] not in furniture_xrefs for img in document[n - 1].get_images(full=True))
    ]
    found["garbled_text_layer"] = [
        p["page_number"] for p in pages if "garbled" in p.get("reason", "")
    ]
    languages = text_languages(document)
    quirks = [
        {"name": name, "pages": found[name], "measure": MEASURES[name]}
        for name in MEASURES
        if found[name]
    ]
    if languages and languages != ["eng"]:
        quirks.append(
            {
                "name": "text_language",
                "languages": languages,
                "measure": MEASURES["text_language"],
            }
        )
    return {
        "scopes": {
            "scanned_pages": [p["page_number"] for p in pages if p["tier"] != "text"],
            "bitmap_pages": bitmap_pages,
            "data_table_pages": data_table_pages,
            "furniture": bool(
                furniture.get("line_patterns")
                or furniture.get("frame_tables")
                or furniture.get("frame_drawings")
            ),
            "toc_entries": len(toc_entries),
            "text_languages": languages,
        },
        "quirks": quirks,
    }
