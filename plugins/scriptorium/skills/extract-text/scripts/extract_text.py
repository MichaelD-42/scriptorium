#!/usr/bin/env python3
"""Extract native text (headings/paragraphs) and tables for tier-1 pages.
See SKILL.md."""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import elements as elements_lib  # noqa: E402
import figures as figures_lib  # noqa: E402
import furniture as furniture_lib  # noqa: E402
import glyphs  # noqa: E402
import paths  # noqa: E402
import toc as toc_lib  # noqa: E402

import fitz  # PyMuPDF

# Furniture removal (Task A2) reads triage.json["furniture"], written by
# pdf-triage's detect_furniture(). The band, the frame matching tolerance and
# the loaders are in lib/furniture.py.


def load_toc_entries(doc: str) -> list[dict]:
    """toc.json's `entries` list (Task A3's `lib/toc.py`/`pdf-triage`
    output) -- empty list if `toc.json` doesn't exist (triage hasn't run) or
    this document has none (no printed TOC, no outline). Drives Task A4's
    TOC-driven heading classification; extract_text.py must still work
    standalone without it, same convention as `furniture_lib.load_furniture`/
    `furniture_lib.load_page_roles`."""
    toc_path = paths.toc_json(doc)
    if not toc_path.exists():
        return []
    return json.loads(toc_path.read_text(encoding="utf-8")).get("entries", [])


def build_toc_heading_lookup(toc_entries: list[dict]) -> dict[str, int]:
    """{normalize_toc_text(entry's "number + title" text): entry["level"]}
    -- the primary (TOC-driven) heading-classification table. Empty exactly
    when this document has no TOC entries at all, which is what signals
    `classify_heading_level` to use the fallback (rank-by-size) path
    instead."""
    lookup = {}
    for entry in toc_entries:
        key = toc_lib.normalize_toc_text(toc_lib.toc_entry_heading_text(entry))
        lookup[key] = entry["level"]
    return lookup


def furniture_filtered_lines(
    block: dict, furniture_masked: set[str], page_height: float, content_rect: list[float] | None = None
) -> list[dict]:
    """The subset of `block["lines"]` that survive furniture filtering.

    A line is dropped only if the block sits in a top/bottom edge band
    *and* that specific line's furniture key matches a known furniture
    line pattern -- matched lines are the unit of exclusion, not the whole
    block. A block that mixes one furniture-matching line with unrelated
    real content on an adjacent line (e.g. PyMuPDF merging a footer note
    next to a page number into one block) keeps its real line(s); the whole
    block is only dropped if every one of its lines matches (the caller
    sees an empty list back). A block outside the edge band, or one with no
    matching lines, is returned unchanged."""
    if not furniture_masked or not furniture_lib.in_furniture_band(block["bbox"], page_height, content_rect):
        return block["lines"]
    return [line for line in block["lines"] if line["masked"] not in furniture_masked]


def figure_region_filtered_lines(lines: list[dict], figure_regions: list[dict]) -> list[dict]:
    """The subset of `lines` that do NOT fall inside any of this page's
    figure regions (Task A5, `lib/figures.py`'s `detect_figure_regions`).
    Same per-line-is-the-unit-of-exclusion shape as `furniture_filtered_lines`
    -- a block that mixes a figure-region line (e.g. a diagram box's "Start"
    label) with unrelated surrounding paragraph text on an adjacent line
    keeps its real line(s). Excluded lines are exactly the ones
    `extract_images.py`'s `figure_text_for_region` collects for the
    matching image element, via the same `figures_lib.line_in_region` test,
    so a line is never dropped here without also appearing there, and never
    duplicated as both a `paragraph` and part of `figure_text`."""
    if not figure_regions:
        return lines
    return [
        line for line in lines
        if not any(figures_lib.line_in_region(line["bbox"], region["bbox"]) for region in figure_regions)
    ]


def table_filtered_lines(lines: list[dict], tables: list[dict]) -> list[dict]:
    """Follow-up R24: the subset of `lines` that are not majority-inside
    any of the page's tables (the same `line_in_region` test figures use),
    for a block that mostly overlaps a table: the table element carries
    those lines' text, and the rest of the block stays body text."""
    return [
        line for line in lines
        if not any(figures_lib.line_in_region(line["bbox"], t["bbox"]) for t in tables)
    ]


def caption_filtered_lines(lines: list[dict], caption_bboxes: set[tuple]) -> list[dict]:
    """The subset of `lines` whose bbox does NOT exactly match one of this
    page's caption lines (Task A6, `lib/figures.py`'s `find_caption_line`,
    called once per image bbox -- vector region or bitmap -- in `main()`).
    Same per-line-is-the-unit-of-exclusion shape as
    `furniture_filtered_lines`/`figure_region_filtered_lines`. `caption`
    is script-authoritative on the matching image element now, so the
    caption text must not also survive as a `paragraph`/`heading` element."""
    if not caption_bboxes:
        return lines
    return [line for line in lines if tuple(line["bbox"]) not in caption_bboxes]


def compute_kept_bbox(block: dict, kept_lines: list[dict]) -> list[float]:
    """The element bbox for `kept_lines` -- PyMuPDF's own block bbox
    unchanged when nothing was dropped, else recomputed from just the
    surviving lines so a partially-furniture/figure/caption-trimmed block
    doesn't keep reporting a discarded line's geometry."""
    if len(kept_lines) == len(block["lines"]):
        return list(block["bbox"])  # nothing dropped -- keep PyMuPDF's own block bbox
    return [
        min(line["bbox"][0] for line in kept_lines),
        min(line["bbox"][1] for line in kept_lines),
        max(line["bbox"][2] for line in kept_lines),
        max(line["bbox"][3] for line in kept_lines),
    ]


