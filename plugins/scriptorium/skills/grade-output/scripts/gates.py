#!/usr/bin/env python3
"""Deterministic structural gates — the hard backpressure layer. See SKILL.md.

These checks never require judgment; anything that needs looking at pixels
belongs in rubric.md instead, applied by the calling agent.
"""

import argparse
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import figures as figures_lib  # noqa: E402
import furniture as furniture_lib  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

OCR_CONFIDENCE_FLOOR = 0.5
MIN_OUTPUT_BYTES = 20

# Task A5b: an excluded figure region (lib/figures.py's
# detect_figure_regions_with_exclusions, written into a PDF page's image
# shard as excluded_regions -- see lib/elements.py's merge_shards) is
# flagged here if it's more than this fraction of its page's area AND its
# reason isn't one of the expected/benign ones (a repeated page frame, the
# page's repeated drawings summary, or a stray sliver too small to matter).
# "frame_drawing"/"repeated_drawing"/"tiny"/"text_box" are excluded on
# purpose (a "repeated_drawing" summary's union bbox is often page-sized,
# because it spans the frame parts; a "text_box" keeps its text as body
# text, so nothing is lost); "furniture_band"/"table_overlap" are exactly the two
# rules the brief calls out as capable of excluding a genuinely large real
# figure, so those are the ones worth a human's attention.
LARGE_REGION_EXCLUDED_AREA_FRACTION = 0.2
# Follow-up R11: "grid_table" is a chart's grid read as a table; its cluster
# is the image, so nothing is lost.
LARGE_REGION_EXCLUDED_BENIGN_REASONS = {"frame_drawing", "repeated_drawing", "tiny", "text_box", "grid_table", "invisible_drawing"}

# Task A9: a `table` element whose bbox is within
# furniture_lib.FRAME_MATCH_TOLERANCE of a triage `frame_tables` entry is the
# page frame, not a real table. The furniture band is
# furniture_lib.in_furniture_band: triage.json records no band field, so
# every stage applies the same fixed rule from lib/furniture.py.

# Task A9: a TOC entry's heading may land one page away from the printed
# page number (a heading at the very top of a page, a page-number offset).
TOC_PAGE_TOLERANCE = 1

# Task A9 fix round 2: only pdf and image documents may use the
# no_visible_text flag (see lib/furniture.py).
NO_VISIBLE_TEXT_FORMATS = furniture_lib.NO_VISIBLE_TEXT_FORMATS


def check_page_count_match(doc_data: dict, true_page_count: int) -> dict:
    got = len(doc_data["pages"])
    passed = got == true_page_count
    return {
        "name": "page_count_match",
        "passed": passed,
        "detail": f"expected {true_page_count} pages, elements.json has {got}",
    }


def check_no_empty_pages(doc_data: dict) -> dict:
    # Follow-up R21: a page whose content was joined into another page's
    # element (a table cut by the page break) is listed in that element's
    # "pages", and is not empty.
    joined = {
        n
        for p in doc_data["pages"].values()
        for el in p["elements"]
        for n in el.get("pages", [])
    }
    empty = [
        p["page_number"]
        for p in doc_data["pages"].values()
        if not p["elements"] and p.get("skipped") != "toc" and p["page_number"] not in joined
    ]
    return {
        "name": "no_empty_pages",
        "passed": not empty,
        "detail": f"empty pages: {empty}" if empty else "every page has at least one element",
    }


def check_image_refs_resolve(doc_data: dict, output_dir: Path) -> dict:
    missing = []
    for page in doc_data["pages"].values():
        for el in page["elements"]:
            if el["type"] == "image":
                if not (output_dir / el["asset"]).exists():
                    missing.append(el["asset"])
    return {
        "name": "image_refs_resolve",
        "passed": not missing,
        "detail": f"missing assets: {missing}" if missing else "all image assets resolve",
    }


def check_ocr_confidence_floor(doc_data: dict) -> dict:
    low = [
        p["page_number"]
        for p in doc_data["pages"].values()
        if p["tier"] == "ocr" and p.get("ocr_confidence", 0) < OCR_CONFIDENCE_FLOOR
    ]
    return {
        "name": "ocr_confidence_floor",
        "passed": not low,
        "detail": f"pages below {OCR_CONFIDENCE_FLOOR} confidence: {low}" if low else "all OCR pages meet the confidence floor",
    }


