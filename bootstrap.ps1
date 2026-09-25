param([switch]$SkipInstall)
$ErrorActionPreference = "Stop"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Error "MISSING: Python 3.10+" }
$py=Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { python -m venv .venv }
if (-not $SkipInstall -and (Test-Path requirements.txt)) { & $py -m pip install -r requirements.txt }
$hasPyproject = Test-Path pyproject.toml
if ($hasPyproject -and (Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path uv.lock)) { uv sync }
& $py scripts/doctor.py
