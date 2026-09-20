# Build the single-file fmri-qa-run.exe. The Windows twin of `make bundle`,
# for a machine with no make: the same two commands, so change them together.
# See packages/fmri-qa-launcher/bundle/fmri-qa-run.spec for what goes in and why.
#
# Usage, from anywhere inside the checkout:
#     .\scripts\bundle.ps1
# If script execution is disabled on this machine (the Windows default):
#     powershell -ExecutionPolicy Bypass -File scripts\bundle.ps1
#
# Requires uv (`winget install astral-sh.uv`). uv provisions the pinned Python
# and builds from an isolated environment resolved from uv.lock, so nothing
# else needs installing and the state of any local .venv does not matter.
#
# This file is ASCII on purpose: Windows PowerShell 5.1 reads a script with no
# byte-order mark as the ANSI code page, not UTF-8.

$ErrorActionPreference = 'Stop'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found on PATH. Install it with: winget install astral-sh.uv'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repoRoot 'dist\bundle\fmri-qa-run.exe'

# The spec and the output paths are relative to the workspace root.
Push-Location $repoRoot
try {
    uv run --isolated --locked --all-packages --no-default-groups --group bundle `
        pyinstaller --noconfirm --distpath dist/bundle --workpath build/bundle `
        packages/fmri-qa-launcher/bundle/fmri-qa-run.spec
    # $ErrorActionPreference does not cover a native command's exit code in
    # Windows PowerShell 5.1, so a failed build has to be checked for by hand.
    # Do not add `2>&1` above to capture the log: PyInstaller writes all of its
    # progress to stderr, and 5.1 turns redirected stderr into error records,
    # which 'Stop' would then end the build on at its first INFO line.
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed (exit code $LASTEXITCODE)."
    }

    # The cheapest proof the result starts and found its own metadata. Slow
    # (seconds) because a one-file executable unpacks itself on every launch.
    & $exe --version
    if ($LASTEXITCODE -ne 0) {
        throw "$exe was built but does not start (exit code $LASTEXITCODE)."
    }

    Write-Host "Built $exe"
}
finally {
    Pop-Location
}