def check_large_region_excluded(doc_data: dict, page_areas: dict[int, float]) -> list[dict]:
    """Task A5b: a WARNING (never a hard gate failure -- see main()) for
    every page whose image shard recorded an `excluded_regions` entry that
    is both large (more than LARGE_REGION_EXCLUDED_AREA_FRACTION of its
    page) and not one of the benign, expected reasons
    (LARGE_REGION_EXCLUDED_BENIGN_REASONS). `page_areas` maps page_number to
    that page's area in points^2 -- absent/0 for a page this gate can't
    evaluate (no PDF geometry available, e.g. a non-pdf input format), which
    is silently skipped rather than raising, since this check is PDF-vector-
    region-specific and every other input format never writes
    `excluded_regions` at all.

    Deliberately a warning, not a hard failure: the brief's point is
    visibility (the grader/human reviewer must be able to see that a large
    region was dropped and judge whether that was correct), not an
    automatic block -- a large excluded region is very often a correct
    exclusion (a genuinely oversized table, say), and gating hard on it
    would make every one of those a forced escalation for no reason."""
    warnings = []
    for page in doc_data["pages"].values():
        page_number = page.get("page_number")
        page_area = page_areas.get(page_number, 0)
        if not page_area:
            continue
        for region in page.get("excluded_regions", []):
            if region.get("reason") in LARGE_REGION_EXCLUDED_BENIGN_REASONS:
                continue
            bbox = region["bbox"]
            area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            fraction = area / page_area
            if fraction > LARGE_REGION_EXCLUDED_AREA_FRACTION:
                warnings.append({
                    "name": "large_region_excluded",
                    "page": page_number,
                    "bbox": bbox,
                    "reason": region.get("reason"),
                    "area_fraction": round(fraction, 3),
                    "detail": (
                        f"page {page_number}: a region covering {fraction:.0%} of the page "
                        f"was excluded (reason: {region.get('reason')}) -- verify this wasn't a real figure"
                    ),
                })
    return warnings


def _normalized(text: str) -> str:
    return " ".join((text or "").split())


def check_orphan_figure_caption(doc_data: dict) -> list[dict]:
    """Follow-up R1: a WARNING (never a hard gate failure, like
    check_large_region_excluded) for every `paragraph` whose text is a
    figure caption (`figures.is_figure_caption`: CAPTION_PATTERN in its
    "Figure n" / "Fig. n" form) when no `image` element on the same page
    or on the next page has that text as its `caption`.

    extract-images claims a caption line for the image it belongs to, and
    extract-text then leaves the line out of the body. A caption that is
    still a paragraph with no image claiming it means that its figure was
    probably lost: removed as furniture, kept as a text box, or never
    detected. The next page counts because a caption can sit at the top
    of the page after its figure, and an OCR or vision page can keep the
    caption as a paragraph next to its image.

    A warning, not a gate: the line can also be a list-of-figures entry or
    a body sentence that starts with "Figure 3 shows". The grader looks at
    the page and decides."""
    pages = doc_data.get("pages", {})
    claimed: dict[int, set[str]] = {}
    for page in pages.values():
        claimed[page.get("page_number")] = {
            _normalized(el["caption"])
            for el in page.get("elements", [])
            if el.get("type") == "image" and el.get("caption")
        }
    warnings = []
    for page in sorted(pages.values(), key=lambda p: p.get("page_number") or 0):
        page_number = page.get("page_number")
        for el in page.get("elements", []):
            if el.get("type") != "paragraph":
                continue
            caption = (el.get("text") or "").strip()
            if not figures_lib.is_figure_caption(caption):
                continue
            key = _normalized(caption)
            if key in claimed.get(page_number, set()) or key in claimed.get((page_number or 0) + 1, set()):
                continue
            warnings.append({
                "name": "orphan_figure_caption",
                "page": page_number,
                "caption": caption,
                "detail": (
                    f"page {page_number}: the figure caption {caption!r} is a paragraph, and no image "
                    f"on this page or the next has it as its caption -- verify the figure was not lost"
                ),
            })
    return warnings


