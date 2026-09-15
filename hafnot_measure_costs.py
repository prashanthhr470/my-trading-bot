"""
Measure per-symbol spreads -> data/broker/measured_costs_<date>_<source>.json

    .ctrader_venv\\Scripts\\python.exe hafnot_measure_costs.py                  # from the broker (default)
    .ctrader_venv\\Scripts\\python.exe hafnot_measure_costs.py --weekdays 5
    .venv\\Scripts\\python.exe hafnot_measure_costs.py --source local            # from locally logged quotes

broker: asks cTrader for historical BID and ASK ticks (ProtoOAGetTickDataReq) in a short
        window at the top of every UTC hour of the last N weekdays, samples the spread at a
        fixed interval, and keeps only hourly statistics - no raw ticks are stored. Every
        hour, including the Asian session and rollover, is covered immediately. Needs
        .ctrader_venv and the DEMO credentials the other cTrader tools use.
local:  reads data/openapi/<symbol>_market_events.jsonl, which the storage guard trims.

A profile is never overwritten, because research series pin its hash.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.forex_v2 import instrument_specs
from app.forex_v2.risk import FX_USD_MAJOR_SPECS, RiskConfig, register_research_specs, resolve_spec
from app.quant import cost_profile

ROOT = Path(__file__).resolve().parent
QUOTES_DIR = ROOT / "data" / "openapi"
PRICE_DIVISOR = 100000.0
REQUEST_SPACING_SECONDS = 0.25   # at most 4 historical requests per second
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 5


# ---------------------------------------------------------------- local quotes

def collect_local(args) -> tuple[dict, dict]:
    collected = {}
    for symbol, spec in sorted(FX_USD_MAJOR_SPECS.items()):
        path = QUOTES_DIR / f"{symbol.lower()}_market_events.jsonl"
        quotes, first, last = [], None, None
        if path.exists():
            with path.open(encoding="utf-8", errors="ignore") as handle:
                for n, line in enumerate(handle):
                    if n % args.sample_every:
                        continue
                    try:
                        event = json.loads(line)
                        bid, ask = float(event["bid"]), float(event["ask"])
                        moment = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if bid <= 0 or ask < bid:
                        continue
                    quotes.append((moment, (ask - bid) / spec.pip_size))
                    first = first or moment
                    last = moment
        collected[symbol] = (quotes, first, last)
    return collected, {"source": "data/openapi/<symbol>_market_events.jsonl - live cTrader DEMO spot quotes",
                       "sample_every": args.sample_every}


# ---------------------------------------------------------------- broker ticks

class BrokerSpreadSampler:
    """Fetches BID and ASK ticks window by window; keeps only sampled spreads, never raw ticks."""

    def __init__(self, args, symbols):
        self.args = args
        self.symbols = list(symbols)
        self.windows = cost_profile.hourly_windows(_anchor(args), args.weekdays, args.window_minutes, hours=_hours(args))
        self.queue = [(symbol, start, end) for symbol in self.symbols for start, end in self.windows]
        self.total = len(self.queue)
        self.collected = {symbol: ([], None, None) for symbol in self.symbols}
        self.symbol_ids: dict[str, int] = {}
        self.item = None
        self.side = None
        self.range_ms = None
        self.ticks = {"BID": [], "ASK": []}
        self.retries = 0
        self.timeout_call = None
        self.delta_sign = None
        self.failed_windows = 0

    # -- plumbing
    def run(self) -> None:
        from dotenv import load_dotenv
        from twisted.internet import reactor
        from ctrader_open_api import Client, EndPoints, TcpProtocol
        from hafnot_download_historical_data import ACCOUNT_FILE, TOKEN_FILE, load_json

        load_dotenv(ROOT / ".env")
        self.reactor = reactor
        self.access_token = str(load_json(TOKEN_FILE).get("accessToken", "")).strip()
        account = load_json(ACCOUNT_FILE)
        if not self.access_token or not account:
            raise SystemExit("[FATAL] cTrader credentials missing; run the cTrader auth tools first.")
        if bool(account.get("isLive", True)):
            raise SystemExit("[FATAL] Authorized account is not flagged DEMO (isLive=true or unknown). Refusing.")
        self.account_id = int(account["ctidTraderAccountId"])

        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        print(f"[INFO] {self.total} windows x 2 sides queued ({self.args.weekdays} weekdays, "
              f"{self.args.window_minutes}-minute windows, spread sampled every {self.args.step_seconds}s).")
        self.client.startService()
        reactor.run()

    def on_connected(self, client) -> None:
        import os
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq
        request = ProtoOAApplicationAuthReq()
        request.clientId = os.getenv("CTRADER_CLIENT_ID", "")
        request.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "")
        client.send(request)

    def on_disconnected(self, client, reason) -> None:
        if self.queue or self.item:
            print(f"[FAIL] Disconnected before finishing: {reason}")
        self._stop()

    def _stop(self) -> None:
        try:
            self.reactor.stop()
        except Exception:
            pass

    def on_message(self, client, message) -> None:
        from ctrader_open_api import Protobuf
        from ctrader_open_api.messages import OpenApiMessages_pb2 as m
        try:
            kind = message.payloadType
            if kind == m.ProtoOAApplicationAuthRes().payloadType:
                request = m.ProtoOAAccountAuthReq()
                request.ctidTraderAccountId = self.account_id
                request.accessToken = self.access_token
                client.send(request)
            elif kind == m.ProtoOAAccountAuthRes().payloadType:
                request = m.ProtoOASymbolsListReq()
                request.ctidTraderAccountId = self.account_id
                request.includeArchivedSymbols = False
                client.send(request)
            elif kind == m.ProtoOASymbolsListRes().payloadType:
                response = Protobuf.extract(message)
                names = {str(s.symbolName).upper(): int(s.symbolId) for s in response.symbol}
                self.symbol_ids = {s: names[s] for s in self.symbols if s in names}
                missing = sorted(set(self.symbols) - set(self.symbol_ids))
                if missing:
                    print(f"[WARN] Symbols not offered by the broker: {missing}")
                    self.queue = [q for q in self.queue if q[0] in self.symbol_ids]
                self._next_window()
            elif kind == m.ProtoOAGetTickDataRes().payloadType:
                self._on_ticks(Protobuf.extract(message))
            elif kind == m.ProtoOAErrorRes().payloadType:
                self._on_error(Protobuf.extract(message))
        except Exception as exc:
            print(f"[FAIL] {type(exc).__name__}: {exc}")
            self._stop()

    # -- requests
    def _next_window(self) -> None:
        if self.item:
            self._sample_current()
        if not self.queue:
            self.item = None
            self._stop()
            return
        self.item = self.queue.pop(0)
        done = self.total - len(self.queue)
        if done % 48 == 1:
            print(f"[PROGRESS] window {done}/{self.total}: {self.item[0]} {self.item[1]:%Y-%m-%d %H:%M}")
        self.ticks = {"BID": [], "ASK": []}
        self._start_side("BID")

    def _start_side(self, side: str) -> None:
        _, start, end = self.item
        self.side = side
        self.range_ms = [int(start.timestamp() * 1000), int(end.timestamp() * 1000)]
        self.retries = 0
        self.reactor.callLater(REQUEST_SPACING_SECONDS, self._send)

    def _send(self) -> None:
        from ctrader_open_api.messages import OpenApiMessages_pb2 as m
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAQuoteType
        symbol = self.item[0]
        request = m.ProtoOAGetTickDataReq()
        request.ctidTraderAccountId = self.account_id
        request.symbolId = self.symbol_ids[symbol]
        request.type = ProtoOAQuoteType.Value(self.side)
        request.fromTimestamp, request.toTimestamp = self.range_ms
        self._arm_timeout()
        deferred = self.client.send(request)
        if hasattr(deferred, "addErrback"):
            # The library's own 5-second response timer; this sampler's timeout and retry handle slow replies.
            deferred.addErrback(lambda failure: None)

    def _arm_timeout(self) -> None:
        self._disarm_timeout()
        self.timeout_call = self.reactor.callLater(REQUEST_TIMEOUT_SECONDS, self._on_timeout)

    def _disarm_timeout(self) -> None:
        if self.timeout_call is not None and self.timeout_call.active():
            self.timeout_call.cancel()
        self.timeout_call = None

    def _retry_or_skip(self, why: str) -> None:
        self.retries += 1
        if self.retries > MAX_RETRIES:
            print(f"[WARN] Skipping {self.item[0]} {self.item[1]:%Y-%m-%d %H:%M} {self.side}: {why}")
            self.failed_windows += 1
            self.ticks = {"BID": [], "ASK": []}
            self._next_window()
            return
        self.reactor.callLater(2.0 * self.retries, self._send)

    def _on_timeout(self) -> None:
        self.timeout_call = None
        self._retry_or_skip("request timed out")

    def _on_error(self, error) -> None:
        self._disarm_timeout()
        self._retry_or_skip(f"{error.errorCode} {getattr(error, 'description', '')}")

    def _on_ticks(self, response) -> None:
        self._disarm_timeout()
        entries = [(t.timestamp, t.tick) for t in response.tickData]
        ticks = self._decode(entries)
        self.ticks[self.side].extend(ticks)
        if response.hasMore and ticks:
            times = [t for t, _ in ticks]
            if len(times) > 1 and times[0] > times[-1]:
                self.range_ms[1] = min(times) - 1     # newest first: continue with older ticks
            else:
                self.range_ms[0] = max(times) + 1     # oldest first: continue with newer ticks
            if self.range_ms[0] < self.range_ms[1]:
                self.reactor.callLater(REQUEST_SPACING_SECONDS, self._send)
                return
        if self.side == "BID":
            self._start_side("ASK")
        else:
            self._next_window()

    def _decode(self, entries):
        if not entries:
            return []
        lo, hi = self.range_ms[0] - 60_000, self.range_ms[1] + 60_000
        signs = (self.delta_sign,) if self.delta_sign else (1, -1)
        for sign in signs:
            ticks = cost_profile.decode_tick_data(entries, PRICE_DIVISOR, delta_sign=sign)
            if all(lo <= t <= hi for t, _ in ticks):
                if self.delta_sign is None:
                    self.delta_sign = sign
                    print(f"[INFO] Tick deltas decode with sign {sign:+d} (verified against the requested window).")
                return ticks
        raise ValueError("Tick data does not decode inside the requested window with either delta convention.")

    def _sample_current(self) -> None:
        symbol, start, end = self.item
        samples = cost_profile.sample_spreads(self.ticks["BID"], self.ticks["ASK"], int(start.timestamp() * 1000),
                                              int(end.timestamp() * 1000), step_ms=self.args.step_seconds * 1000)
        if not samples:
            return
        pip = resolve_spec(symbol).pip_size
        quotes, first, last = self.collected[symbol]
        quotes.extend((datetime.fromtimestamp(t / 1000, tz=timezone.utc), spread / pip) for t, spread in samples)
        first = first or start
        self.collected[symbol] = (quotes, first, end)


def _hours(args):
    """The UTC hours to sample (from --hours), or None for all 24."""

    if not getattr(args, "hours", None):
        return None
    hours = tuple(sorted({int(h) for h in str(args.hours).split(",") if h.strip()}))
    if not hours or any(h < 0 or h > 23 for h in hours):
        raise SystemExit(f"[REFUSED] --hours must be UTC hours 0-23, got {args.hours!r}.")
    return hours


def _anchor(args) -> datetime:
    """The day the sampled weekdays are counted back from - shared by every worker of one run."""

    return datetime.strptime(args.anchor_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def collect_broker(args, symbols) -> tuple[dict, dict]:
    sampler = BrokerSpreadSampler(args, symbols)
    sampler.run()
    if sampler.queue:
        raise SystemExit(f"[FAIL] Stopped with {len(sampler.queue)} windows unfetched; no profile written.")
    return sampler.collected, {
        "source": "cTrader Open API ProtoOAGetTickDataReq, BID and ASK ticks (DEMO server)",
        "weekdays": args.weekdays, "window_minutes": args.window_minutes, "step_seconds": args.step_seconds,
        "hours_utc": list(_hours(args) or range(24)),
        "windows": [f"{start:%Y-%m-%d}" for start, _ in sampler.windows[::len(_hours(args) or range(24))]],
        "failed_windows": sampler.failed_windows, "tick_delta_sign": sampler.delta_sign,
        "raw_ticks_stored": False,
    }


def run_broker_workers(args, symbols) -> tuple[dict, dict]:
    """One cTrader connection per worker process, each summarising its own symbols; the broker answers
    a tick request in seconds, so a single connection would take hours for a full profile."""

    import subprocess
    import sys

    groups = [symbols[i::args.workers] for i in range(args.workers) if symbols[i::args.workers]]
    processes = [
        subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve()), "--source", "broker", "--worker",
             "--weekdays", str(args.weekdays), "--window-minutes", str(args.window_minutes),
             "--step-seconds", str(args.step_seconds), "--anchor-date", args.anchor_date,
             "--symbols", ",".join(group)] + (["--hours", args.hours] if args.hours else []),
            cwd=str(ROOT), stdout=subprocess.PIPE, text=True,
        )
        for group in groups
    ]
    summaries, provenance = {}, None
    for process in processes:
        out, _ = process.communicate()
        if process.returncode != 0 or not out.strip():
            raise SystemExit(f"[FAIL] A spread worker failed (exit {process.returncode}); no profile written.")
        result = json.loads(out)
        summaries.update(result["symbols"])
        if provenance is None:
            provenance = result["provenance"]
        else:
            provenance["failed_windows"] += result["provenance"]["failed_windows"]
    provenance["workers"] = len(groups)
    return summaries, provenance


def summarize(collected: dict) -> dict:
    summaries = {}
    for symbol in sorted(collected):
        quotes, first, last = collected[symbol]
        stats = cost_profile.hourly_spread_stats(quotes)
        summaries[symbol] = {
            "pip_size": resolve_spec(symbol).pip_size, "samples": len(quotes),
            "first": first.isoformat() if first else None, "last": last.isoformat() if last else None,
            "hours": stats, "hours_observed": cost_profile.hours_observed(stats),
            "backtest_spread_pips": cost_profile.backtest_spread_pips(stats),
        }
    return summaries


# ---------------------------------------------------------------- profile

def main() -> None:
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("broker", "local"), default="broker")
    parser.add_argument("--weekdays", type=int, default=10, help="broker: number of past weekdays (default 10)")
    parser.add_argument("--window-minutes", type=int, default=10, help="broker: minutes sampled at the top of each hour")
    parser.add_argument("--step-seconds", type=int, default=2, help="broker: spread sampling interval")
    parser.add_argument("--workers", type=int, default=4, help="broker: parallel cTrader connections (default 4)")
    parser.add_argument("--symbols", default=None, help="comma-separated symbols (default: the built-in FX majors and gold); "
                                                        "other USD-quoted instruments use the broker's symbol specs")
    parser.add_argument("--hours", default=None, help="broker: comma-separated UTC hours to sample (default: all 24)")
    parser.add_argument("--anchor-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help=argparse.SUPPRESS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sample-every", type=int, default=5, help="local: use every Nth quote line")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    symbols = sorted(s.strip().upper() for s in args.symbols.split(",")) if args.symbols else sorted(FX_USD_MAJOR_SPECS)
    try:
        # Instruments beyond the FX majors and gold take their contract data from the broker's own specs.
        register_research_specs(instrument_specs.research_specs_for(symbols))
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"[REFUSED] No cost model: {exc}")

    if args.worker:
        # Worker: summary JSON on stdout for the parent, progress on stderr.
        stream, sys.stdout = sys.stdout, sys.stderr
        collected, provenance = collect_broker(args, symbols)
        json.dump({"symbols": summarize(collected), "provenance": provenance}, stream)
        stream.flush()
        return

    now = datetime.now(timezone.utc)
    output = args.output or cost_profile.PROFILE_DIR / f"measured_costs_{now:%Y%m%d}_{args.source}.json"
    if output.exists():
        raise SystemExit(f"[REFUSED] {output} already exists; research series may have pinned its hash.")

    if args.source == "local":
        collected, provenance = collect_local(args)
        summaries = summarize(collected)
    elif args.workers > 1:
        summaries, provenance = run_broker_workers(args, symbols)
    else:
        collected, provenance = collect_broker(args, symbols)
        summaries = summarize(collected)

    config = RiskConfig()
    print(f"\n{'symbol':<8}{'samples':>9}{'hours':>7}{'spread (p90 worst hour)':>25}")
    for symbol, entry in sorted(summaries.items()):
        spread = entry["backtest_spread_pips"]
        print(f"{symbol:<8}{entry['samples']:>9}{entry['hours_observed']:>7}{spread if spread is not None else '-':>25}")
    starts = [e["first"] for e in summaries.values() if e["first"]]
    ends = [e["last"] for e in summaries.values() if e["last"]]
    symbols = summaries

    payload = {
        "measured_at": now.isoformat(),
        "measured_from": min(starts) if starts else None,
        "measured_to": max(ends) if ends else None,
        **provenance,
        "rule": cost_profile.RULE,
        "minimum_hours_for_a_full_day": cost_profile.MIN_HOURS_FOR_FULL_DAY,
        "not_measured": {
            "commission_usd_per_lot_round_turn": config.commission_per_lot_round_turn_usd,
            "slippage_pips_per_side": config.slippage_pips_per_side,
            "note": "Assumed, from app.forex_v2.risk.RiskConfig; only real DEMO fills can measure these. The broker "
                    "symbol spec's commission field (300, type 2) is consistent with $3 per lot per side, below the "
                    "assumed $7 round turn.",
        },
        "symbols": symbols,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    incomplete = [s for s, e in symbols.items() if e["hours_observed"] < cost_profile.MIN_HOURS_FOR_FULL_DAY]
    print(f"\n[WRITTEN] {output}")
    if incomplete and not args.hours:
        print(f"[NOT YET USABLE] fewer than {cost_profile.MIN_HOURS_FOR_FULL_DAY} weekday hours observed for: {', '.join(incomplete)}")


if __name__ == "__main__":
    main()
