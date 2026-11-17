"""A printed TOC in a document whose every page has a title block above a
drawn content frame. The title block holds a revision field shaped like a
section number ("1.0.0.0") at the same y as the document title."""

import json

import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

W, H = 595.0, 842.0
FRAME = (42.5, 154.7, 558.1, 813.7)  # content frame drawn on every page


def _furniture(page, number: int, total: int) -> None:
    """Title block above the frame. The revision line "1.0.0.0" sits at
    ~16.7% of the page height (below the fixed 12% edge band) and shares its
    y with the document-title line."""
    page.draw_line((46, 97), (532, 97), width=0.5)
    page.insert_text((50, 120), "Label A", fontsize=6)
    page.insert_text((50, 150), "Synthetic document title", fontsize=10)
    page.insert_text((340, 150), "1.0.0.0", fontsize=10)
    page.insert_text((480, 150), f"{number} ( {total} )", fontsize=10)
    page.draw_rect(fitz.Rect(*FRAME), width=0.5)


TOC = [  # (number, title, page) -- levels 1..3 only
    ("1", "Alpha", 3),
    ("1.1", "Alpha one", 3),
    ("1.1.1", "Alpha one a", 3),
    ("1.1.2", "Alpha one b", 3),
    ("1.2", "Alpha two", 4),
    ("1.2.1", "Alpha two a", 4),
    ("1.2.2", "Alpha two b", 4),
    ("2", "Beta", 5),
    ("2.1", "Beta one", 5),
    ("2.1.1", "Beta one a", 5),
    ("2.1.2", "Beta one b", 5),
    ("2.2", "Beta two", 6),
    ("2.2.1", "Beta two a", 6),
    ("2.2.2", "Beta two b", 6),
    ("3", "Gamma", 6),
    ("3.1", "Gamma one", 6),
]
SIZE = {1: 18, 2: 16, 3: 14}


# Lines after "2.1.2" that the TOC does not list: (text, size, underlined).
SUB_LINES = [
    ("Larger bold sub heading", 12, False),
    ("Underlined bold sub heading", 10, True),
    ("Plain bold label", 10, False),
]


def _toc_doc(path, deep_heading: bool = False, stray_leader: bool = False, sub_lines: bool = False) -> None:
    pdf = fitz.open()
    total = 6
    for _ in range(total):
        pdf.new_page(width=W, height=H)
    for i in range(total):
        _furniture(pdf[i], i + 1, total)
    pdf[0].insert_text((60, 300), "Cover page", fontsize=20)
    y = 180
    for number, title, target in TOC:
        pdf[1].insert_text(
            (60, y), f"{number} {title} " + "." * 60 + f" {target}", fontsize=10
        )
        y += 16
    if stray_leader:
        pdf[1].insert_text((60, y), "Foreword " + "." * 60 + " 3", fontsize=10)
    by_page: dict[int, list] = {}
    for number, title, target in TOC:
        by_page.setdefault(target, []).append((number, title))
    for target, heads in by_page.items():
        page, y = pdf[target - 1], 190
        for number, title in heads:
            level = number.count(".") + 1
            page.insert_text(
                (46, y), f"{number} {title}", fontsize=SIZE[level], fontname="hebo"
            )
            page.insert_text(
                (46, y + 20), "Body sentence for this section.", fontsize=10
            )
            y += 50
            if deep_heading and number == "2.1.1":
                # A level-4 numbered heading the TOC does not list.
                page.insert_text(
                    (46, y), "2.1.1.1 Beta one a deep", fontsize=12, fontname="hebo"
                )
                page.insert_text(
                    (46, y + 20), "Body sentence for the deep section.", fontsize=10
                )
                y += 50
            if sub_lines and number == "2.1.2":
                for text, size, underlined in SUB_LINES:
                    page.insert_text((46, y), text, fontsize=size, fontname="hebo")
                    if underlined:
                        width = fitz.get_text_length(text, fontname="hebo", fontsize=size)
                        page.draw_line((46, y + 1.5), (46 + width, y + 1.5), width=0.5)
                    page.insert_text((46, y + 20), "Body sentence under it.", fontsize=10)
                    y += 50
    pdf.save(str(path))
    pdf.close()