def check_table_as_figure(doc_data: dict) -> list[dict]:
    """Re-review 2 I1: a WARNING (never a hard gate failure, like
    check_large_region_excluded) when a table may have become an image:

    - a `grid_table` excluded region whose `filled_cells` is above 0. Its
      table had text, so its cell structure is now only `figure_text`;
    - an `image` element whose `caption` is a "Table n" caption
      (`figures.CAPTION_PATTERN` in its "Table" form).

    `lib/figures.py`'s `is_grid_table` asks for a data series or almost no
    text, so either case can still be a correct chart. The grader looks at
    the page and decides."""
    warnings = []
    for page in sorted(doc_data.get("pages", {}).values(), key=lambda p: p.get("page_number") or 0):
        page_number = page.get("page_number")
        for region in page.get("excluded_regions", []):
            if region.get("reason") == "grid_table" and region.get("filled_cells", 0) > 0:
                warnings.append({
                    "name": "table_as_figure",
                    "page": page_number,
                    "bbox": region["bbox"],
                    "filled_cells": region["filled_cells"],
                    "detail": (
                        f"page {page_number}: a table with {region['filled_cells']} filled cells was read as "
                        f"a chart's grid and became part of an image -- verify it is not a real table"
                    ),
                })
        for el in page.get("elements", []):
            if el.get("type") != "image":
                continue
            caption = (el.get("caption") or "").strip()
            match = figures_lib.CAPTION_PATTERN.match(caption)
            if match and match.group(1).lower() == "table":
                warnings.append({
                    "name": "table_as_figure",
                    "page": page_number,
                    "caption": caption,
                    "detail": (
                        f"page {page_number}: an image has the table caption {caption!r} -- "
                        f"verify the table was not turned into an image"
                    ),
                })
    return warnings


def _output_line_candidates(line: str) -> list[str]:
    """The text pieces of one assembled-output line: the line with HTML tags
    removed, and each Markdown table cell, each with leading Markdown
    markers (#, -, *, >) stripped."""
    plain = re.sub(r"<[^>]+>", " ", line)
    pieces = [plain] + (plain.split("|") if "|" in plain else [])
    result = []
    for piece in pieces:
        cleaned = re.sub(r"^[\s#>*-]+", "", piece).strip()
        if cleaned:
            result.append(cleaned)
    return result


# Follow-up R14: a furniture pattern is flagged in the assembled output only
# when it is a whole line at least max(OUTPUT_REPEAT_MIN_COUNT,
# OUTPUT_REPEAT_MIN_FRACTION of the body pages) times.
OUTPUT_REPEAT_MIN_COUNT = 3
OUTPUT_REPEAT_MIN_FRACTION = 0.10


def output_repeat_threshold(doc_data: dict) -> int:
    """See OUTPUT_REPEAT_MIN_COUNT. Body pages are the pages not skipped as
    a printed TOC."""
    body = sum(1 for p in doc_data.get("pages", {}).values() if p.get("skipped") != "toc")
    return max(OUTPUT_REPEAT_MIN_COUNT, math.ceil(OUTPUT_REPEAT_MIN_FRACTION * body))


