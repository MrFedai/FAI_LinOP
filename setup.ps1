# FAI_LinOP v3 bootstrap for Windows — skeleton only (CLAUDE.md D3).
# FAI_LinOP v3.0 configures Linux (Arch, Debian, Ubuntu, Fedora). On Windows it only
# reports what it detects; nothing is changed.
$ErrorActionPreference = 'Stop'
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "FAI_LinOP v3.0: Windows support is not implemented (interfaces only)."
    Write-Host "Install uv (https://docs.astral.sh/uv/) to run 'linop doctor'."
    exit 3
}
& uv run --quiet --project $PSScriptRoot linop doctor
exit 3
