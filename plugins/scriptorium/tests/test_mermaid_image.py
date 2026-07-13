"""Unit tests for extract-images/scripts/mermaid_image.py."""

import json

import pytest

import elements as elements_lib
import paths
from conftest import load_script

mermaid_image = load_script("extract-images/scripts/mermaid_image.py", "mermaid_image_module")


class TestFirstDiagramLine:
    def test_skips_leading_blank_lines(self):
        assert mermaid_image.first_diagram_line("\n\nflowchart TD\n  A --> B") == "flowchart TD"

    def test_skips_percent_comments(self):
        text = "%% a comment\nflowchart TD\n  A --> B"
        assert mermaid_image.first_diagram_line(text) == "flowchart TD"

    def test_skips_yaml_frontmatter_block(self):
        text = "---\ntitle: My Diagram\n---\nflowchart TD\n  A --> B"
        assert mermaid_image.first_diagram_line(text) == "flowchart TD"

    def test_empty_input_returns_none(self):
        assert mermaid_image.first_diagram_line("   \n\n") is None


@pytest.mark.parametrize("keyword", ["flowchart TD", "sequenceDiagram", "classDiagram", "pie title x"])
def test_known_diagram_keywords_accepted_via_main(tmp_path, monkeypatch, keyword, capsys):
    monkeypatch.chdir(tmp_path)
    shard_path = paths.shard_path("doc", 1, "image")
    elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/a.png", "caption": ""}])

    monkeypatch.setattr("sys.argv", ["mermaid_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(f"{keyword}\n  A --> B"))
    mermaid_image.main()

    shard = json.loads(shard_path.read_text())
    assert shard["elements"][0]["mermaid"].startswith(keyword)


def test_non_diagram_input_exits_with_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths.assets_dir("doc").mkdir(parents=True)

    monkeypatch.setattr("sys.argv", ["mermaid_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("just some prose"))
    with pytest.raises(SystemExit) as exc_info:
        mermaid_image.main()
    assert exc_info.value.code == 1


def test_missing_shard_exits_with_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["mermaid_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("flowchart TD\n  A --> B"))
    with pytest.raises(SystemExit) as exc_info:
        mermaid_image.main()
    assert exc_info.value.code == 1


def test_unknown_asset_on_page_exits_with_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shard_path = paths.shard_path("doc", 1, "image")
    elements_lib.write_shard(shard_path, 1, [{"type": "image", "asset": "assets/other.png", "caption": ""}])

    monkeypatch.setattr("sys.argv", ["mermaid_image.py", "--doc", "doc", "--page", "1", "--asset", "assets/a.png"])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("flowchart TD\n  A --> B"))
    with pytest.raises(SystemExit) as exc_info:
        mermaid_image.main()
    assert exc_info.value.code == 1
