"""Find LibreOffice's `soffice` and build its pdf conversion command.

Order: the SCRIPTORIUM_SOFFICE environment variable, then `soffice` or
`libreoffice` on PATH, then (on WSL) a Windows install.
"""

import os
import shutil
from pathlib import Path, PureWindowsPath

import wsl

ENV_VAR = "SCRIPTORIUM_SOFFICE"
WSL_INSTALLS = (
    "Program Files/LibreOffice/program/soffice.exe",
    "Program Files (x86)/LibreOffice/program/soffice.exe",
    "Users/*/scoop/apps/libreoffice/current/LibreOffice/program/soffice.exe",
)


def find_soffice() -> str | None:
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    for name in ("soffice", "libreoffice"):
        if found := shutil.which(name):
            return found
    installs = wsl.windows_installs(*WSL_INSTALLS)
    return str(installs[0]) if installs else None


def pdf_command(soffice: str, src: Path, outdir: Path, profile: Path) -> list[str]:
    """Convert `src` to `outdir/<stem>.pdf` with a private profile, so two
    conversions can run at once."""
    if wsl.is_windows_exe(soffice):
        profile_uri = PureWindowsPath(wsl.path_for(soffice, profile)).as_uri()
    else:
        profile_uri = Path(profile).as_uri()
    return [
        soffice, f"-env:UserInstallation={profile_uri}", "--headless", "--convert-to", "pdf",
        "--outdir", wsl.path_for(soffice, outdir), wsl.path_for(soffice, src),
    ]
