#!/usr/bin/env sh
# Bootstrap the tools this plugin needs: uv, then (via uv sync) the Python
# environment, then the tesseract binary + its script-detection (osd) data,
# then the soffice (LibreOffice) binary needed to rasterize pptx slides.
# POSIX sh, no uv/python dependency on purpose — this is the thing that
# checks whether uv itself exists, so it can't depend on uv to run.
#
# Usage: check_env.sh <plugin-root>
# Exit codes: 0 = ready to proceed (possibly in text-only / no-pptx-render
# mode if tesseract/soffice could not be installed); 1 = fatal, uv itself
# could not be obtained.

set -eu

PLUGIN_ROOT="${1:?usage: check_env.sh <plugin-root>}"

log() { printf '[env] %s\n' "$1"; }

# --- uv -----------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    log "uv not found, installing via the official installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || true
    # The installer places uv in ~/.local/bin; that's usually already on
    # PATH, but pick it up explicitly in case this shell hasn't re-sourced
    # its profile yet.
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    log "FATAL: uv still not on PATH after install attempt. Install it"
    log "manually (https://docs.astral.sh/uv/) and re-run."
    exit 1
fi
log "uv: ok ($(uv --version))"

# uv fetches a matching Python per pyproject.toml's requires-python itself —
# no separate Python bootstrap step needed.
uv sync --project "$PLUGIN_ROOT" --quiet
log "python env: synced"

can_sudo() { sudo -n true >/dev/null 2>&1; }

# --- tesseract ------------------------------------------------------------
if command -v tesseract >/dev/null 2>&1; then
    log "tesseract: ok ($(tesseract --version 2>&1 | head -n1))"
else
    log "tesseract not found, attempting to install..."

    install_cmd=""
    if command -v apt-get >/dev/null 2>&1; then
        install_cmd="apt-get install -y tesseract-ocr"
    elif command -v pacman >/dev/null 2>&1; then
        install_cmd="pacman -S --noconfirm tesseract tesseract-data-osd"
    elif command -v dnf >/dev/null 2>&1; then
        install_cmd="dnf install -y tesseract"
    elif command -v zypper >/dev/null 2>&1; then
        install_cmd="zypper install -y tesseract-ocr"
    elif command -v brew >/dev/null 2>&1; then
        install_cmd="brew install tesseract"  # brew's formula ships English + osd data already
    fi

    if [ -z "$install_cmd" ]; then
        log "no supported package manager found (checked apt-get, pacman, dnf, zypper, brew)."
        log "install tesseract manually; continuing in text-only mode until then."
    elif [ "${install_cmd%%[ ]*}" = "brew" ]; then
        if brew install tesseract; then
            log "tesseract: installed via brew"
        else
            log "install attempt failed; continuing in text-only mode until tesseract is installed."
        fi
    elif can_sudo; then
        if sudo -n sh -c "$install_cmd"; then
            log "tesseract: installed via ${install_cmd%% *}"
        else
            log "install attempt failed; continuing in text-only mode until tesseract is installed."
        fi
    else
        log "no cached sudo credentials (non-interactive session can't prompt for a password)."
        log "run manually: sudo $install_cmd"
    fi
fi

# --- soffice (LibreOffice, needed only for pptx -> slide-PNG rendering) ----
if command -v soffice >/dev/null 2>&1; then
    log "soffice: ok"
    exit 0
fi

log "soffice not found, attempting to install (only needed for pptx documents)..."

office_cmd=""
if command -v apt-get >/dev/null 2>&1; then
    office_cmd="apt-get install -y libreoffice"
elif command -v pacman >/dev/null 2>&1; then
    office_cmd="pacman -S --noconfirm libreoffice-fresh"
elif command -v dnf >/dev/null 2>&1; then
    office_cmd="dnf install -y libreoffice"
elif command -v zypper >/dev/null 2>&1; then
    office_cmd="zypper install -y libreoffice"
elif command -v brew >/dev/null 2>&1; then
    office_cmd="brew install --cask libreoffice"
fi

if [ -z "$office_cmd" ]; then
    log "no supported package manager found for LibreOffice."
    log "install it manually if you plan to process pptx documents; continuing."
    exit 0
fi

if [ "${office_cmd%%[ ]*}" = "brew" ]; then
    if brew install --cask libreoffice; then
        log "soffice: installed via brew"
    else
        log "install attempt failed; pptx documents will fail to render until LibreOffice is installed."
    fi
elif can_sudo; then
    if sudo -n sh -c "$office_cmd"; then
        log "soffice: installed via ${office_cmd%% *}"
    else
        log "install attempt failed; pptx documents will fail to render until LibreOffice is installed."
    fi
else
    log "no cached sudo credentials (non-interactive session can't prompt for a password)."
    log "run manually: sudo $office_cmd"
fi

exit 0
