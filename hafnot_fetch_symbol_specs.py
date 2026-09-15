"""
Fetch REAL broker symbol specifications from the live cTrader account.

WHY THIS EXISTS
---------------
app/forex_v2/risk.py's FX_USD_MAJOR_SPECS carries hand-written pip sizes,
contract sizes and lot limits. For the FX majors those conventions are
standard, but the XAUUSD entry was written from a documented Pepperstone
CFD spec rather than read from the account, and its own comment says
"verify against your own broker's symbol spec before relying on this for
sizing". That assumption has a live consequence: with pip_size=0.01, a
normal ~10-cent gold spread measures as ~10 "pips" against
RiskConfig.max_spread_pips=2.0, so every gold candidate is refused on
spread.

The correct fix is not to raise the limit until trades appear - it is to
learn what the broker actually reports and make pip/spread/volume
arithmetic symbol-specific and correct. This script reads that from the
authenticated DEMO account (ProtoOASymbolByIdReq) and writes it to
data/broker/symbol_specs.json for the risk layer and for review.

Fields captured (cTrader semantics):
  pipPosition    - decimal position of one pip; pip_size = 10 ** -pipPosition
  digits         - price precision
  lotSize        - units per lot, in cents of the base unit (/100 for units)
  minVolume      - minimum order volume, in centi-lots (/100 for lots)
  stepVolume     - volume increment, same scaling
  maxVolume      - maximum order volume, same scaling
  commission, commissionType, preciseTradingCommissionRate, minimum commission
  base/quote asset, symbol category and asset class (for non-FX instruments)
  trading schedule and holidays

Run under .ctrader_venv (Python 3.12), same as the market worker:

    .ctrader_venv\\Scripts\\python.exe hafnot_fetch_symbol_specs.py
    .ctrader_venv\\Scripts\\python.exe hafnot_fetch_symbol_specs.py --list
    .ctrader_venv\\Scripts\\python.exe hafnot_fetch_symbol_specs.py --symbols US500,XAGUSD

--list prints every symbol the account offers, grouped by asset class, and writes
nothing. --symbols fetches extra symbols and MERGES them into symbol_specs.json;
existing entries are kept (and refreshed if fetched again).

Read-only: it requests specifications and places no orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages import OpenApiMessages_pb2 as m

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

TOKEN_FILE = ROOT / "data" / "ctrader_oauth_tokens.json"
ACCOUNT_FILE = ROOT / "data" / "ctrader_authorized_account.json"
OUTPUT_FILE = ROOT / "data" / "broker" / "symbol_specs.json"

# Every symbol the market worker subscribes to. The USD majors and gold
# are what the risk layer and strategy registry use; the three crosses are
# included because the supervisor watches their feeds too, and
# app.core.market_hours needs a schedule for every watched feed - a feed
# with no known schedule is (deliberately) treated as a genuine outage
# when it goes quiet, which would keep the weekend restart loop alive.
WANTED = (
    "XAUUSD", "EURUSD", "GBPUSD", "USDJPY",
    "AUDUSD", "NZDUSD", "USDCHF", "USDCAD",
    "GBPJPY", "AUDJPY", "GBPAUD",
)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class SpecFetcher:

    def __init__(self, list_only: bool = False, extra: tuple = ()):
        self.list_only = list_only
        self.wanted = tuple(dict.fromkeys(WANTED + tuple(s.upper() for s in extra)))
        self.extra = tuple(s.upper() for s in extra)
        self.access_token = ""
        self.account_id = None
        self.assets: dict[int, str] = {}
        self.asset_classes: dict[int, str] = {}
        self.categories: dict[int, tuple[str, int]] = {}
        self.light: dict[str, dict] = {}
        self.name_by_id: dict[int, str] = {}
        self.specs: dict[str, dict] = {}
        self.client = None
        self.done = False

    def _load_credentials(self) -> None:
        token_data = load_json(TOKEN_FILE)
        self.access_token = str(token_data.get("accessToken", "")).strip()
        if not self.access_token:
            print("[FATAL] Access token missing. Run app\\openapi\\auth\\oauth.py first.")
            sys.exit(1)

        account_data = load_json(ACCOUNT_FILE)
        if not account_data:
            print("[FATAL] Authorized account missing. Run app\\openapi\\auth\\account_auth.py first.")
            sys.exit(1)

        if bool(account_data.get("isLive", True)):
            print("[FATAL] Authorized account is not flagged DEMO. Refusing.")
            sys.exit(1)

        self.account_id = int(account_data["ctidTraderAccountId"])

    def start(self) -> None:
        self._load_credentials()
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()
        reactor.run()

    def _send(self, message) -> None:
        deferred = self.client.send(message)
        if hasattr(deferred, "addErrback"):
            deferred.addErrback(lambda failure: None)

    def _request(self, name: str) -> None:
        request = getattr(m, name)()
        request.ctidTraderAccountId = int(self.account_id)
        self._send(request)

    def on_connected(self, client_instance) -> None:
        print("[CONNECTED] cTrader Open API")
        req = m.ProtoOAApplicationAuthReq()
        req.clientId = os.getenv("CTRADER_CLIENT_ID", "")
        req.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "")
        self._send(req)

    def on_disconnected(self, client_instance, reason) -> None:
        if not self.done:
            self._finish(error=str(reason))

    def _finish(self, error: str | None = None) -> None:
        if self.done:
            return
        self.done = True

        if error:
            print(f"[FAIL] {error}")

        if self.specs and not self.list_only:
            existing = load_json(OUTPUT_FILE).get("symbols", {})
            merged = {**existing, **self.specs}
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT_FILE.write_text(
                json.dumps(
                    {
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "source": "cTrader Open API ProtoOASymbolByIdReq (DEMO account)",
                        "symbols": merged,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"\n[PASS] Wrote {len(self.specs)} fetched spec(s); {len(merged)} symbol(s) in {OUTPUT_FILE}")

        try:
            reactor.stop()
        except Exception:
            pass

    def _print_catalogue(self) -> None:
        groups: dict[str, list] = defaultdict(list)
        for name, info in sorted(self.light.items()):
            groups[f"{info['asset_class']} / {info['category']}"].append(info)
        print(f"\n{len(self.light)} symbols offered by the account:")
        for group in sorted(groups):
            print(f"\n[{group}]")
            for info in groups[group]:
                print(f"  {info['name']:<14} base={info['base_asset']:<8} quote={info['quote_asset']:<5} {info['description'][:50]}")

    def on_message(self, client_instance, message) -> None:
        try:
            kind = message.payloadType

            if kind == m.ProtoOAApplicationAuthRes().payloadType:
                print("[PASS] Application authenticated")
                req = m.ProtoOAAccountAuthReq()
                req.ctidTraderAccountId = int(self.account_id)
                req.accessToken = self.access_token
                self._send(req)

            elif kind == m.ProtoOAAccountAuthRes().payloadType:
                print("[PASS] Account authenticated")
                self._request("ProtoOAAssetListReq")

            elif kind == m.ProtoOAAssetListRes().payloadType:
                self.assets = {int(a.assetId): str(a.name) for a in Protobuf.extract(message).asset}
                self._request("ProtoOAAssetClassListReq")

            elif kind == m.ProtoOAAssetClassListRes().payloadType:
                self.asset_classes = {int(c.id): str(c.name) for c in Protobuf.extract(message).assetClass}
                self._request("ProtoOASymbolCategoryListReq")

            elif kind == m.ProtoOASymbolCategoryListRes().payloadType:
                self.categories = {int(c.id): (str(c.name), int(c.assetClassId))
                                   for c in Protobuf.extract(message).symbolCategory}
                req = m.ProtoOASymbolsListReq()
                req.ctidTraderAccountId = int(self.account_id)
                req.includeArchivedSymbols = False
                self._send(req)

            elif kind == m.ProtoOASymbolsListRes().payloadType:
                for s in Protobuf.extract(message).symbol:
                    name = str(getattr(s, "symbolName", "")).upper()
                    category, asset_class_id = self.categories.get(int(s.symbolCategoryId), ("?", -1))
                    self.name_by_id[int(s.symbolId)] = name
                    self.light[name] = {
                        "name": name, "symbol_id": int(s.symbolId),
                        "base_asset": self.assets.get(int(s.baseAssetId), "?"),
                        "quote_asset": self.assets.get(int(s.quoteAssetId), "?"),
                        "category": category, "asset_class": self.asset_classes.get(asset_class_id, "?"),
                        "description": str(getattr(s, "description", "")),
                        "enabled": bool(getattr(s, "enabled", True)),
                    }

                if self.list_only:
                    self._print_catalogue()
                    self._finish()
                    return

                missing = [w for w in self.extra if w not in self.light]
                if missing:
                    print(f"[WARN] Not offered by this account: {missing}")
                wanted_ids = [self.light[w]["symbol_id"] for w in self.wanted if w in self.light]
                print(f"[PASS] Resolved {len(wanted_ids)} of {len(self.wanted)} wanted symbols")
                if not wanted_ids:
                    self._finish(error="None of the wanted symbols were found on this account.")
                    return
                req = m.ProtoOASymbolByIdReq()
                req.ctidTraderAccountId = int(self.account_id)
                for symbol_id in wanted_ids:
                    req.symbolId.append(symbol_id)
                self._send(req)

            elif kind == m.ProtoOASymbolByIdRes().payloadType:
                from google.protobuf.json_format import MessageToDict

                for s in Protobuf.extract(message).symbol:
                    symbol_id = int(s.symbolId)
                    name = self.name_by_id.get(symbol_id, str(symbol_id))
                    light = self.light.get(name, {})
                    pip_position = int(getattr(s, "pipPosition", 0))
                    lot_size = int(getattr(s, "lotSize", 0))

                    spec = {
                        # Trading sessions as the broker defines them. Each interval is seconds from
                        # the start of the week in schedule_time_zone.
                        "schedule_time_zone": str(getattr(s, "scheduleTimeZone", "")),
                        "schedule": [{"start_second": int(i.startSecond), "end_second": int(i.endSecond)} for i in s.schedule],
                        "holidays": [MessageToDict(h) for h in s.holiday],
                        "sl_distance": int(getattr(s, "slDistance", 0)),
                        "tp_distance": int(getattr(s, "tpDistance", 0)),
                        "distance_set_in": int(getattr(s, "distanceSetIn", 0)),
                        "max_exposure": int(getattr(s, "maxExposure", 0)),
                        "swap_long": float(getattr(s, "swapLong", 0.0)),
                        "swap_short": float(getattr(s, "swapShort", 0.0)),
                        "swap_calculation_type": int(getattr(s, "swapCalculationType", 0)),
                        "swap_rollover3_days": int(getattr(s, "swapRollover3Days", 0)),
                        "charge_swap_at_weekends": bool(getattr(s, "chargeSwapAtWeekends", False)),
                        "swap_time": int(getattr(s, "swapTime", 0)),
                        "swap_period": int(getattr(s, "swapPeriod", 0)),
                        "skip_swap_periods": int(getattr(s, "skipSWAPPeriods", 0)),
                        "commission": int(getattr(s, "commission", 0)),
                        "commission_type": int(getattr(s, "commissionType", 0)),
                        "precise_trading_commission_rate": int(getattr(s, "preciseTradingCommissionRate", 0)),
                        "min_commission": int(getattr(s, "minCommission", 0)),
                        "precise_min_commission": int(getattr(s, "preciseMinCommission", 0)),
                        "min_commission_type": int(getattr(s, "minCommissionType", 0)),
                        "min_commission_asset": str(getattr(s, "minCommissionAsset", "")),
                        "symbol_id": symbol_id,
                        "base_asset": light.get("base_asset"),
                        "quote_asset": light.get("quote_asset"),
                        "category": light.get("category"),
                        "asset_class": light.get("asset_class"),
                        "pip_position": pip_position,
                        "pip_size": 10.0 ** (-pip_position),
                        "digits": int(getattr(s, "digits", 0)),
                        "lot_size_raw": lot_size,
                        "units_per_lot": lot_size / 100.0,
                        "min_volume_raw": int(getattr(s, "minVolume", 0)),
                        # Volume and lotSize share the same raw scaling, so lots = volume / lotSize.
                        "min_lots": int(getattr(s, "minVolume", 0)) / lot_size if lot_size else None,
                        "lot_step": int(getattr(s, "stepVolume", 0)) / lot_size if lot_size else None,
                        "step_volume_raw": int(getattr(s, "stepVolume", 0)),
                        "max_volume_raw": int(getattr(s, "maxVolume", 0)),
                        "measurement_units": str(getattr(s, "measurementUnits", "")),
                        "description": light.get("description") or str(getattr(s, "description", "")),
                        "trading_mode": int(getattr(s, "tradingMode", -1)),
                    }
                    self.specs[name] = spec
                    print(f"  {name:<10} {spec['asset_class']}/{spec['category']} quote={spec['quote_asset']} "
                          f"pip_size={spec['pip_size']} digits={spec['digits']} units/lot={spec['units_per_lot']} "
                          f"min_lots={spec['min_lots']} commission={spec['commission']} type={spec['commission_type']} "
                          f"precise_rate={spec['precise_trading_commission_rate']}")

                self._finish()

        except Exception as exc:
            self._finish(error=f"{type(exc).__name__}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read broker symbol specifications (read-only).")
    parser.add_argument("--list", action="store_true", help="print every symbol the account offers; writes nothing")
    parser.add_argument("--symbols", default="", help="comma-separated extra symbols to fetch and merge")
    args = parser.parse_args()

    print("=" * 70)
    print(" HAFNOT BROKER SYMBOL SPEC FETCHER (read-only)")
    print("=" * 70)
    print()

    extra = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    SpecFetcher(list_only=args.list, extra=extra).start()


if __name__ == "__main__":
    main()
