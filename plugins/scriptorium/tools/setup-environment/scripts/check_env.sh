#!/usr/bin/env sh
# Bootstrap the tools this plugin needs: uv, then (via uv sync) the Python
# environment, then the tesseract binary + its script-detection (osd) data,
# then the soffice (LibreOffice) binary needed to rasterize pptx slides.
# POSIX sh, no uv/python dependency on purpose — this is the thing that
# checks whether uv itself exists, so it can't depend on uv to run.
# Writes runs/env.json: the tesseract and soffice paths the scripts will
# use, null when missing.
#
# Usage: check_env.sh <plugin-root>
# Exit codes: 0 = ready to proceed (possibly in text-only / no-pptx-render
# mode if tesseract/soffice could not be installed); 1 = fatal, uv itself
# could not be obtained, or `uv sync` failed.

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
if ! uv sync --project "$PLUGIN_ROOT" --quiet; then
    log "FATAL: uv sync failed; the Python environment is not usable."
    exit 1
fi
log "python env: synced"

# --- tesseract and soffice ------------------------------------------------

can_sudo() { sudo -n true >/dev/null 2>&1; }

# The path the scripts will use (lib/tesseract.py, lib/office.py): the
# SCRIPTORIUM_* variable, then PATH, then under WSL a Windows install.
# With no argument: writes runs/env.json and prints its path.
find_tool() {
    uv run --project "$PLUGIN_ROOT" python "$PLUGIN_ROOT/tools/setup-environment/scripts/find_tools.py" "$@" || true
}

# The install command for the first package manager found:
# <apt-get pkg> <pacman pkgs> <dnf pkg> <zypper pkg> <brew args>
install_cmd() {
    if command -v apt-get >/dev/null 2>&1; then echo "apt-get install -y $1"
    elif command -v pacman >/dev/null 2>&1; then echo "pacman -S --noconfirm $2"
    elif command -v dnf >/dev/null 2>&1; then echo "dnf install -y $3"
    elif command -v zypper >/dev/null 2>&1; then echo "zypper install -y $4"
    elif command -v brew >/dev/null 2>&1; then echo "brew install $5"
    fi
}

# What runs as root: apt-get needs its package index refreshed first (a
# fresh image has none).
root_cmd() {
    case "$1" in
        apt-get*) echo "apt-get update && $1" ;;
        *) echo "$1" ;;
    esac
}

# brew needs no root. Otherwise only cached sudo (a non-interactive session
# can't prompt for a password); sudo resets the environment, so the proxy
# variables are passed on explicitly (apt reads the lower-case names).
run_install() {
    case "$1" in
        brew*) $1 ;;
        *)
            can_sudo || return 1
            sudo -n env http_proxy="${http_proxy:-${HTTP_PROXY:-}}" https_proxy="${https_proxy:-${HTTPS_PROXY:-}}" \
                sh -c "$(root_cmd "$1")"
            ;;
    esac
}

# ensure_tool <tool> <env var> <needed for> <no-root option> <install_cmd args...>
ensure_tool() {
    tool=$1 var=$2 needed_for=$3 no_root=$4
    shift 4
    found=$(find_tool "$tool")
    case "$found" in
        "") ;;
        *.exe|*.com) log "$tool: ok, Windows install at $found (set $var to this path to pin it)"; return 0 ;;
        *) log "$tool: ok ($found)"; return 0 ;;
    esac
    log "$tool not found, attempting to install (needed for $needed_for)..."
    cmd=$(install_cmd "$@")
    if [ -n "$cmd" ] && run_install "$cmd"; then
        found=$(find_tool "$tool")
    fi
    if [ -n "$found" ]; then
        log "$tool: installed via ${cmd%% *} ($found)"
        return 0
    fi
    log "$tool is missing, so $needed_for will not work. Continuing. To fix it:"
    if [ -n "$cmd" ] && [ "${cmd%% *}" != brew ]; then
        log "  - with root: sudo sh -c '$(root_cmd "$cmd")'"
    fi
    log "  - without root: install it on Windows (under WSL it is found in Program Files or scoop)"
    log "    or anywhere in your home, and set $var to the program's path"
    log "  - without root: $no_root"
}

ensure_tool tesseract SCRIPTORIUM_TESSERACT "OCR of scanned pages and images" \
    "micromamba install -c conda-forge tesseract into your home, then set SCRIPTORIUM_TESSERACT" \
    tesseract-ocr "tesseract tesseract-data-osd" tesseract tesseract-ocr tesseract
ensure_tool soffice SCRIPTORIUM_SOFFICE "pptx slide rendering" \
    "convert the pptx to PDF yourself and save it as work/<doc>/<doc>.pdf (render.py reuses it)" \
    libreoffice libreoffice-fresh libreoffice libreoffice "--cask libreoffice"

log "tool paths: $(find_tool)"
exit 0
