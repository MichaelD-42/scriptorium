---
name: setup-environment
description: Bootstrap the tools this plugin needs (uv, the Python env, tesseract, and the right OCR language pack) before running the pipeline. Use once at the very start of the queue loop, and again per-document before OCR if the document needs a language you haven't checked yet.
---

# Setup Environment

Closes the "pipeline stalls mid-run because a system dependency is missing"
failure mode — this used to require a manual `sudo pacman -S
tesseract-data-eng` outside the loop; now the harness detects and installs
it itself.

Two stages, because the first stage has to work *without* the tool the rest
of the pipeline depends on:

## 1. `check_env.sh` / `check_env.ps1` — once, before the queue loop

On Linux/macOS:

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/setup-environment/scripts/check_env.sh" "${CLAUDE_PLUGIN_ROOT}"
```

On Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}\skills\setup-environment\scripts\check_env.ps1" "${CLAUDE_PLUGIN_ROOT}"
```

Plain POSIX `sh` / plain PowerShell, not `uv run` — this is the thing
checking whether `uv` itself exists, so it can't depend on `uv` to run it.
Same contract on both platforms, in order:

1. `uv` missing → installs it via `scoop` if available (Windows), otherwise
   the official installer, re-checks. Still missing → **exits 1** (fatal —
   nothing downstream can run without it).
2. `uv sync` — this also fetches a matching Python per `pyproject.toml`, so
   there's no separate Python bootstrap step.
3. `tesseract` binary missing → detects the package manager (`apt-get`,
   `pacman`, `dnf`, `zypper`, `brew` on POSIX; `scoop`, `winget`, `choco` on
   Windows, each checked in that order — `scoop` first since it needs no
   admin prompt) and installs the base package. No sudo/admin available, or
   no manager recognized → prints the manual command and continues (soft —
   a document with no scanned pages never needs tesseract at all, so this
   shouldn't block the whole run).
4. `soffice` (LibreOffice) binary missing → same package-manager detection,
   installs the base package. Needed only to rasterize **pptx** slides
   (`render-pages` shells out to `soffice --headless --convert-to pdf`
   first for that format); a document with no pptx never needs it. Missing
   with no way to install → prints the manual command and **exits 0** (soft
   for the same reason as tesseract — this only blocks pptx documents,
   never the whole run).

## 2. `ensure_language.py` — per document, only when triage found an `ocr`-tier page

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" python \
  "${CLAUDE_PLUGIN_ROOT}/skills/setup-environment/scripts/ensure_language.py" work/<doc>/pages/page5.png \
  [--extra deu,fra]
```

Runs tesseract's own OSD (orientation & script detection) on one
representative OCR-tier page to guess the **script** (Latin, Han,
Cyrillic, ...), maps it to a best-guess language code, and installs the
matching tesseract language pack if missing (per-manager package name
table, e.g. `tesseract-data-deu` on Arch vs `tesseract-ocr-deu` on
Debian). Pass `--extra` with the plugin's `userConfig.ocr_languages` (if
the user configured any) — OSD only tells you the script, not the exact
language, so a Latin-script German document still detects as "Latin" and
needs to be told explicitly.

**This is coarse, not exact language ID.** The goal is closing the
missing-language-pack failure mode, not solving language identification.

**Windows note:** `scoop`/`winget`/`choco` don't ship per-language tesseract
packages, so a missing language on Windows (or on any OS with no supported
package manager at all) falls back to downloading `<lang>.traineddata`
directly into a user-writable tessdata dir — no admin rights needed. When
that fallback dir ends up holding the wanted language(s), the JSON also
reports `tessdata_prefix` (its path); pass that through to `ocr-page` as
`--tessdata-dir` alongside `--lang`. `tessdata_prefix: null` means the
system tessdata dir already covers everything and no override is needed.

Prints one JSON object:

```json
{"detected_script": "Latin", "requested_languages": ["eng"], "newly_installed": ["eng"], "still_missing": [], "lang_flag": "eng", "tessdata_prefix": null}
```

Pass `lang_flag` straight through to every `ocr-page` skill invocation for
this document as `--lang`, and `tessdata_prefix` (if not `null`) as
`--tessdata-dir`.