def _triage(tmp_project, doc: str) -> tuple[dict, dict]:
    result = run_script("pdf-triage/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    assert result.returncode == 0, result.stderr
    triage = json.loads(paths.triage_json(doc).read_text(encoding="utf-8"))
    toc = json.loads(paths.toc_json(doc).read_text(encoding="utf-8"))
    return triage, toc


def test_title_block_field_is_not_an_unparsed_toc_line(tmp_project):
    doc = "toc_header"
    _toc_doc(tmp_project / "input" / f"{doc}.pdf")
    triage, toc = _triage(tmp_project, doc)
    assert [p["page_number"] for p in triage["pages"] if p.get("role") == "toc"] == [2]
    assert len(toc["entries"]) == len(TOC)
    assert "#.#.#.#" in {p["masked"] for p in triage["furniture"]["line_patterns"]}
    assert toc["unparsed"] == []


def test_real_unparsed_leader_line_is_still_reported(tmp_project):
    doc = "toc_stray"
    _toc_doc(tmp_project / "input" / f"{doc}.pdf", stray_leader=True)
    _, toc = _triage(tmp_project, doc)
    assert len(toc["entries"]) == len(TOC)
    assert len(toc["unparsed"]) == 1 and toc["unparsed"][0].startswith("Foreword")


def _extract_page(tmp_project, doc: str, page: int) -> list[dict]:
    for args in (
        ("pdf-triage/scripts/triage.py", "--doc", doc),
        ("extract-text/scripts/extract_text.py", "--doc", doc, "--pages", str(page)),
    ):
        result = run_script(*args, cwd=tmp_project)
        assert result.returncode == 0, f"{args[0]}: {result.stderr}"
    return json.loads(paths.shard_path(doc, page, "text").read_text(encoding="utf-8"))["elements"]


def _gate_on_page(doc: str, page: int, elements: list[dict]) -> dict:
    gates = load_script("grade-output/scripts/gates.py", "gates_toc_title_block")
    entries = json.loads(paths.toc_json(doc).read_text(encoding="utf-8"))["entries"]
    doc_data = {"pages": {page: {"page_number": page, "elements": elements}}}
    return gates.check_toc_headings_match(doc_data, [e for e in entries if e["page"] == page], [])


def test_numbered_heading_deeper_than_toc_is_a_heading(tmp_project):
    doc = "deep_heading"
    _toc_doc(tmp_project / "input" / f"{doc}.pdf", deep_heading=True)
    elements = _extract_page(tmp_project, doc, 5)
    deep = [e for e in elements if e.get("text") == "2.1.1.1 Beta one a deep"]
    assert deep, "deep heading text missing"
    assert deep[0]["type"] == "heading" and deep[0]["level"] == 4
    # Nested under a TOC entry, one level deeper: the gate accepts it.
    check = _gate_on_page(doc, 5, elements)
    assert check["extra"] == [], check["detail"]


def test_bold_sub_heading_is_one_level_below_the_heading_above(tmp_project):
    doc = "sub_heading"
    _toc_doc(tmp_project / "input" / f"{doc}.pdf", sub_lines=True)
    elements = _extract_page(tmp_project, doc, 5)
    by_text = {e.get("text"): e for e in elements}
    for text in ("Larger bold sub heading", "Underlined bold sub heading"):
        assert (by_text[text]["type"], by_text[text]["level"]) == ("heading", 4), by_text[text]
    # Bold at body size, not underlined: a label, not a heading.
    assert by_text["Plain bold label"]["type"] == "paragraph"
    check = _gate_on_page(doc, 5, elements)
    assert check["passed"], check["detail"]


def test_gate_accepts_sub_headings_whose_parent_it_cannot_see():
    gates = load_script("grade-output/scripts/gates.py", "gates_toc_title_block")
    entries = [{"number": "1", "title": "Alpha", "page": 1, "level": 1}]

    def heading(text, level, **extra):
        return {"type": "heading", "level": level, "text": text, **extra}

    doc_data = {"pages": {
        1: {"page_number": 1, "elements": [
            heading("1 Alpha", 1),
            heading("1.1.1.1.1.1 Deep six", 6),
            heading("Below the level-six heading", 6, sub_heading=True),
        ]},
        # Seeded from the TOC entry on page 1, below the deeper heading.
        2: {"page_number": 2, "elements": [heading("Top of the next page", 2, sub_heading=True)]},
    }}
    check = gates.check_toc_headings_match(doc_data, entries)
    assert check["passed"], check["detail"]
