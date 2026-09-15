HAFNOT FINAL CONSOLIDATION - 2026-09-04

This overlay consolidates the canonical HAFNOT paper-analysis path.

Included fixes:
- AgentRuntime is now the canonical intelligence source for the paper engine.
- AI validation receives the authoritative requested symbol.
- Native cTrader OpenAPI Level-II depth is merged into deterministic intelligence.
- Depth imbalance is exposed as a footprint proxy; true executed trade delta is never fabricated.
- AI evidence now carries MTF technical summaries, structure, liquidity, macro/news, order-flow and depth.
- FinalAgentPipeline exposes stable final_decision/paper_trade_plan aliases for the paper engine.
- Paper market snapshot skips malformed partial bid/ask events.
- Missing core paper_account.py and trade_plan.py were restored from project backups.

SAFETY:
DRY_RUN=True
PAPER_TRADING=True
LIVE_EXECUTION=False
BROKER_ORDERS=0
AI_DIRECT_EXECUTION=False
READ_ONLY=True

IMPORTANT:
This consolidation does not claim or guarantee a profitable win rate. The system must earn statistical evidence through paper/replay validation before DEMO execution is enabled. No live broker execution is enabled by this package.
