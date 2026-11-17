"""A caption an agent wrote (`caption_source: "agent"`) is interpretation,
not document text, in every output."""

import json
from xml.etree import ElementTree as ET

import elements as elements_lib
import paths

from conftest import load_script, run_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_agent_caption_module")
reqif_builder = load_script("assemble-output/scripts/reqif_builder.py", "reqif_builder_agent_caption_module")
text_mode_grade = load_script("grade-output/scripts/text_mode_grade.py", "text_mode_grade_agent_caption_module")

AGENT_IMAGE = {
    "type": "image", "asset": "assets/p1.png",
    "caption": "Agent caption", "caption_source": "agent", "description": "Agent description",
}


def _doc(*elements):
    return {"doc": "d", "pages": {1: {"page_number": 1, "elements": list(elements)}}}


def test_an_agent_caption_is_marked_as_interpretation():
    lines = assemble.render_image_markdown(AGENT_IMAGE)
    start = lines.index(assemble.INTERPRETATION_START)
    assert not any("Agent caption" in line for line in lines[:start])
    assert "Agent caption" in "\n".join(lines[start:])


def test_a_printed_caption_stays_outside_the_markers():
    lines = assemble.render_image_markdown({**AGENT_IMAGE, "caption_source": None, "description": ""})
    assert lines[1] == "Agent caption"
    assert assemble.INTERPRETATION_START not in lines


def test_html_puts_an_agent_caption_inside_the_markers_not_in_figcaption():
    html = assemble.to_html(_doc(AGENT_IMAGE))
    assert "<figcaption>" not in html
    start = html.index("<!-- scriptorium:interpretation -->")
    assert "Agent caption" not in html[:start]
    assert "Agent caption" in html[start:]


def test_reqif_long_name_falls_back_to_image_for_an_agent_caption():
    root = ET.fromstring(reqif_builder.build_reqif_xml("d", _doc(AGENT_IMAGE)))
    names = [el.get("LONG-NAME") for el in root.iter(reqif_builder._q("SPEC-OBJECT"))]
    assert names == ["Image"]
    assert "Agent caption" not in ET.tostring(root, encoding="unicode")


def test_bad_caption_ignores_agent_and_empty_captions():
    from openpyxl import Workbook

    ws = Workbook().active
    _, bad = text_mode_grade.xlsx_check_images(ws, [{**AGENT_IMAGE, "caption": "image"}, {"type": "image", "asset": "b.png"}])
    assert bad is False


def test_describe_image_marks_a_caption_as_agent_written(tmp_project):
    (tmp_project / "input" / "doc.pptx").write_bytes(b"synthetic")
    shard = paths.shard_path("doc", 1, "image")
    elements_lib.write_shard(shard, 1, [{"type": "image", "asset": "assets/a.png"}])
    result = run_script(
        "extract-images/scripts/describe_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png",
        "--description", "d", "--caption", "c", cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    el = json.loads(shard.read_text())["elements"][0]
    assert el["caption"] == "c" and el["caption_source"] == "agent"
