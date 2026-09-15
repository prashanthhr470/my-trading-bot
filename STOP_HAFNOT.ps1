$ErrorActionPreference = "Continue"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host ""
Write-Host "============================================================"
Write-Host " STOPPING HAFNOT"
Write-Host "============================================================"
Write-Host ""

# The supervisor starts its children with CREATE_NEW_PROCESS_GROUP, so
# stopping only the supervisor leaves the paper engine and cTrader worker
# running as orphans - and a later START_HAFNOT would then run a SECOND
# paper engine against the same journal/account files. Every HAFNOT
# process is therefore matched by script name and stopped, children first
# so the supervisor cannot try to restart one mid-shutdown.

function Get-HafnotProcesses {
    param([string[]]$Scripts)

    $matched = @()

    foreach ($proc in (Get-CimInstance Win32_Process)) {

        if ($proc.Name -notin "python.exe", "pythonw.exe") {
            continue
        }

        if (-not $proc.CommandLine) {
            continue
        }

        foreach ($script in $Scripts) {

            if ($proc.CommandLine -match $script) {
                $matched += $proc
                break
            }
        }
    }

    return $matched
}

# Children first, supervisor last. multi_symbol_market_data is launched BY
# hafnot_ctrader_worker; Stop-Process does not stop a process tree, so it must
# be matched itself - otherwise it survives holding its own broker connection
# (found 2026-09-12: two such orphans still connected to cTrader). It is
# listed after the worker so a dying worker cannot relaunch it.
$CHILD_SCRIPTS = @(
    "multi_symbol_paper",
    "hafnot_ctrader_worker",
    "multi_symbol_market_data",
    "hafnot_live_bar_feed",
    "hafnot_download_historical_data",
    "hafnot_storage_guard"
)

$SUPERVISOR_SCRIPTS = @(
    "hafnot_final_runtime"
)

$BEFORE = Get-HafnotProcesses -Scripts ($CHILD_SCRIPTS + $SUPERVISOR_SCRIPTS)

if (-not $BEFORE -or $BEFORE.Count -eq 0) {

    Write-Host "[INFO] No HAFNOT processes are running. Nothing to stop."
    Write-Host ""
    exit 0
}

Write-Host "[FOUND] HAFNOT processes currently running:"
Write-Host ""

$BEFORE |
Select-Object ProcessId, ParentProcessId, CommandLine |
Format-List

Write-Host "[STOP] Stopping child processes..."

foreach ($proc in (Get-HafnotProcesses -Scripts $CHILD_SCRIPTS)) {

    Write-Host ("  -> PID " + $proc.ProcessId + " (child)")

    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    }
    catch {
        Write-Host ("     [WARN] Could not stop PID " + $proc.ProcessId + ": " + $_.Exception.Message)
    }
}

Start-Sleep -Seconds 2

Write-Host "[STOP] Stopping supervisor..."

foreach ($proc in (Get-HafnotProcesses -Scripts $SUPERVISOR_SCRIPTS)) {

    Write-Host ("  -> PID " + $proc.ProcessId + " (supervisor)")

    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    }
    catch {
        Write-Host ("     [WARN] Could not stop PID " + $proc.ProcessId + ": " + $_.Exception.Message)
    }
}

Start-Sleep -Seconds 2

$AFTER = Get-HafnotProcesses -Scripts ($CHILD_SCRIPTS + $SUPERVISOR_SCRIPTS)

Write-Host ""

if (-not $AFTER -or $AFTER.Count -eq 0) {

    Write-Host "[PASS] All HAFNOT processes stopped."
    Write-Host ""
    Write-Host "You can now start it again with:"
    Write-Host "  .\START_HAFNOT.ps1"
}
else {

    Write-Host "[FAIL] Some HAFNOT processes are still running:"
    Write-Host ""

    $AFTER |
    Select-Object ProcessId, CommandLine |
    Format-List

    Write-Host "Do NOT run START_HAFNOT.ps1 yet - starting a second copy"
    Write-Host "while one of these is alive would run two paper engines"
    Write-Host "against the same files."
}

Write-Host ""
Write-Host "============================================================"
Write-Host ""
