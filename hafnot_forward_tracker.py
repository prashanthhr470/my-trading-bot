"""
Forward paper tracking - score a rule on prices that did not exist when it was registered.

    python hafnot_forward_tracker.py --register     # once: pins the rules and the start time (refuses to change them)
    python hafnot_forward_tracker.py                # any day: recomputes every forward trade from the start

Tracks the index dip-in-uptrend rule (report 7u: closest to an edge, beat its "just buy" benchmark, missed validation
narrowly) and that benchmark, with the parameters their preregistered selection chose, on US500 and US2000. Every run
fetches daily bars from cTrader into memory, keeps only bars that have CLOSED, and replays the rules with the same costs
and overnight financing as the backtests. Only trades ENTERED on bars that open after the registration's start count.
Trades still open are shown marked at the last close and are not scored.

Nothing is traded: the only broker access is historical trendbars. The registration and a small ledger of the last run
are written to data/research/forward/. The verdict rule is pinned at registration: at least MIN_TRADES closed trades,
the out-of-sample gate, a higher expectancy than the benchmark, and the multiple-testing guard counting every experiment
recorded when the rule was registered.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import hafnot_run_research_pipeline as runner
from app.core.zones import parse_ts
from app.forex_v2.metrics import evaluate_promotion, summarize_trades
from app.quant import cost_profile, experiment_registry, multiple_testing, portfolio_pipeline as pp, signal_filters

ROOT = Path(__file__).resolve().parent
FORWARD_DIR = ROOT / "data" / "research" / "forward"
TRACK_ID = "index-dip-forward-20260915"
SERIES = "portfolio-d1-v7-index-anomalies"
RULE, BENCHMARK = "index-dip-in-uptrend", "index-unconditional-long"
MIN_TRADES = 30
WARMUP_DAYS = 420   # calendar days of history before the start: the 200-day average and ATR need it


def registration_path(directory: Path = FORWARD_DIR) -> Path:
    return directory / f"{TRACK_ID}.json"


def build_registration(now: datetime) -> dict:
    config, families = runner.PORTFOLIO_SERIES[SERIES]
    records = {e["experiment_id"]: e for e in experiment_registry.list_experiments()}
    tracked = {}
    for family in families:
        if family.strategy_id not in (RULE, BENCHMARK):
            continue
        record = records[pp.experiment_id_for(family, config)]
        tracked[family.strategy_id] = {
            "module": family.module, "fixed_params": family.fixed_params,
            "chosen_params": record["result"]["metrics"]["TRAIN"]["chosen_params"],
            "backtest_decision": record["decision"], "backtest_stage_reached": record["result"]["stage_reached"],
        }
    return {
        "track_id": TRACK_ID,
        "registered_at": now.isoformat(),
        "start": now.isoformat(),
        "start_rule": "Only trades entered on daily bars that OPEN after `start` count; bars must have closed.",
        "series": SERIES, "symbols": list(config.symbols), "cost_profile": config.cost_profile_file,
        "tracked": tracked,
        "verdict_rule": {
            "minimum_closed_trades": MIN_TRADES,
            "out_of_sample_gate": pp.asdict(config.out_of_sample_gate),
            "must_beat_benchmark_expectancy": BENCHMARK,
            "multiple_testing": multiple_testing.RULE,
            "experiments_counted": len(records) + 1,
        },
        "orders": "none - historical trendbars only",
    }


def register(directory: Path = FORWARD_DIR, now: Optional[datetime] = None) -> Path:
    path = registration_path(directory)
    if path.exists():
        raise SystemExit(f"[REFUSED] {path.name} already exists; a forward registration is never changed.")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_registration(now or datetime.now(timezone.utc)), indent=2), encoding="utf-8")
    return path


def closed_bars(bars: list[dict], now: datetime) -> list[dict]:
    """Daily bars whose 24 hours have fully elapsed; a bar still forming is dropped."""

    return [b for b in bars if (parse_ts(b["timestamp"]) or now) + timedelta(days=1) <= now]


def split_at_start(bars: list[dict], start: datetime) -> tuple[list[dict], list[dict]]:
    before = [b for b in bars if parse_ts(b["timestamp"]) <= start]
    return before, bars[len(before):]


def score(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("exit_reason") != "END_OF_DATA"]
    still_open = [t for t in trades if t.get("exit_reason") == "END_OF_DATA"]
    summary = summarize_trades(closed, initial_equity=pp.STARTING_EQUITY_USD) if closed else None
    return {
        "closed_trades": len(closed), "open_trades": len(still_open),
        "expectancy_r": summary.expectancy_r if summary else None,
        "profit_factor": summary.profit_factor if summary else None,
        "win_rate": summary.win_rate if summary else None,
        "net_r": round(sum(t["result_r"] for t in closed), 4),
        "open_marked_r": round(sum(t["result_r"] for t in still_open), 4),
    }


def verdict(registration: dict, rule_trades: list[dict], benchmark_score: dict) -> dict:
    rule_rules = registration["verdict_rule"]
    closed = [t for t in rule_trades if t.get("exit_reason") != "END_OF_DATA"]
    if len(closed) < rule_rules["minimum_closed_trades"]:
        return {"status": "COLLECTING", "reason": f"{len(closed)} of {rule_rules['minimum_closed_trades']} closed trades so far."}
    gate = pp.PromotionGate(**rule_rules["out_of_sample_gate"])
    decision = evaluate_promotion(summarize_trades(closed, initial_equity=pp.STARTING_EQUITY_USD), gate)
    significance = multiple_testing.check(closed, rule_rules["experiments_counted"])
    rule_exp = score(rule_trades)["expectancy_r"]
    beats = benchmark_score["expectancy_r"] is None or (rule_exp is not None and rule_exp > benchmark_score["expectancy_r"])
    passed = decision.passed and significance.passed and beats
    return {"status": "PASSED" if passed else "FAILED",
            "reasons": list(decision.reasons) + list(significance.reasons)
                       + ([] if beats else ["Did not beat the benchmark's forward expectancy."])}


def run(directory: Path = FORWARD_DIR, now: Optional[datetime] = None,
        fetch_data: Callable = pp.fetch_portfolio_data) -> dict:
    path = registration_path(directory)
    if not path.exists():
        raise SystemExit("[BLOCKED] Not registered yet: run with --register first.")
    registration = json.loads(path.read_text(encoding="utf-8"))
    now = now or datetime.now(timezone.utc)
    start = datetime.fromisoformat(registration["start"])
    config, families = runner.PORTFOLIO_SERIES[registration["series"]]
    config = replace(config, data_start=(start - timedelta(days=WARMUP_DAYS)).date().isoformat(),
                     data_end=(now + timedelta(days=1)).date().isoformat(), symbol_data_starts=(),
                     close_open_trades_at_slice_end=True)
    data = fetch_data(config, cost_profile.PROFILE_DIR / registration["cost_profile"])

    results, trades_by_rule = {}, {}
    for family in families:
        if family.strategy_id not in registration["tracked"]:
            continue
        tracked = registration["tracked"][family.strategy_id]
        if tracked["module"] != family.module or tracked["fixed_params"] != family.fixed_params:
            raise SystemExit(f"[REFUSED] {family.strategy_id} no longer matches its forward registration.")
        factory = family.factory(timeframe_minutes=signal_filters.TIMEFRAME_MINUTES[config.timeframe])
        trades = []
        for symbol in config.symbols:
            warmup, forward = split_at_start(closed_bars(data.bars[symbol], now), start)
            if forward:
                trades.extend(pp.run_symbol_trades(warmup, forward, symbol, factory, tracked["chosen_params"],
                                                   data.costs_for(symbol), config))
        trades_by_rule[family.strategy_id] = sorted(trades, key=lambda t: t["exit_timestamp"])
        results[family.strategy_id] = score(trades)

    report = {
        "track_id": registration["track_id"], "run_at": now.isoformat(), "start": registration["start"],
        "bars_sha256": data.bars_sha256, "rates_sha256": data.external_rates_sha256,
        "scores": results,
        "verdict": verdict(registration, trades_by_rule.get(RULE, []), results.get(BENCHMARK, score([]))),
        "trades": trades_by_rule,
    }
    (directory / f"{TRACK_ID}.ledger.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    if args.register:
        print(f"[REGISTERED] {register()}")
        return
    report = run()
    print(f"FORWARD TRACK {report['track_id']} since {report['start']} (run {report['run_at']})")
    for rule, s in report["scores"].items():
        exp = "-" if s["expectancy_r"] is None else f"{s['expectancy_r']:+.3f}R"
        print(f"  {rule:<28} closed {s['closed_trades']:>3}  open {s['open_trades']}  expectancy {exp}  net {s['net_r']:+.2f}R"
              f"  (open marked {s['open_marked_r']:+.2f}R)")
    print(f"  VERDICT: {report['verdict']['status']} - " + "; ".join(report["verdict"].get("reasons") or [report["verdict"].get("reason", "")]))


if __name__ == "__main__":
    main()