def build_block_element(
    block: dict,
    kept_lines: list[dict],
    body_size: float,
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
    list_level_lookup: list[float] | None = None,
) -> dict | None:
    """Reassemble a `heading`/`list_item`/`paragraph` element from
    `kept_lines` (a possibly-trimmed subset of `block["lines"]`, per
    `furniture_filtered_lines`). Returns None if nothing survived (the
    whole block was furniture).

    When lines were dropped, the bbox and heading-classification size are
    recomputed from just the surviving lines, so a partially-furniture
    block doesn't keep reporting the discarded line's geometry/size.

    Task A4b: `list_level_lookup` is the document-wide, sorted-ascending
    list-marker x-position clusters (`document_list_marker_levels`). Kept
    optional, defaulting to None (list-item detection skipped entirely) so
    the two direct-call unit tests in `test_furniture_removal.py` that
    predate this task keep working unchanged -- neither of their hand-built
    blocks' text starts with a marker anyway, but this keeps the function's
    old behavior available on purpose, not just by accident. A TOC-matched
    heading always wins over marker-shaped text (checked first, same as
    before) -- e.g. a numbered heading like "1) Some Heading" would never
    reach the list-item check if its text matches a TOC entry."""
    if not kept_lines:
        return None
    bbox = compute_kept_bbox(block, kept_lines)
    first_line = kept_lines[0]
    text = " ".join(line["text"] for line in kept_lines)
    max_size = max(line["max_size"] for line in kept_lines)
    is_bold_block = all(line["bold"] for line in kept_lines)

    level = classify_heading_level(text, is_bold_block, max_size, body_size, toc_lookup, heading_size_ranks)
    if level:
        return {"type": "heading", "level": level, "text": text, "bbox": bbox}

    if list_level_lookup is not None:
        marker_info = parse_list_marker(first_line["text"])
        if marker_info:
            marker, rest = marker_info
            # Wrapped continuation lines of the SAME block (no marker of
            # their own) belong to this item's text -- e.g. a bullet whose
            # body text wraps onto a second PyMuPDF line within one block.
            # Fix round 2: bounded by the same LIST_MARKER_X_TOLERANCE
            # x-check `parse_block_list_items` uses -- an unconditional
            # join (any remaining kept_lines, regardless of x) risked
            # silently absorbing an unrelated following paragraph that
            # PyMuPDF happened to group into the same block (reviewer
            # Re-review 1, Important). The marker is inline (first token of
            # `first_line`'s own text), so its "text x0" is approximated as
            # that same line's own bbox x0 -- same approximation this
            # module already documents elsewhere (no per-word x available).
            text_x = first_line["bbox"][0]
            absorbed = [first_line]
            for line in kept_lines[1:]:
                if abs(line["bbox"][0] - text_x) > LIST_MARKER_X_TOLERANCE:
                    break
                absorbed.append(line)
            item_text = " ".join([rest] + [line["text"] for line in absorbed[1:]])
            item_level = level_for_x(first_line["bbox"][0], list_level_lookup)
            item_bbox = compute_kept_bbox(block, absorbed)
            return {"type": "list_item", "marker": marker, "level": item_level, "text": item_text, "bbox": item_bbox}

    return {"type": "paragraph", "text": text, "bbox": bbox}


# Task A4: heading-level classification is TOC-driven when this document
# has TOC entries at all, with a rank-by-distinct-bold-size fallback when it
# doesn't. The old fixed-ratio thresholds (1.9/1.45/1.15) are gone --
# ranking replaces ratio comparison entirely, even in the fallback path.

# The fallback path's "does this block carry real heading text, not just a
# bullet glyph or stray mark" gate: a candidate block needs at least this
# many alphanumeric characters. "Non-glyph" is defined here as simply
# `str.isalnum()` (unicode-aware) -- a lone bullet glyph ("-", "•", or a
# private-use-area dingbat) has zero alphanumeric characters and never
# qualifies, regardless of its font size or boldness. This is the simple
# heuristic the brief calls out as an acceptable choice, over building a
# printable-character-range table.
FALLBACK_NON_GLYPH_MIN_CHARS = 3

# The fallback path ranks at most this many distinct bold-heading sizes;
# the 6th-largest and every smaller distinct size all collapse to level 6
# rather than growing unbounded.
FALLBACK_MAX_LEVELS = 6

# PyMuPDF span flag bit for bold (TEXT_FONT_BOLD). Some fonts don't set it
# reliably (e.g. non-embedded/substituted fonts), so this is combined with a
# "bold" substring check on the font name as a second, independent signal --
# both this fixture's and typical real documents' bold fonts are literally
# named e.g. "Helvetica-Bold".
_BOLD_FLAG_BIT = 16


def is_bold_span(span: dict) -> bool:
    flags = span.get("flags", 0) or 0
    font = span.get("font", "") or ""
    return bool(flags & _BOLD_FLAG_BIT) or "bold" in font.lower()


def non_glyph_char_count(text: str) -> int:
    """See FALLBACK_NON_GLYPH_MIN_CHARS -- count of alphanumeric characters
    in `text`."""
    return sum(1 for ch in text if ch.isalnum())


def is_fallback_heading_candidate(text: str, is_bold_block: bool, max_size: float, body_size: float) -> bool:
    """Fallback-path (no TOC) candidacy gate: bold, strictly larger than the
    document's body size, and carrying at least FALLBACK_NON_GLYPH_MIN_CHARS
    of real (non-glyph) text. Used both to build the document-wide size
    ranking (`document_heading_size_ranks`) and to classify each block
    against it, so the two stay consistent with each other."""
    if body_size <= 0 or not is_bold_block or max_size <= body_size:
        return False
    return non_glyph_char_count(text) >= FALLBACK_NON_GLYPH_MIN_CHARS


# Task A4b: list items. Bullet-glyph markers are single characters -- Symbol-
# font private-use glyphs (U+F02D/U+F0B7/U+F0A7/U+F0D8, the shapes actually
# found in real documents), plus the common Unicode bullet punctuation
# (middle dot, bullet, black small square, en dash) and a plain ASCII
# hyphen. Keep the set in one place so parse_list_marker/document scanning/
# tests all agree on exactly which characters count.
LIST_BULLET_GLYPHS = "·•▪–-"

# Follow-up R7: Word's default bullet chain is "·" (Symbol) at level 1, "o"
# (Courier New) at level 2 and "§" (Wingdings U+00A7, drawn as a square) at
# level 3. "o" and "§" are also ordinary text (a letter; a "§ 4.2" section
# reference), so they are LONE-ONLY markers: they count only in the
# separate-glyph shapes (the glyph as its own block, or as its own line of a
# block, with the item text at a larger x on the same visual line). As the
# first token of a text span (`parse_list_marker`) they never count. Like
# the other glyphs they render as "-", and level clustering includes them.
LIST_LONE_BULLET_GLYPHS = "o§"


def is_lone_bullet(text: str) -> bool:
    """True when `text`, stripped, is exactly one bullet glyph that may
    stand alone as a marker: any of LIST_BULLET_GLYPHS or
    LIST_LONE_BULLET_GLYPHS. The separate-glyph shapes use this; the inline
    shape (`parse_list_marker`) uses LIST_BULLET_GLYPHS only."""
    stripped = text.strip()
    return len(stripped) == 1 and (stripped in LIST_BULLET_GLYPHS or stripped in LIST_LONE_BULLET_GLYPHS)


