"""
Run the pre-registered research pipeline for the strategy families below.

All selected experiments are preregistered BEFORE any of them runs, so every
criterion in this series predates every result in it. Completed experiments are
skipped, so an interrupted series resumes; changing a family's grid or rules
after preregistration is refused - bump the series name instead.

    python hafnot_run_research_pipeline.py
    python hafnot_run_research_pipeline.py --family range-fade --symbol EURUSD
    python hafnot_run_research_pipeline.py --preregister-only
    python hafnot_run_research_pipeline.py --series pipeline-v2-filters
    python hafnot_run_research_pipeline.py --compare-filters
    python hafnot_run_research_pipeline.py --series portfolio-d1-v1 --preregister-only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from statistics import median

from app.quant import cost_profile, portfolio_pipeline
from app.quant.experiment_registry import list_experiments, print_selection_bias_report, selection_bias_report
from app.quant.research_pipeline import FamilyDefinition, PipelineConfig, experiment_id_for, preregister, run_experiment
from app.quant.strategy_registry import StrategyFamily

SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]

FAMILIES = [
    FamilyDefinition(
        strategy_id="mean-reversion-zscore", version="1.0.0", family=StrategyFamily.MEAN_REVERSION.value,
        hypothesis="When an H1 close sits an unusually large number of standard deviations from its rolling mean, "
                   "price moves back toward that mean often enough to pay for the trade after costs.",
        entry_rules="z = (close - mean) / stdev over the last `lookback` closes; BUY when z <= -entry_z, SELL when z >= +entry_z, at the close.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the entry.",
        take_profit_logic="The rolling mean at decision time; skipped unless reward:risk >= 1.5.",
        session_conditions="None.", regime_conditions="None.",
        module="app.quant.mean_reversion_strategy",
        param_grid={"lookback": [30, 50, 80], "entry_z": [2.0, 2.5, 3.0]},
        fixed_params={"stop_atr": 1.5, "atr_period": 14, "min_reward_to_risk": 1.5},
    ),
    FamilyDefinition(
        strategy_id="volatility-compression-breakout", version="1.0.0", family=StrategyFamily.VOLATILITY_EXPANSION.value,
        hypothesis="An unusually narrow H1 range relative to earlier volatility is followed by a directional expansion "
                   "large enough that a close outside the range pays for the trade after costs.",
        entry_rules="Box = high/low of the `box_bars` bars before the current bar; compressed when box range / ATR over the "
                    "preceding atr_lookback bars <= max_box_atr_ratio; BUY on a close above the box, SELL on a close below.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="The box midpoint.",
        take_profit_logic="Entry +/- target_r x risk.",
        session_conditions="None.", regime_conditions="None.",
        module="app.quant.volatility_breakout_strategy",
        param_grid={"box_bars": [8, 12, 20], "max_box_atr_ratio": [3.0, 4.0, 5.0]},
        fixed_params={"atr_lookback": 100, "target_r": 2.0},
    ),
    FamilyDefinition(
        strategy_id="failed-breakout-reversal", version="1.0.0", family=StrategyFamily.FAILED_BREAKOUT.value,
        hypothesis="When an H1 bar closes outside a range and the next bar closes back inside it, the breakout has failed "
                   "and price travels back toward the middle of the range often enough to pay for the trade after costs.",
        entry_rules="Range = high/low of the `range_bars` bars before the breakout bar; SELL when the breakout bar closed above "
                    "the range high and the current bar closes back below it; BUY on the mirror case.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="Beyond the more extreme of the breakout and current bar, plus stop_buffer_atr x ATR(atr_period).",
        take_profit_logic="The range midpoint; skipped unless reward:risk >= 1.5.",
        session_conditions="None.", regime_conditions="None.",
        module="app.quant.failed_breakout_strategy",
        param_grid={"range_bars": [12, 24, 48], "stop_buffer_atr": [0.1, 0.25, 0.5]},
        fixed_params={"atr_period": 14, "min_reward_to_risk": 1.5},
    ),
    FamilyDefinition(
        strategy_id="range-fade", version="1.0.0", family=StrategyFamily.RANGE.value,
        hypothesis="When recent H1 price action is choppy rather than trending, price reaching the edge of its recent range "
                   "turns back toward the middle often enough to pay for the trade after costs.",
        entry_rules="Range = high/low of the `range_bars` bars before the current bar; trade only when the Kaufman efficiency "
                    "ratio <= max_efficiency_ratio; BUY within the bottom 10% of the range, SELL within the top 10%.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="Beyond the range edge by stop_buffer_atr x ATR(atr_period).",
        take_profit_logic="The range midpoint; skipped unless reward:risk >= 1.5.",
        session_conditions="None.", regime_conditions="Efficiency ratio filter (choppy price only).",
        module="app.quant.range_fade_strategy",
        param_grid={"range_bars": [24, 48, 96], "max_efficiency_ratio": [0.2, 0.3, 0.4]},
        fixed_params={"entry_zone": 0.10, "atr_period": 14, "stop_buffer_atr": 0.5, "min_reward_to_risk": 1.5},
    ),
]


# Incremental-feature series: each pipeline-v1 family, unchanged, plus ONE fixed filter.
# The same filter is applied to every family - no per-family choice - and nothing
# about it is tuned, so the filter is the only difference from the unfiltered run.
FILTERS = {
    "liquid-hours": (
        {"type": "session", "allowed_sessions": ["LONDON", "NEW_YORK"]},
        "Only when London or New York is open at the decision bar's close.",
        "The backtests assume a fixed 1.2-pip spread and small slippage, which is realistic in liquid London/New York hours "
        "and optimistic outside them; restricted to those hours, the family is tested under costs it can actually get.",
    ),
    "no-high-vol": (
        {"type": "volatility_regime", "blocked_labels": ["HIGH", "UNKNOWN"]},
        "Not when the volatility regime is HIGH (ATR(14) >= 1.5x the median of the preceding 200) or not yet known.",
        "Fixed spread and slippage assumptions are most wrong, and fixed stops most often overrun, in high-volatility "
        "bursts; excluding them tests the family in the conditions its cost model describes.",
    ),
}


def _filtered(base: FamilyDefinition, name: str) -> FamilyDefinition:
    spec, condition, rationale = FILTERS[name]
    session, regime = base.session_conditions, base.regime_conditions
    if spec["type"] == "session":
        session = condition
    else:
        regime = condition if regime == "None." else f"{regime} Plus: {condition}"
    return replace(
        base, strategy_id=f"{base.strategy_id}-{name}", signal_filter=spec,
        session_conditions=session, regime_conditions=regime,
        hypothesis=(f"Incremental test of {base.strategy_id} v{base.version} (series pipeline-v1, same rules, grid, data "
                    f"and gates) with one fixed filter. {rationale} Base hypothesis: {base.hypothesis}"),
    )


FILTERED_FAMILIES = [_filtered(base, name) for base in FAMILIES for name in FILTERS]
BASE_OF = {variant.strategy_id: base for base in FAMILIES for variant in FILTERED_FAMILIES
           if variant.strategy_id.startswith(base.strategy_id + "-")}

SERIES = {"pipeline-v1": FAMILIES, "pipeline-v2-filters": FILTERED_FAMILIES}

# Portfolio series (report section 7i): one parameter set pooled across every costable
# symbol, on long daily history, with measured per-symbol spreads.
COSTABLE_SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "XAUUSD")

DAILY_TREND_FAMILIES = [
    FamilyDefinition(
        strategy_id="donchian-trend", version="1.0.0", family=StrategyFamily.TREND_MOMENTUM.value,
        hypothesis="A daily close beyond the highest high or lowest low of the previous channel_bars days marks a trend "
                   "that, pooled across the costable FX majors and gold, runs far enough and often enough to pay for the "
                   "trade after measured costs. Trend following is among the longest-documented return sources in futures "
                   "and currencies; it is modest and has had multi-year drawdowns.",
        entry_rules="BUY on a daily close above the highest high of the previous channel_bars bars; SELL on a close below "
                    "their lowest low. The current bar never helps define the channel.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the entry.",
        take_profit_logic="target_r x the stop distance beyond the entry.",
        session_conditions="None (daily bars).", regime_conditions="None.",
        module="app.quant.donchian_trend_strategy",
        param_grid={"channel_bars": [20, 55, 100], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"stop_atr": 2.0, "atr_period": 20},
    ),
    FamilyDefinition(
        strategy_id="time-series-momentum", version="1.0.0", family=StrategyFamily.TREND_MOMENTUM.value,
        hypothesis="A market that rose over the last `lookback` days tends to keep rising and one that fell tends to keep "
                   "falling, often enough, pooled across the costable FX majors and gold, to pay for the trade after "
                   "measured costs. This is the documented time-series momentum effect; it is modest and slow and has had "
                   "long flat or losing stretches.",
        entry_rules="BUY when the daily close is above the close `lookback` bars earlier, SELL when below; with one position "
                    "per symbol, the next trade is taken on the first bar after the previous one exits.",
        exit_rules="Fixed stop and target; no trailing; at most one open position per symbol.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the entry.",
        take_profit_logic="target_r x the stop distance beyond the entry.",
        session_conditions="None (daily bars).", regime_conditions="None.",
        module="app.quant.time_series_momentum_strategy",
        param_grid={"lookback": [63, 126, 252], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"stop_atr": 2.0, "atr_period": 20},
    ),
]

DAILY_TRAILING_FAMILIES = [
    FamilyDefinition(
        strategy_id="donchian-trend-trailing", version="1.0.0", family=StrategyFamily.TREND_MOMENTUM.value,
        hypothesis="Trend following as it is usually traded: enter on a daily close beyond the previous channel_bars-day "
                   "high or low and let the trade run behind a trailing stop until the trend reverses. Its documented "
                   "returns come from a few very large winners, which the fixed 2-4R targets of portfolio-d1-v1 cut off; "
                   "pooled across the costable FX majors and gold, the winners pay for the many small losses after "
                   "measured costs.",
        entry_rules="BUY on a daily close above the highest high of the previous channel_bars bars; SELL on a close below "
                    "their lowest low.",
        exit_rules="A stop trail_atr x ATR(atr_period) from the entry that trails the best price since entry at that "
                   "distance (checked before each bar moves it; a gap beyond it fills at the open), or the distant "
                   "target. At most one open position per symbol.",
        stop_loss_logic="trail_atr x ATR(atr_period), fixed at entry, trailing.",
        take_profit_logic="target_r x the initial stop distance - a distant cap the live safety gate requires.",
        session_conditions="None (daily bars).", regime_conditions="None.",
        module="app.quant.donchian_trend_strategy",
        param_grid={"channel_bars": [20, 55, 100], "trail_atr": [2.0, 3.0, 4.0]},
        fixed_params={"atr_period": 20, "target_r": 10.0},
    ),
    FamilyDefinition(
        strategy_id="time-series-momentum-trailing", version="1.0.0", family=StrategyFamily.TREND_MOMENTUM.value,
        hypothesis="Time-series momentum with the exit trend followers use: take the direction of the past `lookback`-day "
                   "return and hold behind a trailing stop until the move reverses, so the rare long trends are kept "
                   "rather than capped at 2-4R as in portfolio-d1-v1; pooled across the costable FX majors and gold, "
                   "this pays for the trade after measured costs.",
        entry_rules="BUY when the daily close is above the close `lookback` bars earlier, SELL when below; with one "
                    "position per symbol, the next trade is taken on the first bar after the previous one exits.",
        exit_rules="A stop trail_atr x ATR(atr_period) from the entry that trails the best price since entry at that "
                   "distance (checked before each bar moves it; a gap beyond it fills at the open), or the distant "
                   "target. At most one open position per symbol.",
        stop_loss_logic="trail_atr x ATR(atr_period), fixed at entry, trailing.",
        take_profit_logic="target_r x the initial stop distance - a distant cap the live safety gate requires.",
        session_conditions="None (daily bars).", regime_conditions="None.",
        module="app.quant.time_series_momentum_strategy",
        param_grid={"lookback": [63, 126, 252], "trail_atr": [2.0, 3.0, 4.0]},
        fixed_params={"atr_period": 20, "target_r": 10.0},
    ),
]

PORTFOLIO_SERIES = {
    "portfolio-d1-v1": (
        portfolio_pipeline.PortfolioConfig(
            series="portfolio-d1-v1", symbols=COSTABLE_SYMBOLS,
            symbol_data_starts=(
                ("XAUUSD", "2014-02-20",
                 "The broker's XAUUSD daily history has gaps of 25 days (2012-09-19 to 2012-10-14) and 92 days "
                 "(2013-11-19 to 2014-02-19); a trade held across either would be valued at prices that never traded."),
            ),
            execution_hours_utc=(22, 23),
            execution_rule=(
                "The daily signal falls at the close, the 17:00 New York rollover, when measured FX spreads widen to "
                "6-18 pips and the live 2-pip spread cap refuses entries. Execution is assumed one hour later, 18:00-19:00 "
                "New York (22:00-23:00 UTC in the measured daylight-saving period), charging the worst 90th-percentile "
                "spread of those two hours. The entry price is still the daily close: price movement during that hour "
                "is not modelled."
            ),
            cost_profile_file="measured_costs_20260914_broker.json",
        ),
        DAILY_TREND_FAMILIES,
    ),
}
# Same data, costs, gates and execution rule as portfolio-d1-v1; only the exit differs, and trades
# still open at a slice's end are closed there rather than dropped (they are a trend follower's longest trades).
PORTFOLIO_SERIES["portfolio-d1-v2-trailing"] = (
    replace(PORTFOLIO_SERIES["portfolio-d1-v1"][0], series="portfolio-d1-v2-trailing", close_open_trades_at_slice_end=True),
    DAILY_TRAILING_FAMILIES,
)

# Diversified trend following. The universe was fixed from data quality and market structure BEFORE any
# result: USD-quoted instruments with at least ~10 years of clean daily history on this broker, open at the
# execution hour. Excluded: US Treasuries (2 years of history), corn/wheat/soybeans (5-6 years), copper
# (a 33-month gap and 882 flat bars), sugar/coffee and Brent crude (closed at the execution hour - Brent's
# broker schedule reopens at 20:00 New York, and measured no ticks at 21-23 UTC), VIX (a volatility index,
# not a trending asset), and instruments quoted in other currencies (no conversion is modelled).
MULTI_ASSET_SYMBOLS = (
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD",
    "XAUUSD", "XAGUSD", "XPTUSD",
    "US500", "NAS100", "US30", "US2000",
    "SPOTCRUDE", "NATGAS",
)

_DIVERSIFIED = (
    " Diversified across US equity indices, energies, precious metals and the USD FX majors - the breadth the "
    "documented trend-following results rest on. The FX and gold part of this universe was already tested in "
    "portfolio-d1-v2-trailing (rejected at validation), so this series is not independent of it; its locked "
    "2022-2026 slice was never used."
)

PORTFOLIO_SERIES["portfolio-d1-v3-multiasset"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v2-trailing"][0],
        series="portfolio-d1-v3-multiasset",
        symbols=MULTI_ASSET_SYMBOLS,
        symbol_data_starts=(
            ("XAUUSD", "2014-02-20", "Gaps of 25 days (2012-09-19 to 2012-10-14) and 92 days (2013-11-19 to 2014-02-19)."),
            ("XAGUSD", "2014-02-20", "The same two gaps as XAUUSD in the broker's history."),
            ("XPTUSD", "2016-04-19", "A 22-day gap (2016-03-27 to 2016-04-18)."),
            ("NATGAS", "2016-05-23", "Gaps of 304, 6 and 89 days in 2015-2016, the last ending 2016-05-22."),
            ("US2000", "2015-10-22", "A 315-day gap (2014-12-09 to 2015-10-21)."),
        ),
        broker_instrument_specs=True,
        spread_cap_multiple=2.0,
        cost_profile_file="measured_costs_20260914_multiasset_broker.json",
        execution_rule=(
            "The daily signal falls at the close, the 17:00 New York rollover, when FX spreads widen to 6-18 pips and "
            "index, metal and energy CFDs take their daily break. Execution is assumed one hour later, 18:00-19:00 New "
            "York (22:00-23:00 UTC in the measured daylight-saving period), charging the worst 90th-percentile spread of "
            "those two hours. The entry price is still the daily close: price movement during that hour is not modelled."
        ),
    ),
    [replace(family, hypothesis=family.hypothesis + _DIVERSIFIED) for family in DAILY_TRAILING_FAMILIES],
)

# Discretionary-style market structure on H4 (report §7o). Broker H4 bars close at the 17:00 New York rollover
# once a day; signals decided then are dropped, while the strategy still tracks every bar.
ROLLOVER_FILTER = {"type": "exclude_new_york_hours", "hours": [17]}
_STRUCTURE_REGIME = "Only with the market structure described; no volatility or news filter."
_STRUCTURE_SESSION = "Any hour except decisions at the 17:00 New York rollover (bars closing then are skipped)."

H4_STRUCTURE_FAMILIES = [
    FamilyDefinition(
        strategy_id="market-structure-pullback", version="1.0.0", family="TREND_MOMENTUM",
        hypothesis=(
            "The discretionary 'trade with the structure' setup: when price makes higher highs and higher lows, a "
            "pullback to the latest higher low that is rejected there resumes the trend often enough, with a stop "
            "just beyond that low, to pay for costs across many markets. Lower highs and lower lows mirror it."
        ),
        entry_rules=("Up structure (last two confirmed swing highs and lows both rising): the decision bar's low is "
                     "within zone_atr x ATR above the latest swing low, and it closes bullish, above that zone, below "
                     "the latest swing high. SELL mirrors."),
        exit_rules="Stop or target, whichever is hit first; stop checked first on the same bar.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the latest swing low (BUY) or high (SELL).",
        take_profit_logic="target_r x the risk from the entry close.",
        session_conditions=_STRUCTURE_SESSION, regime_conditions=_STRUCTURE_REGIME,
        module="app.quant.market_structure_pullback_strategy",
        param_grid={"swing_bars": [2, 3, 5], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"zone_atr": 0.5, "stop_atr": 0.5, "atr_period": 14},
        signal_filter=ROLLOVER_FILTER,
    ),
    FamilyDefinition(
        strategy_id="structure-break-retest", version="1.0.0", family="BREAKOUT",
        hypothesis=(
            "The discretionary 'break and retest' setup: after price closes beyond the latest swing high and holds, "
            "a return to that level that is rejected shows old resistance acting as support often enough, with a "
            "stop just below the level, to pay for costs across many markets. A break below a swing low mirrors it."
        ),
        entry_rules=("The first close above the latest confirmed swing high came no more than retest_bars bars ago and "
                     "every close since held above it; the decision bar's low reaches within zone_atr x ATR of the "
                     "level and it closes bullish above the level. SELL mirrors."),
        exit_rules="Stop or target, whichever is hit first; stop checked first on the same bar.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the broken level.",
        take_profit_logic="target_r x the risk from the entry close.",
        session_conditions=_STRUCTURE_SESSION, regime_conditions=_STRUCTURE_REGIME,
        module="app.quant.structure_break_retest_strategy",
        param_grid={"swing_bars": [2, 3, 5], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"retest_bars": 20, "zone_atr": 0.5, "stop_atr": 0.5, "atr_period": 14},
        signal_filter=ROLLOVER_FILTER,
    ),
]

PORTFOLIO_SERIES["portfolio-h4-v1-structure"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v3-multiasset"][0],
        series="portfolio-h4-v1-structure",
        timeframe="H4",
        close_open_trades_at_slice_end=False,
        require_multiple_testing_significance=True,
        cost_profile_file="measured_costs_20260914_multiasset24h_broker.json",
        execution_hours_utc=(1, 5, 9, 13, 17),
        symbol_data_starts=(
            ("XAUUSD", "2020-09-30", "H4 gaps of 24 days (2012), 91 days (2013-11-20 to 2014-02-19) and 92 days "
                                     "(2020-06-30 to 2020-09-30); the last is absent from the D1 history."),
            ("XAGUSD", "2014-02-19", "H4 gaps of 24 days (2012) and 91 days (2013-11-20 to 2014-02-19)."),
            ("XPTUSD", "2016-04-19", "An H4 gap of 21 days (2016-03-28 to 2016-04-19)."),
            ("US2000", "2015-10-21", "An H4 gap of 315 days (2014-12-10 to 2015-10-21)."),
            ("NATGAS", "2016-05-22", "H4 gaps of 304, 5 and 89 days in 2015-2016, the last ending 2016-05-22."),
        ),
        execution_rule=(
            "Signals are decided at H4 bar closes: 01, 05, 09, 13 and 17 UTC in the measured daylight-saving period "
            "(the same New York times in winter). Decisions at the 17:00 New York rollover close (21 UTC in summer) are "
            "dropped by the rollover filter. Each market is charged the worst 90th-percentile spread of those five hours "
            "from a 24-hour broker tick profile measured in summer; winter is assumed to follow the same New York-time "
            "pattern. Entry is at the decision bar's close: price movement before the order fills is not modelled."
        ),
    ),
    H4_STRUCTURE_FAMILIES,
)

# ---- Idea batch of 2026-09-14 (report §7p): currency strength, weekday-hour seasonality, shock-day continuation.
# Every series requires the multiple-testing guard.

CURRENCY_STRENGTH_FAMILIES = [
    FamilyDefinition(
        strategy_id="currency-strength-momentum", version="1.0.0", family="TREND_MOMENTUM",
        hypothesis=(
            "Cross-sectional currency momentum: the currencies that strengthened most against the others over recent "
            "months keep outperforming and the weakest keep underperforming, so buying the strongest against USD and "
            "selling the weakest, with a trailing stop, pays for costs. Unlike time-series momentum, a currency is "
            "ranked against the other seven, not against its own past."
        ),
        entry_rules=("Rank EUR, GBP, AUD, NZD, JPY, CHF, CAD and USD by log return against USD over `lookback` daily "
                     "bars (USD = minus the mean of the seven). Long a currency in the top top_k that is stronger than "
                     "USD; short one in the bottom top_k that is weaker than USD, through its USD pair."),
        exit_rules="Trailing stop; a distant target cap; trades open at a slice end are closed at its last close.",
        stop_loss_logic="trail_atr x ATR(atr_period), trailing the best price since entry.",
        take_profit_logic="target_r x the initial risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="None.",
        module="app.quant.currency_strength_strategy",
        param_grid={"lookback": [21, 63, 126], "trail_atr": [2.0, 3.0, 4.0]},
        fixed_params={"top_k": 2, "atr_period": 20, "target_r": 10.0},
    ),
]

SEASONALITY_FAMILIES = [
    FamilyDefinition(
        strategy_id="weekday-hour-seasonality", version="1.0.0", family="SESSION_BASED",
        hypothesis=(
            "Recurring flows at the same time of the week - fixings, session opens, week-end squaring, index "
            "rebalancing - make the average return of a weekday-and-time slot persist from week to week, strongly "
            "enough to trade the next H4 bar in that direction after costs."
        ),
        entry_rules=("At an H4 close, take the next bar's New York (weekday, hour) slot and the log returns of that "
                     "slot's last lookback_weeks bars (at least half present): BUY if mean / (sd / sqrt(n)) >= min_t, "
                     "SELL if <= -min_t."),
        exit_rules="At the close of the next bar (hold_bars = 1), unless the stop or the distant cap is hit first.",
        stop_loss_logic="stop_atr x ATR(atr_period) from the entry close.",
        take_profit_logic="target_r x the risk, a distant cap only.",
        session_conditions=_STRUCTURE_SESSION,
        regime_conditions="None.",
        module="app.quant.weekday_hour_seasonality_strategy",
        param_grid={"lookback_weeks": [26, 52, 104], "min_t": [1.0, 1.5, 2.0]},
        fixed_params={"stop_atr": 1.0, "atr_period": 14, "target_r": 10.0, "hold_bars": 1, "bar_minutes": 240},
        signal_filter=ROLLOVER_FILTER,
    ),
]

SHOCK_FAMILIES = [
    FamilyDefinition(
        strategy_id="shock-day-continuation", version="1.0.0", family="VOLATILITY_EXPANSION",
        hypothesis=(
            "A day with a far larger range than normal, closing near its extreme, usually reflects news (a data "
            "release, a central-bank surprise). Markets absorb news over several days, so the move continues often and "
            "far enough, with a stop at the far end of the shock day, to pay for costs. The broker has no historical "
            "news calendar, so shocks are identified from price alone."
        ),
        entry_rules=("The decision day's true range >= shock_atr x ATR(atr_period) of the days before it; BUY if it "
                     "closes in the top close_zone of its range, SELL if in the bottom close_zone."),
        exit_rules="Stop or target, whichever is hit first; stop checked first on the same bar.",
        stop_loss_logic="The shock day's low (BUY) or high (SELL).",
        take_profit_logic="target_r x the risk from the close.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only after a shock day as defined.",
        module="app.quant.shock_day_continuation_strategy",
        param_grid={"shock_atr": [1.5, 2.0, 2.5], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"close_zone": 0.25, "atr_period": 20},
    ),
]

PORTFOLIO_SERIES["portfolio-d1-v4-currency-strength"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v3-multiasset"][0],
        series="portfolio-d1-v4-currency-strength",
        symbols=("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"),
        symbol_data_starts=(),
        bar_features="currency_strength",
        require_multiple_testing_significance=True,
    ),
    CURRENCY_STRENGTH_FAMILIES,
)

PORTFOLIO_SERIES["portfolio-h4-v2-seasonality"] = (
    # 3,200 H4 bars (about two years) of warm-up, so even the 104-week lookback is filled at the start of every
    # validation, walk-forward and locked slice; 300 bars would leave those slices untraded for months.
    replace(PORTFOLIO_SERIES["portfolio-h4-v1-structure"][0], series="portfolio-h4-v2-seasonality", warmup_bars=3200),
    SEASONALITY_FAMILIES,
)

DAY_WINDOW_SEASONALITY_FAMILIES = [
    FamilyDefinition(
        strategy_id="weekday-day-window-seasonality", version="1.0.0", family="SESSION_BASED",
        hypothesis=(
            "Recurring weekly flows make the return of the next 24 hours, starting from a given weekday and time, "
            "persist from week to week; trading that full-day window and holding it for the day pays the round-trip "
            "cost once instead of on every four-hour bar. CHOSEN AFTER LOOKING AT TRAINING DATA: the gross-edge "
            "diagnostic (report 7r) showed one-bar weekday-hour seasonality at +0.045R before costs and -0.038R after "
            "on its training slice. The stop scales with the hold (sqrt(6) x one-bar ATR, about 2.5 ATR), fixed "
            "before any run. Counted in the registry and judged by the multiple-testing guard."
        ),
        entry_rules=("At an H4 close, take the New York (weekday, hour) slot of the next bar and the log returns of the "
                     "six-bar windows that started in that slot over the last lookback_weeks weeks (at least half "
                     "present): BUY if mean / (sd / sqrt(n)) >= min_t, SELL if <= -min_t."),
        exit_rules="At the close of the sixth bar after entry (one trading day), unless the stop or the distant cap is hit first.",
        stop_loss_logic="stop_atr (2.5) x ATR(atr_period) of H4 bars from the entry close.",
        take_profit_logic="target_r x the risk, a distant cap only.",
        session_conditions=_STRUCTURE_SESSION,
        regime_conditions="None.",
        module="app.quant.weekday_hour_seasonality_strategy",
        param_grid={"lookback_weeks": [26, 52, 104], "min_t": [1.0, 1.5, 2.0]},
        fixed_params={"stop_atr": 2.5, "atr_period": 14, "target_r": 10.0, "hold_bars": 6, "bar_minutes": 240},
        signal_filter=ROLLOVER_FILTER,
    ),
]

PORTFOLIO_SERIES["portfolio-h4-v3-seasonality-day-window"] = (
    replace(PORTFOLIO_SERIES["portfolio-h4-v2-seasonality"][0], series="portfolio-h4-v3-seasonality-day-window"),
    DAY_WINDOW_SEASONALITY_FAMILIES,
)

CARRY_FAMILIES = [
    FamilyDefinition(
        strategy_id="fx-carry", version="1.0.0", family="REGIME_SPECIFIC",
        hypothesis=(
            "Currencies with higher short-term interest rates tend to earn the interest differential without losing "
            "it all to exchange-rate moves (the forward-premium puzzle). Holding the higher-yielding side of a USD "
            "pair when the 3-month rate differential is large, and collecting the modelled overnight swap, pays for "
            "spread, commission and the broker's swap markup. Interest rates come from an outside source (FRED), "
            "approved by the user on 2026-09-15; this is new, non-price information, not another chart pattern."
        ),
        entry_rules=("At the daily close, with as-of 3-month rates (2-month publication lag, at most 3 months old): BUY "
                     "the pair if base rate - quote rate >= min_diff_pct, SELL if <= -min_diff_pct."),
        exit_rules="At the close 21 bars after entry (about a month) unless stopped; still qualifying pairs are re-entered.",
        stop_loss_logic="stop_atr x ATR(atr_period) from the entry close.",
        take_profit_logic="target_r x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only when the as-of rate differential clears min_diff_pct.",
        module="app.quant.fx_carry_strategy",
        param_grid={"min_diff_pct": [0.5, 1.0, 2.0], "stop_atr": [3.0, 5.0, 8.0]},
        fixed_params={"atr_period": 20, "target_r": 10.0, "hold_bars": 21},
    ),
]

PORTFOLIO_SERIES["portfolio-d1-v6-carry"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v4-currency-strength"][0],
        series="portfolio-d1-v6-carry",
        bar_features="interest_rates",
        external_rates="fred_3m_interbank",
        swap_model=True,
    ),
    CARRY_FAMILIES,
)

_INDEX_NOTE = (
    " US500 and US2000 only: at a $50 risk the minimum 0.1-lot NAS100 and US30 position exceeds a 3-ATR stop from "
    "2020 and 2016 onward, so their trades would be refused. Overnight index financing is modelled from the as-of "
    "USD rate and the broker's measured markup."
)

INDEX_ANOMALY_FAMILIES = [
    FamilyDefinition(
        strategy_id="index-dip-in-uptrend", version="1.0.0", family="MEAN_REVERSION",
        hypothesis=("In US equity indices, a new multi-day closing low while price is above its 200-day average is "
                    "usually a temporary overshoot that rebounds within days, enough to pay spread, slippage and "
                    "overnight financing. Long only." + _INDEX_NOTE),
        entry_rules="Close above the 200-day mean of closes and below every close of the previous dip_days days: BUY.",
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="3 x ATR(20) below the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only above the 200-day mean.",
        module="app.quant.index_dip_strategy",
        param_grid={"dip_days": [2, 3, 5], "hold_bars": [3, 5, 10]},
        fixed_params={"trend_days": 200, "stop_atr": 3.0, "atr_period": 20, "target_r": 10.0},
    ),
    FamilyDefinition(
        strategy_id="turn-of-month-long", version="1.0.0", family="SESSION_BASED",
        hypothesis=("US equity returns concentrate around the month boundary (month-end inflows, rebalancing, window "
                    "dressing); holding an index long from the k-th last weekday of a month for a few days earns "
                    "enough to pay spread, slippage and overnight financing. Long only." + _INDEX_NOTE),
        entry_rules=("BUY at the close of the session that is the k-th last calendar weekday of its month "
                     "(k = days_before_month_end); holidays not modelled."),
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="3 x ATR(20) below the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close around month end; execution per the series' execution rule.",
        regime_conditions="None.",
        module="app.quant.turn_of_month_strategy",
        param_grid={"days_before_month_end": [1, 2, 3], "hold_bars": [3, 4, 6]},
        fixed_params={"stop_atr": 3.0, "atr_period": 20, "target_r": 10.0},
    ),
    FamilyDefinition(
        strategy_id="index-unconditional-long", version="1.0.0", family="TREND_MOMENTUM",
        hypothesis=("BENCHMARK: US equity indices carry a positive risk premium, so buying at every close when flat and "
                    "holding a fixed number of days beats spread, slippage and overnight financing. The dip and "
                    "turn-of-month rules show timing skill only if they beat this; if this passes too, their profits "
                    "may be the market's rise rather than timing. Long only." + _INDEX_NOTE),
        entry_rules="BUY at every daily close while flat.",
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="stop_atr x ATR(20) below the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="None.",
        module="app.quant.index_unconditional_long_strategy",
        param_grid={"hold_bars": [3, 5, 10], "stop_atr": [2.0, 3.0, 4.0]},
        fixed_params={"atr_period": 20, "target_r": 10.0},
    ),
]

PORTFOLIO_SERIES["portfolio-d1-v7-index-anomalies"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v3-multiasset"][0],
        series="portfolio-d1-v7-index-anomalies",
        symbols=("US500", "US2000"),
        symbol_data_starts=(("US2000", "2015-10-22", "A 315-day gap (2014-12-09 to 2015-10-21)."),),
        external_rates="fred_3m_interbank",
        swap_model=True,
        require_multiple_testing_significance=True,
        # Two tradable markets: both must have enough trades and BOTH must be positive (stricter than half of four).
        breadth_min_eligible_symbols=2,
        breadth_min_positive_fraction=1.0,
    ),
    INDEX_ANOMALY_FAMILIES,
)

VIX_SPIKE_FAMILIES = [
    FamilyDefinition(
        strategy_id="index-vix-spike", version="1.0.0", family="VOLATILITY_EXPANSION",
        hypothesis=(
            "A sharp rise in the VIX marks fear-driven selling that usually overshoots; US equity indices tend to "
            "recover over the following days to weeks as the fear premium decays, enough to pay spread, slippage and "
            "overnight financing. It uses option-implied volatility (FRED VIXCLS), information the price chart does "
            "not contain. Long only. CHOSEN AFTER SEEING the index dip-in-uptrend result on the same two indices and "
            "the same training and validation slices (report 7u); counted in the registry and judged by the "
            "multiple-testing guard." + _INDEX_NOTE
        ),
        entry_rules=("BUY when the latest VIX close known at the decision (one-day lag) is at least spike_pct above "
                     "the mean of the 20 closes before it."),
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="3 x ATR(20) below the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only after a VIX spike as defined.",
        module="app.quant.index_vix_spike_strategy",
        param_grid={"spike_pct": [0.20, 0.35, 0.50], "hold_bars": [5, 10, 20]},
        fixed_params={"lookback": 20, "stop_atr": 3.0, "atr_period": 20, "target_r": 10.0},
    ),
]

PORTFOLIO_SERIES["portfolio-d1-v8-vix-spike"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v7-index-anomalies"][0],
        series="portfolio-d1-v8-vix-spike",
        external_daily=("VIX",),
        bar_features="fred_daily",
    ),
    VIX_SPIKE_FAMILIES,
)

_FIX_HYPOTHESIS = (
    "International investors reset the currency hedges on their foreign equity holdings at month-end, largely at the "
    "London 4pm fix. When US equities outperformed foreign equities over the month, foreign holders of US stocks must "
    "sell more US dollars to stay hedged, so the dollar tends to weaken in the hours before the fix on the month's last "
    "weekday, and strengthen when US equities underperformed. Documented in academic work on the London fix. Inputs: "
    "FX hourly bars and equity index daily closes, all from the broker; the indices are signal inputs, never traded. "
    "CHF, CAD and NZD are excluded: the broker's SWI20 and CA60 histories start only in 2020 and it lists no New "
    "Zealand index."
)


def _fix_family(strategy_id: str, placebo: int, hypothesis: str) -> FamilyDefinition:
    day = ("the last weekday on or before the 15th (a mid-month control day)" if placebo
           else "the last weekday of the month")
    return FamilyDefinition(
        strategy_id=strategy_id, version="1.0.0", family="SESSION_BASED", hypothesis=hypothesis,
        entry_rules=(f"On {day}, at the close of the hourly bar ending hours_before_fix hours before 16:00 London: if "
                     "US500 month-to-date return minus the pair's foreign index return (EUSTX50, UK100, AUS200, "
                     "JPN225) exceeds threshold_pct points, BUY XXXUSD / SELL USDJPY; below -threshold_pct, the reverse."),
        exit_rules="At the close of the bar ending 16:00 London, unless stopped.",
        stop_loss_logic="3 x ATR(24) of hourly bars from the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="London morning to the 4pm fix.",
        regime_conditions="Only when the US-minus-foreign month-to-date equity gap exceeds threshold_pct.",
        module="app.quant.month_end_fix_strategy",
        param_grid={"threshold_pct": [0.0, 1.0, 2.0], "hours_before_fix": [2, 4, 6]},
        fixed_params={"fix_hour": 16, "stop_atr": 3.0, "atr_period": 24, "target_r": 10.0, "bar_minutes": 60,
                      "mid_month_placebo": placebo},
    )


MONTH_END_FIX_FAMILIES = [
    _fix_family("month-end-fix-flow", 0, _FIX_HYPOTHESIS),
    _fix_family("mid-month-fix-placebo", 1, (
        "CONTROL for month-end-fix-flow: the identical rule on a mid-month day, when no month-end hedge rebalancing "
        "happens. If this also passes, the month-end rule's profits reflect a general link between equity and currency "
        "moves, not month-end flows. " + _FIX_HYPOTHESIS)),
]

PORTFOLIO_SERIES["portfolio-h1-v1-month-end-fix"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v4-currency-strength"][0],
        series="portfolio-h1-v1-month-end-fix",
        timeframe="H1",
        symbols=("EURUSD", "GBPUSD", "AUDUSD", "USDJPY"),
        data_start="2014-08-01",
        data_start_reason=(
            "cTrader's daily history for the foreign equity indices begins in July 2014 (EUSTX50 9 Jul, AUS200 6 Jul, "
            "FRA40 14 Jul, JPN225 16 Jul, UK100 17 Jul); August 2014 is the first month with a previous month-end "
            "close for all of them."
        ),
        symbol_data_starts=(),
        bar_features="month_end_equity",
        feature_symbols=("US500", "EUSTX50", "UK100", "AUS200", "JPN225"),
        feature_timeframe="D1",
        cost_profile_file="measured_costs_20260914_multiasset24h_broker.json",
        execution_hours_utc=(9, 10, 11, 12, 13, 14, 15, 16),
        execution_rule=(
            "Entries are decided at hourly closes 2, 4 or 6 hours before 16:00 London and exit at the bar ending "
            "16:00 London: 09:00-16:00 UTC across summer and winter. Each pair is charged the worst 90th-percentile "
            "spread of those UTC hours from the 24-hour broker tick profile. Trades close the same day before the "
            "rollover, so no swaps apply. Entry is at the decision bar's close: price movement before the order fills, "
            "and any widening at the fix itself beyond the profile, are not modelled."
        ),
        close_open_trades_at_slice_end=False,
    ),
    MONTH_END_FIX_FAMILIES,
)

_COT_NOTE = (
    " Positioning is CFTC Traders in Financial Futures leveraged-funds net positions in CME currency futures (outside, "
    "non-price data approved by the user on 2026-09-15), known from the Monday after each Tuesday report; delayed "
    "publication during US government shutdowns is not modelled. Trades last weeks, so overnight swaps are modelled as "
    "in the carry series. Both the reversal and the momentum reading of positioning are preregistered and counted."
)

COT_FAMILIES = [
    FamilyDefinition(
        strategy_id="cot-crowding-reversal", version="1.0.0", family="MEAN_REVERSION",
        hypothesis=("When leveraged funds hold an extreme net position in a currency relative to the last three years, "
                    "the trade is crowded and tends to reverse as they exit; fading the extreme pays for costs." + _COT_NOTE),
        entry_rules=("Rank the latest known net position among the last 156 weekly reports: at or above the 1 - extreme "
                     "share, sell the currency against USD; at or below the extreme share, buy it."),
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="3 x ATR(20) from the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only at a positioning extreme.",
        module="app.quant.cot_crowding_strategy",
        param_grid={"extreme": [0.05, 0.10, 0.20], "hold_bars": [5, 10, 20]},
        fixed_params={"lookback_weeks": 156, "stop_atr": 3.0, "atr_period": 20, "target_r": 10.0},
    ),
    FamilyDefinition(
        strategy_id="cot-positioning-momentum", version="1.0.0", family="TREND_MOMENTUM",
        hypothesis=("When leveraged funds add an unusually large net position in a currency over recent weeks, the "
                    "currency tends to keep moving their way while that capital arrives; following it pays for costs."
                    + _COT_NOTE),
        entry_rules=("Change in the latest known net position over change_weeks reports, divided by the standard "
                     "deviation of that change over the previous 104 reports: >= 1.0 buy the currency against USD, "
                     "<= -1.0 sell it."),
        exit_rules="At the close hold_bars bars after entry, unless stopped.",
        stop_loss_logic="3 x ATR(20) from the entry close.",
        take_profit_logic="10 x the risk, a distant cap only.",
        session_conditions="Daily close; execution per the series' execution rule.",
        regime_conditions="Only after an unusually large positioning change.",
        module="app.quant.cot_momentum_strategy",
        param_grid={"change_weeks": [1, 4, 13], "hold_bars": [5, 10, 20]},
        fixed_params={"lookback_weeks": 104, "z_min": 1.0, "stop_atr": 3.0, "atr_period": 20, "target_r": 10.0},
    ),
]

PORTFOLIO_SERIES["portfolio-d1-v9-cot-positioning"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v6-carry"][0],
        series="portfolio-d1-v9-cot-positioning",
        bar_features="cot_positioning",
        external_cot=True,
        cot_first_year=2006,
    ),
    COT_FAMILIES,
)

PORTFOLIO_SERIES["portfolio-d1-v5-shock-continuation"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-d1-v3-multiasset"][0],
        series="portfolio-d1-v5-shock-continuation",
        close_open_trades_at_slice_end=False,
        require_multiple_testing_significance=True,
    ),
    SHOCK_FAMILIES,
)

# ---- Liquidity levels on 15-minute bars (report §7q): yesterday's and last week's high and low, where stops rest.
LIQUIDITY_ROLLOVER_FILTER = {"type": "exclude_new_york_hours", "hours": [17, 18]}
_LIQUIDITY_SESSION = "Any hour except decisions in New York hours 17 and 18 (the rollover and the thin hour after it)."
_LIQUIDITY_REGIME = "Daily bias: the last completed daily close above (BUY) or below (SELL) the mean of bias_days closes."

LIQUIDITY_FAMILIES = [
    FamilyDefinition(
        strategy_id="liquidity-sweep-reversal", version="1.0.0", family="LIQUIDITY_SWEEP_CONFIRMATION",
        hypothesis=(
            "Many traders rest stops just beyond the previous day's and previous week's high and low. When price first "
            "runs those stops and closes straight back inside, the stop orders were absorbed and the move fails; "
            "trading back with the daily bias, with a stop just beyond the sweep, pays for costs (the smart-money / "
            "ICT liquidity grab at daily and weekly liquidity)."
        ),
        entry_rules=("Bias up: at the previous day's or week's low L, the prior bar closed above L, today had not traded "
                     "below L before, and this 15-minute bar trades below L and closes back above it. SELL mirrors at "
                     "the highs with bias down."),
        exit_rules="Stop or target, whichever is hit first; stop checked first on the same bar.",
        stop_loss_logic="stop_buffer_atr x ATR(atr_period) beyond the sweep bar's extreme.",
        take_profit_logic="target_r x the risk from the entry close.",
        session_conditions=_LIQUIDITY_SESSION, regime_conditions=_LIQUIDITY_REGIME,
        module="app.quant.liquidity_sweep_reversal_strategy",
        param_grid={"bias_days": [10, 20, 50], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"stop_buffer_atr": 0.1, "atr_period": 14},
        signal_filter=LIQUIDITY_ROLLOVER_FILTER,
    ),
    FamilyDefinition(
        strategy_id="liquidity-run-continuation", version="1.0.0", family="BREAKOUT",
        hypothesis=(
            "A close through the previous day's or week's high in the direction of the daily bias means the stops "
            "resting there fuelled a genuine move; a pullback that retests the broken level and is rejected shows it "
            "has turned to support, and the trend continues often enough, with a stop just beyond the level, to pay "
            "for costs."
        ),
        entry_rules=("Bias up: within the last retest_bars 15-minute bars of today, a fresh close above the previous "
                     "day's or week's high H with every close since above it; this bar's low reaches within zone_atr x "
                     "ATR of H and it closes bullish above H. SELL mirrors at the lows with bias down."),
        exit_rules="Stop or target, whichever is hit first; stop checked first on the same bar.",
        stop_loss_logic="stop_atr x ATR(atr_period) beyond the broken level.",
        take_profit_logic="target_r x the risk from the entry close.",
        session_conditions=_LIQUIDITY_SESSION, regime_conditions=_LIQUIDITY_REGIME,
        module="app.quant.liquidity_run_continuation_strategy",
        param_grid={"bias_days": [10, 20, 50], "target_r": [2.0, 3.0, 4.0]},
        fixed_params={"retest_bars": 16, "zone_atr": 0.25, "stop_atr": 0.5, "atr_period": 14},
        signal_filter=LIQUIDITY_ROLLOVER_FILTER,
    ),
]

PORTFOLIO_SERIES["portfolio-m15-v1-liquidity"] = (
    replace(
        PORTFOLIO_SERIES["portfolio-h4-v1-structure"][0],
        series="portfolio-m15-v1-liquidity",
        timeframe="M15",
        symbols=("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "XAUUSD", "US500", "NAS100"),
        data_start="2019-01-01",
        data_start_reason=(
            "15-minute history is large - about 190,000 bars a symbol since 2019 - and is held in memory; 2019 keeps "
            "ten markets within this PC's memory and still leaves about four years of training data."
        ),
        symbol_data_starts=(
            ("XAUUSD", "2020-09-30", "The broker's H4 XAUUSD history has a 92-day gap (2020-06-30 to 2020-09-30); "
                                     "the 15-minute fetch is gap-checked as well."),
        ),
        # About 52 trading days of 15-minute bars, so the 50-day bias is filled at the start of every evaluated slice.
        warmup_bars=5000,
        # Seven-plus years of data cannot fit 4 + 1 year windows; 2 years in-sample, 6 months out-of-sample.
        walk_forward_in_sample_days=730,
        walk_forward_out_of_sample_days=182,
        execution_hours_utc=tuple(h for h in range(24) if h not in (21, 22)),
        execution_rule=(
            "Signals are decided at 15-minute bar closes at any hour except New York hours 17 and 18 (21 and 22 UTC in "
            "the measured daylight-saving period), which the rollover filter drops. Each market is charged the worst "
            "90th-percentile spread over the remaining 22 UTC hours of a 24-hour broker tick profile measured in "
            "summer; winter is assumed to follow the same New York-time pattern. Entry is at the decision bar's close: "
            "price movement before the order fills is not modelled."
        ),
    ),
    LIQUIDITY_FAMILIES,
)


def run_portfolio_series(args) -> None:
    config, families = PORTFOLIO_SERIES[args.series]
    families = [f for f in families if not args.family or f.strategy_id in args.family]
    # A series names its own profile, so a newer profile measured for another series never becomes its default.
    profile = args.cost_profile or (cost_profile.PROFILE_DIR / config.cost_profile_file if config.cost_profile_file
                                    else cost_profile.latest_profile_path())
    if profile is None:
        raise SystemExit("[BLOCKED] No measured cost profile. Run hafnot_measure_costs.py after a full weekday of quotes.")
    print(f"[FETCH] {config.timeframe} bars {config.data_start} to {config.data_end} for {len(config.symbols)} symbols "
          "from cTrader, into memory (nothing is stored)...")
    try:
        data = portfolio_pipeline.fetch_portfolio_data(config, Path(profile))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"[BLOCKED] {exc}")
    print("[FETCH] " + ", ".join(f"{s} {len(b)}" for s, b in data.bars.items()))

    for family in families:
        print(f"[PREREGISTERED] {portfolio_pipeline.preregister(family, config, data).name}")
    if args.preregister_only:
        return

    print()
    print(f"{'strategy':<24}{'decision':<10}{'stopped at':<22}{'train exp':>10}{'breadth':>9}{'val trades':>11}{'val PF':>8}{'val exp':>9}")
    for family in families:
        try:
            outcome = portfolio_pipeline.run_portfolio_experiment(family, config, data)
        except RuntimeError as exc:
            print(f"{family.strategy_id:<24}SKIPPED   {exc}")
            continue
        stages = {s.stage: s for s in outcome.stages}
        train = stages["TRAIN"].metrics
        chosen = next((c for c in train["combos"] if c["params"] == train["chosen_params"]), {})
        vm = stages["VALIDATION"].metrics if "VALIDATION" in stages else {}
        print(f"{family.strategy_id:<24}{outcome.decision:<10}{outcome.stage_reached:<22}"
              f"{_fmt(chosen.get('expectancy_r')):>10}{_fmt(train.get('breadth_positive_fraction'), '{:.2f}'):>9}"
              f"{_fmt(vm.get('trade_count'), '{}'):>11}{_fmt(vm.get('profit_factor'), '{:.2f}'):>8}{_fmt(vm.get('expectancy_r')):>9}")
        failed = next((s for s in outcome.stages if not s.passed), None)
        if failed:
            for reason in failed.reasons[:3]:
                print(f"{'':<24}- {reason}")
    print_selection_bias_report(selection_bias_report())


def _fmt(value, spec="{:.3f}"):
    return "-" if value is None else spec.format(value)


def _train_combos(experiment_id: str):
    for experiment in list_experiments():
        if experiment.get("experiment_id") == experiment_id:
            result = experiment.get("result") or {}
            combos = ((result.get("metrics") or {}).get("TRAIN") or {}).get("combos") or []
            return {json.dumps(c["params"], sort_keys=True): c for c in combos}, result.get("stage_reached")
    return None, None


def print_filter_comparison(symbols: list[str]) -> None:
    """
    Each filtered family against its unfiltered pipeline-v1 run: the same nine parameter
    combinations on the same TRAIN slice. Validation and locked data are not used here.
    """

    base_config, variant_config = PipelineConfig(), PipelineConfig(series="pipeline-v2-filters")
    print()
    print("INCREMENTAL FILTER COMPARISON - TRAIN slice only, same 9 combinations with and without the filter")
    print(f"{'filtered family':<48}{'symbol':<8}{'profitable combos':>18}{'combos improved':>16}"
          f"{'median exp change':>18}{'trades kept':>12}  stopped at (base -> filtered)")
    for variant in FILTERED_FAMILIES:
        base = BASE_OF[variant.strategy_id]
        for symbol in symbols:
            base_combos, base_stage = _train_combos(experiment_id_for(base, symbol, base_config))
            variant_combos, variant_stage = _train_combos(experiment_id_for(variant, symbol, variant_config))
            if base_combos is None or variant_combos is None:
                continue
            paired = [(base_combos[k], variant_combos[k]) for k in base_combos if k in variant_combos
                      and base_combos[k].get("expectancy_r") is not None and variant_combos[k].get("expectancy_r") is not None]
            if not paired:
                continue
            deltas = [v["expectancy_r"] - b["expectancy_r"] for b, v in paired]
            base_trades = sum(b["trade_count"] for b, _ in paired)
            kept = sum(v["trade_count"] for _, v in paired) / base_trades if base_trades else None
            base_profitable = sum(1 for b, _ in paired if b["net_pnl_usd"] > 0)
            variant_profitable = sum(1 for _, v in paired if v["net_pnl_usd"] > 0)
            print(f"{variant.strategy_id:<48}{symbol:<8}{f'{base_profitable} -> {variant_profitable} of {len(paired)}':>18}"
                  f"{f'{sum(1 for d in deltas if d > 0)} of {len(paired)}':>16}{median(deltas):>+18.3f}"
                  f"{_fmt(kept, '{:.0%}'):>12}  {base_stage} -> {variant_stage}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", choices=sorted(SERIES) + sorted(PORTFOLIO_SERIES), default="pipeline-v1")
    parser.add_argument("--cost-profile", type=Path, default=None,
                        help="portfolio series only: measured cost profile (default: the one the series names, "
                             "else the newest data/broker/measured_costs_*.json)")
    parser.add_argument("--family", action="append", help="strategy_id to run (repeatable); default all")
    parser.add_argument("--symbol", action="append", help="symbol to run (repeatable); default all")
    parser.add_argument("--preregister-only", action="store_true")
    parser.add_argument("--compare-filters", action="store_true", help="print the filter comparison and exit")
    args = parser.parse_args()

    symbols = [s.upper() for s in (args.symbol or SYMBOLS)]
    if args.compare_filters:
        print_filter_comparison(symbols)
        return
    if args.series in PORTFOLIO_SERIES:
        run_portfolio_series(args)
        return

    config = PipelineConfig(series=args.series)
    families = [f for f in SERIES[args.series] if not args.family or f.strategy_id in args.family]

    for family in families:
        for symbol in symbols:
            print(f"[PREREGISTERED] {preregister(family, symbol, config).name}")
    if args.preregister_only:
        return

    print()
    print(f"{'strategy':<34}{'symbol':<8}{'decision':<10}{'stopped at':<22}{'train exp':>10}{'val trades':>11}{'val PF':>8}{'val exp':>9}")
    for family in families:
        for symbol in symbols:
            try:
                outcome = run_experiment(family, symbol, config, all_symbols=SYMBOLS)
            except RuntimeError as exc:
                print(f"{family.strategy_id:<34}{symbol:<8}SKIPPED   {exc}")
                continue
            stages = {s.stage: s for s in outcome.stages}
            train = stages["TRAIN"].metrics
            chosen = next((c for c in train["combos"] if c["params"] == train["chosen_params"]), {})
            validation = stages.get("VALIDATION")
            vm = validation.metrics if validation else {}
            print(f"{family.strategy_id:<34}{symbol:<8}{outcome.decision:<10}{outcome.stage_reached:<22}"
                  f"{_fmt(chosen.get('expectancy_r')):>10}{_fmt(vm.get('trade_count'), '{}'):>11}"
                  f"{_fmt(vm.get('profit_factor'), '{:.2f}'):>8}{_fmt(vm.get('expectancy_r')):>9}")
            failed = next((s for s in outcome.stages if not s.passed), None)
            if failed:
                for reason in failed.reasons[:3]:
                    print(f"{'':<42}- {reason}")

    if args.series == "pipeline-v2-filters":
        print_filter_comparison(symbols)
    print_selection_bias_report(selection_bias_report())


if __name__ == "__main__":
    main()
