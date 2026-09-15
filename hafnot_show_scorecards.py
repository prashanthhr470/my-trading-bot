"""
Print the Phase 16 scorecard for every strategy currently in the registry.

Run:  python hafnot_show_scorecards.py
"""

from app.quant.strategy_registry import list_strategies
from app.quant.strategy_scorecard import build_scorecard, print_scorecard


def main() -> None:
    specs = list_strategies()
    if not specs:
        print("No strategies registered yet. Run hafnot_seed_strategy_registry.py first.")
        return

    for spec in specs:
        card = build_scorecard(spec.strategy_id, spec.version)
        print_scorecard(card)


if __name__ == "__main__":
    main()