def check_furniture_absent(
    doc_data: dict, furniture: dict, output_dir: Path, page_heights: dict[int, float] | None = None,
    page_widths: dict[int, float] | None = None,
) -> dict:
    """Task A9: no page furniture (pdf-triage's `triage.json["furniture"]`)
    survived into the merged elements or the assembled output.

    - Text: no heading/paragraph/list_item text, table cell, image
      `figure_text` or `caption` has a line whose furniture key equals
      a `line_patterns` entry.
    - Tables: no `table` element's bbox matches a `frame_tables` entry.
    - Assembled output: no whole line of the .md/.html files under the
      doc's output dir (md, md-tree, okf, html) matches a `line_patterns`
      entry at least output_repeat_threshold() times in one output
      (follow-up R14: furniture is repetition, a single matching line is
      body text). These offenders have `page: None` -- an output file names
      no page.
    - Furniture images: NOT checked. No extractor records the source image
      xref on an image element, so gates.py cannot tell which asset came
      from a furniture xref. extract-images skips those xrefs itself.

    Which patterns may match an element is `furniture.patterns_for_element`
    (follow-up R14): an element with a bbox matches any pattern only when
    the bbox lies in a furniture band of its page (`page_heights`, from the
    PDF); an element without a bbox (or with no page height) matches only
    the letter-bearing patterns, anywhere. A digit-only pattern (e.g. "#",
    a footer that is only the page number) is never checked in the
    assembled output, where a bare number tells nothing.

    Passes trivially when the document has no furniture (no line patterns
    and no frame tables -- e.g. every non-PDF format, or no triage.json)."""
    all_patterns = {p["masked"] for p in furniture.get("line_patterns", [])}
    masked_patterns = {m for m in all_patterns if not furniture_lib.is_digit_only_pattern(m)}
    page_heights = page_heights or {}
    page_widths = page_widths or {}
    frame_bboxes = [f["bbox"] for f in furniture.get("frame_tables", [])]
    offenders = []

    def add(page, where, text):
        offenders.append({"page": page, "where": where, "text": text})

    if all_patterns or frame_bboxes:
        for page in doc_data["pages"].values():
            page_number = page.get("page_number")
            for el in page.get("elements", []):
                el_type = el.get("type")
                patterns = furniture_lib.patterns_for_element(
                    all_patterns, el.get("bbox"), page_heights.get(page_number),
                    furniture_lib.page_content_rect(
                        furniture, page_widths.get(page_number), page_heights.get(page_number)
                    ),
                )
                if el_type in ("heading", "paragraph", "list_item"):
                    for hit in furniture_lib.furniture_line_hits(el.get("text") or "", patterns):
                        add(page_number, el_type, hit)
                elif el_type == "table":
                    for row in el.get("rows", []):
                        for cell in row:
                            for hit in furniture_lib.furniture_line_hits(str(cell or ""), patterns):
                                add(page_number, "table cell", hit)
                    if any(furniture_lib.bbox_matches(el.get("bbox"), fb) for fb in frame_bboxes):
                        add(page_number, "frame table", f"table bbox {el.get('bbox')}")
                elif el_type == "image":
                    for field in ("figure_text", "caption"):
                        for hit in furniture_lib.furniture_line_hits(el.get(field) or "", patterns):
                            add(page_number, f"image {field}", hit)

    if masked_patterns and output_dir.exists():
        # Follow-up R14: furniture is repetition. A pattern is flagged in the
        # assembled output only when it is a whole line at least
        # output_repeat_threshold() times in one output (a single-file md or
        # html, or one split bundle).
        threshold = output_repeat_threshold(doc_data)
        hits: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for out_file in sorted(list(output_dir.rglob("*.md")) + list(output_dir.rglob("*.html"))):
            rel = out_file.relative_to(output_dir).as_posix()
            group = rel if out_file.parent == output_dir and out_file.stem == output_dir.name else "split"
            for line_number, line in enumerate(out_file.read_text(encoding="utf-8").splitlines(), start=1):
                candidates = _output_line_candidates(line)
                if not candidates:
                    continue
                key = furniture_lib.furniture_key(candidates[0])
                if key in masked_patterns:
                    hits.setdefault((group, key), []).append((f"{rel} line {line_number}", candidates[0]))
        for found in hits.values():
            if len(found) >= threshold:
                for where, text in found:
                    add(None, where, text)

    pages = sorted({o["page"] for o in offenders if o["page"] is not None})
    if not all_patterns and not frame_bboxes:
        detail = "no furniture detected for this document"
    elif offenders:
        detail = "furniture left in the output: " + "; ".join(
            f"{'page ' + str(o['page']) if o['page'] is not None else 'output'} ({o['where']}): {o['text']!r}"
            for o in offenders
        )
    else:
        detail = "no furniture line or frame table in the elements or the assembled output"
    return {"name": "furniture_absent", "passed": not offenders, "detail": detail, "pages": pages, "offenders": offenders}


