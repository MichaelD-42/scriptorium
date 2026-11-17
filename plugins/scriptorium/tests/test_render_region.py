"""Follow-up R26: `render_region.py` renders an element's bbox at a high dpi
so an agent can read small figure labels before transcribing them."""

from pathlib import Path

import fitz  # PyMuPDF
from conftest import run_script


def test_region_is_rendered_at_the_requested_dpi(tmp_project):
    doc = "zoom"
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(100, 100, 200, 150), width=1)
    page.insert_text((110, 130), "10%", fontsize=4)
    pdf.save(str(tmp_project / "input" / f"{doc}.pdf"))
    pdf.close()

    result = run_script(
        "render-pages/scripts/render_region.py",
        "--doc",
        doc,
        "--page",
        "1",
        "--bbox",
        "100,100,200,150",
        "--dpi",
        "400",
        cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    out = Path(tmp_project) / result.stdout.strip()
    assert out.exists()
    pix = fitz.Pixmap(str(out))
    # (100 + 2 * 6) pt wide at 400 dpi.
    assert abs(pix.width - round(112 * 400 / 72)) <= 2


def test_bad_bbox_is_an_error(tmp_project):
    result = run_script(
        "render-pages/scripts/render_region.py",
        "--doc",
        "none",
        "--page",
        "1",
        "--bbox",
        "1,2,3",
        cwd=tmp_project,
    )
    assert result.returncode == 1


def test_a_pptx_region_is_cropped_from_the_cached_slide_pdf(tmp_project):
    (tmp_project / "input" / "deck.pptx").write_bytes(b"synthetic")
    (tmp_project / "work" / "deck").mkdir(parents=True)
    pdf = fitz.open()
    pdf.new_page(width=720, height=405)
    pdf.save(str(tmp_project / "work" / "deck" / "deck.pdf"))
    pdf.close()
    result = run_script(
        "render-pages/scripts/render_region.py", "--doc", "deck", "--page", "1", "--bbox", "10,10,110,60",
        cwd=tmp_project,
    )
    assert result.returncode == 0, result.stderr
    assert (Path(tmp_project) / result.stdout.strip()).exists()


def test_a_pptx_without_the_slide_pdf_is_an_error(tmp_project):
    (tmp_project / "input" / "deck.pptx").write_bytes(b"synthetic")
    result = run_script(
        "render-pages/scripts/render_region.py", "--doc", "deck", "--page", "1", "--bbox", "10,10,110,60",
        cwd=tmp_project,
    )
    assert result.returncode == 1
    assert "render.py" in result.stderr


def test_describe_image_refuses_a_note_in_figure_text():
    from conftest import load_script

    describe = load_script("extract-images/scripts/describe_image.py", "describe_image_r26")
    assert describe.figure_text_note("U (V)\n(percentage labels are too small to read reliably)") == "too small"
    assert describe.figure_text_note("U (V)\n10%\n90%") is None
