"""Triage preflight for the non-PDF formats: an input the extract step cannot
read fails triage with a one-line error instead of a traceback."""

import pytest
from PIL import Image
from pptx import Presentation

import paths
from conftest import run_script

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _assert_rejected(tmp_project, skill, doc, phrase):
    result = run_script(f"{skill}/scripts/triage.py", "--doc", doc, cwd=tmp_project)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert result.stderr.startswith("error: ")
    assert phrase in result.stderr
    assert not paths.triage_json(doc).exists()


@pytest.mark.parametrize("ext", ["pptx", "docx", "xlsx"])
def test_password_protected_office_file(tmp_project, ext):
    (tmp_project / "input" / f"locked.{ext}").write_bytes(OLE_MAGIC + b"\0" * 504)
    _assert_rejected(tmp_project, f"{ext}-triage", "locked", "password-protected")


@pytest.mark.parametrize("ext", ["pptx", "docx", "xlsx"])
def test_corrupt_office_file(tmp_project, ext):
    (tmp_project / "input" / f"broken.{ext}").write_bytes(
        b"PK\x03\x04 not really a zip"
    )
    _assert_rejected(tmp_project, f"{ext}-triage", "broken", "cannot be opened")


def test_pptx_without_slides(tmp_project):
    Presentation().save(tmp_project / "input" / "empty.pptx")
    _assert_rejected(tmp_project, "pptx-triage", "empty", "no slides")


def test_corrupt_image(tmp_project):
    (tmp_project / "input" / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\n garbage")
    _assert_rejected(tmp_project, "image-triage", "broken", "cannot be opened")


def test_multi_page_tiff(tmp_project):
    """render-pages saves the first frame only; pages 2+ would be lost."""
    frames = [Image.new("RGB", (50, 50), c) for c in ("white", "gray")]
    frames[0].save(
        tmp_project / "input" / "fax.tiff", save_all=True, append_images=frames[1:]
    )
    _assert_rejected(tmp_project, "image-triage", "fax", "2 pages")