def check_toc_headings_match(doc_data: dict, toc_entries: list[dict], unparsed: list[str] | None = None) -> dict:
    """Task A9: the TOC (`toc.json["entries"]`) and the body headings agree.

    Every TOC entry must appear as a `heading` element whose normalized
    text (lib/toc.py's `normalize_toc_text`, the same match extract-text
    uses) equals the entry's "<number> <title>" text, on a page within
    TOC_PAGE_TOLERANCE of the entry's `page`, at the entry's `level`
    (toc.json's dot-depth level, which is what extract-text assigns). One
    heading satisfies one entry only. Every heading that no entry uses is
    reported as `extra` -- extract-text's TOC-driven rule should make none.

    Fix wave I2: `unparsed` is toc.json's `unparsed` list -- dot-leader
    lines on a printed TOC page that gave no entry. Each one may be a lost
    entry whose heading then became a paragraph, which the comparison above
    cannot see. So the check fails while `unparsed` is not empty, and lists
    those lines.

    Passes trivially when toc.json has no entries and no unparsed lines (no
    TOC, or not a PDF): heading levels then come from extract-text's
    size-rank fallback, and there is nothing to compare against."""
    unparsed = list(unparsed or [])
    empty = {"missing": [], "page_mismatch": [], "level_mismatch": [], "extra": [], "unparsed": unparsed}
    if not toc_entries and not unparsed:
        return {"name": "toc_headings_match", "passed": True, "detail": "no TOC entries -- nothing to check", "pages": [], **empty}

    headings = []
    for page in doc_data["pages"].values():
        for el in page.get("elements", []):
            if el.get("type") == "heading":
                text = el.get("text") or ""
                headings.append({
                    "page": page.get("page_number"), "level": el.get("level"), "text": text,
                    "norm": toc_lib.normalize_toc_text(text), "used": False,
                })
    headings.sort(key=lambda h: h["page"] or 0)

    missing, page_mismatch, level_mismatch = [], [], []
    for entry in toc_entries:
        expected = toc_lib.normalize_toc_text(toc_lib.toc_entry_heading_text(entry))
        candidates = [h for h in headings if not h["used"] and h["norm"] == expected]
        if not candidates:
            missing.append({k: entry.get(k) for k in ("number", "title", "page", "level")})
            continue
        closest = min(candidates, key=lambda h: abs(h["page"] - entry["page"]))
        closest["used"] = True
        if abs(closest["page"] - entry["page"]) > TOC_PAGE_TOLERANCE:
            page_mismatch.append({"text": closest["text"], "toc_page": entry["page"], "heading_page": closest["page"]})
        elif closest["level"] != entry["level"]:
            level_mismatch.append({"text": closest["text"], "page": closest["page"], "toc_level": entry["level"], "heading_level": closest["level"]})

    extra = [{"text": h["text"], "page": h["page"], "level": h["level"]} for h in headings if not h["used"]]

    pages = {m["page"] for m in missing} | {m["page"] for m in level_mismatch} | {m["page"] for m in extra}
    for m in page_mismatch:
        pages |= {m["toc_page"], m["heading_page"]}

    problems = []
    if missing:
        problems.append("missing: " + ", ".join(f"{toc_lib.toc_entry_heading_text(m)!r} (page {m['page']})" for m in missing))
    if page_mismatch:
        problems.append("page off by more than 1: " + ", ".join(f"{m['text']!r} (TOC page {m['toc_page']}, heading page {m['heading_page']})" for m in page_mismatch))
    if level_mismatch:
        problems.append("level mismatch: " + ", ".join(f"{m['text']!r} (TOC level {m['toc_level']}, heading level {m['heading_level']})" for m in level_mismatch))
    if extra:
        problems.append("not in the TOC: " + ", ".join(f"{m['text']!r} (page {m['page']})" for m in extra))
    if unparsed:
        problems.append("TOC lines not parsed into an entry: " + ", ".join(repr(line) for line in unparsed))
    detail = "; ".join(problems) if problems else f"all {len(toc_entries)} TOC entries match a heading"
    return {
        "name": "toc_headings_match", "passed": not problems, "detail": detail, "pages": sorted(pages),
        "missing": missing, "page_mismatch": page_mismatch, "level_mismatch": level_mismatch, "extra": extra,
        "unparsed": unparsed,
    }


