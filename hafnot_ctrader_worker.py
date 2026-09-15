from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CTRADER_PYTHON = ROOT / ".ctrader_venv" / "Scripts" / "python.exe"

ENGINE = (
    ROOT
    / "app"
    / "openapi"
    / "market"
    / "multi_symbol_market_data.py"
)

# ------------------------------------------------------------
# HARD PAPER / READ-ONLY SAFETY
# ------------------------------------------------------------

os.environ["DRY_RUN"] = "true"
os.environ["PAPER_TRADING"] = "true"
os.environ["LIVE_EXECUTION"] = "false"
os.environ["BROKER_ORDERS"] = "0"
os.environ["AI_DIRECT_EXECUTION"] = "false"
os.environ["READ_ONLY"] = "true"

print("=" * 70)
print(" HAFNOT cTRADER MARKET WORKER")
print("=" * 70)
print("Interpreter :", CTRADER_PYTHON)
print("Engine      :", ENGINE)
print("Mode        : DEMO / READ-ONLY")
print("Orders      : 0")
print("=" * 70)
print()

if not CTRADER_PYTHON.exists():
    raise SystemExit(
        "[FAIL] cTrader Python missing: "
        + str(CTRADER_PYTHON)
    )

if not ENGINE.exists():
    raise SystemExit(
        "[FAIL] cTrader engine missing: "
        + str(ENGINE)
    )

# ------------------------------------------------------------
# IMPORTANT:
# The worker runs the OpenAPI engine using Python 3.12
# and does NOT import it into Python 3.14.
# ------------------------------------------------------------

process = subprocess.Popen(
    [
        str(CTRADER_PYTHON),
        str(ENGINE),
    ],
    cwd=str(ROOT),
    env=os.environ.copy(),
)

print("[PASS] cTrader worker PID =", process.pid)
print("[PASS] cTrader worker running.")

code = process.wait()

print()
print("[EXIT] cTrader worker =", code)

raise SystemExit(code)

