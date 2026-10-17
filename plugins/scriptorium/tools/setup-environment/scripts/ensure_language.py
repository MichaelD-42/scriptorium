#!/usr/bin/env python3
"""Detect the script of a representative OCR-tier page and make sure the
matching tesseract language pack(s) are installed, installing them if not.

This is coarse by design: tesseract's OSD (orientation & script detection)
tells you the *script* (Latin, Han, Cyrillic, ...), not the exact language —
Latin-script documents in German, French, etc. all detect as "Latin" and
fall back to `eng` unless you pass --extra with additional language codes
(the orchestrator does this from the plugin's userConfig.ocr_languages).
The point is closing the "pipeline silently fails because a language pack
is missing" failure mode, not solving language identification exactly.

Prints one JSON object to stdout: the detected script, the resulting
"+"-joined language string for ocr.py's --lang flag, and which packs (if
any) were newly installed.
"""

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import tesseract as tesseract_lib  # noqa: E402

SCRIPT_TO_LANG = {
    "Latin": "eng",
    "Han": "chi_sim",
    "Cyrillic": "rus",
    "Arabic": "ara",
    "Hiragana": "jpn",
    "Katakana": "jpn",
    "Hangul": "kor",
    "Devanagari": "hin",
    "Greek": "ell",
}
DEFAULT_LANG = "eng"

# package name for <lang> per package manager; "*" installs everything for
# that manager (used where the distro doesn't split language packs finely)
PACKAGE_NAME = {
    "apt-get": "tesseract-ocr-{lang}",
    "pacman": "tesseract-data-{lang}",
    "dnf": "tesseract-langpack-{lang}",
    "zypper": "tesseract-ocr-traineddata-{lang}",
    "brew": "tesseract-lang",  # bundles every language in one formula
}

# Windows package managers don't split tesseract language packs at all
# (winget/choco just reinstall the same bundle) — a missing language on
# Windows always falls through to the direct traineddata download below.
WINDOWS_MANAGERS = ("scoop", "winget", "choco")

TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"


def _tesseract_cmd() -> str:
    return tesseract_lib.find_tesseract() or "tesseract"


