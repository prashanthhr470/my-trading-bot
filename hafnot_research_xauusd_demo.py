"""
Honest research demonstration: runs the full validation framework
(app/quant/*) against the ONE real historical dataset in this project
(data/xauusd_historical_batch10.json - ~740 H4 gold bars, 2026-03-12 to
2026-09-03) using app.forex_v2.strategy's default EMA trend/pullback
strategy.

This is a DEMONSTRATION that the pipeline works end-to-end on real data,
NOT a claim that this strategy is profitable or ready for anything. ~180
H4 bars (30 trading days) of data is far too little to draw a real
conclusion from - see the printed caveats at the end of the report.

Run: .venv\\Scripts\\python.exe hafnot_research_xauusd_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.forex_v2.metrics import summarize_trades
from app.quant.costed_backtest import run_costed_backtest
from app.quant.data_split import chronological_split
from app.quant.monte_carlo import resample_trade_sequence
from app.quant.robustness import run_robustness_sweep
from app.quant.strategy_adapter import make_signal_provider
from app.quant.walk_forward import run_walk_forward

DATA_FILE = ROOT / "data" / "xauusd_historical_batch10.json"
SYMBOL = "XAUUSD"
STARTING_EQUITY = 10_000.0


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:

    if not DATA_FILE.exists():
        print(f"[FAIL] Data file not found: {DATA_FILE}")
        sys.exit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    bars = data["H4"]["bars"]

    section("HAFNOT RESEARCH DEMONSTRATION - XAUUSD H4")
    print(f"Bars available : {len(bars)}")
    print(f"From           : {bars[0]['timestamp']}")
    print(f"To             : {bars[-1]['timestamp']}")
    print(f"Strategy       : app.forex_v2.strategy.ForexIntradayStrategy (defaults)")
    print(f"Starting equity: ${STARTING_EQUITY:,.2f}")

    # ================================================================
    # 1. FULL-SAMPLE COSTED BACKTEST
    # ================================================================

    section("1. FULL-SAMPLE COSTED BACKTEST (all bars)")

    full_result = run_costed_backtest(
        bars=bars, signal_provider=make_signal_provider(), symbol=SYMBOL,
        starting_equity_usd=STARTING_EQUITY,
    )

    print(f"Raw signals fired  : {full_result.raw_signal_count}")
    print(f"Accepted trades    : {full_result.accepted_trade_count}")
    print(f"Rejected trades    : {full_result.rejected_trade_count} {full_result.rejection_reasons}")

    if full_result.trades:
        summary = summarize_trades(
            [{"pnl_usd": t.net_pnl_usd, "result_r": t.result_r} for t in full_result.trades],
            initial_equity=STARTING_EQUITY,
        )
        print(f"Win rate           : {summary.win_rate}")
        print(f"Expectancy (R)     : {summary.expectancy_r}")
        print(f"Profit factor      : {summary.profit_factor}")
        print(f"Net PnL (USD)      : {summary.net_pnl_usd:,.2f}")
        print(f"Max drawdown       : ${summary.max_drawdown_usd:,.2f} ({summary.max_drawdown_percent:.2f}%)")
    else:
        print("No trades were produced on the full sample.")

    # ================================================================
    # 2. IN-SAMPLE / OUT-OF-SAMPLE SPLIT
    # ================================================================

    section("2. IN-SAMPLE (70%) / OUT-OF-SAMPLE (30%) SPLIT")

    split = chronological_split(bars, in_sample_fraction=0.7)
    print(f"In-sample bars     : {len(split.in_sample)} ({split.in_sample[0]['timestamp']} to {split.in_sample[-1]['timestamp']})")
    print(f"Out-of-sample bars : {len(split.out_of_sample)} ({split.out_of_sample[0]['timestamp']} to {split.out_of_sample[-1]['timestamp']})")

    for label, slice_bars in (("IN-SAMPLE", split.in_sample), ("OUT-OF-SAMPLE", split.out_of_sample)):
        result = run_costed_backtest(
            bars=slice_bars, signal_provider=make_signal_provider(), symbol=SYMBOL,
            starting_equity_usd=STARTING_EQUITY,
        )
        print(f"\n  [{label}] trades={len(result.trades)}", end="")
        if result.trades:
            s = summarize_trades(
                [{"pnl_usd": t.net_pnl_usd, "result_r": t.result_r} for t in result.trades],
                initial_equity=STARTING_EQUITY,
            )
            print(f" expectancy_r={s.expectancy_r} profit_factor={s.profit_factor} net_pnl=${s.net_pnl_usd:,.2f}")
        else:
            print(" (no trades)")

    # ================================================================
    # 3. WALK-FORWARD
    # ================================================================

    section("3. WALK-FORWARD VALIDATION")
    print("Rolling windows: 200 H4 bars in-sample, 80 H4 bars out-of-sample.")
    print("Parameter grid: fast_ema_period in [8, 13], slow_ema_period in [21, 34].")

    wf_result = run_walk_forward(
        bars=bars, symbol=SYMBOL,
        param_grid={"fast_ema_period": [8, 13], "slow_ema_period": [21, 34]},
        in_sample_bars=200, out_of_sample_bars=80,
    )

    print(f"\nWindows produced          : {len(wf_result.windows)}")
    for w in wf_result.windows:
        print(
            f"  Window {w.window_index}: chosen={w.chosen_params} "
            f"IS_expectancy={w.in_sample_expectancy_r} "
            f"OOS_expectancy={w.out_of_sample_expectancy_r} "
            f"OOS_trades={w.out_of_sample_trade_count}"
        )
    print(f"\nPositive OOS window fraction : {wf_result.positive_window_fraction}")
    print(f"Mean OOS expectancy (R)      : {wf_result.mean_out_of_sample_expectancy_r}")

    # ================================================================
    # 4. MONTE CARLO (on the full-sample trade sequence, if any)
    # ================================================================

    section("4. MONTE CARLO TRADE-SEQUENCE RESAMPLING")

    if full_result.trades:
        pnl_sequence = [t.net_pnl_usd for t in full_result.trades]
        mc = resample_trade_sequence(pnl_sequence, starting_equity_usd=STARTING_EQUITY, trials=2000)
        print(f"Trials                : {mc.trial_count}")
        print(f"Final equity  P05/P50/P95 : ${mc.final_equity_p05:,.2f} / ${mc.final_equity_p50:,.2f} / ${mc.final_equity_p95:,.2f}")
        print(f"Max drawdown  P50/P95     : ${mc.max_drawdown_p50_usd:,.2f} / ${mc.max_drawdown_p95_usd:,.2f}")
        print(f"Probability of ruin (>=50% loss) : {mc.probability_of_ruin:.1%}")
        print(f"\n[CAVEAT] Only {len(pnl_sequence)} real trades exist to resample from.")
        print("         A handful of trades produces a wide, low-confidence distribution.")
    else:
        print("No trades on the full sample - nothing to resample.")

    # ================================================================
    # 5. PARAMETER ROBUSTNESS
    # ================================================================

    section("5. PARAMETER ROBUSTNESS SWEEP")

    robustness = run_robustness_sweep(
        bars=bars, symbol=SYMBOL,
        param_grid={"fast_ema_period": [5, 8, 13], "slow_ema_period": [21, 34, 55]},
        starting_equity_usd=STARTING_EQUITY,
    )
    print(f"Grid combinations tried    : {len(robustness.results)}")
    print(f"Fraction net-positive      : {robustness.profitable_fraction:.1%}")
    for r in robustness.results:
        print(f"  {r.params} -> trades={r.trade_count} expectancy_r={r.expectancy_r} net_pnl=${r.net_pnl_usd:,.2f}")

    # ================================================================
    # HONEST CONCLUSION
    # ================================================================

    section("HONEST CONCLUSION")
    print("This run demonstrates the validation PIPELINE works end-to-end")
    print("against real (not fabricated) price data. It does NOT demonstrate")
    print("that this strategy is profitable, robust, or ready for paper/DEMO")
    print("trading. Reasons this cannot be claimed from this run alone:")
    print()
    print("  - Only ~180 days of single-symbol (XAUUSD), single-timeframe (H4)")
    print("    data exists in this project. That is far below the promotion")
    print("    gate's own minimum of 100 closed trades for a real decision.")
    print("  - The strategy used is app.forex_v2.strategy's UNTUNED defaults -")
    print("    no optimization or curation has been done.")
    print("  - Spread is approximated (assumed_spread_pips), not historical.")
    print()
    print("Before any real conclusion: acquire multi-year, multi-symbol")
    print("historical data (see hafnot_download_historical_data.py) and rerun")
    print("this same pipeline against it.")


if __name__ == "__main__":
    main()
