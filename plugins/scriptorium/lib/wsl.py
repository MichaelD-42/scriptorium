"""Windows programs seen from WSL.

Under WSL a tool may be installed only on the Windows side (Program Files,
scoop). Linux can run its `.exe`, but the program reads Windows paths, so
every file path handed to it goes through `wslpath -w` first.
"""

import subprocess
import sys
from pathlib import Path, PureWindowsPath

INTEROP = Path("/proc/sys/fs/binfmt_misc/WSLInterop")
PROC_VERSION = Path("/proc/version")
DRIVE = Path("/mnt/c")
WSLPATH = "wslpath"


def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    if INTEROP.exists():
        return True
    try:
        return "microsoft" in PROC_VERSION.read_text().lower()
    except OSError:
        return False


def windows_installs(*patterns: str) -> list[Path]:
    """Files matching `patterns` (globs relative to C:\\) on WSL, else []."""
    if not is_wsl():
        return []
    return [p for pattern in patterns for p in sorted(DRIVE.glob(pattern)) if p.is_file()]


def is_windows_exe(cmd: str) -> bool:
    return is_wsl() and str(cmd).lower().endswith((".exe", ".com"))


def path_for(cmd: str, path) -> str:
    """`path` as `cmd` reads it: a Windows path for a Windows program run
    from WSL. The parent is translated, since the file itself may not exist
    yet (an output name, a profile dir)."""
    if not is_windows_exe(cmd):
        return str(path)
    path = Path(path).absolute()
    parent = subprocess.run([WSLPATH, "-w", str(path.parent)], capture_output=True, text=True, check=True).stdout.strip()
    return str(PureWindowsPath(parent) / path.name)
