"""
DEMO order-execution verification.

    python hafnot_verify_demo_execution.py           # read-only: no order is sent
    python hafnot_verify_demo_execution.py --send    # plus ONE minimum-size DEMO round trip

Read-only checks:
  account_is_demo          the authorized account is flagged DEMO
  authentication           application + DEMO account authentication (via RECONCILE)
  reconcile                the broker's open positions and orders can be read
  volume_normalization     minimum lot -> broker volume, against data/broker/symbol_specs.json

With --send (requires explicit approval; only if the account has no open positions):
  order_submission         a 0.01-lot EURUSD market BUY, relative 50-pip stop / 100-pip target
  fill_confirmation        ORDER_FILLED received, with execution price
  stops_attached           the position carries the stop-loss and take-profit
  position_tracking        RECONCILE shows the position with the expected volume
  position_close           the position is closed and the close fills
  flat_after_close         RECONCILE no longer shows it

Each check is VERIFIED, FAILED or NOT RUN. A small JSON report is written to
data/openapi/execution/verification_<timestamp>.json. Live trading is never touched:
the worker only ever connects to the DEMO host and refuses isLive accounts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.openapi.execution import native_execution_client as client
from app.openapi.execution import order_math

ROOT = Path(__file__).resolve().parent
ACCOUNT_FILE = ROOT / "data" / "ctrader_authorized_account.json"
TOKEN_FILE = ROOT / "data" / "ctrader_oauth_tokens.json"
SPECS_FILE = ROOT / "data" / "broker" / "symbol_specs.json"
REPORT_DIR = ROOT / "data" / "openapi" / "execution"

SYMBOL, LOTS, STOP_DISTANCE, TARGET_DISTANCE = "EURUSD", 0.01, 0.0050, 0.0100


def token_scope(path: Path = TOKEN_FILE) -> str:
    """
    The OAuth scope the stored token was authorized with. Tokens saved before the scope was
    recorded all came from oauth.py's only scope at the time, read-only "accounts" - which is
    why the first --send attempt (14 Sep) was refused with "TRADE permission required".
    """

    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("scope") or "accounts")
    except (OSError, ValueError):
        return "missing"


def _check(report, name, ok, detail):
    report[name] = {"result": "VERIFIED" if ok else "FAILED", "detail": detail}
    print(f"  {name:<22}{report[name]['result']:<10}{detail}")
    return ok


async def verify(send: bool) -> dict:
    report: dict = {}
    print("DEMO execution verification" + (" (with one DEMO round trip)" if send else " (read-only)"))

    account = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8")) if ACCOUNT_FILE.exists() else {}
    if not _check(report, "account_is_demo", account.get("isLive") is False, f"isLive={account.get('isLive')!r}"):
        return report

    before = await client.reconcile()
    _check(report, "authentication", before.get("status") == "OK", before.get("error") or "application and DEMO account authenticated")
    if not _check(report, "reconcile", before.get("status") == "OK",
                  f"{len(before.get('positions', []))} open positions, {len(before.get('orders', []))} orders"):
        return report

    spec = json.loads(SPECS_FILE.read_text(encoding="utf-8"))["symbols"][SYMBOL]
    volume = order_math.raw_volume(LOTS, lot_size=spec["lot_size_raw"], min_volume=spec["min_volume_raw"],
                                   step_volume=spec["step_volume_raw"], max_volume=spec["max_volume_raw"])
    _check(report, "volume_normalization", volume == spec["min_volume_raw"],
           f"{LOTS} lot {SYMBOL} -> volume {volume} (broker minimum {spec['min_volume_raw']})")

    scope = token_scope()
    report["token_scope"] = {"result": "INFO", "detail": scope}
    print(f"  {'token_scope':<22}{'INFO':<10}{scope} ({'can trade' if scope == 'trading' else 'cannot place orders'})")

    order_checks = ("order_submission", "fill_confirmation", "stops_attached", "position_tracking",
                    "position_close", "flat_after_close")
    if not send:
        for name in order_checks:
            report[name] = {"result": "NOT RUN", "detail": "needs --send and explicit approval"}
        return report

    if scope != "trading":
        detail = (f"the stored token has scope '{scope}', and cTrader refuses orders without 'trading'. Re-authorize with "
                  "`.venv\\Scripts\\python.exe app\\openapi\\auth\\oauth.py --scope trading` and approve ONLY the DEMO account.")
        for name in order_checks:
            report[name] = {"result": "NOT RUN", "detail": detail}
        print(f"  {'order_submission':<22}{'NOT RUN':<10}{detail}")
        return report

    if before.get("positions"):
        report["order_submission"] = {"result": "NOT RUN", "detail": "account already has open positions; refusing to add one"}
        return report

    os.environ["DEMO_ORDER_EXECUTION_ENABLED"] = "true"   # this process and its worker only
    order_id = f"verify-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    placed = await client.place_market_order(client_order_id=order_id, symbol=SYMBOL, side="BUY", volume_lots=LOTS,
                                             stop_loss_distance=STOP_DISTANCE, take_profit_distance=TARGET_DISTANCE)
    report["order_result"] = placed
    if not _check(report, "order_submission", placed.get("status") in ("OK", "REJECTED") and "error" not in placed,
                  f"status {placed.get('status')} {placed.get('description') or placed.get('error') or ''}"):
        return report
    if not _check(report, "fill_confirmation", placed.get("execution_type") == "ORDER_FILLED" and placed.get("execution_price"),
                  f"{placed.get('execution_type')} at {placed.get('execution_price')}, position {placed.get('position_id')}"):
        return report
    _check(report, "stops_attached", bool(placed.get("position_stop_loss")) and bool(placed.get("position_take_profit")),
           f"stop {placed.get('position_stop_loss')}, target {placed.get('position_take_profit')}")

    position_id = placed["position_id"]
    tracked = await client.reconcile()
    row = next((p for p in tracked.get("positions", []) if p["position_id"] == position_id), None)
    _check(report, "position_tracking", row is not None and row["volume"] == volume,
           f"position {position_id} volume {row and row['volume']}")

    closed = await client.close_position(position_id=position_id)
    report["close_result"] = closed
    _check(report, "position_close", closed.get("status") == "OK" and closed.get("execution_type") == "ORDER_FILLED",
           f"{closed.get('status')} {closed.get('execution_type')} at {closed.get('execution_price')}")

    after = await client.reconcile()
    _check(report, "flat_after_close", after.get("status") == "OK"
           and all(p["position_id"] != position_id for p in after.get("positions", [])),
           f"{len(after.get('positions', []))} open positions")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="also send ONE minimum-size DEMO round trip")
    args = parser.parse_args()
    report = asyncio.run(verify(args.send))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"verification_{datetime.now(timezone.utc):%Y%m%d%H%M%S}.json"
    path.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "sent_order": args.send,
                                "checks": report}, indent=2, default=str), encoding="utf-8")
    print(f"\n[REPORT] {path}")


if __name__ == "__main__":
    main()