def check_figures_complete(doc_data: dict, input_format: str | None = None) -> dict:
    """Task A9: every `image` element has a non-empty `caption` or a
    non-empty `figure_text`, AND a non-empty `description`.

    Fix round 1: an image with no printed caption and no visible text passes
    the first half only with the recorded flag `no_visible_text: true`
    (describe_image.py --no-visible-text, set by the agent after it checked
    the render). The agent never writes a caption for such an image --
    `caption` is only the printed caption the script extracts.

    Fix round 2: the flag counts only when `input_format` is in
    NO_VISIBLE_TEXT_FORMATS (pdf, image). For pptx/docx/xlsx/html, or an
    unknown format, the agent writes `--caption`, so the flag is ignored.

    Ordering: the extractor agent writes `description` (and, when the
    scripts found no caption and no figure_text, one of them) with
    describe_image.py in commands/extract.md step 2. merge.py, assemble.py
    and gates.py run after that, in step 3, so this check sees the agent's
    fields. If gates.py runs straight after the extract scripts, with no
    describe step, this check fails -- on purpose."""
    incomplete = []
    for page in sorted(doc_data["pages"].values(), key=lambda p: p.get("page_number") or 0):
        for el in page.get("elements", []):
            if el.get("type") != "image":
                continue
            missing = []
            has_text = (el.get("caption") or "").strip() or (el.get("figure_text") or "").strip()
            flag_counts = input_format in NO_VISIBLE_TEXT_FORMATS and el.get("no_visible_text") is True
            if not has_text and not flag_counts:
                missing.append("caption or figure_text")
            if not (el.get("description") or "").strip():
                missing.append("description")
            if missing:
                incomplete.append({"page": page.get("page_number"), "asset": el.get("asset"), "missing": missing})
    pages = sorted({i["page"] for i in incomplete})
    detail = (
        "incomplete images: " + "; ".join(f"page {i['page']} {i['asset']}: missing {', '.join(i['missing'])}" for i in incomplete)
        if incomplete else "every image has a caption, figure_text or no_visible_text, and a description"
    )
    return {"name": "figures_complete", "passed": not incomplete, "detail": detail, "pages": pages, "incomplete": incomplete}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pdf_page_areas(input_path: Path) -> dict[int, float]:
    """{page_number: width*height in points^2} for a PDF input -- the
    geometry check_large_region_excluded needs to turn an excluded region's
    bbox into a page-area fraction. gates.py otherwise never opens the
    source PDF (it works entirely from elements.json + the independent
    true_page_count oracle), so this import is local to keep that the
    common case."""
    import fitz  # PyMuPDF

    with fitz.open(input_path) as doc:
        return {i: page.rect.width * page.rect.height for i, page in enumerate(doc, start=1)}


