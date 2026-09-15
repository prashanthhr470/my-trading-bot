$ErrorActionPreference = "Continue"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$PYTHON = Join-Path $ROOT ".venv\Scripts\python.exe"
$RUNTIME = Join-Path $ROOT "hafnot_final_runtime.py"
$LOG_DIR = Join-Path $ROOT "data\runtime"
$LOG_FILE = Join-Path $LOG_DIR "hafnot_market_watchdog.log"

$STALE_MINUTES = 15
$CHECK_SECONDS = 60

New-Item `
    -ItemType Directory `
    -Path $LOG_DIR `
    -Force | Out-Null

function Write-WatchdogLog {

    param(
        [string]$Message
    )

    $TIME = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    $LINE = "[$TIME] $Message"

    Add-Content `
        -Path $LOG_FILE `
        -Value $LINE

    Write-Host $LINE
}

Write-WatchdogLog "HAFNOT MARKET WATCHDOG STARTED"

while ($true) {

    try {

        $NOW = Get-Date

        # Weekend protection.
        $DAY = $NOW.DayOfWeek

        if (
            $DAY -eq [System.DayOfWeek]::Saturday -or
            $DAY -eq [System.DayOfWeek]::Sunday
        ) {

            Write-WatchdogLog `
                "MARKET CLOSED WINDOW - no restart action"

            Start-Sleep -Seconds $CHECK_SECONDS
            continue
        }

        $FILES = Get-ChildItem `
            "$ROOT\data\openapi\*_market_events.jsonl" `
            -ErrorAction SilentlyContinue

        if (!$FILES) {

            Write-WatchdogLog `
                "WARNING - no market event files found"

            Start-Sleep -Seconds $CHECK_SECONDS
            continue
        }

        $NEWEST = $FILES |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

        $AGE = (
            $NOW - $NEWEST.LastWriteTime
        ).TotalMinutes

        $MARKET_PROCESS = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "python.exe" -and
            $_.CommandLine -match "multi_symbol_market_data.py"
        }

        if (!$MARKET_PROCESS) {

            Write-WatchdogLog `
                "WARNING - market data process not detected"

            Write-WatchdogLog `
                "Starting HAFNOT runtime..."

            Start-Process `
                -FilePath $PYTHON `
                -ArgumentList "`"$RUNTIME`"" `
                -WorkingDirectory $ROOT
        }
        elseif ($AGE -gt $STALE_MINUTES) {

            Write-WatchdogLog (
                "STALE DATA - newest file: " +
                $NEWEST.Name +
                " age=" +
                [Math]::Round($AGE,2) +
                " minutes"
            )

            Write-WatchdogLog `
                "No automatic kill action performed. Manual review required."

        }
        else {

            Write-WatchdogLog (
                "HEALTHY - newest market event age=" +
                [Math]::Round($AGE,2) +
                " minutes"
            )
        }
    }
    catch {

        Write-WatchdogLog (
            "WATCHDOG ERROR - " +
            $_.Exception.Message
        )
    }

    Start-Sleep -Seconds $CHECK_SECONDS
}
