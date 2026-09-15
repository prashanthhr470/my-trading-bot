$ErrorActionPreference = "Continue"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host ""
Write-Host "============================================================"
Write-Host " HAFNOT COMPLETE SYSTEM STATUS"
Write-Host "============================================================"
Write-Host ""

Write-Host "CURRENT TIME:"
Get-Date

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " HAFNOT PROCESSES"
Write-Host "------------------------------------------------------------"

Get-CimInstance Win32_Process |
Where-Object {
    $_.Name -in "python.exe","pythonw.exe" -and
    ($_.CommandLine -match "hafnot_final_runtime" -or
     $_.CommandLine -match "hafnot_ctrader_worker" -or
     $_.CommandLine -match "multi_symbol_market_data" -or
     $_.CommandLine -match "hafnot_live_bar_feed" -or
     $_.CommandLine -match "hafnot_storage_guard" -or
     $_.CommandLine -match "multi_symbol_paper")
} |
Select-Object ProcessId,ParentProcessId,CommandLine |
Format-List

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " MARKET EVENT FILES"
Write-Host "------------------------------------------------------------"

$EVENT_FILES = Get-ChildItem `
    "$ROOT\data\openapi\*_market_events.jsonl" `
    -ErrorAction SilentlyContinue

if ($EVENT_FILES) {

    $EVENT_FILES |
    Select-Object Name,Length,LastWriteTime |
    Sort-Object LastWriteTime -Descending |
    Format-Table -AutoSize
}
else {
    Write-Host "[WARNING] No market event files found."
}

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " LIVE BAR FILES (what the strategy actually reads)"
Write-Host "------------------------------------------------------------"

$BAR_FILES = Get-ChildItem "$ROOT\data\live\bars\*.json" -ErrorAction SilentlyContinue

if ($BAR_FILES) {

    $NOW_BARS = Get-Date

    $BAR_ROWS = @()

    foreach ($BAR_FILE in $BAR_FILES) {

        $BAR_COUNT = "?"

        try {
            $BAR_COUNT = (Get-Content $BAR_FILE.FullName -Raw | ConvertFrom-Json).bar_count
        }
        catch {
            $BAR_COUNT = "unreadable"
        }

        $BAR_ROWS += [PSCustomObject]@{
            File       = $BAR_FILE.Name
            Bars       = $BAR_COUNT
            AgeMinutes = [Math]::Round(($NOW_BARS - $BAR_FILE.LastWriteTime).TotalMinutes, 1)
        }
    }

    $BAR_ROWS |
    Sort-Object AgeMinutes |
    Format-Table -AutoSize
}
else {
    Write-Host "[WARNING] No live bar files yet - the strategy will report WAIT."
    Write-Host "          Check that hafnot_live_bar_feed.py is running."
}

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " PAPER ENGINE STATE"
Write-Host "------------------------------------------------------------"

$STATE_FILE = "$ROOT\data\paper\multi_symbol_state.json"

if (Test-Path $STATE_FILE) {

    Get-Item $STATE_FILE |
    Select-Object FullName,Length,LastWriteTime |
    Format-List
}
else {
    Write-Host "[WARNING] Paper state file missing."
}

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " RUNTIME HEALTH"
Write-Host "------------------------------------------------------------"

$HEALTH_LOG = "$ROOT\data\runtime\hafnot_final_runtime.log"

if (Test-Path $HEALTH_LOG) {
    Get-Content $HEALTH_LOG -Tail 10
}
else {
    Write-Host "[WARNING] Runtime health log missing."
}

Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host " MARKET DATA FRESHNESS"
Write-Host "------------------------------------------------------------"

if ($EVENT_FILES) {

    $NOW = Get-Date
    $RESULTS = @()

    foreach ($FILE in $EVENT_FILES) {

        $AGE = $NOW - $FILE.LastWriteTime

        $RESULTS += [PSCustomObject]@{
            SymbolFile = $FILE.Name
            LastUpdate = $FILE.LastWriteTime
            AgeMinutes = [Math]::Round($AGE.TotalMinutes,2)
        }
    }

    $RESULTS |
    Sort-Object AgeMinutes |
    Format-Table -AutoSize
}

Write-Host ""
Write-Host "============================================================"
Write-Host " STATUS CHECK COMPLETE"
Write-Host "============================================================"
