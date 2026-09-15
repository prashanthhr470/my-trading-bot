"""
Report forward-performance degradation for every symbol that has a
strategy attached in the live decision path.

Read-only by default: it assesses and prints. Pass --enforce to also
quarantine any DEGRADED strategy whose promotion candidate_id is known
(moving it to REVIEW_REQUIRED so new_trades_allowed() returns False).

    python hafnot_check_degradation.py
    python hafnot_check_degradation.py --enforce --candidate-id my-candidate
"""

from __future__ import annotations

import argparse

from app.forex_v2.risk import FX_USD_MAJOR_SPECS
from app.monitoring.degradation_monitor import assess_symbol, enforce, print_report
from app.paper.canonical_signal_adapter import STRATEGY_FOR_SYMBOL

# The spread the costed backtests assumed, for the execution-deterioration
# comparison (app.quant.costed_backtest.run_costed_backtest's default).
BACKTEST_ASSUMED_SPREAD_PIPS = 1.2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enforce", action="store_true",
                        help="Quarantine degraded strategies (requires --candidate-id).")
    parser.add_argument("--candidate-id", default=None,
                        help="Promotion candidate_id to quarantine when degraded.")
    args = parser.parse_args()

    if not STRATEGY_FOR_SYMBOL:
        print("No symbols have a strategy attached in canonical_signal_adapter.")
        return

    degraded_any = False

    for symbol, (strategy_id, version, _period) in sorted(STRATEGY_FOR_SYMBOL.items()):

        spec = FX_USD_MAJOR_SPECS.get(symbol)

        report = assess_symbol(
            symbol,
            strategy_id=strategy_id,
            strategy_version=version,
            assumed_backtest_spread_pips=BACKTEST_ASSUMED_SPREAD_PIPS,
            pip_size=spec.pip_size if spec else None,
        )

        print_report(report)

        if report.degraded:
            degraded_any = True

            if args.enforce and args.candidate_id:
                new_stage = enforce(report, args.candidate_id)
                print(f"[ENFORCED] {args.candidate_id} -> {new_stage}")
            elif args.enforce:
                print("[SKIPPED] --enforce given but no --candidate-id supplied.")

    print()
    if not degraded_any:
        print("No strategy was flagged as degraded.")
    print()


if __name__ == "__main__":
    main()