def detect_script(image_path: str) -> str | None:
    try:
        result = subprocess.run(
            [_tesseract_cmd(), image_path, "stdout", "--psm", "0"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Script:"):
            return line.split(":", 1)[1].strip()
    return None


def installed_languages() -> set[str]:
    try:
        result = subprocess.run([_tesseract_cmd(), "--list-langs"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return set()
    lines = result.stdout.splitlines()[1:]  # first line is "List of available languages ..."
    installed = {line.strip() for line in lines if line.strip() and line.strip() != "osd"}
    # A prior run may have downloaded packs straight into the user-writable
    # fallback dir rather than the system tessdata dir tesseract just
    # reported on — count those too.
    fallback_dir = tesseract_lib.user_tessdata_dir()
    if fallback_dir.is_dir():
        installed |= {p.stem for p in fallback_dir.glob("*.traineddata")}
    return installed


def detect_package_manager() -> str | None:
    if sys.platform == "win32":
        for manager in WINDOWS_MANAGERS:
            if shutil.which(manager):
                return manager
        return None
    for manager in ("apt-get", "pacman", "dnf", "zypper", "brew"):
        if shutil.which(manager):
            return manager
    return None


def can_sudo() -> bool:
    if sys.platform == "win32" or not shutil.which("sudo"):
        return False
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0


def manager_install_argv(manager: str, package: str) -> list[str]:
    if manager == "pacman":
        return ["pacman", "-S", "--noconfirm", package]
    return [manager, "install", "-y", package]


def install_language(lang: str, manager: str) -> bool:
    if manager in WINDOWS_MANAGERS:
        # No per-language package on Windows — handled by download_language().
        return False
    package = PACKAGE_NAME[manager].format(lang=lang)
    if manager == "brew":
        cmd = ["brew", "install", package]
    elif can_sudo():
        cmd = ["sudo", "-n", *manager_install_argv(manager, package)]
    else:
        manual = " ".join(manager_install_argv(manager, package))
        print(f"[ensure_language] no cached sudo credentials — install manually: sudo {manual}", file=sys.stderr)
        return False
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def download_language(lang: str) -> bool:
    """Admin-free fallback: fetch <lang>.traineddata straight into the
    user-writable tessdata dir. Used on Windows (no per-language package
    manager support) and anywhere else install_language() couldn't write to
    the system tessdata dir."""
    target_dir = tesseract_lib.user_tessdata_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{lang}.traineddata"
    try:
        urllib.request.urlretrieve(TESSDATA_URL.format(lang=lang), target)
        return target.is_file() and target.stat().st_size > 0
    except OSError as exc:
        print(f"[ensure_language] download failed for {lang}: {exc}", file=sys.stderr)
        return False


def resolve_tessdata_override(languages: list[str]) -> str | None:
    """Only reached on Windows or when no package manager was found. If the
    tesseract install's own tessdata dir already has every wanted language,
    no override is needed. Otherwise assemble a self-sufficient dir (system
    files copied in where available, downloaded otherwise) and return its
    path for ocr.py's --tessdata-dir."""
    tesseract_path = tesseract_lib.find_tesseract()
    system_dir = tesseract_lib.tessdata_dir_for(tesseract_path) if tesseract_path else None
    if system_dir and all((system_dir / f"{lang}.traineddata").is_file() for lang in languages):
        return None

    fallback_dir = tesseract_lib.user_tessdata_dir()
    if not any((fallback_dir / f"{lang}.traineddata").is_file() for lang in languages):
        return None  # nothing actually landed there — no point overriding

    fallback_dir.mkdir(parents=True, exist_ok=True)
    for lang in languages:
        target = fallback_dir / f"{lang}.traineddata"
        if target.is_file():
            continue
        if system_dir and (system_dir / f"{lang}.traineddata").is_file():
            shutil.copy(system_dir / f"{lang}.traineddata", target)
        else:
            download_language(lang)
    return str(fallback_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="path to a rendered PNG of a representative OCR-tier page")
    parser.add_argument("--extra", default="", help="comma-separated additional tesseract language codes to ensure")
    args = parser.parse_args()

    script = detect_script(args.image)
    wanted = {SCRIPT_TO_LANG.get(script, DEFAULT_LANG)}
    wanted |= {lang.strip() for lang in args.extra.split(",") if lang.strip()}

    installed = installed_languages()
    missing = sorted(wanted - installed)
    newly_installed = []

    manager = detect_package_manager()
    # Windows managers don't split language packs (see WINDOWS_MANAGERS) and
    # a missing manager means nothing else can install it either — both
    # cases fall through to the direct traineddata download below.
    use_download_fallback = sys.platform == "win32" or manager is None

    if missing and manager and manager not in WINDOWS_MANAGERS:
        for lang in missing:
            if install_language(lang, manager):
                newly_installed.append(lang)
        missing = sorted(wanted - installed_languages())

    if missing and use_download_fallback:
        for lang in missing:
            if download_language(lang):
                newly_installed.append(lang)

    # Whatever is now actually installed (best-effort) wins; anything still
    # missing after a failed install attempt is dropped rather than passed
    # to tesseract, where it would just error out.
    final_installed = installed_languages()
    languages = sorted(wanted & final_installed) or [DEFAULT_LANG]

    tessdata_prefix = resolve_tessdata_override(languages) if use_download_fallback else None

    print(json.dumps({
        "detected_script": script,
        "requested_languages": sorted(wanted),
        "newly_installed": newly_installed,
        "still_missing": sorted(wanted - final_installed),
        "lang_flag": "+".join(languages),
        "tessdata_prefix": tessdata_prefix,
    }))


if __name__ == "__main__":
    main()
