$ErrorActionPreference = "Continue"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host ""
Write-Host "============================================================"
Write-Host " HAFNOT LIVE MARKET WATCH"
Write-Host " Press CTRL+C to stop"
Write-Host "============================================================"

while ($true) {

    Clear-Host

    $NOW = Get-Date

    Write-Host "============================================================"
    Write-Host " HAFNOT LIVE MARKET WATCH"
    Write-Host "============================================================"

    Write-Host ""
    Write-Host "Time: $NOW"

    $FILES = Get-ChildItem `
        "$ROOT\data\openapi\*_market_events.jsonl" `
        -ErrorAction SilentlyContinue

    if (!$FILES) {

        Write-Host ""
        Write-Host "[WARNING] No market event files found."
    }
    else {

        $RESULTS = @()

        foreach ($FILE in $FILES) {

            $AGE = $NOW - $FILE.LastWriteTime

            $RESULTS += [PSCustomObject]@{
                Symbol = $FILE.Name
                LastUpdate = $FILE.LastWriteTime
                AgeMinutes = [Math]::Round($AGE.TotalMinutes,2)
                SizeMB = [Math]::Round(
                    $FILE.Length / 1MB,
                    2
                )
            }
        }

        Write-Host ""
        Write-Host "MARKET DATA:"

        $RESULTS |
        Sort-Object AgeMinutes |
        Format-Table -AutoSize
    }

    Write-Host ""
    Write-Host "PAPER ENGINE:"

    $STATE = "$ROOT\data\paper\multi_symbol_state.json"

    if (Test-Path $STATE) {

        Get-Item $STATE |
        Select-Object Length,LastWriteTime |
        Format-List
    }

    Start-Sleep -Seconds 10
}