# Enumerator marker shapes: "1)" / "1.", "(1)", "a)", "(a)", short roman
# numerals like "i)"/"ii)" (1-4 roman-numeral characters -- "short" per the
# brief). Order doesn't affect correctness here: every alternative that can
# match a given prefix captures the identical substring (e.g. "i)" matches
# both the roman-numeral and the single-letter alternative the same way),
# so which one "wins" the alternation never changes the captured marker text.
_ROMAN_NUMERAL_MARKER = r"[ivxlcdmIVXLCDM]{1,4}\)"
_ENUMERATOR_RE = re.compile(
    r"^(?:\d{1,3}[.)]|\(\d{1,3}\)|\([A-Za-z]\)|" + _ROMAN_NUMERAL_MARKER + r"|[A-Za-z]\))(?=\s)"
)

# Marker x-positions within this many points count as the same indent level
# (Task A4b) -- same tolerance convention as FRAME_MATCH_TOLERANCE/A5's
# other ~3pt geometry tolerances elsewhere in this pipeline.
LIST_MARKER_X_TOLERANCE = 3.0  # pt
# How close two lines' y0 must be to count as "the same visual line" for the
# separate-glyph-block merge case (brief: "y differs by about 1 pt" on the
# real document -- cushioned to match the other ~3pt tolerances above).
LIST_MARKER_Y_TOLERANCE = 3.0  # pt


def parse_list_marker(text: str) -> tuple[str, str] | None:
    """If `text` starts with a bullet-glyph or enumerator marker token
    followed by whitespace and more text on the same line, return
    `(marker, rest)` -- `marker` verbatim (exactly as printed), `rest` the
    remaining text with the separating whitespace stripped. `None` if
    `text` doesn't start with a recognized marker, or if there's no real
    text after it on the same line (a lone marker/number -- e.g. a table
    cell's bare "10" -- is not a list item; a marker needs text after it)."""
    if not text:
        return None
    if text[0] in LIST_BULLET_GLYPHS:
        rest = text[1:]
        if rest[:1] in (" ", "\t") and rest.strip():
            return text[0], rest.strip()
        return None
    match = _ENUMERATOR_RE.match(text)
    if match:
        rest = text[match.end():]
        if rest.strip():
            return match.group(0), rest.lstrip()
    return None


def cluster_x_positions(xs: list[float], tolerance: float = LIST_MARKER_X_TOLERANCE) -> list[float]:
    """Distinct x-positions, clustered within `tolerance` pt and returned
    sorted ascending -- `document_list_marker_levels`'s document-wide
    ranking table (index+1, via `level_for_x`, becomes a list_item's
    `level`). Deterministic: sorts first, then greedily joins each value
    into the previous cluster if it's within `tolerance` of that cluster's
    (lowest-x) representative, else starts a new cluster."""
    clusters: list[float] = []
    for x in sorted(set(xs)):
        if clusters and x - clusters[-1] <= tolerance:
            continue
        clusters.append(x)
    return clusters


def level_for_x(x: float, cluster_reps: list[float]) -> int:
    """1-based rank (in `cluster_reps`, sorted ascending) of the cluster
    nearest to `x` -- ties broken toward the lower (shallower) level. Falls
    back to level 1 if `cluster_reps` is empty (defensive: only possible if
    a block matches `parse_list_marker` during real per-page classification
    but was somehow missed by the whole-document scan that builds
    `cluster_reps`)."""
    if not cluster_reps:
        return 1
    best_i, best_d = 0, abs(x - cluster_reps[0])
    for i, rep in enumerate(cluster_reps[1:], start=1):
        d = abs(x - rep)
        if d < best_d:
            best_i, best_d = i, d
    return best_i + 1


def _block_marker_start(kept_lines: list[dict], i: int) -> tuple[str, str, dict, float, int] | None:
    """Task A4b fix round 1 (reviewer Finding 1): does `kept_lines[i]`
    start a new list item WITHIN a single block? Two shapes, both reusing
    `parse_list_marker` (no second copy of the marker-recognition rule):

    - `lines_consumed == 2`: `kept_lines[i]` is a lone bullet-glyph
      character and nothing else, and `kept_lines[i + 1]` sits on the same
      visual line (`LIST_MARKER_Y_TOLERANCE`) at a larger x -- the real
      document's actual shape, confirmed empirically: a glyph drawn at a
      larger font size than its text lands as TWO separate `lines` of ONE
      PyMuPDF block, not two spans of one line (which the single-line
      `parse_list_marker` check alone could read) and not two top-level
      blocks (which `merge_list_and_paragraph_blocks`'s own cross-BLOCK
      case already handled, one level up from this cross-LINE case).
    - `lines_consumed == 1`: `kept_lines[i]`'s own text is itself
      "marker + text" (`parse_list_marker` matches directly) -- the
      original inline-marker shape (e.g. `furniture_sample.pdf`'s
      `"- Ingestion"`, one span, one line).

    Returns `(marker, item_text_so_far, x_line, text_x, lines_consumed)`:
    `x_line` is whichever line's bbox determines the marker's LEVEL (the
    glyph line for the pair shape, the marker line itself for the inline
    shape); `text_x` (fix round 2) is the item's own TEXT x0, used to
    bound continuation-line absorption -- the real text line's own x0 for
    the glyph-pair shape (an exact value), or the marker line's own x0 for
    the inline shape (an approximation: this pipeline has no per-word x to
    find where the text after the marker actually starts on that shared
    line). `None` if `kept_lines[i]` doesn't start an item either way."""
    line = kept_lines[i]
    stripped = line["text"].strip()
    if is_lone_bullet(stripped) and i + 1 < len(kept_lines):
        next_line = kept_lines[i + 1]
        same_line = abs(next_line["bbox"][1] - line["bbox"][1]) <= LIST_MARKER_Y_TOLERANCE
        further_right = next_line["bbox"][0] > line["bbox"][0]
        if same_line and further_right and parse_list_marker(next_line["text"]) is None:
            return stripped, next_line["text"], line, next_line["bbox"][0], 2
        return None
    marker_info = parse_list_marker(line["text"])
    if marker_info:
        marker, rest = marker_info
        return marker, rest, line, line["bbox"][0], 1
    return None


# Follow-up R25: the bullet glyphs that may start an item in the middle of
# a block. Not the dashes: a wrapped line can start with "– PT)".
MID_BLOCK_BULLET_GLYPHS = "·•▪"


