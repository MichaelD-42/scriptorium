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


def _toc_doc(path, deep_heading: bool = False, stray_leader: bool = False) -> None:
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
