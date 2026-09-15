$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

$PYTHON = Join-Path $ROOT ".venv\Scripts\python.exe"
$RUNTIME = Join-Path $ROOT "hafnot_final_runtime.py"

Write-Host ""
Write-Host "============================================================"
Write-Host " STARTING HAFNOT"
Write-Host "============================================================"
Write-Host ""

if (!(Test-Path $PYTHON)) {
    throw "Python missing: $PYTHON"
}

if (!(Test-Path $RUNTIME)) {
    throw "Runtime missing: $RUNTIME"
}

$EXISTING = Get-CimInstance Win32_Process |
Where-Object {
    $_.Name -eq "python.exe" -and
    $_.CommandLine -match "hafnot_final_runtime.py"
}

if ($EXISTING) {

    Write-Host "[INFO] HAFNOT runtime is already running."
    Write-Host ""

    $EXISTING |
    Select-Object ProcessId,ParentProcessId,CommandLine |
    Format-List

    exit 0
}

# Children left behind by an earlier supervisor (found 2026-09-12: two
# multi_symbol_market_data.py processes still connected to cTrader). Starting
# now would add a second broker connection - and possibly a second paper
# engine writing the same journal and account files.
$ORPHANS = Get-CimInstance Win32_Process |
Where-Object {
    $_.Name -in "python.exe","pythonw.exe" -and
    $_.CommandLine -match "multi_symbol_paper|hafnot_ctrader_worker|multi_symbol_market_data|hafnot_live_bar_feed|hafnot_storage_guard"
}

if ($ORPHANS) {

    Write-Host "[FAIL] HAFNOT processes are running without a supervisor:"
    Write-Host ""

    $ORPHANS |
    Select-Object ProcessId,ParentProcessId,CommandLine |
    Format-List

    Write-Host "Starting now would run a second copy. Run .\STOP_HAFNOT.ps1 first."
    exit 1
}

Write-Host "[START] Launching HAFNOT runtime..."

Start-Process `
    -FilePath $PYTHON `
    -ArgumentList "`"$RUNTIME`"" `
    -WorkingDirectory $ROOT

Write-Host "[PASS] HAFNOT launch command sent."