def _is_glyph_marker_start(kept_lines: list[dict], i: int) -> bool:
    """Follow-up R25: True when `kept_lines[i]` starts a list item with a
    bullet glyph of MID_BLOCK_BULLET_GLYPHS (a lone glyph line paired with
    its text, or an inline glyph), not with a dash or an enumerator."""
    start = _block_marker_start(kept_lines, i)
    return start is not None and start[0] in MID_BLOCK_BULLET_GLYPHS


def parse_block_list_items(kept_lines: list[dict], list_level_lookup: list[float]) -> list[dict] | None:
    """Task A4b: a single block can hold ONE OR SEVERAL list items end to
    end (glyph, text, glyph, text, ... -- fix round 1's reviewer repro
    shape), each recognized via `_block_marker_start`.

    Fix round 2 (reviewer Re-review 1, Important): a line with no marker
    of its own continues the currently open item ONLY IF its x0 is within
    `LIST_MARKER_X_TOLERANCE` of that item's own `text_x` (see
    `_block_marker_start`'s docstring) -- the same tolerance constant the
    pre-existing cross-BLOCK continuation case already uses, not a second
    one. PyMuPDF sometimes groups a short list item and the ordinary
    paragraph that follows it (same left margin, normal line spacing) into
    ONE block -- confirmed directly against real PyMuPDF output -- so
    absorbing every remaining line unconditionally (fix round 1's original
    behavior) risked silently swallowing that unrelated paragraph into the
    item's text. The FIRST line that fails the x-check ends the list: that
    line, and everything after it in the block up to the next marker-start
    (or the end of the block), becomes its own `paragraph` element instead
    -- or the start of a further list item, if a marker-start line comes
    next. Line order and text are otherwise unchanged (no rewrapping, no
    character changes).

    Returns `None` (not a list) when `kept_lines[0]` isn't itself a marker
    start -- the block isn't list content at all, so the caller falls back
    to ordinary heading/paragraph handling exactly as before this task
    (this function changes nothing for a block that doesn't start with a
    marker). Otherwise returns a list of `list_item`/`paragraph` elements
    in document order (never headings -- the caller already ruled that out
    before calling this)."""
    if not kept_lines:
        return None
    if _block_marker_start(kept_lines, 0) is None:
        # Follow-up R25: the block may open with the last wrapped line(s) of
        # the previous block's item and then start a new item. Only a
        # bullet-glyph marker counts here, not an enumerator: a wrapped
        # line can start with "10. " by chance.
        later = next(
            (i for i in range(1, len(kept_lines)) if _is_glyph_marker_start(kept_lines, i)),
            None,
        )
        if later is None:
            return None
        lead_paragraphs = []
        # Follow-up R27: label/value rows before the list are their own
        # paragraphs here too.
        for group in split_row_groups(kept_lines[:later]):
            group_bbox = list(group[0]["bbox"])
            for line in group[1:]:
                group_bbox = _union_bbox(group_bbox, line["bbox"])
            lead_paragraphs.append({"type": "paragraph", "text": " ".join(line["text"] for line in group), "bbox": group_bbox})
        rest = parse_block_list_items(kept_lines[later:], list_level_lookup) or []
        return [*lead_paragraphs, *rest]

    elements: list[dict] = []
    open_item: dict | None = None
    open_item_text_x: float | None = None
    paragraph_lines: list[dict] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        p_bbox = list(paragraph_lines[0]["bbox"])
        for p_line in paragraph_lines[1:]:
            p_bbox = _union_bbox(p_bbox, p_line["bbox"])
        elements.append({
            "type": "paragraph",
            "text": " ".join(p_line["text"] for p_line in paragraph_lines),
            "bbox": p_bbox,
        })
        paragraph_lines.clear()

    i, n = 0, len(kept_lines)
    while i < n:
        start = _block_marker_start(kept_lines, i)
        if start is not None:
            flush_paragraph()
            marker, first_text, x_line, text_x, consumed = start
            level = level_for_x(x_line["bbox"][0], list_level_lookup)
            if consumed == 2:
                item_bbox = _union_bbox(kept_lines[i]["bbox"], kept_lines[i + 1]["bbox"])
            else:
                item_bbox = list(kept_lines[i]["bbox"])
            item = {"type": "list_item", "marker": marker, "level": level, "text": first_text, "bbox": item_bbox}
            elements.append(item)
            open_item, open_item_text_x = item, text_x
            i += consumed
            continue

        line = kept_lines[i]
        if open_item is not None and abs(line["bbox"][0] - open_item_text_x) <= LIST_MARKER_X_TOLERANCE:
            open_item["text"] = open_item["text"] + " " + line["text"]
            open_item["bbox"] = _union_bbox(open_item["bbox"], line["bbox"])
            i += 1
            continue

        # x-check failed (or no item open yet) -- this line ends the
        # currently open item for good (no later line can re-open it) and
        # starts (or continues) a trailing paragraph run instead.
        open_item, open_item_text_x = None, None
        paragraph_lines.append(line)
        i += 1

    flush_paragraph()
    return elements


