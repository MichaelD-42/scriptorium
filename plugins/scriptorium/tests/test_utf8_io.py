"""Follow-up R8: every text read and write is UTF-8, whatever the locale.

On Windows the default text encoding is the ANSI code page (cp1252), so a
`read_text()` with no encoding turns the UTF-8 bytes of "•" into "â€¢".
Every text read and write in the plugin's Python code states
`encoding="utf-8"`, and every text write also states `newline=""`.

Two checks:
- a static sweep of lib/, skills/*/scripts and examples/ for text I/O calls
  that leave the encoding (or, for a write, the newline) to the default;
- a pipeline run with the locale default forced off UTF-8
  (`PYTHONUTF8=0`, `PYTHONIOENCODING=cp1252`): a vision shard holding "•"
  and a private-use glyph goes in on stdin, through merge.py and
  `assemble.py --format md-tree`, and the output bytes must be the right
  UTF-8. The locale default is cp1252 only on Windows; elsewhere the run
  still checks the round trip, and the sweep guards every platform.
"""

import ast
import json
import os
import subprocess
from pathlib import Path

import fitz  # PyMuPDF
from conftest import PLUGIN_ROOT, SKILLS_ROOT

SWEEP_ROOTS = [PLUGIN_ROOT / "lib", PLUGIN_ROOT / "skills", PLUGIN_ROOT / "examples"]
NON_TEXT_OPENERS = {"fitz", "pymupdf", "pdfplumber", "zipfile", "tarfile", "Image"}

BULLET = chr(0x2022)  # bullet
PUA_GLYPH = chr(0xF0B7)  # Symbol-font private-use bullet
DOC = "utf8_roundtrip"


def _keywords(call: ast.Call) -> set[str]:
    return {kw.arg for kw in call.keywords if kw.arg}


def _mode(call: ast.Call, position: int) -> str:
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    if len(call.args) > position and isinstance(call.args[position], ast.Constant):
        return call.args[position].value
    return "r"


def _io_problems(path: Path) -> list[str]:
    problems = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name, owner = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            name, owner = func.id, ""
        else:
            continue
        keywords = _keywords(node)
        where = f"{path.relative_to(PLUGIN_ROOT).as_posix()}:{node.lineno}"
        if name == "read_text" and "encoding" not in keywords:
            problems.append(f"{where}: read_text() without encoding")
        elif name == "write_text" and not {"encoding", "newline"} <= keywords:
            problems.append(f"{where}: write_text() without encoding and newline")
        elif name == "open" and owner not in NON_TEXT_OPENERS:
            # Path.open(mode, ...) vs open(file, mode, ...)
            mode = _mode(node, 0 if owner and owner not in ("io", "builtins") else 1)
            if not isinstance(mode, str) or "b" in mode:
                continue
            needed = {"encoding"} | (
                {"newline"} if any(c in mode for c in "wax+") else set()
            )
            if not needed <= keywords:
                problems.append(
                    f"{where}: open({mode!r}) without {sorted(needed - keywords)}"
                )
        elif (
            name == "reconfigure"
            and owner in ("sys.stdin", "sys.stdout")
            and "encoding" not in keywords
        ):
            problems.append(f"{where}: {owner}.reconfigure() without encoding")
    return problems


def test_no_text_io_relies_on_the_locale_encoding():
    problems = []
    for root in SWEEP_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            problems.extend(_io_problems(path))
    assert problems == []


def _run(
    relpath: str, *args: str, cwd: Path, stdin: bytes | None = None
) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PLUGIN_ROOT),
            "python",
            str(SKILLS_ROOT / relpath),
            *args,
        ],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        check=False,
        env=env,
    )


def test_bullet_and_private_use_glyph_survive_merge_and_md_tree(tmp_project):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 150), "Scanned page placeholder.", fontsize=11)
    doc.save(str(tmp_project / "input" / f"{DOC}.pdf"))
    doc.close()

    elements = [
        {"type": "heading", "level": 1, "text": "1 Scope"},
        {
            "type": "paragraph",
            "text": f"Marker {BULLET} and glyph {PUA_GLYPH} in body text.",
        },
        {
            "type": "list_item",
            "marker": BULLET,
            "level": 1,
            "text": f"Item with {BULLET} inside",
        },
    ]
    payload = json.dumps(elements, ensure_ascii=False).encode("utf-8")
    for relpath, args, stdin in (
        (
            "ocr-page/scripts/write_vision_page.py",
            ("--doc", DOC, "--page", "1"),
            payload,
        ),
        ("assemble-output/scripts/merge.py", ("--doc", DOC), None),
        (
            "assemble-output/scripts/assemble.py",
            ("--doc", DOC, "--format", "md-tree"),
            None,
        ),
    ):
        result = _run(relpath, *args, cwd=tmp_project, stdin=stdin)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    out_dir = tmp_project / "output" / DOC
    data = b"".join(p.read_bytes() for p in sorted(out_dir.rglob("*.md")))
    assert BULLET.encode("utf-8") in data
    assert PUA_GLYPH.encode("utf-8") in data
    assert (
        BULLET.encode("utf-8").decode("cp1252").encode("utf-8") not in data
    )  # no "â€¢"
    data.decode("utf-8")  # the whole output is valid UTF-8
