# Bootstrap the tools this plugin needs: uv, then (via uv sync) the Python
# environment, then the tesseract binary, then the soffice (LibreOffice)
# binary needed to rasterize pptx slides. PowerShell mirror of
# check_env.sh — same contract, same exit codes.
#
# Usage: check_env.ps1 <plugin-root>
# Exit codes: 0 = ready to proceed (possibly in text-only / no-pptx-render
# mode if tesseract/soffice could not be installed); 1 = fatal, uv itself
# could not be obtained.

param(
    [Parameter(Mandatory = $true)]
    [string]$PluginRoot
)

$ErrorActionPreference = "Stop"

function Log($msg) {
    Write-Host "[env] $msg"
}

# --- uv -------------------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if (Get-Command scoop -ErrorAction SilentlyContinue) {
        Log "uv not found, installing via scoop..."
        scoop install uv
    } else {
        Log "uv not found, installing via the official installer..."
        try {
            Invoke-Expression (Invoke-RestMethod https://astral.sh/uv/install.ps1)
        } catch {
            Log "uv installer failed: $_"
        }
        # The installer places uv in %USERPROFILE%\.local\bin; pick it up
        # explicitly in case this session hasn't refreshed its PATH yet.
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Log "FATAL: uv still not on PATH after install attempt. Install it"
    Log "manually (https://docs.astral.sh/uv/) and re-run."
    exit 1
}
Log "uv: ok ($(uv --version))"

# uv fetches a matching Python per pyproject.toml's requires-python itself —
# no separate Python bootstrap step needed.
uv sync --project "$PluginRoot" --quiet
Log "python env: synced"

# --- tesseract --------------------------------------------------------------
if (Get-Command tesseract -ErrorAction SilentlyContinue) {
    Log "tesseract: ok ($(& tesseract --version 2>&1 | Select-Object -First 1))"
} else {
    Log "tesseract not found, attempting to install..."

    $installed = $false
    if (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install tesseract
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id UB-Mannheim.TesseractOCR -e --silent `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install tesseract -y
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    } else {
        Log "no supported package manager found (checked scoop, winget, choco)."
        Log "install tesseract manually; continuing in text-only mode until then."
    }

    # Installers frequently finish without this session's PATH knowing about
    # the new binary yet — add the default install dir explicitly.
    $defaultBin = "C:\Program Files\Tesseract-OCR"
    if ((Test-Path $defaultBin) -and ($env:Path -notlike "*$defaultBin*")) {
        $env:Path = "$defaultBin;$env:Path"
    }

    if ($installed -or (Get-Command tesseract -ErrorAction SilentlyContinue)) {
        Log "tesseract: installed"
    } else {
        Log "install attempt failed; continuing in text-only mode until tesseract is installed."
    }
}

# --- soffice (LibreOffice, needed only for pptx -> slide-PNG rendering) ----
if (Get-Command soffice -ErrorAction SilentlyContinue) {
    Log "soffice: ok"
    exit 0
}

Log "soffice not found, attempting to install (only needed for pptx documents)..."

$officeInstalled = $false
if (Get-Command scoop -ErrorAction SilentlyContinue) {
    scoop install libreoffice
    if ($LASTEXITCODE -eq 0) { $officeInstalled = $true }
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install --id TheDocumentFoundation.LibreOffice -e --silent `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) { $officeInstalled = $true }
} elseif (Get-Command choco -ErrorAction SilentlyContinue) {
    choco install libreoffice-fresh -y
    if ($LASTEXITCODE -eq 0) { $officeInstalled = $true }
} else {
    Log "no supported package manager found (checked scoop, winget, choco)."
    Log "install LibreOffice manually if you plan to process pptx documents; continuing."
    exit 0
}

$defaultOfficeBin = "C:\Program Files\LibreOffice\program"
if ((Test-Path $defaultOfficeBin) -and ($env:Path -notlike "*$defaultOfficeBin*")) {
    $env:Path = "$defaultOfficeBin;$env:Path"
}

if ($officeInstalled -or (Get-Command soffice -ErrorAction SilentlyContinue)) {
    Log "soffice: installed"
} else {
    Log "install attempt failed; pptx documents will fail to render until LibreOffice is installed."
}

exit 0
