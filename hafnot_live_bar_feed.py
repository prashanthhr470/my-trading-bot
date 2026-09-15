"""
HAFNOT live bar feed.

THE GAP THIS FILLS
------------------
The decision pipeline needs clean, CLOSED OHLC bars (the same shape the
backtests were validated against). Before this script, nothing produced
them live:

  - app/openapi/market/multi_symbol_market_data.py subscribes to LIVE M1
    trendbars, but those arrive as repeated updates of the same
    still-forming bar, stamped with ARRIVAL time rather than bar-open
    time (verified in data/openapi/*_market_events.jsonl: three events
    inside one quarter-second, all the same bar, with `high` creeping up
    as it formed). Useful for a current price, unusable as a bar series.

  - app/ctrader/market_data.get_market_snapshot fetches proper multi-
    timeframe bars, but only over the cTrader DESKTOP APP's MCP server on
    127.0.0.1:9876. When that app is not running, every call fails - and
    a pipeline built on it silently reports "no trade" forever.

So this script periodically fetches genuinely CLOSED bars over the same
native OpenAPI connection the market worker already uses successfully,
and writes them where the paper/DEMO decision path can read them.

HOW
---
Each refresh runs hafnot_download_historical_data.py as a subprocess -
the already-proven fetch/auth/decode path, not a second copy of it -
pointed at data/live/bars/ via --output-dir so a short live window can
never overwrite the multi-year backtest corpus in
data/historical/bars/.

Must run under .ctrader_venv (Python 3.12), same as the market worker:

    .ctrader_venv\\Scripts\\python.exe hafnot_live_bar_feed.py

The supervisor (hafnot_final_runtime.py) starts it automatically.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CTRADER_PYTHON = ROOT / ".ctrader_venv" / "Scripts" / "python.exe"
DOWNLOADER = ROOT / "hafnot_download_historical_data.py"

LIVE_BARS_DIR = ROOT / "data" / "live" / "bars"

# (symbol, period, days_of_history). `days` must cover the strategy's
# longest lookback: app.quant.core_strategy uses ZONE_LOOKBACK_BARS=4000,
# so M5 needs ~14 calendar days of trading and M15 needs ~42. Rounded up
# for weekends/holidays. Mirrors app.paper.canonical_signal_adapter's
# STRATEGY_FOR_SYMBOL table - if that table changes, change this too.
FEEDS: tuple[tuple[str, str, int], ...] = (
    ("XAUUSD", "M5", 25),
    ("EURUSD", "M15", 60),
    ("GBPUSD", "M15", 60),
    ("USDJPY", "M15", 60),
)

REFRESH_INTERVAL_SECONDS = 300
PER_FETCH_TIMEOUT_SECONDS = 240


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def refresh_one(symbol: str, period: str, days: int) -> bool:
    command = [
        str(CTRADER_PYTHON),
        "-u",
        str(DOWNLOADER),
        "--symbol", symbol,
        "--period", period,
        "--days", str(days),
        "--output-dir", str(LIVE_BARS_DIR),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=PER_FETCH_TIMEOUT_SECONDS,
        )

    except subprocess.TimeoutExpired:
        log(f"[FAIL] {symbol} {period}: fetch timed out after {PER_FETCH_TIMEOUT_SECONDS}s")
        return False

    if completed.returncode != 0:
        tail = (completed.stdout or "").strip().splitlines()[-3:]
        log(f"[FAIL] {symbol} {period}: exit {completed.returncode}")
        for line in tail:
            log(f"        {line}")
        return False

    out_path = LIVE_BARS_DIR / f"{symbol.lower()}_{period.lower()}.json"

    if not out_path.exists():
        log(f"[FAIL] {symbol} {period}: downloader reported success but {out_path.name} is missing")
        return False

    log(f"[PASS] {symbol} {period} -> {out_path.name}")
    return True


def main() -> None:
    print("=" * 70)
    print(" HAFNOT LIVE BAR FEED")
    print("=" * 70)
    print("Interpreter :", CTRADER_PYTHON)
    print("Output      :", LIVE_BARS_DIR)
    print("Refresh     :", REFRESH_INTERVAL_SECONDS, "seconds")
    print("Feeds       :", ", ".join(f"{s} {p}" for s, p, _ in FEEDS))
    print("=" * 70)
    print()

    if not CTRADER_PYTHON.exists():
        raise SystemExit(f"[FATAL] cTrader Python missing: {CTRADER_PYTHON}")

    if not DOWNLOADER.exists():
        raise SystemExit(f"[FATAL] Downloader missing: {DOWNLOADER}")

    LIVE_BARS_DIR.mkdir(parents=True, exist_ok=True)

    cycle = 0

    while True:
        cycle += 1
        started = time.monotonic()

        log(f"--- refresh cycle {cycle} ---")

        succeeded = 0
        for symbol, period, days in FEEDS:
            if refresh_one(symbol, period, days):
                succeeded += 1

        log(f"[CYCLE {cycle}] {succeeded}/{len(FEEDS)} feeds refreshed")

        elapsed = time.monotonic() - started
        remaining = max(0.0, REFRESH_INTERVAL_SECONDS - elapsed)

        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
