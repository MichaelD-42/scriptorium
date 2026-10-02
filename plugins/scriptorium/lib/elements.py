"""Read/write helpers for the per-document extraction data.

Extraction is sharded, one file per page per extractor, so that parallel
subagents never read-modify-write the same file (that was the v1 design and
it races under concurrency — see git history). Each extractor writes its own
shard once and never touches another page's or another tier's shard:

    work/<doc>/shards/page{N}.{text|ocr|vision}.json   body shard (one tier wins)
    work/<doc>/shards/page{N}.image.json                image shard (independent)

merge_shards() combines them into the same page shape v1 used, so
assemble.py and gates.py don't need to know sharding exists. merge.py (in
assemble-output) builds the final on-disk elements.json around it, adding
`furniture_text` (Task A2) -- pdf-triage's verbatim repeated header/footer
text (see skills/pdf-triage), `None` for non-PDF inputs or when no
furniture was detected:

{
  "doc": "sample",
  "source_file": "input/sample.pdf",
  "page_count": 5,
  "furniture_text": "Doc No. SYN-FUR-0001\nRev. B\npage 1 (9)",
  "pages": [ {"page_number": 1, "tier": "text", "elements": [...]}, ... ]
}

Every element additionally carries a "bbox": [x0, y0, x1, y1] field
(fitz/pdfplumber-style, top-left origin, y increasing downward) -- written
by extract_text.py/extract_images.py, passed through unchanged here.
merge_shards() sorts a page's combined body+image elements by bbox y0
(Task A5), so an image element lands in true document reading position --
interleaved with the surrounding text -- rather than always trailing after
every text element regardless of where it actually sits on the page.

A shard may also carry extra top-level keys via write_shard()'s **extra
(e.g. "skipped": "toc", written by extract_text.py/extract_images.py for a
page pdf-triage marked role: "toc" -- Task A3; "excluded_regions", written
by extract_images.py -- Task A5b, see lib/figures.py's
detect_figure_regions_with_exclusions). merge_shards() folds any such extra
key from BOTH the winning body shard and the image shard into the merged
page dict alongside "elements" (body-shard keys win on a name collision,
though none exist today), so a downstream consumer like gates.py can see it.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import furniture as furniture_lib  # noqa: E402

BODY_KINDS_BY_PRIORITY = ("vision", "ocr", "text")  # highest tier first — wins at merge time

# Task A4b: page-break joins. A page's last body element with no terminal
# punctuation is assumed to continue onto the next page's first body
# element -- these are the characters that count as "ends the sentence".
JOIN_TERMINAL_PUNCTUATION = ".!?:;"
# Same ~3pt tolerance convention as extract_text.py's other geometry
# tolerances (FRAME_MATCH_TOLERANCE, LIST_MARKER_X_TOLERANCE, etc).
JOIN_X_TOLERANCE = 3.0  # pt

# Fix wave I5: the body tiers that do no furniture removal of their own.
# extract-text removes furniture lines while it extracts; OCR and a vision
# transcription see the whole page image, title block included.
UNFILTERED_BODY_TIERS = ("ocr", "vision")
FURNITURE_TEXT_TYPES = ("heading", "paragraph", "list_item")


def write_shard(shard_path: Path, page_number: int, elements: list, **extra) -> None:
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"page_number": page_number, "elements": elements, **extra}
    shard_path.write_text(json.dumps(payload, indent=2))


def read_shard(shard_path: Path) -> dict | None:
    if not shard_path.exists():
        return None
    return json.loads(shard_path.read_text())


def remove_furniture_lines(
    elements: list[dict], all_patterns: set[str], page_height: float | None
) -> tuple[list[dict], int]:
    """Fix wave I5: drop the furniture lines from an `ocr`/`vision` body,
    with lib/furniture.py's band plus pattern rule (the rule gates.py's
    `furniture_absent` checks). An element that is empty afterwards is
    dropped. Returns the kept elements and the number of removed lines."""
    kept, removed = [], 0
    for el in elements:
        if el.get("type") not in FURNITURE_TEXT_TYPES or not el.get("text"):
            kept.append(el)
            continue
        patterns = furniture_lib.patterns_for_element(all_patterns, el.get("bbox"), page_height)
        text, count = furniture_lib.strip_furniture_lines(el["text"], patterns)
        removed += count
        if count and not text:
            continue
        kept.append({**el, "text": text} if count else el)
    return kept, removed


def merge_shards(
    shards_dir: Path,
    page_count: int,
    furniture: dict | None = None,
    page_heights: dict[int, float] | None = None,
) -> dict[int, dict]:
    """Combine every page's shards into {page_number: page_dict}. A page
    with no body shard yet (extraction incomplete or still in flight) gets
    tier "text" with no elements — assemble/gates will flag it as empty
    rather than silently dropping it.

    `furniture` (triage.json["furniture"]) and `page_heights` (PDF page
    heights in points) are optional. With them, an `ocr`/`vision` body
    loses its furniture lines (`remove_furniture_lines`), and the page
    records `furniture_lines_removed` when that count is above zero."""
    all_patterns = {p["masked"] for p in (furniture or {}).get("line_patterns", [])}
    page_heights = page_heights or {}
    pages: dict[int, dict] = {}
    for n in range(1, page_count + 1):
        body_tier, body_shard = None, None
        for tier in BODY_KINDS_BY_PRIORITY:
            shard = read_shard(shards_dir / f"page{n}.{tier}.json")
            if shard:
                body_tier, body_shard = tier, shard
                break

        image_shard = read_shard(shards_dir / f"page{n}.image.json")
        image_elements = image_shard["elements"] if image_shard else []
        # Task A5b: an image shard's own extra keys (e.g. "excluded_regions")
        # must reach the merged page dict too, not just a body shard's -- see
        # module docstring.
        image_extra = (
            {k: v for k, v in image_shard.items() if k not in {"page_number", "elements"}}
            if image_shard else {}
        )

        if body_shard:
            body_extra = {k: v for k, v in body_shard.items() if k not in {"page_number", "elements"}}
            extra = {**image_extra, **body_extra}  # body shard wins on a name collision
            # Task A5: sort by bbox y0 so an image element interleaves with
            # surrounding text in true document reading order instead of
            # always trailing after every text element. Stable sort, and
            # bbox-less elements default to y0=0 -- so elements that predate
            # the additive bbox field (or a hand-built test fixture without
            # one) keep their original append order relative to each other.
            body_elements = body_shard["elements"]
            furniture_removed = 0
            if all_patterns and body_tier in UNFILTERED_BODY_TIERS:
                body_elements, furniture_removed = remove_furniture_lines(
                    body_elements, all_patterns, page_heights.get(n)
                )
            combined = body_elements + image_elements
            combined.sort(key=lambda e: e.get("bbox", [0, 0, 0, 0])[1])
            pages[n] = {
                "page_number": n,
                "tier": body_tier,
                "elements": combined,
                **extra,
            }
            if furniture_removed:
                pages[n]["furniture_lines_removed"] = furniture_removed
        else:
            pages[n] = {"page_number": n, "tier": "text", "elements": image_elements, **image_extra}

    apply_page_break_joins(pages)
    return pages


def _body_elements(page: dict) -> list[dict]:
    """The elements a page-break join considers -- every non-`image`
    element, in the page's own (already reading-order-sorted) order. A
    figure-region-excluded drawing (`excluded_regions`, Task A5b) never
    became an element in the first place, so "ignore ... anything in
    excluded_regions" needs no extra filtering here beyond dropping images
    -- there is nothing else to filter out."""
    return [el for el in page["elements"] if el["type"] != "image"]


def _ends_with_terminal_punctuation(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in JOIN_TERMINAL_PUNCTUATION


def apply_page_break_joins(pages: dict[int, dict]) -> None:
    """Task A4b, controller-ruled: page-break joins are detected HERE, at
    merge time (the step that already sees every page), not in the
    extractor -- extractors run as parallel per-page-batch subprocesses, so
    the extractor for page n+1 can't see page n's last element to know a
    join is even needed.

    For each page n (ascending) with a page n+1 also present: if page n's
    last body element (see `_body_elements`) is a `paragraph` or
    `list_item` whose text does NOT end with terminal punctuation
    (`JOIN_TERMINAL_PUNCTUATION`), and page n+1's first body element is a
    plain `paragraph` (not a heading, not a table, not a new list item —
    anything else is excluded by construction, since only `type ==
    "paragraph"` passes) starting within `JOIN_X_TOLERANCE` of the first
    element's left x, the two are joined into ONE element: the second
    element's text is appended to the first with a single space (no
    de-hyphenation, no other character changes — a verbatim concatenation),
    the first element gains `"pages": [n, n+1]` (additive; absent on every
    element this doesn't touch) and stays under page n, and the second
    element is removed from page n+1's own list.

    Never joins two tables (page n's last element being a `table` always
    fails the type check above) -- a table cut by a page break stays two
    tables, a known, documented, out-of-scope risk per the brief. Pairwise
    only, one pass, ascending page order -- a 3+ page chain (page n's
    element joins page n+1's, and the COMBINED text still lacks terminal
    punctuation, and page n+2's first element would also qualify) is not
    attempted; no fixture in this repo exercises more than a 2-page split,
    and the brief's own wording ("for each page n and n+1") is pairwise,
    not transitive.

    Fix wave I3: when the joining (page n) element is a `list_item`, the
    x-tolerance check uses its `text_x` (where its text starts, after the
    marker; written by `extract_text.py`'s `list_item_text_x`), because a
    continuation line is printed at the text indent, not at the marker.
    An element without `text_x` (a paragraph, or a list item from an older
    shard) uses `bbox[0]`, as before."""
    page_numbers = sorted(pages)
    for n in page_numbers:
        n_next = n + 1
        if n_next not in pages:
            continue
        prev_body = _body_elements(pages[n])
        next_body = _body_elements(pages[n_next])
        if not prev_body or not next_body:
            continue
        prev_el = prev_body[-1]
        next_el = next_body[0]

        if prev_el["type"] not in ("paragraph", "list_item"):
            continue
        if _ends_with_terminal_punctuation(prev_el["text"]):
            continue
        if next_el["type"] != "paragraph":
            continue
        if "bbox" not in prev_el or "bbox" not in next_el:
            continue  # defensive: real elements always carry bbox (Task A2); a hand-built fixture without one just never joins
        if abs(next_el["bbox"][0] - prev_el.get("text_x", prev_el["bbox"][0])) > JOIN_X_TOLERANCE:
            continue

        prev_el["text"] = prev_el["text"] + " " + next_el["text"]
        prev_el["pages"] = [n, n_next]
        prev_el["bbox"] = [
            min(prev_el["bbox"][0], next_el["bbox"][0]),
            min(prev_el["bbox"][1], next_el["bbox"][1]),
            max(prev_el["bbox"][2], next_el["bbox"][2]),
            max(prev_el["bbox"][3], next_el["bbox"][3]),
        ]
        pages[n_next]["elements"] = [el for el in pages[n_next]["elements"] if el is not next_el]


def load_doc(elements_path: Path) -> dict:
    """Read the merged elements.json (merge_shards()' output, written by
    merge.py). Returns pages as a dict keyed by page_number for convenience."""
    if elements_path.exists():
        data = json.loads(elements_path.read_text())
        data["pages"] = {p["page_number"]: p for p in data.get("pages", [])}
        return data
    return {"doc": None, "source_file": None, "page_count": 0, "pages": {}}


def save_doc(elements_path: Path, doc: dict) -> None:
    elements_path.parent.mkdir(parents=True, exist_ok=True)
    pages_sorted = sorted(doc["pages"].values(), key=lambda p: p["page_number"])
    payload = {**doc, "pages": pages_sorted}
    elements_path.write_text(json.dumps(payload, indent=2))
