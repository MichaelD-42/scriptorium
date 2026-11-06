"""--format jsonl: one line per element, in reading order, with the heading
path above it and its source pages -- for chunking (RAG) and for anyone
who wants per-element files. Furniture is left out."""

import json

import paths
from conftest import load_script, run_script

assemble = load_script("assemble-output/scripts/assemble.py", "assemble_jsonl")
gates = load_script("grade-output/scripts/gates.py", "gates_jsonl")


def _doc():
    return {
        "doc": "d",
        "pages": {
            1: {
                "page_number": 1,
                "furniture_images": [
                    {"asset": "assets/furniture1.png", "bbox": [0, 0, 9, 9]}
                ],
                "elements": [
                    {"type": "heading", "level": 1, "text": "1 System"},
                    {"type": "heading", "level": 2, "text": "1.1 Interfaces"},
                    {
                        "type": "paragraph",
                        "text": "The meter speaks Modbus",
                        "pages": [1, 2],
                        "bbox": [72, 700, 500, 715],
                    },
                ],
            },
            2: {
                "page_number": 2,
                "elements": [
                    {"type": "table", "rows": [["Port", "Use"], ["502", "Modbus"]]},
                    {
                        "type": "image",
                        "kind": "vector",
                        "asset": "assets/page2_vector1.png",
                        "caption": "Figure 1: Wiring",
                        "description": "A wiring diagram.",
                        "figure_text": "L1\nN",
                    },
                    {"type": "heading", "level": 1, "text": "2 Safety"},
                    {
                        "type": "list_item",
                        "marker": "-",
                        "level": 1,
                        "text": "Switch off first.",
                    },
                ],
            },
        },
    }


def test_one_record_per_element_with_heading_path_and_pages():
    doc_data = _doc()
    assemble.add_furniture_images(doc_data)
    records = [json.loads(line) for line in assemble.to_jsonl(doc_data).splitlines()]
    assert [r["id"] for r in records] == [
        "p1-1",
        "p1-2",
        "p1-3",
        "p2-1",
        "p2-2",
        "p2-3",
        "p2-4",
    ]
    assert all("furniture" not in json.dumps(r) for r in records)
    assert records[0] == {
        "id": "p1-1",
        "type": "heading",
        "pages": [1],
        "heading_path": [],
        "level": 1,
        "text": "1 System",
    }
    assert records[2]["heading_path"] == ["1 System", "1.1 Interfaces"]
    assert records[2]["pages"] == [1, 2]
    assert records[3]["rows"] == [["Port", "Use"], ["502", "Modbus"]]
    assert (
        records[4]["caption"] == "Figure 1: Wiring"
        and records[4]["asset"] == "assets/page2_vector1.png"
    )
    assert (
        records[5]["heading_path"] == []
    )  # a level-1 heading closes the chapter above
    assert records[6]["heading_path"] == ["2 Safety"]


def test_cli_writes_the_file_and_the_gate_accepts_it(tmp_project):
    (tmp_project / "input" / "d.pdf").write_bytes(b"%PDF")
    path = paths.elements_json("d")
    path.parent.mkdir(parents=True)
    import elements as elements_lib

    elements_lib.save_doc(path, _doc())
    result = run_script(
        "assemble-output/scripts/assemble.py",
        "--doc",
        "d",
        "--format",
        "jsonl",
        cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    out = tmp_project / "output" / "d" / "d.jsonl"
    assert len(out.read_text().splitlines()) == 7
    assert gates.check_output_file_exists("d", "jsonl")["passed"] is True
    out.write_text('{"id": "p1-1"}\nnot json\n')
    assert gates.check_output_file_exists("d", "jsonl")["passed"] is False
