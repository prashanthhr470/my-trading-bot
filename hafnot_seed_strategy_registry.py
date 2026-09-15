"""
One-time registration of the 3 strategies actually tested today, with
their ACTUAL recorded results (all of them, including losses). This is
not a demonstration with fake data - every number here was a real
output from a real backtest run earlier in this session.
"""

from app.quant.strategy_registry import StrategySpec, StrategyFamily, register_strategy, record_result

# ============================================================
# 1. EMA TREND/MOMENTUM STRATEGY
# ============================================================

ema_spec = StrategySpec(
    strategy_id="ema-trend-momentum",
    version="1.0.0",
    family=StrategyFamily.TREND_MOMENTUM.value,
    entry_rules="Fast/slow EMA alignment + pullback to fast EMA + momentum confirmation bar (app.forex_v2.strategy.ForexIntradayStrategy).",
    exit_rules="Fixed stop-loss/take-profit, no trailing.",
    stop_loss_logic="ATR-buffer below/above pullback low/high (stop_atr_buffer param).",
    take_profit_logic="reward_to_risk multiple of stop distance.",
    timeframe="H1",
    symbols=["XAUUSD", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"],
    session_conditions="None applied by the strategy itself.",
    regime_conditions="None applied.",
    parameters={"fast_ema_period": 8, "slow_ema_period": 21, "reward_to_risk": 1.5, "stop_atr_buffer": 0.25},
    transaction_cost_assumptions="app.forex_v2.risk default RiskConfig.",
    risk_model="app.forex_v2.risk.size_position, 0.5% equity risk per trade.",
    signal_provider_module="app.quant.strategy_adapter",
    signal_provider_factory="make_signal_provider",
    notes="Default-parameter full-sample result was the FIRST test of this session.",
)
register_strategy(ema_spec, overwrite=True)

record_result(
    "ema-trend-momentum", "1.0.0", test_type="FULL_SAMPLE_8_SYMBOLS", symbol="ALL",
    period_start="2024-09", period_end="2026-09",
    scorecard={"trade_count": 44, "net_pnl_usd": -462.0, "note": "5 of 8 symbols produced zero trades (safety-rejected)."},
)
record_result(
    "ema-trend-momentum", "1.0.0", test_type="PARAMETER_SWEEP_9_COMBOS", symbol="USDJPY",
    scorecard={"combos_tried": 9, "profitable_fraction": 0.0, "best_net_pnl_usd": -6055.43, "best_params": {"stop_atr_buffer": 0.2, "reward_to_risk": 2.0}},
)
record_result(
    "ema-trend-momentum", "1.0.0", test_type="PARAMETER_SWEEP_9_COMBOS", symbol="EURUSD",
    scorecard={"combos_tried": 9, "profitable_fraction": 0.0, "best_net_pnl_usd": -6274.48, "best_params": {"stop_atr_buffer": 0.5, "reward_to_risk": 2.5}},
)

# ============================================================
# 2. ASIAN RANGE BREAKOUT STRATEGY
# ============================================================

breakout_spec = StrategySpec(
    strategy_id="asian-range-breakout",
    version="1.0.0",
    family=StrategyFamily.BREAKOUT.value,
    entry_rules="Close breaks Asian session (00:00-08:00 UTC) high/low by >=10% of session range, during London window (07:00-10:00 UTC).",
    exit_rules="Fixed stop-loss/take-profit, no trailing.",
    stop_loss_logic="15% of Asian range, back inside the broken level (fixed after a bug where the far side of the range made risk always exceed reward).",
    take_profit_logic="Measured move: entry +/- Asian range size.",
    timeframe="H1",
    symbols=["XAUUSD", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"],
    session_conditions="London window (07:00-10:00 UTC) only.",
    regime_conditions="None applied.",
    parameters={"min_breakout_fraction_of_range": 0.10, "stop_buffer_fraction": 0.15},
    transaction_cost_assumptions="app.forex_v2.risk default RiskConfig.",
    risk_model="app.forex_v2.risk.size_position, 0.5% equity risk per trade.",
    signal_provider_module="app.quant.asian_range_breakout_strategy",
    signal_provider_factory="make_signal_provider",
    notes="First version had a stop-placement bug producing zero signals across all 8 symbols - caught, traced, fixed.",
)
register_strategy(breakout_spec, overwrite=True)

record_result(
    "asian-range-breakout", "1.0.0", test_type="IN_SAMPLE_8_SYMBOLS_70PCT", symbol="ALL",
    period_start="2024-09", period_end="~2026-03",
    scorecard={"trade_count": 858, "net_pnl_usd": -6070.15},
)
record_result(
    "asian-range-breakout", "1.0.0", test_type="OUT_OF_SAMPLE_8_SYMBOLS_30PCT", symbol="ALL",
    period_start="~2026-03", period_end="2026-09",
    scorecard={"trade_count": 348, "net_pnl_usd": -4184.26},
)
record_result(
    "asian-range-breakout", "1.0.0", test_type="OUT_OF_SAMPLE_8_SYMBOLS_30PCT", symbol="XAUUSD",
    scorecard={"trade_count": 34, "win_rate": 0.294, "expectancy_r": 0.183, "profit_factor": 1.24, "net_pnl_usd": 227.78, "note": "Only clearly positive single result all session - flagged for follow-up, did NOT survive multi-window testing."},
)
record_result(
    "asian-range-breakout", "1.0.0", test_type="ROLLING_6_WINDOW_CONSISTENCY", symbol="XAUUSD",
    period_start="2024-09", period_end="2026-09",
    scorecard={
        "windows": 6, "profitable_windows": 3, "total_trades": 132, "total_net_pnl_usd": -629.39,
        "note": "3/6 profitable - not a consistent edge. Two most recent windows (Jan-Sep 2026) were both profitable, coinciding with gold's strong uptrend - likely trend-dependent, not a durable edge.",
    },
)

# ============================================================
# 3. LIQUIDITY SWEEP + FVG (core_strategy)
# ============================================================

sweep_spec = StrategySpec(
    strategy_id="liquidity-sweep-fvg",
    version="2.0.0",  # v2 = ATR-based stop buffer (v1 = fixed 5% fib-range buffer, deprecated after this test)
    family=StrategyFamily.LIQUIDITY_SWEEP_CONFIRMATION.value,
    entry_rules="Sweep of PDH/PDL/PWH/PWL/Asian-session/equal-highs-lows level with >=50% rejection wick, followed by BOS/CHoCH structure break within 60 bars, followed by a Fair Value Gap overlapping the 50-61.8% Fibonacci retracement zone, entered on first retracement back into that zone.",
    exit_rules="Fixed stop-loss/take-profit, no trailing. Min 1.5 reward:risk required.",
    stop_loss_logic="v2: 2.5x ATR(14) beyond the swept level (credible external research-based). v1 (deprecated): 5% of the fib retracement range.",
    take_profit_logic="Nearest opposing liquidity level (or 2R fallback if none).",
    timeframe="M5 (XAUUSD) / M15 (FX pairs)",
    symbols=["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
    session_conditions="London (07:00-10:00 UTC) or New York (13:00-16:00 UTC) open only.",
    regime_conditions="None applied historically (market_regime engine exists but not yet wired into this strategy).",
    parameters={"min_rejection_wick_fraction": 0.5, "max_bars_to_mss": 60, "max_bars_to_retracement": 40, "min_reward_to_risk": 1.5, "stop_buffer_atr_multiple": 2.5},
    transaction_cost_assumptions="app.forex_v2.risk default RiskConfig.",
    risk_model="app.forex_v2.risk.size_position, 0.5% equity risk per trade.",
    signal_provider_module="app.quant.core_strategy",
    signal_provider_factory="make_signal_provider",
    notes="v1 (fixed buffer) also tested with an H4 trend confluence filter (app.quant.mtf_confluence_strategy) - results recorded under this same strategy_id for comparison.",
)
register_strategy(sweep_spec, overwrite=True)

# v1 results (fixed 5% buffer)
record_result(
    "liquidity-sweep-fvg", "1.0.0", test_type="FULL_SAMPLE", symbol="XAUUSD",
    period_start="2026-03", period_end="2026-09",
    scorecard={"trade_count": 14, "win_rate": 0.071, "expectancy_r": -0.788, "profit_factor": 0.156, "net_pnl_usd": -483.94},
)
record_result(
    "liquidity-sweep-fvg", "1.0.0", test_type="H4_TREND_CONFLUENCE_FILTER", symbol="XAUUSD",
    scorecard={"trade_count": 10, "win_rate": 0.10, "expectancy_r": -0.704, "net_pnl_usd": -299.75},
)
record_result(
    "liquidity-sweep-fvg", "1.0.0", test_type="H4_TREND_CONFLUENCE_FILTER", symbol="EURUSD",
    scorecard={"trade_count": 7, "win_rate": 0.286, "expectancy_r": -0.235, "net_pnl_usd": -81.22},
)
record_result(
    "liquidity-sweep-fvg", "1.0.0", test_type="H4_TREND_CONFLUENCE_FILTER", symbol="GBPUSD",
    scorecard={"trade_count": 4, "win_rate": 0.0, "expectancy_r": -1.0, "net_pnl_usd": -196.03},
)
record_result(
    "liquidity-sweep-fvg", "1.0.0", test_type="H4_TREND_CONFLUENCE_FILTER", symbol="USDJPY",
    scorecard={"trade_count": 1, "win_rate": 0.0, "expectancy_r": -1.0, "net_pnl_usd": -49.24},
)

# v2 results (ATR-based buffer), 2-year data
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_2YR", symbol="XAUUSD",
    scorecard={"trade_count": 11, "win_rate": 0.182, "expectancy_r": -0.457, "profit_factor": 0.50, "net_pnl_usd": -164.34},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_2YR", symbol="XAUUSD",
    scorecard={"trade_count": 3, "win_rate": 0.333, "expectancy_r": -0.002, "profit_factor": 0.80, "net_pnl_usd": -18.62},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_2YR", symbol="USDJPY",
    scorecard={"trade_count": 7, "win_rate": 0.286, "expectancy_r": -0.200, "net_pnl_usd": -70.35},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_2YR", symbol="USDJPY",
    scorecard={"trade_count": 1, "win_rate": 0.0, "expectancy_r": -1.0, "net_pnl_usd": -48.78},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_2YR", symbol="EURUSD",
    scorecard={"trade_count": 9, "win_rate": 0.333, "expectancy_r": -0.050, "net_pnl_usd": -22.77},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_2YR", symbol="EURUSD",
    scorecard={"trade_count": 2, "win_rate": 0.50, "expectancy_r": 0.407, "profit_factor": 1.85, "net_pnl_usd": 40.39, "note": "n=2, not statistically meaningful on its own."},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_2YR", symbol="GBPUSD",
    scorecard={"trade_count": 7, "win_rate": 0.286, "expectancy_r": -0.192, "net_pnl_usd": -64.14},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_2YR", symbol="GBPUSD",
    scorecard={"trade_count": 2, "win_rate": 1.0, "expectancy_r": 2.207, "net_pnl_usd": 214.17, "note": "n=2. This result did NOT hold up with 5 years of data (see below) - flagged as a false positive from a tiny sample."},
)

# v2 results (ATR-based buffer), 5-year data - the rigor check that caught
# the GBPUSD false positive above.
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_5YR", symbol="XAUUSD",
    period_start="2021-09", period_end="~2024-11",
    scorecard={"trade_count": 12, "win_rate": 0.333, "expectancy_r": -0.003, "profit_factor": 0.87, "net_pnl_usd": -43.46},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_5YR", symbol="XAUUSD",
    period_start="~2024-11", period_end="2026-09",
    scorecard={"trade_count": 1, "win_rate": 0.0, "expectancy_r": -1.0, "net_pnl_usd": -41.35},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_5YR", symbol="EURUSD",
    scorecard={"trade_count": 13, "win_rate": 0.385, "expectancy_r": 0.121, "profit_factor": 1.20, "net_pnl_usd": 75.49},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_5YR", symbol="EURUSD",
    scorecard={"trade_count": 7, "win_rate": 0.286, "expectancy_r": -0.160, "profit_factor": 0.72, "net_pnl_usd": -68.04},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_5YR", symbol="GBPUSD",
    scorecard={"trade_count": 8, "win_rate": 0.0, "expectancy_r": -1.0, "profit_factor": 0.0, "net_pnl_usd": -359.07, "note": "Same symbol whose 2-year OOS (n=2) looked like a 100% win rate. With more data: complete wipeout. Real evidence the earlier result was luck, not edge."},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_5YR", symbol="GBPUSD",
    scorecard={"trade_count": 5, "win_rate": 0.40, "expectancy_r": 0.171, "profit_factor": 1.33, "net_pnl_usd": 45.89},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="IN_SAMPLE_5YR", symbol="USDJPY",
    scorecard={"trade_count": 8, "win_rate": 0.375, "expectancy_r": 0.085, "profit_factor": 1.12, "net_pnl_usd": 28.62},
)
record_result(
    "liquidity-sweep-fvg", "2.0.0", test_type="OUT_OF_SAMPLE_5YR", symbol="USDJPY",
    scorecard={"trade_count": 4, "win_rate": 0.0, "expectancy_r": -1.0, "net_pnl_usd": -184.95},
)

print("Registered 3 strategies with all real results from today's session.")
print("Verify with: python -c \"from app.quant.strategy_registry import list_strategies; [print(s.strategy_id, s.version) for s in list_strategies()]\"")
