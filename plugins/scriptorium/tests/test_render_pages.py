"""render-pages/scripts/render.py: a page PNG is reused once it exists, and
parallel agents may read it, so it only ever appears complete."""

import sys
from pathlib import Path

import pytest

import paths
from conftest import load_script

render = load_script("render-pages/scripts/render.py", "render_pages")


def test_an_interrupted_render_leaves_no_page_png(pdf_doc, monkeypatch):
    def broken_save(self, path, *args, **kwargs):
        Path(path).write_bytes(b"\x89PNG half")
        raise RuntimeError("disk full")

    monkeypatch.setattr(render.fitz.Pixmap, "save", broken_save)
    monkeypatch.setattr(sys, "argv", ["render.py", "--doc", pdf_doc, "--pages", "1"])
    with pytest.raises(RuntimeError):
        render.main()
    assert list(paths.pages_dir(pdf_doc).iterdir()) == []


def test_a_rendered_page_is_a_png(pdf_doc, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["render.py", "--doc", pdf_doc, "--pages", "1"])
    render.main()
    png = paths.page_png(pdf_doc, 1)
    assert capsys.readouterr().out.strip() == str(png)
    assert png.read_bytes()[:4] == b"\x89PNG"
