#!/usr/bin/env python3
"""Deterministic structural gates — the hard backpressure layer. See SKILL.md.

These checks never require judgment; anything that needs looking at pixels
belongs in rubric.md instead, applied by the calling agent.
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

OCR_CONFIDENCE_FLOOR = 0.5
MIN_OUTPUT_BYTES = 20

# Task A5b: an excluded figure region (lib/figures.py's
# detect_figure_regions_with_exclusions, written into a PDF page's image
# shard as excluded_regions -- see lib/elements.py's merge_shards) is
# flagged here if it's more than this fraction of its page's area AND its
# reason isn't one of the two that are expected/benign (a repeated page
# frame, or a stray sliver too small to matter). "frame_drawing"/"tiny" are
# excluded on purpose; "furniture_band"/"table_overlap" are exactly the two
# rules the brief calls out as capable of excluding a genuinely large real
# figure, so those are the ones worth a human's attention.
LARGE_REGION_EXCLUDED_AREA_FRACTION = 0.2
LARGE_REGION_EXCLUDED_BENIGN_REASONS = {"frame_drawing", "tiny"}

# Task A9: a `table` element whose bbox is within this many points of a
# triage `frame_tables` entry is the page frame, not a real table. Same
# matching tolerance extract_text.py uses when it drops frame tables.
FRAME_TABLE_BBOX_TOLERANCE = 3.0

# Task A9 fix round 1: the top/bottom fraction of the page that counts as
# a furniture band -- the same value and rule as pdf-triage's and
# extract_text.py's FURNITURE_EDGE_BAND / in_furniture_band. triage.json
# records no band field, so this copy applies the same rule.
FURNITURE_EDGE_BAND = 0.12

# Task A9: a TOC entry's heading may land one page away from the printed
# page number (a heading at the very top of a page, a page-number offset).
TOC_PAGE_TOLERANCE = 1

EMPTY_FURNITURE = {"line_patterns": [], "frame_tables": [], "frame_drawings": [], "image_xrefs": []}


def check_page_count_match(doc_data: dict, true_page_count: int) -> dict:
    got = len(doc_data["pages"])
    passed = got == true_page_count
    return {
        "name": "page_count_match",
        "passed": passed,
        "detail": f"expected {true_page_count} pages, elements.json has {got}",
    }


def check_no_empty_pages(doc_data: dict) -> dict:
    empty = [
        p["page_number"]
        for p in doc_data["pages"].values()
        if not p["elements"] and p.get("skipped") != "toc"
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


def _mask_digits(text: str) -> str:
    """The same digit mask pdf-triage uses for `line_patterns` (every run of
    digits becomes one "#")."""
    return re.sub(r"\d+", "#", text)


def _furniture_hits(text: str, masked_patterns: set[str]) -> list[str]:
    """Every line of `text` (and the whole text) whose stripped,
    digit-masked form equals a furniture pattern."""
    hits = []
    for candidate in [text] + text.splitlines():
        stripped = candidate.strip()
        if stripped and _mask_digits(stripped) in masked_patterns and stripped not in hits:
            hits.append(stripped)
    return hits


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


def _is_digit_only_pattern(masked: str) -> bool:
    """A masked furniture pattern with no letters, e.g. "#" or "# / #" (a
    footer that is only the page number)."""
    return not re.search(r"[^\W\d_]", masked)


def _in_furniture_band(bbox, page_height: float | None) -> bool:
    """Same rule as extract_text.py's in_furniture_band: the bbox lies in
    the top or bottom FURNITURE_EDGE_BAND of the page. False when the bbox
    or the page height is unknown."""
    if not page_height or not bbox or len(bbox) != 4:
        return False
    top_frac, bottom_frac = bbox[1] / page_height, bbox[3] / page_height
    return bottom_frac <= FURNITURE_EDGE_BAND or top_frac >= 1 - FURNITURE_EDGE_BAND


def _bbox_matches(a: list[float], b: list[float], tolerance: float) -> bool:
    return len(a) == 4 and len(b) == 4 and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def check_furniture_absent(doc_data: dict, furniture: dict, output_dir: Path, page_heights: dict[int, float] | None = None) -> dict:
    """Task A9: no page furniture (pdf-triage's `triage.json["furniture"]`)
    survived into the merged elements or the assembled output.

    - Text: no heading/paragraph/list_item text, table cell, image
      `figure_text` or `caption` has a line whose digit-masked text equals
      a `line_patterns` entry.
    - Tables: no `table` element's bbox matches a `frame_tables` entry.
    - Assembled output: no line of any .md/.html file under the doc's
      output dir (md, md-tree, okf, html) matches a `line_patterns` entry.
      These offenders have `page: None` -- an output file names no page.
    - Furniture images: NOT checked. No extractor records the source image
      xref on an image element, so gates.py cannot tell which asset came
      from a furniture xref. extract-images skips those xrefs itself.

    Digit-only patterns (fix round 1): a pattern with no letters, e.g.
    "#" for a footer that is only the page number, also matches any bare
    number in the body (a table cell "3", a quantity). So a digit-only
    pattern matches an element only when the element's bbox lies in a
    furniture band of its page (`page_heights`, from the PDF), and it is
    never checked in the assembled output, where a bare number tells
    nothing. With no page height (non-PDF input) it never matches.

    Passes trivially when the document has no furniture (no line patterns
    and no frame tables -- e.g. every non-PDF format, or no triage.json)."""
    all_patterns = {p["masked"] for p in furniture.get("line_patterns", [])}
    masked_patterns = {m for m in all_patterns if not _is_digit_only_pattern(m)}
    digit_only_patterns = all_patterns - masked_patterns
    page_heights = page_heights or {}
    frame_bboxes = [f["bbox"] for f in furniture.get("frame_tables", [])]
    offenders = []

    def add(page, where, text):
        offenders.append({"page": page, "where": where, "text": text})

    if all_patterns or frame_bboxes:
        for page in doc_data["pages"].values():
            page_number = page.get("page_number")
            for el in page.get("elements", []):
                el_type = el.get("type")
                patterns = masked_patterns
                if digit_only_patterns and _in_furniture_band(el.get("bbox"), page_heights.get(page_number)):
                    patterns = all_patterns
                if el_type in ("heading", "paragraph", "list_item"):
                    for hit in _furniture_hits(el.get("text") or "", patterns):
                        add(page_number, el_type, hit)
                elif el_type == "table":
                    for row in el.get("rows", []):
                        for cell in row:
                            for hit in _furniture_hits(str(cell or ""), patterns):
                                add(page_number, "table cell", hit)
                    if any(_bbox_matches(list(el.get("bbox") or []), fb, FRAME_TABLE_BBOX_TOLERANCE) for fb in frame_bboxes):
                        add(page_number, "frame table", f"table bbox {el.get('bbox')}")
                elif el_type == "image":
                    for field in ("figure_text", "caption"):
                        for hit in _furniture_hits(el.get(field) or "", patterns):
                            add(page_number, f"image {field}", hit)

    if masked_patterns and output_dir.exists():
        for out_file in sorted(list(output_dir.rglob("*.md")) + list(output_dir.rglob("*.html"))):
            rel = out_file.relative_to(output_dir).as_posix()
            for line_number, line in enumerate(out_file.read_text(encoding="utf-8").splitlines(), start=1):
                for candidate in _output_line_candidates(line):
                    if _mask_digits(candidate) in masked_patterns:
                        add(None, f"{rel} line {line_number}", candidate)
                        break

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


def check_toc_headings_match(doc_data: dict, toc_entries: list[dict]) -> dict:
    """Task A9: the TOC (`toc.json["entries"]`) and the body headings agree.

    Every TOC entry must appear as a `heading` element whose normalized
    text (lib/toc.py's `normalize_toc_text`, the same match extract-text
    uses) equals the entry's "<number> <title>" text, on a page within
    TOC_PAGE_TOLERANCE of the entry's `page`, at the entry's `level`
    (toc.json's dot-depth level, which is what extract-text assigns). One
    heading satisfies one entry only. Every heading that no entry uses is
    reported as `extra` -- extract-text's TOC-driven rule should make none.

    Passes trivially when toc.json has no entries (no TOC, or not a PDF):
    heading levels then come from extract-text's size-rank fallback, and
    there is nothing to compare against."""
    empty = {"missing": [], "page_mismatch": [], "level_mismatch": [], "extra": []}
    if not toc_entries:
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
    detail = "; ".join(problems) if problems else f"all {len(toc_entries)} TOC entries match a heading"
    return {
        "name": "toc_headings_match", "passed": not problems, "detail": detail, "pages": sorted(pages),
        "missing": missing, "page_mismatch": page_mismatch, "level_mismatch": level_mismatch, "extra": extra,
    }


def check_figures_complete(doc_data: dict) -> dict:
    """Task A9: every `image` element has a non-empty `caption` or a
    non-empty `figure_text`, AND a non-empty `description`.

    Fix round 1: an image with no printed caption and no visible text passes
    the first half only with the recorded flag `no_visible_text: true`
    (describe_image.py --no-visible-text, set by the agent after it checked
    the render). The agent never writes a caption for such an image --
    `caption` is only the printed caption the script extracts.

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
            if not has_text and el.get("no_visible_text") is not True:
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
    return json.loads(path.read_text()) if path.exists() else {}


def _pdf_page_heights(input_path: Path) -> dict[int, float]:
    """{page_number: height in points} for a PDF input -- the geometry
    check_furniture_absent needs for its furniture-band rule."""
    import fitz  # PyMuPDF

    with fitz.open(input_path) as doc:
        return {i: page.rect.height for i, page in enumerate(doc, start=1)}


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
    parser.add_argument("--format", choices=["md", "html", "okf", "reqif", "reqifz"], default="md")
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
            _load_json(paths.triage_json(args.doc)).get("furniture") or EMPTY_FURNITURE,
            paths.output_dir(args.doc),
            _pdf_page_heights(input_path) if input_format == "pdf" else {},
        ),
        check_toc_headings_match(doc_data, _load_json(paths.toc_json(args.doc)).get("entries") or []),
        check_figures_complete(doc_data),
    ]

    # Task A5b: large_region_excluded is a WARNING, not one of the checks
    # above -- it never affects `passed`. See check_large_region_excluded's
    # docstring for why.
    page_areas = _pdf_page_areas(input_path) if input_format == "pdf" else {}
    warnings = check_large_region_excluded(doc_data, page_areas)

    result = {"doc": args.doc, "passed": all(c["passed"] for c in checks), "checks": checks, "warnings": warnings}

    out_path = paths.gates_report_json(args.doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