def document_list_marker_levels(
    fitz_doc,
    body_size: float,
    furniture_masked: set[str],
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
    page_roles: dict[int, str],
    furniture: dict | None = None,
) -> list[float]:
    """Document-wide list-marker x-position clusters (Task A4b's "collect
    the distinct marker x-positions ... across the whole document, sort
    ascending, level = rank" rule) -- see `cluster_x_positions`/`level_for_x`.

    Scans the WHOLE document rather than just the current `--pages` batch,
    for the same reason `document_heading_size_ranks` does (see that
    function's own docstring): the elastic-loop pipeline can invoke this
    script once per page batch, as separate subprocesses, and a given
    indent's level must come out identical regardless of which batch runs.

    Applies furniture-line filtering (the same `furniture_filtered_lines`
    helper the per-page loop uses, and the same lesson
    `document_heading_size_ranks` learned the hard way in its own fix round
    1 -- an unfiltered running header/footer could otherwise seed a bogus
    cluster) AND skips pages `pdf-triage` marked `role: "toc"` -- a printed
    TOC's dot-leader lines can start with a bare number immediately
    followed by "." (e.g. "10.1 Internal Standards ....... 9" reads as
    marker "10." to `parse_list_marker`), which would otherwise pollute the
    cluster table with a spurious x-position from a page that never
    contributes any elements at all (`main()` skips TOC pages entirely).
    Does NOT apply figure-region/caption filtering -- a whole-document scan
    would need every page's figure regions computed twice (once here, once
    in `main()`'s own per-page loop); same documented, accepted gap shape
    as `document_heading_size_ranks`'s own carried-forward figure/table-
    overlap gap (see task-A5-report.md's "Concerns" section).

    Fix round 1 (reviewer Finding 1): a block's marker candidates are now
    collected via `_block_marker_start`, walked across every line in the
    block (not just the first) -- the same function `parse_block_list_items`
    uses for the real per-page extraction, so this ranking table can never
    disagree with what the real pass actually detects as a marker."""
    xs: list[float] = []
    for page in fitz_doc:
        page_number = page.number + 1
        if page_roles.get(page_number) == "toc":
            continue
        page_height = page.rect.height
        content_rect = furniture_lib.page_content_rect(furniture, page.rect.width, page_height)
        text_blocks, _ = extract_page_text_blocks(page, body_size)
        for block in text_blocks:
            kept_lines = furniture_filtered_lines(block, furniture_masked, page_height, content_rect)
            if not kept_lines:
                continue
            first_line = kept_lines[0]
            text = " ".join(line["text"] for line in kept_lines)
            max_size = max(line["max_size"] for line in kept_lines)
            is_bold_block = all(line["bold"] for line in kept_lines)
            if classify_heading_level(text, is_bold_block, max_size, body_size, toc_lookup, heading_size_ranks):
                continue  # a TOC-matched/fallback heading never seeds a marker x-position
            if _block_marker_start(kept_lines, 0) is not None:
                j = 0
                while j < len(kept_lines):
                    start = _block_marker_start(kept_lines, j)
                    if start is not None:
                        xs.append(start[2]["bbox"][0])  # x_line's own x0
                        j += start[4]  # lines_consumed (index 4 -- text_x is now index 3)
                    else:
                        j += 1
            elif len(kept_lines) == 1 and is_lone_bullet(first_line["text"]):
                # Separate-glyph-block candidate: a whole block that is
                # nothing but one bullet-glyph character, paired with the
                # NEXT top-level block (merge_list_and_paragraph_blocks's
                # cross-BLOCK case) -- distinct from the within-block pair
                # above (cross-LINE, one block).
                xs.append(first_line["bbox"][0])
    return cluster_x_positions(xs)


