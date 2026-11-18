"""Small graphics the size floor and the page's image list used to miss: a
curve-dense stroke drawing (a handwritten signature) and a bitmap the
page's image list does not report (an inline image, or one drawn inside a
form XObject)."""

import json

import fitz  # PyMuPDF
import paths
from conftest import load_script, run_script

W, H = 595.0, 842.0
SIGNATURE = (164.0, 467.0, 204.0, 487.0)
INLINE = (125.0, 465.0, 182.0, 488.0)

figures = load_script("../lib/figures.py", "figures_small_graphics")


def _signature(page) -> None:
    """A 40 x 20 pt scribble of 32 bezier curves, one drawing."""
    shape = page.new_shape()
    x0, y0, x1, y1 = SIGNATURE
    for i in range(32):
        a = fitz.Point(x0 + i * (x1 - x0) / 32, y1 - (i % 4) * 4)
        b = fitz.Point(x0 + (i + 1) * (x1 - x0) / 32, y0 + (i % 5) * 3)
        shape.draw_bezier(a, (a.x, y0), (b.x, y1), b)
    shape.finish(color=(0, 0, 0.5), width=0.6, closePath=False)
    shape.commit()


def _inline_image(pdf, page) -> None:
    """A 2 x 2 px RGB bitmap written as an inline image (BI ... EI)."""
    x0, y0, x1, y1 = INLINE
    data = bytes([30, 30, 200] * 4)
    ops = f"\nq {x1 - x0} 0 0 {y1 - y0} {x0} {H - y1} cm BI /W 2 /H 2 /CS /RGB /BPC 8 ID ".encode() + data + b" EI Q\n"
    xref = page.get_contents()[-1]
    pdf.update_stream(xref, pdf.xref_stream(xref) + ops)


def _doc(path, signature: bool = False, inline: bool = False, form: bool = False) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.insert_text((72, 200), "Body text above the signature block.", fontsize=10)
    page.insert_text((72, 560), "Body text below the signature block.", fontsize=10)
    if signature:
        _signature(page)
    if inline:
        _inline_image(pdf, page)
    if form:
        src = fitz.open()
        src_page = src.new_page(width=80, height=40)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 4), False)
        pix.clear_with(120)
        src_page.insert_image(src_page.rect, pixmap=pix)
        page.show_pdf_page(fitz.Rect(*INLINE), src, 0)
    pdf.save(str(path))
    pdf.close()


def test_curve_dense_small_drawing_is_a_figure(tmp_path):
    pdf_path = tmp_path / "signature.pdf"
    _doc(pdf_path, signature=True)
    with fitz.open(pdf_path) as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, pdf_path)
    assert len(regions) == 1, excluded
    assert figures._inside(SIGNATURE, regions[0]["bbox"], 1.0), regions


def test_small_drawing_with_few_curves_is_still_tiny(tmp_path):
    pdf = fitz.open()
    page = pdf.new_page(width=W, height=H)
    page.draw_circle((80, 300), 3, color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((90, 303), "Bullet item text.", fontsize=10)
    pdf.save(str(tmp_path / "bullet.pdf"))
    pdf.close()
    with fitz.open(tmp_path / "bullet.pdf") as doc:
        regions, excluded = figures.detect_figure_regions_with_exclusions(doc[0], 1, tmp_path / "bullet.pdf")
    assert regions == [] and [r["reason"] for r in excluded] == ["tiny"], excluded


def _image_elements(tmp_project, doc: str) -> list[dict]:
    result = run_script("extract-images/scripts/extract_images.py", "--doc", doc, "--pages", "1", cwd=tmp_project)
    assert result.returncode == 0, result.stderr
    shard = json.loads(paths.shard_path(doc, 1, "image").read_text(encoding="utf-8"))
    return [e for e in shard["elements"] if e["type"] == "image"]


def test_inline_bitmap_is_an_image(tmp_project):
    doc = "inline_bitmap"
    _doc(tmp_project / "input" / f"{doc}.pdf", inline=True)
    with fitz.open(tmp_project / "input" / f"{doc}.pdf") as pdf:
        assert pdf[0].get_images() == []
        assert [[round(v) for v in b] for b in figures.bitmap_bboxes(pdf[0])] == [list(INLINE)]
    images = _image_elements(tmp_project, doc)
    assert [[round(v) for v in e["bbox"]] for e in images] == [list(INLINE)], images
    assert (paths.output_dir(doc) / images[0]["asset"]).exists()


def test_bitmap_in_a_form_xobject_is_one_image(tmp_project):
    doc = "form_bitmap"
    _doc(tmp_project / "input" / f"{doc}.pdf", form=True)
    images = _image_elements(tmp_project, doc)
    assert len(images) == 1 and figures._inside(images[0]["bbox"], INLINE, 0.5), images
