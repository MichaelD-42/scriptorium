"""Triage preflight: reject an input the extract step cannot read, with one
`error:` line on stderr and exit 1, before any work is spent on it. The
orchestrator marks such a document needs-human (commands/extract.md)."""

import sys
from pathlib import Path

# Compound File Binary header: an encrypted OOXML file, or a legacy .doc/.xls/.ppt.
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def fail(path: Path, why: str) -> None:
    print(f"error: {path} {why}", file=sys.stderr)
    sys.exit(1)


def open_office(open_fn, path: Path):
    """`open_fn(path)` for a pptx/docx/xlsx, or fail with the reason."""
    with open(path, "rb") as f:
        if f.read(len(OLE_MAGIC)) == OLE_MAGIC:
            fail(
                path,
                "is password-protected or a legacy binary Office file; save it unprotected in the current format",
            )
    try:
        return open_fn(path)
    except (
        Exception
    ) as e:  # zipfile.BadZipFile, KeyError, PackageNotFoundError, lxml errors...
        fail(path, f"cannot be opened ({type(e).__name__}: {e})")
