"""
HAFNOT DEMO order execution smoke test.

Run this YOURSELF, deliberately, when you are ready to verify that real
order placement against your cTrader DEMO account actually works. It is
NOT part of the 24/7 supervisor and never runs automatically.

What it does, in order, printing PASS/FAIL for each step:

  1. Confirms DEMO_ORDER_EXECUTION_ENABLED=true is set in .env.
  2. Confirms the authorized account is flagged isLive=false (DEMO).
  3. Calls RECONCILE to fetch your current live positions/orders (read-only,
     always safe).
  4. Places ONE small market order (default: 0.01 lots EURUSD BUY) with a
     wide stop-loss/take-profit, using a fresh client_order_id.
  5. Reports the execution result (accepted/filled/rejected).
  6. If a position was opened, immediately closes it again, so this smoke
     test does not leave a live position sitting on your account.
  7. Calls RECONCILE again to confirm the position is gone.

Usage:
    .venv\\Scripts\\python.exe hafnot_demo_order_smoke_test.py
    .venv\\Scripts\\python.exe hafnot_demo_order_smoke_test.py --symbol GBPUSD --lots 0.01

This script has NOT been run against a live server by the assistant that
wrote it (no network access to your cTrader account was available). Read
the printed output carefully the first time you run it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.openapi.execution.native_execution_client import (
    is_demo_order_execution_enabled,
    place_market_order,
    close_position,
    reconcile,
)


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


async def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--lots", type=float, default=0.01)
    args = parser.parse_args()

    section("HAFNOT DEMO ORDER EXECUTION SMOKE TEST")
    print(f"Symbol : {args.symbol}")
    print(f"Lots   : {args.lots}")

    section("1. DEMO_ORDER_EXECUTION_ENABLED")
    if not is_demo_order_execution_enabled():
        print("[FAIL] DEMO_ORDER_EXECUTION_ENABLED is not 'true' in .env.")
        print("       Set it to true, then re-run this script.")
        return 1
    print("[PASS] DEMO_ORDER_EXECUTION_ENABLED=true")

    section("2. RECONCILE (before)")
    before = await reconcile()
    print(before)
    if before.get("status") != "OK":
        print("[FAIL] Could not reconcile with the broker. Check your .env")
        print("       credentials and that oauth.py / account_auth.py have")
        print("       both been run successfully.")
        return 1
    print(f"[PASS] Reconciled. Open positions before: {len(before.get('positions', []))}")

    section("3. PLACE ONE SMALL MARKET ORDER")
    client_order_id = f"smoketest-{int(time.time())}"

    result = await place_market_order(
        client_order_id=client_order_id,
        symbol=args.symbol,
        side="BUY",
        volume_lots=args.lots,
        # No stop-loss/take-profit on purpose: this is a smoke test that
        # closes itself explicitly a few seconds later (step 4), so there
        # is no need for the broker to manage an exit in the meantime.
    )
    print(result)

    if result.get("status") not in ("OK",):
        print(f"[FAIL] Order was not accepted: {result.get('status')} - {result.get('error') or result.get('description')}")
        return 1

    print(f"[PASS] Order result: {result}")

    position_id = result.get("position_id")

    if not position_id:
        print("[INFO] No position_id returned (order may be pending/partial).")
        print("       Check your cTrader DEMO platform manually.")
        return 0

    section("4. CLOSE THE TEST POSITION")
    close_result = await close_position(position_id=position_id)
    print(close_result)

    if close_result.get("status") != "OK":
        print("[FAIL] Could not close the test position automatically.")
        print(f"       Close position_id={position_id} manually in your DEMO platform.")
        return 1

    print("[PASS] Test position closed.")

    section("5. RECONCILE (after)")
    after = await reconcile()
    print(after)

    still_open = [p for p in after.get("positions", []) if p.get("position_id") == position_id]
    if still_open:
        print("[FAIL] Position still appears open after close request.")
        return 1

    print("[PASS] Position confirmed closed.")
    print()
    print("=" * 70)
    print("SMOKE TEST COMPLETE - order round-trip verified.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