def _union_bbox(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _same_row(a: dict, b: dict) -> bool:
    """Follow-up R27: two lines on one visual line, side by side."""
    return (
        abs(a["bbox"][1] - b["bbox"][1]) <= LIST_MARKER_Y_TOLERANCE
        and (a["bbox"][2] <= b["bbox"][0] or b["bbox"][2] <= a["bbox"][0])
    )


def split_row_groups(kept_lines: list[dict]) -> list[list[dict]]:
    """Follow-up R27: `kept_lines` split at label/value rows.

    A row is two or more lines at one y, side by side ("HWC requirement" |
    "REQ ..."; "ASIL Value:" | "To Be"). Each row starts a group. A line
    after a row that is indented past the block's left edge continues the
    row (a value wrapped in its column, "Selected"); the next line back at
    the left edge starts a body group, which runs until the next row. A
    block with no row is returned as one group, unchanged."""
    if len(kept_lines) < 2:
        return [kept_lines]
    left = min(line["bbox"][0] for line in kept_lines)
    groups: list[list[dict]] = []
    kind = None  # "row" or "body"
    for i, line in enumerate(kept_lines):
        prev = kept_lines[i - 1] if i > 0 else None
        nxt = kept_lines[i + 1] if i + 1 < len(kept_lines) else None
        if prev is not None and _same_row(prev, line):
            groups[-1].append(line)
        elif nxt is not None and _same_row(line, nxt):
            groups.append([line])
            kind = "row"
        elif kind == "row" and line["bbox"][0] > left + LIST_MARKER_X_TOLERANCE:
            groups[-1].append(line)
        elif kind == "body":
            groups[-1].append(line)
        else:
            groups.append([line])
            kind = "body"
    if not any(len(g) > 1 and _same_row(g[0], g[1]) for g in groups):
        return [kept_lines]
    return groups


def merge_list_and_paragraph_blocks(
    blocks_and_lines: list[tuple[dict, list[dict]]],
    body_size: float,
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
    list_level_lookup: list[float],
) -> list[dict]:
    """Second pass over a page's furniture/figure/caption/table-filtered
    blocks (Task A4b) -- `blocks_and_lines` is `[(block, kept_lines), ...]`
    with every entry's `kept_lines` already non-empty. Classifies each
    block via `build_block_element` (heading / single-block list_item,
    including same-block wrapped continuation lines / paragraph), then
    resolves two cross-block cases `build_block_element` can't see on its
    own, looking only at the single block it was given:

    1. A bullet-glyph block (exactly one character, one of
       LIST_BULLET_GLYPHS or LIST_LONE_BULLET_GLYPHS -- `is_lone_bullet`,
       nothing else) immediately followed by a block
       that starts on the same visual line (`LIST_MARKER_Y_TOLERANCE`) at a
       larger x -- the marker glyph and its text are two separate PyMuPDF
       blocks whenever the glyph is drawn at a distinctly larger font size
       than the text (the brief's own worked description of the real
       document's Symbol-font bullets). Merged into one `list_item` before
       either block is classified on its own (a lone glyph would otherwise
       become a useless one-character paragraph).
    2. A wrapped continuation block: no marker of its own, not classified
       as a heading, sitting at the immediately-preceding list item's text
       x-position (within `LIST_MARKER_X_TOLERANCE`) -- absorbed into that
       item's text/bbox instead of becoming a standalone paragraph. Only
       the block immediately following an open list item is eligible (the
       brief's own "the next block ... with no marker of its own"); any
       other block in between (a heading, a differently-indented paragraph,
       another list item) closes the open item.

    Judgment call: case 2 only fires for a list item that came from case 1
    (the separate-glyph-block merge), because that's the only shape where
    this pipeline has a real, trustworthy "where does this item's text
    start" x -- the actual text block's own bbox x0. A list item produced
    by `build_block_element`'s inline-marker path (the marker is the first
    token of the block's own line) does NOT set a usable text x here: its
    only available x is the marker's own bbox x0, which on a real document
    is typically the SAME left margin ordinary (non-list) paragraphs also
    start at (this fixture's own LEFT_MARGIN=72 is both a level-1 bullet's
    marker x and every paragraph's left edge) -- absorbing whatever
    happens to follow at that common margin would silently swallow
    unrelated prose into the list item's text, a real correctness risk on
    a document with lists followed by normal paragraphs, not a
    hypothetical. Same-block wrapped continuation (multiple PyMuPDF lines
    inside one block, first line has the marker) is unaffected by this --
    `build_block_element` handles that case directly, with no x-matching
    involved at all."""
    elements: list[dict] = []
    open_item: dict | None = None
    open_item_text_x: float | None = None

    i, n = 0, len(blocks_and_lines)
    while i < n:
        block, kept_lines = blocks_and_lines[i]
        first_line = kept_lines[0]
        stripped_first = first_line["text"].strip()

        if (
            len(kept_lines) == 1
            and is_lone_bullet(stripped_first)
            and i + 1 < n
        ):
            next_block, next_kept_lines = blocks_and_lines[i + 1]
            next_first = next_kept_lines[0]
            same_line = abs(next_first["bbox"][1] - first_line["bbox"][1]) <= LIST_MARKER_Y_TOLERANCE
            further_right = next_block["bbox"][0] > block["bbox"][0]
            if same_line and further_right and parse_list_marker(next_first["text"]) is None:
                item_text = " ".join(line["text"] for line in next_kept_lines)
                bbox = _union_bbox(block["bbox"], next_block["bbox"])
                item_level = level_for_x(block["bbox"][0], list_level_lookup)
                item = {"type": "list_item", "marker": stripped_first, "level": item_level, "text": item_text, "bbox": bbox}
                elements.append(item)
                open_item, open_item_text_x = item, next_block["bbox"][0]
                i += 2
                continue

        # Fix round 1 (reviewer Finding 1): the real document's actual
        # marker shape -- a glyph drawn larger than its text -- lands as
        # two LINES of ONE block, not the cross-block case above and not
        # the single-line inline case build_block_element's own marker
        # check reads. A block can hold several such items end to end
        # (glyph, text, glyph, text, ...) -- parse_block_list_items walks
        # every line and returns all of them at once. The heading check
        # runs FIRST (same as build_block_element's own ordering, reused
        # here rather than duplicated) so a TOC-matched/fallback heading
        # still always wins over marker-shaped text.
        block_text = " ".join(line["text"] for line in kept_lines)
        block_max_size = max(line["max_size"] for line in kept_lines)
        block_is_bold = all(line["bold"] for line in kept_lines)
        if classify_heading_level(block_text, block_is_bold, block_max_size, body_size, toc_lookup, heading_size_ranks) is None:
            block_items = parse_block_list_items(kept_lines, list_level_lookup)
            if block_items is not None:
                # Follow-up R25: leading lines that sit right of the open
                # item's marker are that item's last wrapped line(s).
                first = block_items[0]
                if (
                    first["type"] == "paragraph"
                    and elements
                    and elements[-1]["type"] == "list_item"
                    and first["bbox"][0] > elements[-1]["bbox"][0] + LIST_MARKER_X_TOLERANCE
                ):
                    elements[-1]["text"] = elements[-1]["text"] + " " + first["text"]
                    elements[-1]["bbox"] = _union_bbox(elements[-1]["bbox"], first["bbox"])
                    block_items = block_items[1:]
                elements.extend(block_items)
                # Same restriction as the cross-block case's own
                # open_item_text_x handling below: only a real, distinct
                # text x (not available here -- see parse_block_list_items'
                # docstring) would make cross-BLOCK continuation-absorption
                # safe, so the next block is never auto-absorbed into the
                # last item found here. Fix round 2: block_items can now
                # end in a `paragraph` (the within-block x-check bounced a
                # trailing line out of the list) -- only track it as an
                # open list item when it actually is one.
                last_block_item = block_items[-1]
                if last_block_item["type"] == "list_item":
                    open_item, open_item_text_x = last_block_item, None
                else:
                    open_item, open_item_text_x = None, None
                i += 1
                continue

        element = build_block_element(block, kept_lines, body_size, toc_lookup, heading_size_ranks, list_level_lookup)

        # Follow-up R27: a paragraph block made of label/value rows and a
        # body becomes one paragraph per group.
        if element is not None and element["type"] == "paragraph":
            groups = split_row_groups(kept_lines)
            if len(groups) > 1:
                for group in groups:
                    elements.append({
                        "type": "paragraph",
                        "text": " ".join(line["text"] for line in group),
                        "bbox": compute_kept_bbox({"bbox": block["bbox"], "lines": []}, group),
                    })
                open_item, open_item_text_x = None, None
                i += 1
                continue

        if (
            element is not None
            and element["type"] == "paragraph"
            and open_item is not None
            and open_item_text_x is not None
            and abs(block["bbox"][0] - open_item_text_x) <= LIST_MARKER_X_TOLERANCE
        ):
            open_item["text"] = open_item["text"] + " " + element["text"]
            open_item["bbox"] = _union_bbox(open_item["bbox"], element["bbox"])
            i += 1
            continue

        if element is not None:
            elements.append(element)

        if element is not None and element["type"] == "list_item":
            # Deliberately do NOT track a text x here for the inline-marker
            # case (marker is the first token of the block's own line) --
            # its only available x is the marker's own bbox x0, which on a
            # real document is typically the SAME left margin ordinary
            # (non-list) paragraphs also start at (e.g. this fixture's
            # LEFT_MARGIN=72 is both a level-1 bullet's marker x AND every
            # paragraph's left edge). Absorbing the next block whenever it
            # merely shares that common margin would silently swallow
            # unrelated paragraphs into the list item's text -- a real
            # correctness risk on a document with lists followed by normal
            # prose, not just a hypothetical. Only the separate-glyph-block
            # case above (which has the real TEXT block's own x, distinct
            # from the marker's x) sets a usable open_item_text_x.
            open_item, open_item_text_x = element, None
        else:
            open_item, open_item_text_x = None, None
        i += 1

    return elements


def list_item_text_x(item: dict, words: list[tuple]) -> float:
    """Fix wave I3: the x where a `list_item`'s text starts, after its
    marker -- read from the page's words (`page.get_text("words")`) on the
    item's first visual line, so the same rule covers every marker shape
    (a glyph block plus a text block, a glyph line plus a text line in one
    block, or "marker text" inline on one line). The first word is the
    marker when its text equals the item's marker, or when it is a single
    non-alphanumeric character at the marker's x; the next word then gives
    the text x. When the first word already lies right of the marker's x
    (the glyph is not a word of its own), that word gives it. Falls back to
    `bbox[0]` when the words do not show it.

    `lib/elements.py`'s page-break join compares the next page's first
    paragraph with this value. It is not used to absorb continuation
    blocks within a page: that bound stays as the A4b rulings set it."""
    x0, y0, x1, _y1 = item["bbox"]
    first_line = sorted(
        (w for w in words if y0 - 1 <= w[1] <= y0 + 2 * LIST_MARKER_Y_TOLERANCE and x0 - 1 <= w[0] <= x1),
        key=lambda w: w[0],
    )
    if not first_line:
        return x0
    first = first_line[0]
    marker = item.get("marker") or ""
    is_marker_word = (marker and first[4] == marker) or (
        len(first[4]) == 1 and not first[4].isalnum() and abs(first[0] - x0) <= LIST_MARKER_X_TOLERANCE
    )
    if is_marker_word:
        return first_line[1][0] if len(first_line) > 1 else x0
    if first[0] > x0 + LIST_MARKER_X_TOLERANCE:
        return first[0]
    return x0


def document_heading_size_ranks(
    fitz_doc, body_size: float, furniture_masked: set[str], furniture: dict | None = None
) -> dict[float, int]:
    """Fallback-path (no TOC) heading-level ranking: every DISTINCT font
    size used by a fallback-candidate bold block anywhere in the document
    (not just the pages this invocation's --pages batch covers), ranked
    largest-first -- the largest distinct size is level 1, the next is
    level 2, and so on, with the 6th and any smaller distinct size all
    collapsing to level 6 (FALLBACK_MAX_LEVELS) instead of growing
    unbounded.

    Scans the WHOLE document rather than just the current batch's pages on
    purpose: the elastic-loop pipeline can invoke this script once per page
    batch, as separate subprocesses, and the ranking (and therefore the
    levels a heading of a given size gets) must be identical regardless of
    which batch happens to run -- a per-batch-local ranking would disagree
    with itself across batches of the same document.

    `furniture_masked` (triage.json's furniture["line_patterns"], masked
    text -- same set the per-page loop's `furniture_filtered_lines` uses)
    is applied here too, via the same helper, before a block is even
    considered as a candidate. Fix round 1: without this, a real no-TOC
    document's bold running header/title (a plausible convention for this
    toolkit's actual RFQ-spec target documents) would itself be bold,
    larger than body size, and long enough to clear the 3-alphanumeric-
    character gate -- so it would silently consume a rank slot and shift
    every genuine heading's level down by one (or force an extra collapse
    into level 6), even though the header itself never becomes a heading
    (or any) element on its own page."""
    sizes = set()
    for page in fitz_doc:
        page_height = page.rect.height
        content_rect = furniture_lib.page_content_rect(furniture, page.rect.width, page_height)
        text_blocks, _ = extract_page_text_blocks(page, body_size)
        for block in text_blocks:
            kept_lines = furniture_filtered_lines(block, furniture_masked, page_height, content_rect)
            if not kept_lines:
                continue
            text = " ".join(line["text"] for line in kept_lines)
            max_size = max(line["max_size"] for line in kept_lines)
            is_bold_block = all(line["bold"] for line in kept_lines)
            if is_fallback_heading_candidate(text, is_bold_block, max_size, body_size):
                sizes.add(max_size)
    ranked = sorted(sizes, reverse=True)
    return {size: min(i + 1, FALLBACK_MAX_LEVELS) for i, size in enumerate(ranked)}


def classify_heading_level(
    text: str,
    is_bold_block: bool,
    max_size: float,
    body_size: float,
    toc_lookup: dict[str, int],
    heading_size_ranks: dict[float, int],
) -> int | None:
    """Primary: TOC-driven, whenever this document has any TOC entries at
    all (`toc_lookup` non-empty). A block becomes a heading at its matching
    TOC entry's level only if its normalized text matches a TOC entry's
    normalized "number + title" text exactly -- no match means `paragraph`,
    no matter the block's size or boldness. This is what stops a lone
    bullet glyph, or any other large/bold text that isn't an actual
    TOC-listed heading, from being misclassified as a heading.

    Fallback: only reached when this document has zero TOC entries (no
    printed TOC, no outline) -- rank-by-distinct-bold-size instead, gated by
    `is_fallback_heading_candidate`."""
    if toc_lookup:
        return toc_lookup.get(toc_lib.normalize_toc_text(text))
    if not is_fallback_heading_candidate(text, is_bold_block, max_size, body_size):
        return None
    return heading_size_ranks.get(max_size)


def extract_page_text_blocks(page, body_size: float | None) -> tuple[list[dict], float]:
    """`body_size`, if given, comes from pdf-triage's document-wide,
    character-weighted measurement (`triage.json`'s `body_size` field) and
    is used as-is. A single page's own text is often too sparse (e.g. just
    a heading and one caption line) for a reliable per-page median, so this
    per-page fallback exists only for standalone/manual use of this script
    without triage having run first."""
    raw = page.get_text("dict")
    # Follow-up R18: line text is decoded (Symbol font, ligature glyphs);
    # the furniture key stays on the raw text so triage's patterns match.
    symbol_fonts = glyphs.page_symbol_fonts(page)
    text_blocks = []
    sizes = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            raw_stripped = "".join(span["text"] for span in line.get("spans", [])).strip()
            stripped = glyphs.line_text(line, symbol_fonts).strip()
            if not stripped:
                continue
            line_max_size = 0.0
            line_spans = line.get("spans", [])
            for span in line_spans:
                sizes.append(span["size"])
                line_max_size = max(line_max_size, span["size"])
            lines.append({
                "text": stripped,
                "masked": furniture_lib.furniture_key(raw_stripped),
                "bbox": line["bbox"],
                "max_size": line_max_size,
                "bold": bool(line_spans) and all(is_bold_span(s) for s in line_spans),
            })
        if lines:
            text_blocks.append({"bbox": block["bbox"], "lines": lines})
    resolved_body_size = body_size if body_size else (statistics.median(sizes) if sizes else 0.0)
    return text_blocks, resolved_body_size


def resolve_document_body_size(fitz_doc) -> float:
    """Document-wide, character-weighted median body text size -- the same
    computation as `pdf-triage`'s `document_body_size()`, duplicated here
    (rather than imported cross-skill) so this script stays runnable
    standalone without triage having run, same convention as
    `load_furniture`/`load_page_roles`/`load_toc_entries`. Only used
    to size the fallback (no-TOC) heading ranking document-wide when
    `--body-size` wasn't passed in; per-page extraction keeps its own
    existing sparser per-page fallback in `extract_page_text_blocks`,
    unchanged."""
    weighted_sizes = []
    for page in fitz_doc:
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_len = len(span["text"].strip())
                    if text_len:
                        weighted_sizes.extend([span["size"]] * text_len)
    return statistics.median(weighted_sizes) if weighted_sizes else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 1-indexed page numbers")
    parser.add_argument("--body-size", type=float, default=None, help="document-wide body text size from triage.json's body_size field; falls back to a per-page estimate if omitted")
    args = parser.parse_args()

    page_numbers = [int(p) for p in args.pages.split(",") if p.strip()]
    pdf_path = paths.input_pdf(args.doc)
    if not pdf_path.exists():
        print(f"error: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    furniture = furniture_lib.load_furniture(args.doc)
    frame_tables = furniture.get("frame_tables", [])
    frame_drawings = furniture.get("frame_drawings", [])
    repeated_drawings = furniture.get("repeated_drawings", [])
    furniture_masked = {p["masked"] for p in furniture.get("line_patterns", [])}
    furniture_xrefs = set(furniture.get("image_xrefs", []))
    page_roles = furniture_lib.load_page_roles(args.doc)
    toc_lookup = build_toc_heading_lookup(load_toc_entries(args.doc))

    fitz_doc = fitz.open(pdf_path)

    # Fallback-path (no TOC) heading ranking is document-wide (see
    # document_heading_size_ranks's docstring) and only ever needed when
    # there's no TOC to drive classification instead -- skip the extra
    # whole-document scan otherwise.
    heading_size_ranks: dict[float, int] = {}
    ranking_body_size = args.body_size or 0.0
    if not toc_lookup:
        ranking_body_size = args.body_size if args.body_size else resolve_document_body_size(fitz_doc)
        heading_size_ranks = document_heading_size_ranks(fitz_doc, ranking_body_size, furniture_masked, furniture)

    # Task A4b: list-marker x-position levels are document-wide too, for the
    # same cross-batch-consistency reason as heading_size_ranks above --
    # computed unconditionally (list items can appear in either a TOC-driven
    # or fallback document). `ranking_body_size` is only actually consulted
    # by classify_heading_level's fallback branch inside this scan; when
    # toc_lookup is non-empty it's ignored entirely, so the 0.0 default
    # above is harmless in that case.
    list_level_lookup = document_list_marker_levels(
        fitz_doc, ranking_body_size, furniture_masked, toc_lookup, heading_size_ranks, page_roles,
        furniture=furniture,
    )

    for page_number in page_numbers:
        if page_roles.get(page_number) == "toc":
            # A printed TOC page carries no real content of its own -- skip
            # straight to an empty, explicitly-marked shard instead of
            # running text/table extraction on it.
            shard_path = paths.shard_path(args.doc, page_number, "text")
            elements_lib.write_shard(shard_path, page_number, [], skipped="toc")
            continue

        page = fitz_doc[page_number - 1]
        page_height = page.rect.height
        # Re-review 2 I2: the content rect only on a page it was measured on.
        content_rect = furniture_lib.page_content_rect(furniture, page.rect.width, page_height)
        text_blocks, body_size = extract_page_text_blocks(page, args.body_size)
        # Page-frame tables (furniture, not real content) are left out by
        # the shared query -- before the overlap-drop below, or a frame
        # "table" would swallow real text blocks that merely sit under it.
        tables = [
            {"bbox": t["bbox"], "rows": t["rows"]}
            for t in figures_lib.page_tables(pdf_path, page_number, frame_tables, content_rect)
        ]
        # Task A5: figure regions detected the same way extract_images.py
        # detects them (same shared helper, so the two scripts can never
        # disagree about where a page's figures are) -- their text-layer
        # lines belong to figure_text, not to a paragraph/heading element.
        figure_regions, region_exclusions = figures_lib.detect_figure_regions_with_exclusions(
            page, page_number, pdf_path, frame_tables, frame_drawings, repeated_drawings=repeated_drawings,
            content_rect=content_rect,
        )
        # Follow-up R11: a chart's grid that pdfplumber read as a table is
        # part of the figure, so it is not a table element.
        grid_tables = [r["bbox"] for r in region_exclusions if r["reason"] == "grid_table"]
        tables = [t for t in tables if not any(furniture_lib.bbox_matches(t["bbox"], g) for g in grid_tables)]

        # Task A6: caption lines -- one find_caption_line() search per
        # image bbox on the page (every vector region above, plus every
        # bitmap placement), the exact same universe extract_images.py
        # turns into `image` elements and searches for a caption against.
        # A matched line's bbox is excluded from paragraph/heading
        # extraction below, since its text is now script-authoritative on
        # the matching image element's `caption` field instead.
        image_bboxes = [r["bbox"] for r in figure_regions] + figures_lib.bitmap_bboxes(page, furniture_xrefs)
        # Follow-up R17: a caption joined from two lines (figures'
        # _join_split_captions) excludes both of its source lines.
        caption_bboxes = {
            tuple(part)
            for line in (figures_lib.find_caption_line(page, bbox) for bbox in image_bboxes)
            if line
            for part in line.get("parts", [line["bbox"]])
        }

        # Drop text blocks that mostly overlap a detected table; the table
        # element replaces them so cell text isn't duplicated as prose.
        # Every surviving block's kept_lines is non-empty (an empty result
        # is dropped right here) -- merge_list_and_paragraph_blocks (Task
        # A4b) relies on that so its cross-block lookahead never has to
        # special-case an empty entry.
        filtered_blocks: list[tuple[dict, list[dict]]] = []
        for block in text_blocks:
            kept_lines = block["lines"]
            if any(furniture_lib.overlap_ratio(block["bbox"], t["bbox"]) > 0.5 for t in tables):
                # Follow-up R24: drop only the lines inside a table. A
                # caption printed right above the table can share the block
                # with the header cells, and is not table text.
                kept_lines = table_filtered_lines(kept_lines, tables)
                if not kept_lines:
                    continue
            kept_lines = furniture_filtered_lines({**block, "lines": kept_lines}, furniture_masked, page_height, content_rect)
            kept_lines = figure_region_filtered_lines(kept_lines, figure_regions)
            kept_lines = caption_filtered_lines(kept_lines, caption_bboxes)
            if kept_lines:
                filtered_blocks.append((block, kept_lines))

        page_elements = merge_list_and_paragraph_blocks(
            filtered_blocks, body_size, toc_lookup, heading_size_ranks, list_level_lookup,
        )
        list_items = [el for el in page_elements if el["type"] == "list_item"]
        if list_items:
            words = page.get_text("words")
            for item in list_items:
                item["text_x"] = list_item_text_x(item, words)

        for table in tables:
            page_elements.append({"type": "table", "rows": table["rows"], "bbox": list(table["bbox"])})

        page_elements.sort(key=lambda e: e["bbox"][1])

        shard_path = paths.shard_path(args.doc, page_number, "text")
        elements_lib.write_shard(shard_path, page_number, page_elements)

    fitz_doc.close()
    print(f"extracted text for pages {page_numbers}")


if __name__ == "__main__":
    main()