def check_output_file_exists(doc: str, fmt: str) -> dict:
    if fmt == "okf":
        index = paths.okf_index(doc)
        sections = list(paths.output_dir(doc).glob("[0-9][0-9]-*.md"))
        if index.exists() and index.stat().st_size >= MIN_OUTPUT_BYTES and sections:
            return {"name": "output_file_exists", "passed": True, "detail": f"{index} + {len(sections)} section file(s)"}
        return {"name": "output_file_exists", "passed": False, "detail": "okf bundle incomplete: missing index.md or section files"}

    if fmt == "md-tree":
        # The folder glob does not match OKF's flat NN-slug.md files, so a
        # stale OKF bundle in the same output folder cannot satisfy it.
        out = paths.output_dir(doc)
        index = out / "index.md"
        split_files = sorted(out.glob("[0-9][0-9]-*/[0-9][0-9].[0-9][0-9]-*.md"))
        front = out / "00-front-matter.md"
        if index.exists() and index.stat().st_size >= MIN_OUTPUT_BYTES and (split_files or front.exists()):
            return {"name": "output_file_exists", "passed": True, "detail": f"{index} + {len(split_files)} split file(s)"}
        return {
            "name": "output_file_exists", "passed": False,
            "detail": "md-tree bundle incomplete: missing index.md or NN-slug/NN.MM-slug.md files",
        }

    if fmt == "reqif":
        candidate = paths.output_file(doc, "reqif")
        if not candidate.exists() or candidate.stat().st_size < MIN_OUTPUT_BYTES:
            return {"name": "output_file_exists", "passed": False, "detail": "no assembled reqif output found"}
        try:
            root_tag = ET.parse(candidate).getroot().tag
        except ET.ParseError as e:
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} is not well-formed XML: {e}"}
        if not root_tag.endswith("REQ-IF"):
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} root element is {root_tag!r}, expected REQ-IF"}
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists and is well-formed ReqIF XML"}

    if fmt == "reqifz":
        candidate = paths.output_file(doc, "reqifz")
        if not candidate.exists() or candidate.stat().st_size < MIN_OUTPUT_BYTES:
            return {"name": "output_file_exists", "passed": False, "detail": "no assembled reqifz output found"}
        if not zipfile.is_zipfile(candidate):
            return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} is not a valid zip archive"}
        expected = f"{doc}.reqif"
        with zipfile.ZipFile(candidate) as zf:
            if expected not in zf.namelist():
                return {"name": "output_file_exists", "passed": False, "detail": f"{candidate} missing {expected}"}
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists and contains {expected}"}

    candidate = paths.output_file(doc, fmt)
    if candidate.exists() and candidate.stat().st_size >= MIN_OUTPUT_BYTES:
        return {"name": "output_file_exists", "passed": True, "detail": f"{candidate} exists ({candidate.stat().st_size} bytes)"}
    return {"name": "output_file_exists", "passed": False, "detail": f"no assembled {fmt} output found"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--format", choices=["md", "html", "okf", "md-tree", "reqif", "reqifz"], default="md")
    args = parser.parse_args()

    input_path = paths.input_file(args.doc)
    if input_path is None:
        print(f"error: no input file found for doc '{args.doc}' in input/", file=sys.stderr)
        sys.exit(1)
    input_format = paths.detect_input_format(args.doc)
    true_page_count = paths.true_page_count(args.doc, input_format)

    elements_path = paths.elements_json(args.doc)
    if not elements_path.exists():
        print(f"error: {elements_path} not found — run extraction first", file=sys.stderr)
        sys.exit(1)
    doc_data = elements_lib.load_doc(elements_path)
    page_sizes = furniture_lib.pdf_page_sizes(input_path) if input_format == "pdf" else {}

    checks = [
        check_page_count_match(doc_data, true_page_count),
        check_no_empty_pages(doc_data),
        check_image_refs_resolve(doc_data, paths.output_dir(args.doc)),
        check_ocr_confidence_floor(doc_data),
        check_output_file_exists(args.doc, args.format),
        # Task A9 structure checks. No triage.json / toc.json (non-PDF
        # formats never write toc.json) means no furniture / no TOC: pass.
        check_furniture_absent(
            doc_data,
            _load_json(paths.triage_json(args.doc)).get("furniture") or furniture_lib.empty_furniture(),
            paths.output_dir(args.doc),
            {n: s[1] for n, s in page_sizes.items()},
            {n: s[0] for n, s in page_sizes.items()},
        ),
        check_toc_headings_match(
            doc_data,
            _load_json(paths.toc_json(args.doc)).get("entries") or [],
            _load_json(paths.toc_json(args.doc)).get("unparsed") or [],
        ),
        check_figures_complete(doc_data, input_format),
    ]

    # Task A5b: large_region_excluded is a WARNING, not one of the checks
    # above -- it never affects `passed`. See check_large_region_excluded's
    # docstring for why. Follow-up R1: orphan_figure_caption is a warning
    # for the same reason, and so is re-review 2's table_as_figure.
    page_areas = _pdf_page_areas(input_path) if input_format == "pdf" else {}
    warnings = (
        check_large_region_excluded(doc_data, page_areas)
        + check_orphan_figure_caption(doc_data)
        + check_table_as_figure(doc_data)
    )

    result = {"doc": args.doc, "passed": all(c["passed"] for c in checks), "checks": checks, "warnings": warnings}

    out_path = paths.gates_report_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
