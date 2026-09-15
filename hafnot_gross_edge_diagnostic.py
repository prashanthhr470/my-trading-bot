"""
Gross-edge diagnostic - do rejected strategies lose because of trading costs, or before them?

    python hafnot_gross_edge_diagnostic.py                       # every finished portfolio series except M15
    python hafnot_gross_edge_diagnostic.py --series portfolio-d1-v5-shock-continuation

For each finished portfolio experiment, re-runs the parameters its preregistered rule chose on the TRAINING slice only -
data every one of them has already used - twice:
  net    with the preregistered costs, checked against the recorded training result;
  gross  with spread, slippage and commission set to zero (position sizing and the broker's lot limits unchanged).
Validation, walk-forward and locked data are never touched, nothing is written to any registry, and no parameter is
chosen from the output. The difference is what trading costs take per trade, in R.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hafnot_run_research_pipeline as runner
from app.quant import bar_features, cost_profile, portfolio_pipeline as pp, signal_filters
from app.quant.experiment_registry import list_experiments

DEFAULT_SERIES = (
    "portfolio-d1-v1", "portfolio-d1-v2-trailing", "portfolio-d1-v3-multiasset", "portfolio-h4-v1-structure",
    "portfolio-d1-v4-currency-strength", "portfolio-h4-v2-seasonality", "portfolio-d1-v5-shock-continuation",
)
ZERO_COSTS = pp.SymbolCosts(spread_pips=0.0, commission_rt_usd=0.0, max_spread_pips=100.0, slippage_pips_per_side=0.0)


def zero_cost_runner(warmup, evaluation, symbol, factory, params, costs, config):
    return pp.run_symbol_trades(warmup, evaluation, symbol, factory, params, ZERO_COSTS, config)


def diagnose(series: str) -> list[dict]:
    config, families = runner.PORTFOLIO_SERIES[series]
    records = {e["experiment_id"]: e for e in list_experiments()}
    finished = [(f, records[pp.experiment_id_for(f, config)]) for f in families if pp.experiment_id_for(f, config) in records]
    if not finished:
        return []
    data = pp.fetch_portfolio_data(config, cost_profile.PROFILE_DIR / config.cost_profile_file)
    if config.bar_features:
        data = pp.dataclass_replace(data, bars=bar_features.enrich(config.bar_features, data.bars,
                                                                   data.feature_input(config.bar_features)))
    split = pp.calendar_split(data.bars, config)
    train = {s: pp.slice_with_warmup(data.bars[s], None, split.train_end, 0) for s in config.symbols}

    rows = []
    for family, record in finished:
        training = record["result"]["metrics"]["TRAIN"]
        chosen = training.get("chosen_params")
        if not chosen:
            continue
        recorded = next(c for c in training["combos"] if c["params"] == chosen)
        factory = family.factory(timeframe_minutes=signal_filters.TIMEFRAME_MINUTES[config.timeframe])
        net = pp.summary_fields(pp.pooled_trades(train, factory, chosen, data, config, pp.run_symbol_trades))
        gross = pp.summary_fields(pp.pooled_trades(train, factory, chosen, data, config, zero_cost_runner))
        rows.append({
            "series": series, "strategy": family.strategy_id, "params": chosen,
            "recorded_trades": recorded["trade_count"], "recorded_net_r": recorded["expectancy_r"],
            "net_trades": net["trade_count"], "net_r": net["expectancy_r"],
            "gross_trades": gross["trade_count"], "gross_r": gross["expectancy_r"],
            "reproduces_record": net["trade_count"] == recorded["trade_count"]
                                 and abs((net["expectancy_r"] or 0) - (recorded["expectancy_r"] or 0)) < 1e-9,
        })
        row = rows[-1]
        print(f"{series:<36}{family.strategy_id:<32}{row['net_trades']:>7}{_r(row['net_r']):>9}{row['gross_trades']:>7}"
              f"{_r(row['gross_r']):>9}{_r((row['gross_r'] or 0) - (row['net_r'] or 0)):>9}"
              f"   {'reproduces record' if row['reproduces_record'] else 'DOES NOT REPRODUCE RECORD'}", flush=True)
    return rows


def _r(value) -> str:
    return "-" if value is None else f"{value:+.3f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", action="append", choices=sorted(runner.PORTFOLIO_SERIES))
    args = parser.parse_args()
    print("TRAINING SLICE ONLY - chosen parameters, with preregistered costs (net) and with zero costs (gross)")
    print(f"{'series':<36}{'strategy':<32}{'trades':>7}{'net R':>9}{'trades':>7}{'gross R':>9}{'cost R':>9}")
    for series in args.series or DEFAULT_SERIES:
        diagnose(series)


if __name__ == "__main__":
    main()
