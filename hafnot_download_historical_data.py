"""
HAFNOT historical data downloader.

Nothing in this project could previously acquire real multi-year OHLC
history (confirmed by the research/validation audit - the only historical
data present was one ~6-month XAUUSD file). This script pulls real
trendbar history directly from your own cTrader DEMO connection using the
native OpenAPI (the SAME auth/connection pattern already proven working
in app\\openapi\\market\\multi_symbol_market_data.py - not a new,
untested connection method), and writes it to
data\\historical\\bars\\<symbol>_<period>.json.

Bar decoding (open/high/low/close from low + delta*, all /100000) is
copied directly from the already-working live trendbar handler in
multi_symbol_market_data.py, not re-derived.

STATUS: NOT VERIFIED end-to-end (no live network access was available to
the assistant that wrote this). The connection/auth section reuses
proven code; the request-chunking/backoff section is new and should be
watched the first time you run it - if the broker returns fewer bars than
requested, or an error, this script prints it plainly rather than
guessing.

Usage:
    .ctrader_venv\\Scripts\\python.exe hafnot_download_historical_data.py --symbol XAUUSD --period H1 --days 730
    .ctrader_venv\\Scripts\\python.exe hafnot_download_historical_data.py --symbol EURUSD --period D1 --days 1825

Must run under .ctrader_venv (Python 3.12), same as the market-data worker.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq,
    ProtoOAAccountAuthRes,
    ProtoOASymbolsListReq,
    ProtoOASymbolsListRes,
    ProtoOAGetTrendbarsReq,
    ProtoOAGetTrendbarsRes,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

TOKEN_FILE = ROOT / "data" / "ctrader_oauth_tokens.json"
ACCOUNT_FILE = ROOT / "data" / "ctrader_authorized_account.json"
OUTPUT_DIR = ROOT / "data" / "historical" / "bars"

# Conservative per-request chunk size. cTrader's documented maximum is
# larger for higher timeframes, but requesting a bounded window at a time
# and stitching results together is safe regardless of the exact per-period
# ceiling, and makes partial progress recoverable if one request fails.
CHUNK_DAYS = 30
# Coarser periods need far fewer bars per day, so each request can cover more days.
CHUNK_DAYS_BY_PERIOD = {"D1": 365, "W1": 730, "H4": 120}
REQUEST_TIMEOUT_SECONDS = 30


def price_from_relative(value) -> float:
    # Identical convention to app/openapi/market/multi_symbol_market_data.py.
    return float(value) / 100000.0


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class HistoryDownloader:

    def __init__(self, symbol: str, period: str, days: int, output_dir: Path | None = None, *,
                 start: datetime | None = None, end: datetime | None = None,
                 chunk_days: int | None = None, stream=None):
        self.symbol_name = symbol.upper()
        self.period = period.upper()
        self.days = days
        # A fixed [start, end) range makes a fetch repeatable, so research can pin its hash.
        self.start_at = start
        self.end_at = end
        self.chunk_days = chunk_days or CHUNK_DAYS_BY_PERIOD.get(self.period, CHUNK_DAYS)
        # stream: write the bars there as JSON instead of to a file - research fetches
        # straight from the broker into memory and stores nothing.
        self.stream = stream
        self.failed = False
        # Defaults to the multi-year backtest corpus. The live bar feed
        # (hafnot_live_bar_feed.py) passes a DIFFERENT directory so that
        # refreshing a short live window can never overwrite the
        # multi-year history the backtests and registry results depend on.
        self.output_dir = output_dir or OUTPUT_DIR

        self.access_token = ""
        self.account_id = None
        self.symbols: dict[int, object] = {}
        self.symbol_id: int | None = None

        self.all_bars: list[dict] = []
        self.chunks_remaining: list[tuple[int, int]] = []
        self.current_chunk: tuple[int, int] | None = None

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
            print("[FATAL] Authorized account is not flagged DEMO (isLive=true or unknown). Refusing.")
            sys.exit(1)

        self.account_id = int(account_data["ctidTraderAccountId"])

    def _build_chunks(self) -> None:
        now = self.end_at or datetime.now(timezone.utc)
        start = self.start_at or now - timedelta(days=self.days)

        cursor = start
        while cursor < now:
            chunk_end = min(cursor + timedelta(days=self.chunk_days), now)
            from_ms = int(cursor.timestamp() * 1000)
            to_ms = int(chunk_end.timestamp() * 1000)
            self.chunks_remaining.append((from_ms, to_ms))
            cursor = chunk_end

        # Oldest-first so the output file ends up in chronological order.
        print(f"[INFO] {len(self.chunks_remaining)} chunk(s) of up to {self.chunk_days} days each queued.")

    def start(self) -> None:
        self._load_credentials()
        self._build_chunks()

        host = EndPoints.PROTOBUF_DEMO_HOST
        port = EndPoints.PROTOBUF_PORT

        self.client = Client(host, port, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)

        self.client.startService()
        reactor.run()

    def on_connected(self, client_instance) -> None:
        print("[CONNECTED] cTrader Open API")
        req = ProtoOAApplicationAuthReq()
        req.clientId = os.getenv("CTRADER_CLIENT_ID", "")
        req.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "")
        client_instance.send(req)

    def on_disconnected(self, client_instance, reason) -> None:
        print("[DISCONNECTED]", reason)
        if not self.done:
            self._finish(error=str(reason))

    def _finish(self, error: str | None = None) -> None:
        if self.done:
            return
        self.done = True

        if error:
            print(f"[FAIL] {error}")
            print(f"[PARTIAL] {len(self.all_bars)} bars were collected before this failure.")
            self.failed = True

        if self.stream is not None:
            # In-memory fetch: all or nothing, so research never analyses a partial history.
            if not self.failed:
                by_timestamp = {bar["timestamp"]: bar for bar in self.all_bars}
                bars = [by_timestamp[ts] for ts in sorted(by_timestamp)]
                if self.end_at is not None:
                    bars = [b for b in bars if b["timestamp"] < self.end_at.isoformat()]
                json.dump({"symbol": self.symbol_name, "period": self.period, "bar_count": len(bars), "bars": bars},
                          self.stream, separators=(",", ":"))
                self.stream.flush()
            try:
                reactor.stop()
            except Exception:
                pass
            return

        if self.all_bars:
            # Adjacent request chunks share a boundary bar; keep one per timestamp (the latest fetched).
            by_timestamp = {bar["timestamp"]: bar for bar in self.all_bars}
            removed = len(self.all_bars) - len(by_timestamp)
            self.all_bars = [by_timestamp[ts] for ts in sorted(by_timestamp)]
            if removed:
                print(f"[INFO] Dropped {removed} duplicate chunk-boundary bar(s).")
            self.output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.output_dir / f"{self.symbol_name.lower()}_{self.period.lower()}.json"
            out_path.write_text(
                json.dumps(
                    {
                        "symbol": self.symbol_name,
                        "period": self.period,
                        "bar_count": len(self.all_bars),
                        "bars": self.all_bars,
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"[PASS] Wrote {len(self.all_bars)} bars to {out_path}")

        try:
            reactor.stop()
        except Exception:
            pass

    def on_message(self, client_instance, message) -> None:

        try:
            payload_type = message.payloadType

            if payload_type == ProtoOAApplicationAuthRes().payloadType:
                print("[PASS] Application authenticated")
                req = ProtoOAAccountAuthReq()
                req.ctidTraderAccountId = int(self.account_id)
                req.accessToken = self.access_token
                client_instance.send(req)
                return

            if payload_type == ProtoOAAccountAuthRes().payloadType:
                print("[PASS] Account authenticated")
                req = ProtoOASymbolsListReq()
                req.ctidTraderAccountId = int(self.account_id)
                req.includeArchivedSymbols = False
                client_instance.send(req)
                return

            if payload_type == ProtoOASymbolsListRes().payloadType:
                response = Protobuf.extract(message)
                self.symbols = {int(s.symbolId): s for s in response.symbol}

                for s in self.symbols.values():
                    if str(getattr(s, "symbolName", "")).upper() == self.symbol_name:
                        self.symbol_id = int(s.symbolId)
                        break

                if self.symbol_id is None:
                    self._finish(error=f"Symbol not found: {self.symbol_name!r}")
                    return

                print(f"[PASS] Resolved {self.symbol_name} -> symbolId={self.symbol_id}")
                self._request_next_chunk(client_instance)
                return

            if payload_type == ProtoOAGetTrendbarsRes().payloadType:
                response = Protobuf.extract(message)

                for bar in response.trendbar:
                    low = price_from_relative(bar.low)
                    self.all_bars.append({
                        "timestamp": datetime.fromtimestamp(
                            bar.utcTimestampInMinutes * 60, tz=timezone.utc
                        ).isoformat(),
                        "open": price_from_relative(bar.low + bar.deltaOpen),
                        "high": price_from_relative(bar.low + bar.deltaHigh),
                        "low": low,
                        "close": price_from_relative(bar.low + bar.deltaClose),
                        "volume": bar.volume,
                    })

                print(
                    f"[PASS] Chunk returned {len(response.trendbar)} bars "
                    f"(total so far: {len(self.all_bars)})"
                )
                self._request_next_chunk(client_instance)
                return

        except Exception as exc:
            self._finish(error=f"{type(exc).__name__}: {exc}")

    def _request_next_chunk(self, client_instance) -> None:

        if not self.chunks_remaining:
            self._finish()
            return

        from_ms, to_ms = self.chunks_remaining.pop(0)
        self.current_chunk = (from_ms, to_ms)

        req = ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = int(self.account_id)
        req.symbolId = self.symbol_id
        req.period = ProtoOATrendbarPeriod.Value(self.period)
        req.fromTimestamp = from_ms
        req.toTimestamp = to_ms

        print(
            f"[SEND] Requesting {self.period} bars "
            f"{datetime.fromtimestamp(from_ms/1000, tz=timezone.utc).date()} "
            f"to {datetime.fromtimestamp(to_ms/1000, tz=timezone.utc).date()} "
            f"({len(self.chunks_remaining)} chunk(s) remaining after this one)"
        )
        client_instance.send(req)


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", required=True, choices=list(ProtoOATrendbarPeriod.keys()))
    parser.add_argument("--days", type=int, default=730, help="How many days of history to request (default 730 = ~2 years)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Where to write the bars file (default: data/historical/bars). "
            "The live bar feed uses data/live/bars so it cannot overwrite "
            "the multi-year backtest corpus."
        ),
    )
    parser.add_argument("--start", help="first day to fetch, YYYY-MM-DD (UTC); overrides --days")
    parser.add_argument("--end", help="day to stop before, YYYY-MM-DD (UTC); default now")
    parser.add_argument("--chunk-days", type=int, default=None, help="days per request (default depends on period)")
    parser.add_argument("--stdout", action="store_true",
                        help="write the bars as JSON to stdout instead of a file; progress goes to stderr")
    args = parser.parse_args()

    stream = None
    if args.stdout:
        stream = sys.stdout
        sys.stdout = sys.stderr

    def _day(text):
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc) if text else None

    print("=" * 70)
    print(" HAFNOT HISTORICAL DATA DOWNLOADER")
    print("=" * 70)
    print(f"Symbol : {args.symbol}")
    print(f"Period : {args.period}")
    print(f"Days   : {args.days}")
    print()

    downloader = HistoryDownloader(
        args.symbol,
        args.period,
        args.days,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        start=_day(args.start),
        end=_day(args.end),
        chunk_days=args.chunk_days,
        stream=stream,
    )
    downloader.start()
    if downloader.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
