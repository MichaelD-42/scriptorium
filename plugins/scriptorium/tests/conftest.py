"""Shared fixtures/helpers for the scriptorium test suite.

Two ways of exercising a script:
  - `load_script(...)`: import it as a real module so its pure functions can
    be unit-tested directly. Needed because several scripts share a
    basename (six files are all named `triage.py`), so a plain `import`
    would collide -- each gets its own unique module name instead.
  - `run_script(...)`: run it as a subprocess exactly like the orchestrator
    does, for CLI/integration-level smoke tests.
"""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS_ROOT = PLUGIN_ROOT / "skills"
LIB_ROOT = PLUGIN_ROOT / "lib"
EXAMPLES_ROOT = PLUGIN_ROOT / "examples"

# Every skill script does its own `sys.path.insert(0, .../lib)` at import
# time, so lib/ ends up importable regardless -- but unit tests that want to
# `import paths`/`import elements` directly (without going through
# load_script) need it up front too.
sys.path.insert(0, str(LIB_ROOT))


def load_script(relpath: str, name: str):
    """Import skills/<relpath> as a module registered under a unique
    `name`, so pure functions inside it can be called directly.

    Inserts the script's own directory at the front of sys.path first --
    needed for assemble.py's sibling `import reqif_builder`, which only
    resolves when the script's directory is importable (true automatically
    when run as `python assemble.py`, not true for an arbitrary importlib
    load)."""
    path = SKILLS_ROOT / relpath
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_script(relpath: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run skills/<relpath> as a subprocess, the same way commands/extract.md
    invokes it: `uv run --project <plugin> python <script> <args>`."""
    script_path = SKILLS_ROOT / relpath
    return subprocess.run(
        ["uv", "run", "--project", str(PLUGIN_ROOT), "python", str(script_path), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """A scaffolded project root (input/work/output/runs), cwd'd into --
    scripts resolve every path against the current working directory."""
    for name in ("input", "work", "output", "runs"):
        (tmp_path / name).mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _copy_fixture(tmp_project: Path, ext: str, doc: str = "sample") -> str:
    dest = tmp_project / "input" / f"{doc}.{ext}"
    shutil.copyfile(EXAMPLES_ROOT / f"sample.{ext}", dest)
    return doc


@pytest.fixture
def pdf_doc(tmp_project):
    """input/sample.pdf: 5 pages -- native text, a table, a bitmap image, a
    vector diagram, and a scanned (no-text-layer) page. See
    examples/generate_sample.py."""
    return _copy_fixture(tmp_project, "pdf")


@pytest.fixture
def pptx_doc(tmp_project):
    """input/sample.pptx: slide 1 title+text, slide 2 table+picture."""
    return _copy_fixture(tmp_project, "pptx")


@pytest.fixture
def docx_doc(tmp_project):
    """input/sample.docx: 2 Heading-1 pages, page 2 has a table + image."""
    return _copy_fixture(tmp_project, "docx")


@pytest.fixture
def xlsx_doc(tmp_project):
    """input/sample.xlsx: one sheet, a 3-row/2-col used range."""
    return _copy_fixture(tmp_project, "xlsx")


@pytest.fixture
def html_doc(tmp_project):
    return _copy_fixture(tmp_project, "html")


@pytest.fixture
def png_doc(tmp_project):
    return _copy_fixture(tmp_project, "png")


@pytest.fixture(autouse=True)
def _skip_missing_binaries(request):
    """`requires_tesseract`/`requires_libreoffice`-marked tests skip when
    the binary isn't on PATH, instead of failing CI environments that
    intentionally don't install it (see pyproject.toml's marker docs)."""
    if request.node.get_closest_marker("requires_tesseract") and shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    if request.node.get_closest_marker("requires_libreoffice") and shutil.which("soffice") is None:
        pytest.skip("soffice (LibreOffice) not installed")
