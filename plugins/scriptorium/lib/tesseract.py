"""Cross-platform tesseract discovery.

On Linux/macOS `tesseract` is reliably on PATH once a package manager
installs it. On Windows that's not guaranteed — installers (winget/choco/
scoop) may finish without the current process (or even the current shell
session) seeing an updated PATH, and there's no `sudo`-equivalent for
writing into a system tessdata directory without admin rights. This module
centralizes the fallback lookup so `ocr.py` and `ensure_language.py` agree
on where the binary and its language data actually are.
"""

import os
import shutil
import sys
from pathlib import Path

# Common install locations winget/choco/scoop use, checked only if `tesseract`
# isn't already on PATH.
WINDOWS_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


def find_tesseract() -> str | None:
    """Return a path (or bare command) usable to invoke tesseract, or None."""
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if sys.platform != "win32":
        return None
    candidates = list(WINDOWS_CANDIDATES)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    # scoop's shim dir is normally already on PATH (so shutil.which above
    # would have found it) — this only matters right after a fresh install
    # in a session that hasn't picked that up yet. $SCOOP overrides the
    # install root; most installs never set it and use ~\scoop instead.
    scoop_root = Path(os.environ.get("SCOOP", Path.home() / "scoop"))
    candidates.append(scoop_root / "apps" / "tesseract" / "current" / "tesseract.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def tessdata_dir_for(tesseract_path: str) -> Path | None:
    """The tessdata dir tesseract itself would use — a sibling `tessdata/`
    directory next to the binary. None if it doesn't exist (rare, but
    possible right after a partial install)."""
    sibling = Path(tesseract_path).resolve().parent / "tessdata"
    return sibling if sibling.is_dir() else None


def user_tessdata_dir() -> Path:
    """A per-user, always-writable fallback directory for downloaded
    language packs when the system tessdata dir isn't writable (no admin
    rights) and no package manager installed the pack for us."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "scriptorium" / "tessdata"
