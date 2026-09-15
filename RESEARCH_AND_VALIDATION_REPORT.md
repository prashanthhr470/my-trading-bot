# HAFNOT — Research & Validation Report

**Date:** 2026-09-12
**Test suite:** 568 tests passing (`python -m pytest -q`, ~35–60 s) — updated 2026-09-15 after §7d–§7y
**Scope:** honest status of the research/validation architecture and of every strategy tested.

---

## Headline conclusion

**No strategy tested in this project has demonstrated a robust, validated trading edge.**
All 93 recorded experiments were rejected (latest: §7y, FX positioning from CFTC reports; before it §7x, FX month-end fix flows, profitable 2014–2020 and reversed 2020–2023; closest overall: the §7u index dip-in-uptrend rule, now under forward paper tracking, §7v). The system's steady-state output is
`NO_TRADE`, and that is the correct result given the evidence — not a malfunction.

What *has* been built is the apparatus for finding and validating an edge, and for
refusing to trade without one. The value delivered is the process, not a profitable
strategy, because a profitable strategy was not found.

**HAFNOT is not profitable. It has never placed a profitable validated trade.
Paper trading is live; no real money is or has been at risk.**

---

## 1. Status by verification level

### VERIFIED WORKING (exercised end-to-end against real data)

| Component | Evidence |
|---|---|
| Native cTrader bar fetch | Fetched 552 real M5 XAUUSD bars with correct 5-minute open timestamps and volume |
| Live bar feed (`hafnot_live_bar_feed.py`) | Running under `.ctrader_venv`; produced 4 fresh files (xauusd_m5: 5211 bars, 3× m15: ~4220 bars each) |
| Canonical signal adapter | Consumed real bars and returned a genuine `NO_TRADE — "No qualifying setup this cycle."` |
| Live 24/7 paper pipeline | Supervisor + market worker + bar feed + paper engine all running; 11 feeds fresh |
| Journalling with reasons | Every cycle records `decision_reason`, `pipeline_status`, `pipeline_error`, `strategy_id` |
| Broker symbol specs | Fetched real specs for 8 symbols via `ProtoOASymbolByIdRes` |
| Validated-baseline gate | Blocks all 4 configured symbols; verified by test against the real registry |
| Degradation monitor | Returns `NO_VALIDATED_BASELINE` for all 4 live symbols |
| Experiment registry | 23 experiments recorded; family-wise error probability 0.69 |
| Backtest engine, risk model, execution safety gate | Covered by the test suite; the safety gate demonstrably rejects sub-1.5 reward:risk candidates |
| Storage governor | 1.8 GB against a 5 GB cap, trimming configured |

### PARTIALLY VERIFIED

| Component | What's proven | What isn't |
|---|---|---|
| Regime engine | Deterministic, anti-lookahead, tested; comparison run on XAUUSD | Only 1 symbol compared; expansion/contraction/abnormal states not modelled |
| Walk-forward | Real rolling implementation, used on XAUUSD breakout (6 windows) | Still tied to the EMA `StrategyConfig` path; not generalised to all families |
| Robustness sweeps | Generalised to any strategy family; real 9-combo sweep run | Only spread/slippage *defaults* tested — no deliberate cost-deterioration matrix |
| Monte Carlo | Generic, works on any trade sequence | Never run per registered strategy (samples too small to be meaningful) |
| Extended metrics | Sharpe/Sortino/streaks/payoff implemented and tested; withheld below 30 trades | No strategy has ≥30 trades in one validated sample, so they remain unreported in practice |
| Degradation enforcement | `enforce()` moves a candidate to `REVIEW_REQUIRED`; tested | Never fired on real data (no validated baseline exists to degrade from) |

### NOT VERIFIED

| Item | Why |
|---|---|
| DEMO order execution | **No order has ever been placed.** The native execution path exists but has never been exercised. |
| cTrader desktop MCP path | Port 9876 was closed; `get_market_snapshot` is unused by the live path now |
| News / fundamental / sentiment / order-flow filters | No reliable timestamped historical data; deliberately not fabricated |
| Macro & intermarket features | Not implemented |
| Strategy families D–G (mean reversion, range, session-specific, volatility-regime) | Not implemented |
| Long-horizon forward performance | Paper trading has produced **zero closed trades** |

---

## 2. Every strategy tested

Transaction costs throughout: `app.forex_v2.risk` default `RiskConfig` — spread cap,
adverse slippage both sides, $7/lot round-turn commission, 0.5% equity risk per trade.

### Strategy A — `ema-trend-momentum` v1.0.0 (TREND_MOMENTUM)

- **Hypothesis:** fast/slow EMA alignment with a pullback entry has positive expectancy after costs.
- **Symbols/TF:** 8 USD majors + XAUUSD, H1. **Period:** 2024-09 → 2026-09.
- **Result:** 44 trades, **−$462.00**. Five of eight symbols produced zero trades (safety-rejected).
- **Robustness:** two 9-combination parameter sweeps (USDJPY, EURUSD): **0% of combinations profitable**; best cases −$6,055 and −$6,274.
- **Walk-forward / OOS:** not advanced to these stages — it failed at backtest.
- **Decision: REJECTED.** No profitable parameter region exists anywhere in the tested grid.

### Strategy B — `asian-range-breakout` v1.0.0 (BREAKOUT)

- **Hypothesis:** London-session breakouts of the Asian range continue for a measured move.
- **Symbols/TF:** 8 symbols, H1. **Period:** 2024-09 → 2026-09.
- **In-sample (70%):** 858 trades, **−$6,070.15**.
- **Out-of-sample (30%):** 348 trades, **−$4,184.26**.
- **Notable sub-result:** XAUUSD OOS alone was **+$227.78** (34 trades, 29.4% win, PF 1.24) — the only clearly positive result in the entire project.
- **Robustness:** that XAUUSD result was followed up with 6-window rolling testing → **3/6 windows profitable, −$629.39 total**. The two profitable windows coincided with gold's strong uptrend, indicating trend-dependence rather than edge. A 9-combination parameter sweep on XAUUSD in-sample returned **0/9 profitable** (overfitting-defense verdict: `NO_EDGE`).
- **Decision: REJECTED.** The one positive slice did not survive window or parameter testing.
- **Engineering note:** the first implementation placed the stop on the far side of the range, making reward:risk mathematically incapable of clearing 1.5 — it produced 0 signals across all 8 symbols. Caught because zero signals everywhere is not a plausible market outcome, traced, and fixed.

### Strategy C — `liquidity-sweep-fvg` (LIQUIDITY_SWEEP_CONFIRMATION)

- **Hypothesis:** a swept liquidity level + structure break + FVG retracement entry is tradeable.
- **Symbols/TF:** XAUUSD (M5), EURUSD/GBPUSD/USDJPY (M15).

**v1.0.0** (fixed 5%-of-range stop buffer): XAUUSD full sample 14 trades, 7.1% win, PF 0.156, **−$483.94**.
With an H4 trend-confluence filter: XAUUSD −$299.75, EURUSD −$81.22, GBPUSD −$196.03, USDJPY −$49.24. **REJECTED.**

**v2.0.0** (2.5× ATR stop buffer, grounded in external research):

| Symbol | 2yr IS | 2yr OOS | 5yr IS | 5yr OOS |
|---|---|---|---|---|
| XAUUSD | 11 tr, −$164.34 | 3 tr, −$18.62 | 12 tr, −$43.46 | 1 tr, −$41.35 |
| EURUSD | 9 tr, −$22.77 | 2 tr, **+$40.39** | 13 tr, **+$75.49** | 7 tr, −$68.04 |
| GBPUSD | 7 tr, −$64.14 | 2 tr, **+$214.17** | 8 tr, **−$359.07** | 5 tr, **+$45.89** |
| USDJPY | 7 tr, −$70.35 | 1 tr, −$48.78 | 8 tr, **+$28.62** | 4 tr, −$184.95 |

**The GBPUSD case is the most instructive result in this project.** Its 2-year
out-of-sample looked like a **100% win rate** — on 2 trades. With 5 years of data, the
in-sample became a **−$359 wipeout at a 0% win rate**. That is direct evidence the
earlier result was luck. It is also exactly what the selection-bias arithmetic predicts:
across 23 experiments, ~1.15 were *expected* to look good by chance alone.

- **Decision: REJECTED.** Sample sizes of 1–7 trades cannot support any conclusion; signs flip between periods.

### Feature experiments (does a component earn its place?)

| Experiment | Result | Decision |
|---|---|---|
| **H4 trend confluence** on sweep strategy | Negative on all 4 symbols | REJECTED |
| **Regime filter** (exclude RANGE, H4 EMA20/50), XAUUSD 5yr | Trades 12→1 (IS), 1→0 (OOS); the one surviving trade lost *more* than the unfiltered average | REJECTED — left available but **OFF by default**, not forced into production |
| **Corrected XAUUSD pip_size** (0.01 → broker's real 0.1) | IS −$43.46 → **−$45.34**; OOS −$41.35 → **−$41.43** | Costs correctly more conservative; conclusion unchanged |

---

## 3. What is currently running in paper trading

- **Symbols with a strategy attached:** XAUUSD, EURUSD, GBPUSD, USDJPY.
- **Symbols deliberately inert:** USDCHF, USDCAD, AUDUSD, NZDUSD, GBPJPY, AUDJPY, GBPAUD — journalled as `"No registered strategy configured"`. GBPJPY/AUDJPY/GBPAUD additionally cannot be risk-modelled (neither leg is USD).
- **Actual trading authority: NONE.** `REQUIRE_VALIDATED_BASELINE` is enforced in
  `app/paper/canonical_signal_adapter.py`, and no strategy has a validated
  out-of-sample baseline. Every symbol therefore returns:

  > `NO_TRADE — "liquidity-sweep-fvg 2.0.0 has no validated out-of-sample baseline, so it is not permitted to trade forward."`

  A test asserts this against the real registry, so it cannot regress silently.
- **Closed forward trades to date: 0.**

### What would disable a strategy

Once a strategy *did* have a validated baseline, `app/monitoring/degradation_monitor.py`
would quarantine it (`REVIEW_REQUIRED` → `new_trades_allowed() == False`) on any of:

- forward expectancy more than 0.10R below the validated baseline
- profit factor at or below 0.80
- drawdown exceeding 1.5× the validated maximum
- a losing streak whose probability under the validated win rate is below 1%
- median realised spread exceeding 2× the backtest assumption

Two guards prevent false alarms: nothing is ever flagged below **20 closed forward
trades**, and nothing is flagged at all without a validated baseline. A quarantined
strategy is **never auto-retuned** — it must re-enter research as a new candidate.

---

## 4. Honest findings that changed conclusions

1. **The live pipeline never had a clean bar feed.** Before this work, neither pipeline
   could obtain closed OHLC bars live: the M1 trendbar stream emits repeated updates of
   the still-forming bar stamped with *arrival* time, and the MCP path needed the cTrader
   desktop app (port 9876 was closed). The journal showed 786 consecutive `WAIT`s from
   the old pipeline and, briefly, 97 `NO_TRADE`s that were actually swallowed exceptions.
   Fixed by `hafnot_live_bar_feed.py` plus reason-carrying journalling.

2. **XAUUSD `pip_size` was wrong by 10×.** Hand-written as 0.01; the broker reports
   `pipPosition=1` (0.1). A normal $0.10 gold spread was measured as 10 pips against a
   2.0 cap, so every gold candidate was refused. Corrected from the broker's own value —
   **the threshold was not loosened.** All prior XAUUSD results were mildly cost-optimistic.

3. **Gold is partly untradeable at this account size.** Five of six out-of-sample gold
   signals could not be sized above the 0.01 minimum lot at 0.5% risk on $10k
   (`POSITION_BELOW_MIN_LOT`). The earlier registry entry recorded only the one surviving
   trade and never recorded this.

4. **A zone-caching optimisation silently corrupted results.** Caching the Asian-session
   range by calendar date froze an incomplete range for evaluations before 08:00 UTC.
   Caught because a pure performance change altered results (7 trades vs 15). Fixed by
   splitting genuinely date-stable zones from session zones; a regression test pins it.

---

## 5. Architecture (canonical, single pipeline)

```
Market Data (native cTrader, .ctrader_venv)
  → data/openapi/*_market_events.jsonl   (ticks, quotes)
  → data/live/bars/*.json                (closed OHLC, refreshed every 5 min)
      → canonical_signal_adapter
          → validated-baseline gate       (blocks unvalidated strategies)
          → registered strategy signal provider
          → risk sizing (app.forex_v2.risk)
          → ExecutionSafetyGate           (same class as backtests use)
          → paper execution + journal (with reasons)
              → degradation monitor → promotion state → new_trades_allowed
```

Research side: `strategy_registry` → `costed_backtest` → `data_split` /
`locked_oos_guard` → `walk_forward` → `robustness` → `overfitting_defense` →
`strategy_scorecard` → `experiment_registry` → `promotion`.

Live execution remains hard-disabled: `execution_allowed`, `trade_authorized` and
`broker_order` are `False` unconditionally.

---

## 6. What still needs real DEMO verification

1. **Placing a single DEMO order** — the native execution path has never run. This is the
   largest untested surface in the project.
2. **A validated strategy existing at all** — without one, the promotion, monitoring and
   enforcement machinery has never been exercised on real forward data.
3. **Bar feed endurance** — verified over minutes, not days. Watch for auth expiry and
   reconnection behaviour.
4. **Broker spec review** — `max_lot`, margin, and stop-distance limits were not fetched.

---

## 7. Remaining work, honestly listed

- Strategy families not yet built: mean reversion, range, session-specific, volatility-regime, pullback continuation.
- Incremental feature comparisons: 2 of 8 run (H4 confluence, regime). Volatility, news, fundamental, order-flow and AI comparisons not run.
- `walk_forward.py` still couples to the EMA `StrategyConfig`; needs the same generalisation `robustness.py` received.
- Cost-deterioration stress matrix (increased spread/slippage/delay) not built.
- Monte Carlo not wired per registered strategy.
- Duplicate `batch7_final_integration.py` exists at both repo root and `app/agent/` (verified unreferenced by the live path; flagged for cleanup).

---

## 7b. Addendum (2026-09-12) — weekend restart loop found and fixed

**Finding.** The supervisor treated any market feed older than 90 seconds as
a fault and restarted the cTrader worker and paper engine. When a market is
closed — weekends, XAUUSD's daily 16:59–18:01 New York break, broker
holidays — feeds are quiet *by design*, so it restart-looped. Measured on
Saturday 2026-09-12: **10 worker restarts in 920 seconds, one every 102 s on
average.** Each reconnect wrote subscription data into the event files, so
**all 10 "MARKET RECOVERY COMPLETE" messages were false** — no real market
data had returned. Projected cost: roughly 1,700 broker reconnects per
weekend, plus a daily loop during gold's break.

The supervisor log was also silent from 00:42 to 08:35 with no failure
recorded — most likely the machine slept. A bot cannot run while its host
sleeps; 24/7 operation needs sleep disabled or a host that does not sleep.

**Fix — driven by broker data, not hardcoded session times.**
- `hafnot_fetch_symbol_specs.py` now captures each symbol's `schedule`,
  `scheduleTimeZone` and `holiday` list for **all 11 watched symbols**, plus
  stop/take-profit distances, max exposure, swap rates and commission.
- `app/core/market_hours.py` decides open/closed from that data. Intervals are
  seconds from Sunday 00:00 in the broker's zone (America/New_York); daylight
  saving is handled by `zoneinfo`; holidays carry their own zone and date.
- The supervisor now **holds** (logs `[MARKET CLOSED]`, restarts nothing) when
  every quiet feed is explained by a scheduled closure, and **restarts** only
  for a feed that is stale while its market is open — or whose schedule is
  unknown, so a missing schedule can never hide a real outage.
- Recovery and startup wait only on markets that are open; startup no longer
  claims "all feeds fresh" when every market is closed.

**Verification.**
- 23 market-hours tests built on the real Pepperstone intervals, including the
  broker's own 2026-09-07 holiday.
- Schedule arithmetic checked against observed feed behaviour at 7 instants,
  covering both EDT and EST.
- Decision dry-run on live data: live weekend, all 11 quiet → **hold**;
  EURUSD dead while open → **restart**; gold's daily break alone → **hold**;
  gold break *plus* a EURUSD outage → **restart**, waiting only on the 10 open
  feeds.
- Full suite: **212 passed**.

**Not verified.**
- A process already running keeps its old code until restarted.
- The new behaviour has not yet been observed across a real close → reopen
  transition. The first real test is the Sunday open (17:01 New York for FX,
  18:01 for gold).

**Gaps raised by an external profitability checklist, confirmed real:**
- No correlation limit. `RiskConfig` caps position count and total risk, but
  EURUSD and GBPUSD longs are both effectively short-USD and are not limited
  together.
- Live-vs-backtest slippage tracking does not exist yet (there have been no
  fills to measure).
- Swap is fetched but still not modelled in backtest costs.

---

## 7c. Addendum (2026-09-12) — repository audit, and the defects it found

**Method.** A static import-graph trace: every module's imports were parsed —
never executed — starting from the processes the supervisor actually launches,
plus strategies the registry loads dynamically. Each module was classified as
runtime, research/tools, test-only or unreferenced.

**The first pass was wrong, and is disclosed here.** It reported 51 syntax errors,
including in `hafnot_final_runtime.py`, which compiles cleanly. Those 51 files
begin with a UTF-8 byte-order mark, and the audit script parsed them as text.
Parsed as bytes, there are zero syntax errors. Corrected result for 215 source
files: **35 runtime, 61 research/tools, 11 test-only, 108 unreferenced** (60
production-looking modules; 48 stray test, validation and debug scripts and backup
copies). The 108 have been identified, not yet archived.

**Defects found and fixed — each verified.**

1. **The live paper engine loaded the unused AI stack.** `app/paper/__init__.py`
   re-exported `AutonomousPaperSession`, which imported about 5,900 lines of LLM
   code the engine never called — and whose import failure would have crashed the
   engine at startup. Nothing used those re-exports. Now empty; a fresh import of
   the engine loads **15 `app` modules and zero `app.ai` modules**.
2. **Tests wrote fake decisions into production logs.** `data/ai/decisions.jsonl`
   held 32 XAUUSD `WAIT` entries arriving in pairs, matching test-suite run times
   (two tests call the decision function). The live bot made none of them. Tests
   now redirect every AI log path to a temp folder, and a regression test asserts
   the real logs are unchanged. The existing 32 entries were left in place, not
   deleted: they are test artifacts, not trading decisions.
3. **Unit tests made real LLM calls.** Three AI tests posted to a running local
   Ollama model — up to 38 s each, and nondeterministic. The HTTP boundary is now
   stubbed, which exercises the provider's documented fail-closed path; a new test
   asserts it returns `WAIT`/`NO_TRADE` with all execution flags off. Full suite
   **122.8 s → 29.5 s**.
4. **Import-time side effect.** The AI module created `data/ai` relative to
   whatever directory the process started in. Now anchored to the project root,
   with no folder creation on import.
5. **324 duplicate bars in the historical corpus.** Every duplicate was
   byte-identical and fell on the downloader's 30-day request-chunk boundaries
   (spacing between duplicates: exact multiples of 30 days).
   - Fixed at source in `hafnot_download_historical_data.py`; the live bar files
     healed themselves within one refresh.
   - Corpus repaired in strict mode after a byte-verified backup
     (`data/historical/bars_backup_before_dedup_20260912/`, excluded from releases).
   - Added `clean_bars` / `load_bar_file` to the existing `app/core/data_quality.py`,
     plus a dataset manifest, `data/historical/manifest.json`.
   - **Impact measured: none.** Identical trades, wins, net P&L, profit factor and
     rejections, raw versus cleaned. Scope: XAUUSD H1 only, liquidity-sweep-fvg and
     asian-range-breakout. Other symbols and timeframes were not re-measured.
6. **The strategy scorecard added up overlapping experiments.** It summed 2-year and
   5-year tests of the same symbol, corrected re-runs alongside the results they
   replaced, and single-symbol rows alongside the 8-symbol total. It now reports each
   experiment design separately and never sums across designs.
   - Before/after: breakout out-of-sample **382 → 348 trades** (the true figure).
   - It also exposed a warning the summed view hid: liquidity-sweep-fvg's 2-year
     design shows **+$187 out-of-sample on 8 trades against −$322 in-sample**, a sign
     flip carried by GBPUSD's 2-trade +$214 — the same result later contradicted by
     5 years of data.
7. **The forward order-flow dataset was never being collected.**
   `app/core/research_archive.py` had never run; its folder did not exist, and only
   its tests called it. It is now wired into the paper engine, capped at 500 MB:
   bid, ask, spread, the reconstructed Level-2 book, the strategy decision and its
   reason, the session label, and whether the broker market was open — one record per
   symbol per 5 minutes, only on a new quote.
8. **Archive records mis-described closed markets.** Weekend snapshots were labelled
   `TOKYO` — session labels have no concept of weekends — with no open/closed flag.
   Records now carry `market_open` from the broker schedule. Verified live: every
   record written at 04:06 UTC on Saturday reads `market_open: false`.
9. **Blocked decisions did not name their strategy.** Results stopped by the
   validation gate, or with no setup, recorded `strategy_id: None`. They now name the
   configured strategy. Verified live for EURUSD, GBPUSD, USDJPY and XAUUSD;
   unconfigured symbols correctly name none.

**A suspected defect that turned out to be false.** A first scan of Friday's
in-hours depth events found no book levels at all. Inspecting the actual event
structure showed the scan had looked for the wrong field names: 20,000 of 20,000
sampled events carry real quotes (for example XAUUSD ask 4402.13 × 1.0, bid
4401.97 × 1.0). The worker reconstructs the book from quote IDs and writes the full
sorted book to the snapshot file the archive reads. Two side findings: every depth
event re-writes the top 100 levels per side, which is most of the ~2 GB of event
logs; and the XAUUSD stream has no depth events for the whole 15:00 UTC hour on
Friday, with the supervisor restarted at 16:19 UTC.

**Data availability (verified).** Full detail is in `TRADING_TOOL_INVENTORY.md`.
Available: historical OHLC with broker tick volume — H1 5 years (EURUSD, GBPUSD,
USDJPY, XAUUSD), H1 2 years (AUDUSD, NZDUSD, USDCAD, USDCHF), H4 2 years, M15/M5
six months. **Not available historically:** news, macro releases, sentiment or
positioning, cross-asset data, order-book depth. "Fundamentals" is a scrape of the
current week's Forex Factory calendar only; the pair-level fundamental engines'
input files do not exist. "Sentiment" is a keyword counter over news headlines.

**Not verified.**
- Open-market depth capture into the archive is verified from the worker's code and
  the event stream, not yet observed in archive records: the market has been closed
  since collection began.
- The paper-engine changes (AI stack removed, validation gate, archive) are already
  live, because the supervisor's restart loop keeps relaunching the paper engine with
  the current code. The market-hours fix lives in the supervisor itself and takes
  effect only when the supervisor is restarted. Until then the loop continues — 32
  worker restarts by 09:31 local — and each relaunch archives one closed-market
  snapshot per symbol (flagged `market_open: false`).
- The market-hours behaviour has not yet been observed across a real market reopen.

**Still not done:** new strategy families (mean reversion, volatility
contraction/expansion, failed breakout, range); isolating components that were only
tested inside failed strategies; portfolio and currency-concentration limits; cost
stress tests; generalising walk-forward; extending FX M15 history beyond six months;
archiving the 108 unreferenced modules.

**Test suite after these changes: 244 passed.**

---

## 7d. Addendum (2026-09-12) — backtests held positions live trading never could

**Finding.** The backtest engine records a trade for every signal, even while an
earlier trade on the same symbol is still open, and the costed backtest never told
the risk model about open positions. Live trading allows **one position per
symbol**. So every recorded backtest could stack overlapping positions — worst for
strategies that signal on consecutive bars.

**Measured impact.** Same code, same data; the overlapping runs first reproduced the
recorded trade counts, so the comparison is like-for-like.

| Result | Overlapping (as recorded) | One position per symbol |
|---|---|---|
| Asian breakout, 8 symbols, in-sample | 858 trades, −$6,149 | **691 trades** (193 skipped), −$6,048 |
| Asian breakout, 8 symbols, out-of-sample | 349 trades, −$4,236 | **278 trades** (86 skipped), −$3,683 |
| Liquidity sweep, XAUUSD 5-year, in-sample | 12 trades, −$45 | **9 trades**, −$60 |
| Liquidity sweep, XAUUSD 5-year, out-of-sample | 1 trade, −$41 | 1 trade, −$41 |

About a quarter of the breakout's recorded trades could never have been taken
live. **No conclusion changes** — both strategies remain clearly negative. The
small P&L differences from the original records come from the later
re-downloaded, de-duplicated data.

**What changed.**
- `run_costed_backtest` and `run_walk_forward` now default to one open position per
  symbol. A trade occupies the slot only if risk sizing actually accepted it
  (tested). Overlapping mode remains available only by passing `None` explicitly.
- The four corrected results are recorded in the strategy registry, each explicitly
  superseding the result it replaces. Not re-measured: the breakout's XAUUSD-only and
  rolling-window rows, and the sweep's EURUSD, GBPUSD and USDJPY 5-year rows.

**A scorecard bug caught while recording those corrections.** Superseding breakout's
8-symbol out-of-sample `ALL` row caused its XAUUSD-only subset (+$227.78, measured
with overlapping positions) to become that design's out-of-sample total. The subset
rule only recognised `ALL` rows that were still included. Fixed so a single-symbol
row stays a subset of its aggregate even after the aggregate is superseded; a
regression test pins the exact case.

**The live validation gate was too loose.** It accepted *any* positive out-of-sample
record with 20+ trades as a validated baseline. A strategy that passed only the
validation stage — and then failed walk-forward or the locked set — would have
qualified. It now requires a record the research pipeline marked
`validated: true`, which is written only after every stage has passed.

**Built.** Four new strategy families, each with its own pre-declared hypothesis
(mean reversion, volatility compression breakout, failed breakout, range fade), and
the pre-registered research pipeline that tests them. Results are in §7e.

**Test suite after these changes: 293 passed.**

---

## 7e. Pre-registered research pipeline, series `pipeline-v1` — 16 experiments, 16 rejected

**What was tested.** Four strategy families never tested before, each on XAUUSD,
EURUSD, GBPUSD and USDJPY H1 bars, with full costs and one position per symbol.
All 16 experiments were written to `data/research/preregistrations/` **before
any of them ran**. Each file records the hypothesis, rules, the 3×3 parameter grid,
the fixed parameters, the data split and every pass criterion.

| Family | Hypothesis in one line | Tuned parameters |
|---|---|---|
| Mean reversion (z-score) | A close far from its recent mean tends to return toward it | lookback 30/50/80, entry z 2.0/2.5/3.0 |
| Volatility compression breakout | A narrow box relative to recent volatility precedes an expansion in the breakout's direction | box bars 8/12/20, max box/ATR 3/4/5 |
| Failed breakout reversal | A bar that closes back inside a range it just broke tends to travel to the range middle | range bars 12/24/48, stop buffer 0.1/0.25/0.5 ATR |
| Range fade | In a low-efficiency (sideways) market, entries near a range edge revert to its middle | range bars 24/48/96, max efficiency ratio 0.2/0.3/0.4 |

**Stages, in order; failing any one stops the experiment.**
1. **TRAIN** (first 50% of bars) — all 9 parameter combinations are run.
   - A majority must be profitable: the sensitivity verdict must be PLATEAU.
   - Parameters are chosen by the **median of a combination and its neighbours**, not the single best. That median must be positive.
2. **VALIDATION** (next 25%) — at least 30 trades, profit factor ≥ 1.10, expectancy ≥ 0.03R and drawdown ≤ 15%.
3. **WALK-FORWARD** — rolling 6,000-bar re-optimisation followed by 1,500 unseen bars.
   - At least 3 windows; at least 55% of them positive.
   - Mean out-of-sample expectancy must be positive.
4. **LOCKED OUT-OF-SAMPLE** (last 25%) — looked at once, only after every earlier stage passes.

**Results (verified from the run output and the registry).**

| Family | XAUUSD | EURUSD | GBPUSD | USDJPY |
|---|---|---|---|---|
| Mean reversion | TRAIN: 3/9 profitable | TRAIN: 2/9 | **WALK-FORWARD** | TRAIN: 1/9, negative |
| Volatility compression breakout | TRAIN: 3/9 | TRAIN: 0/9 | TRAIN: 0/9 | TRAIN: 3/9 |
| Failed breakout reversal | TRAIN: 4/9 | **WALK-FORWARD** | VALIDATION | TRAIN: 1/9, negative |
| Range fade | TRAIN: 0/9 | TRAIN: 0/9 | TRAIN: 0/9 | TRAIN: 0/9 |

| Stopped at | Count |
|---|---|
| TRAIN | 13 |
| VALIDATION | 1 |
| WALK-FORWARD | 2 |
| LOCKED OUT-OF-SAMPLE | 0 reached |

**The three experiments that got past training:**
- **Mean reversion, GBPUSD.**
  - Passed validation: 65 trades, profit factor 1.35, expectancy +0.254R.
  - Walk-forward: only 6 of 11 windows positive (0.545 < 0.55), and mean out-of-sample expectancy was −0.0095R.
- **Failed breakout, EURUSD.**
  - Passed validation: 32 trades, just above the 30 minimum; profit factor 1.43, expectancy +0.253R.
  - Walk-forward: 5 of 11 windows positive.
- **Failed breakout, GBPUSD.**
  - Failed validation: 82 trades, profit factor 0.60, expectancy −0.295R.

Two validation passes out of 16 attempts is about what luck alone produces. In
both cases walk-forward showed the result did not hold up as parameters were
re-fitted over time. This is exactly the case the extra stage exists to catch.

**Integrity checks.**
- The locked out-of-sample slice was not used for any of the 16: no consumption file exists and no LOCKED record was written. Those slices stay clean for future, differently designed hypotheses.
- 21 strategy-registry records were written: 16 train, 3 validation, 2 walk-forward.
- The experiment registry now holds 39 experiments, **0 accepted**.
  - With that many attempts at α = 0.05, the chance of at least one false positive is 86%.
  - The Bonferroni per-experiment threshold is 0.00128.
  - Because nothing was accepted, no winner was selected from the multiple tests.

**Conclusion.**
- On H1 price bars with realistic costs, none of these four simple price-only families shows a robust edge on these four symbols.
- **Not established:** that they fail on other timeframes, on other symbols, or combined with context the bars do not contain (news, order flow).
- Adding filters to *these* rejected results to "rescue" them would be data-mining. Any such variant must be a new pre-registered experiment and counts toward the total number of experiments tried.
- The live validation gate therefore still blocks every symbol. That is the correct outcome: WAIT is valid.

---

## 7f. Addendum (2026-09-12) — leftover broker connections after stop and restart

**Restart result (verified).** The supervisor was restarted at 10:10:50 and is
running the market-hours code:
- 10:10:50 — it logged "broker schedule shows every watched market closed".
- 10:12:30 — once the feeds passed the 90 s stale limit, it logged "holding, not restarting".
- Feeds then went past 120 s with no restart.

**Finding.** After the restart, the process list showed **three**
`multi_symbol_market_data.py` processes, each with an established connection to
the cTrader endpoint.
- Two were leftovers from 09:39:31 and 09:40:23. Their parent worker processes were already gone.
- One of them matches the supervisor's own `[RECOVERY] Restarting cTrader worker` entry at 09:39:31.

**Cause.** On Windows, `TerminateProcess` stops exactly one process; its children
keep running. That call sits behind `Popen.terminate()`, `Popen.kill()` and
`Stop-Process`. The cTrader worker is a chain of four processes: .venv launcher →
worker → .ctrader_venv launcher → market data. The code stopped only the top of
that chain:
- the supervisor's `stop_child`;
- `STOP_HAFNOT.ps1`, whose name list did not include `multi_symbol_market_data`.

The same flaw could have left a paper-engine interpreter running behind a
killed launcher.

**What changed.**
- The two leftover processes were stopped. Before stopping, each was checked: its command line matched `multi_symbol_market_data.py` and it had started before the restart. The current worker (started 10:10:50) was not touched.
- New `app/core/process_tree.py`, standard library only:
  - Snapshots a process's descendants **before** stopping it.
  - Afterwards, terminates whichever of them are still alive.
  - A process is terminated only while an open handle proves its PID *and* creation time still match, so a reused PID is never hit.
- `stop_child` in `hafnot_final_runtime.py` now uses it and logs any leftover child it stops.
- `STOP_HAFNOT.ps1` now also stops `multi_symbol_market_data`, listed after the worker.
- `CHECK_HAFNOT_STATUS.ps1` now lists it, so leftovers are visible.
- `START_HAFNOT.ps1` now refuses to start while HAFNOT child processes run without a supervisor, because starting would create a second copy.

**Tests.** 4 new tests spawn real process chains. They confirm the defect (a child
outlives its killed parent), the fix (every process in the snapshot is gone) and
the reused-PID guard. **Suite: 297 passed.**

**Live status.**
- **Verified:** after a user restart at 10:19:34, the supervisor runs this code, with exactly one process of each kind and no leftovers.
- **Not yet exercised:** the recovery path. It only runs when a feed goes stale while its market is open.

---

## 7g. Addendum (2026-09-12) — the paper engine's risk limits never saw the portfolio

**Finding.** Verified by reading the code. No paper position had ever been
opened: `data/paper` contained no account file, so nothing was ever at stake.
1. **Eleven separate accounts.** Each symbol had its own $10,000 account at 1% risk, allowing up to 11 open positions at once, much of it the same USD bet.
2. **The risk model was never told about open positions.** `evaluate_paper_trade` got default equity and an empty position list. Its caps (3 positions, 2% total open risk, one per symbol, daily loss) could never bind.
3. **The safety gate was given hard-coded state.** It was called with `open_positions=0`, `daily_loss_percent=0`, `kill_switch=False` and `duplicate_position=False`. The engine computed kill-switch and daily-loss state, but the adapter never passed it on.
4. **Paper profit/loss had no costs.** It was R × 1% of equity: no commission, no exit slippage, and twice the backtests' 0.5% risk. Forward results would have looked better than the backtests they are monitored against.

**What changed.**
- **One portfolio account** (`data/paper/portfolio_account.json`):
  - 0.5% risk per trade and the backtests' `RiskConfig` caps.
  - At most **one open position across all symbols**. That is the Execution Safety Gate's existing limit, kept, not loosened.
- **Real account state now reaches the risk model and the gate:** equity, realized P&L today, costed open positions, daily loss, kill switch and duplicate position.
- **New currency-exposure cap** (`max_currency_exposure_pct`, 1% of equity):
  - It stops stacked same-direction bets, such as long EURUSD + long GBPUSD + long AUDUSD, which are all short USD.
  - It binds only when a trade adds to existing same-direction exposure.
  - It lives in `portfolio_limit_problem`, the one function both the risk model and the paper account use. The account re-checks the caps under its lock, so symbols on concurrent threads cannot both slip under a limit (tested with 12 threads).
- **Only costed positions are paper-traded.**
  - Closes are priced by `close_paper_position`, the backtests' cost model.
  - A close that ever falls back to the uncosted formula is flagged `cost_model_problem`.
- **Refused opens are journaled** as `PAPER_OPEN_REJECTED` with the reason.
- **The degradation monitor** reads each symbol's forward trades from the portfolio account.

**Honest limits.**
- **The currency cap cannot bind yet:** with one open position allowed across the portfolio, there is nothing to stack. It takes effect only if that limit is deliberately raised.
- **Backtests don't model a shared slot:** every backtest is single-symbol, so none models a trade skipped because another symbol holds the only position. Forward trade counts will be lower than per-symbol backtests suggest. Per-trade comparisons (expectancy, win rate) remain valid.
- **No strategy is validated, so every symbol still returns NO_TRADE.**
- **Restart needed:** the running paper engine uses this code only after its next restart.

**Tests.** 30 new tests cover the currency cap, the portfolio account (costed
take-profit and stop-loss, concurrent opens, restart persistence), the engine's
costed and journaled admission, the gate receiving real state, and the monitor's
per-symbol filtering. One test runs end to end: an open EURUSD paper position
blocks a gold candidate at the safety gate. **Suite: 327 passed.**

---

## 7h. Incremental filters, series `pipeline-v2-filters` — 32 experiments, 32 rejected

**Question.** Does adding ONE fixed filter to a pipeline-v1 family make it robust?

**Design.**
- Every family keeps its v1 rules, grid, data, costs and gates. The only change is one filter, applied identically to all families and not tuned.
  - **liquid-hours:** a signal is kept only if London or New York is open when the decision bar closes. Bar timestamps are open times; sessions come from `app.core.sessions` and handle daylight saving.
  - **no-high-vol:** a signal is dropped when the `app.quant.regime_lookup` volatility regime is HIGH or not yet known. It is reproduced incrementally and tested label-for-label against the original, using only past bars.
- All 32 experiments were preregistered before the first one ran.
- A hash check confirmed the 16 v1 preregistrations were unchanged.
- Filtered strategies are registered through the filter's own factory, so they can never be rebuilt without it.

**Results (verified from the run output).**

| Stopped at | Count |
|---|---|
| TRAIN | 25 |
| VALIDATION | 5 |
| WALK-FORWARD | 2 |
| LOCKED OUT-OF-SAMPLE | 0 reached |

**The only consistent training-slice improvement did not survive validation.** It was failed breakout + no-high-vol, compared on the same 9 parameter combinations with and without the filter:

| Symbol | Combos improved | Median expectancy change | Profitable combos | Validation |
|---|---|---|---|---|
| XAUUSD | 9 of 9 | +0.084R | 4 → 7 | 111 trades, PF 0.69, −0.226R |
| EURUSD | 9 of 9 | +0.086R | 6 → 8 | 25 trades (too few), PF 1.25 |
| GBPUSD | 6 of 9 | +0.015R | 5 → 7 | 91 trades, PF 0.72, −0.213R |
| USDJPY | 1 of 9 | −0.032R | 1 → 1 | stopped at TRAIN |

**Failed breakout + liquid-hours** helped on GBPUSD (9 of 9 combos) and EURUSD (6 of 9) in training, but hurt XAUUSD (0 of 9, −0.129R). On validation:
- GBPUSD: PF 0.58.
- EURUSD: only 14 trades, too few to judge.

**Mean reversion on GBPUSD** failed walk-forward with both filters, at the same 6 of 11 positive windows as without a filter.

**Everything else** changed median training expectancy by less than ±0.05R, with improved-combination counts scattered around half. That is what noise looks like.

**Trade counts rose for some filtered runs.** No-high-vol on the compression breakout kept 102–108% of the unfiltered trades, although a filter only removes signals. The cause is the one-position rule: a dropped signal frees the position slot for later signals that were previously refused. That is the rule's mechanism; I have not traced these individual trades.

**Multiple testing.**
- The experiment registry now holds **71 experiments, 0 accepted**.
- With that many attempts, the chance of at least one false positive is 97%. The Bonferroni per-experiment threshold is 0.0007.
- The 32 training comparisons above are themselves multiple comparisons, so they are descriptive, not evidence.

**Conclusion.**
- Neither a liquid-hours session filter nor a high-volatility exclusion turns any of these four families into a robust strategy on these symbols.
- The one pattern that looked promising in training reversed on unseen data. This is exactly the failure the validation stage exists to catch.
- Session and volatility-regime filters are now **REJECTED** for these families. They remain untested as additions to any future family.

**Tests.** 21 new tests: DST, close-time session semantics, exact regime equivalence and no lookahead, filter specs, and pipeline/registry integration. **Suite: 348 passed.**

---

## 7i. Profitability gap analysis (2026-09-14)

**Bottom line.** No code change, tool or filter makes this project profitable by
itself. Profit needs a real, repeatable edge, and 71 experiments have found none.
The most important finding below is not a bug. It is that **the tests, as
structured, are too small to detect the size of edge that realistically exists**
(section D).

### A. Working correctly — do not change

- **Backtest honesty:**
  - The backtest never sees future bars.
  - Stops win same-bar ties.
  - One position at a time.
  - Every result is costed.
- **Research discipline:**
  - Every experiment is preregistered.
  - Experiments chain train → validation → walk-forward → locked out-of-sample.
  - No experiment is run twice, and multiple testing is accounted for.
- **Live system:** every symbol is blocked until a strategy validates.
- **Health after the 2026-09-14 11:52 restart, with markets open:**
  - Feeds were 0.0–0.4 s old; live bars refreshed within 4 minutes.
  - 88 paper cycles ran, all NO_TRADE, with no pipeline errors.
  - The archive is recording `market_open: true`.

### B. What does not help profitability

1. **Unused code.**
   - An import-graph trace from the live runtime, the PowerShell launchers, the README commands and the tests (including string-named modules and script paths) found **110 of 265 Python files (34,405 lines) referenced by none of them**.
   - 6 of those are backup copies, such as `multi_symbol_paper_BEFORE_*.py`.
   - **No AI/agent module is on the live path.**
   - The unused files change no result, but they make it harder to know what actually runs.
2. **AI/LLM decisions.**
   - They cannot be validated on history: a language model's training data already contains the "future" of any historical test period.
   - They could only ever be forward-tested, and there is no evidence of value.
3. **More variations of the same families on the same data.**
   - 32 filtered experiments added nothing.
   - Each extra test on the same 5-year H1 data raises the false-positive odds, now 97% for at least one false pass across 71 experiments.
4. **M5/M15 strategy work** on 6 months of history.
5. **Order-flow and depth ideas** have no historical data; they are forward-only.
6. **Raw quote logging** runs at roughly 1.4 GB per trading day (2.2 GB since 11 Sep).
   - The storage guard caps `data/` at 5 GB and trims raw events near the cap, so raw quotes are not a lasting dataset.
   - The curated research archive is 0.1 MB.
   - If spread studies are wanted, a compact per-minute spread summary would outlast the raw ticks.

### C. What is miscalibrated: the cost model

**Charged vs. actual.** Bars are bid-based (verified above). The model charges the
same costs for every symbol:
- half of an assumed 1.2-pip spread at entry (in effect 0.6 pip);
- 0.1 pip slippage per side;
- $7 per lot commission.

Median spreads measured from 30–100k sampled broker quotes per symbol (Fri 11 Sep 11:20 UTC to Mon 14 Sep 06:23 UTC, so no Asian-session or rollover sample):

| | EURUSD | GBPUSD | USDJPY | AUDUSD | USDCHF/CAD | XAUUSD |
|---|---|---|---|---|---|---|
| Measured median spread (pips) | 0.0 | 0.2 | 0.3 | 0.1 | 0.1 | 1.2 |
| Charged by the model (pips) | 0.6 | 0.6 | 0.6 | 0.6 | 0.6 | 0.6 |

**What that means:**
- **FX majors are overcharged** by about 0.3–0.6 pip per trade.
- **Gold is undercharged** by about 0.6 pip ($0.06/oz).
- **Commission:** the broker's field (300, type 2) is consistent with $3 per lot per side, about $6 round turn. That reading of the units is not yet verified against a real fill.
- **Swaps are not modelled.** They are small for H1 holds and material for multi-day holds.

**Effect.** Measured on the same trades, costs took 0.02–0.14R per trade from the
pipeline-v1 training results. The FX overcharge is roughly 0.02–0.05R: enough to
move borderline results, nowhere near enough to rescue the failures (validation
profit factors of 0.58–0.72).

### D. The structural problem: too few trades per test

A simulation of the project's own gates, with trades of +1.8R or −1R (typical of
these families after costs), shows how often a strategy passes.

**Passes the validation gate**, by trade count:

| True edge | 30 trades | 65 | 150 | 400 | 1000 |
|---|---|---|---|---|---|
| **None (0R)** | 37% | 37% | 31% | 17% | 6% |
| **+0.05R** | 46% | 49% | 47% | 42% | 34% |
| **+0.10R** | 52% | 59% | 64% | 73% | 77% |
| **+0.20R** | 69% | 83% | 90% | 97% | 99% |

**Passes walk-forward** (11 windows, at least 55% positive), by trades per window:

| True edge | 20 per window | 40 | 120 |
|---|---|---|---|
| **None (0R)** | 14% | 18% | 29% |
| **+0.05R** | 26% | 43% | 73% |
| **+0.10R** | 44% | 68% | 96% |

**At current trade counts.** A realistic good FX edge is about +0.05R per trade
after costs. With 30–150 validation trades and 20–40 per walk-forward window, it
passes validation only about half the time and walk-forward 26–43% of the time.
After the training and locked stages as well, most genuine modest edges would be
**rejected**. Meanwhile, a strategy with no edge passes validation 37% of the time.

**The gates are not too strict.** Loosening them would mostly admit noise. What is
missing is **more independent trades per hypothesis**, which only more data gives.

### E. What the project needs, in priority order

1. **More trades per hypothesis.**
   - **Pool symbols:** test one parameter set across all 8 costable symbols as a single preregistered hypothesis. That gives 4–8× the trades and fewer tuned choices than per-symbol fitting.
   - **Longer history:** there is 5 years of H1 for 4 symbols, 2 years for 4 others, and no daily bars. The downloader already accepts any period and `--days`; how far back the broker serves data is unknown until probed.
2. **Hypotheses with an economic reason, not chart patterns.**
   - Daily time-series trend-following and interest-rate carry across many currencies are the FX return sources with the longest published record. Both are slow (days to weeks), so costs matter less.
   - Both need daily history. Carry also needs historical interest rates, which the project does not have; only current swap rates exist.
   - Published returns for both are modest, with long drawdowns. Not a promise.
3. **A per-symbol measured cost model**, fixed and preregistered before any new series: spread by hour, full spread charged once on bid bars. Re-testing the v1 families under it would count as a new series.
4. **DEMO execution verification** — orders have never been sent. Real fills are the only proof of slippage and commission, and sending them needs the user's explicit go-ahead.
5. **Forward data**: let the archive accumulate for months before any order-flow work.
6. **Archive the 110 unused files**, after a full test run, so what runs is obvious.

**Deliberately not recommended.**
- **Loosening the gates, the 1.5 minimum reward:risk, or the one-position limit.** They do exclude some strategy types and trades, but changing them without evidence would admit noise rather than profit.
- **Re-running rejected strategies until one passes.**

---

## 7j. Fixing the causes (2026-09-14) — built and tested; results pending

Section 7i named three causes. Each now has a fix in code. No new result exists
yet, and none is promised.

### Cause 1 — the cost model

- **Bid-based bars verified.** On 11 Sep, gold's 12:00 H1 bar had high 4390.30 = highest bid and low 4291.80 = lowest bid; the lowest ask was 4292.70.
- **`run_costed_backtest(bid_bars=True)`** charges one full spread per round trip: a BUY at the ask on entry, a SELL at the ask when buying back. The default stays the legacy model, so every recorded result remains reproducible. 5 tests.
- **`hafnot_measure_costs.py` + `app/quant/cost_profile.py`** build a dated profile from raw broker quotes.
  - Rule: the worst hourly 90th-percentile spread.
  - It cannot be used for research until at least 22 of 24 weekday hours are observed, so rollover and Asian-session spreads are included.
  - It never overwrites a profile; research series pin the profile's SHA-256.
  - Commission and slippage remain RiskConfig assumptions until DEMO fills can measure them. 7 tests.
- **Spreads now come straight from cTrader.** `hafnot_measure_costs.py` (default `--source broker`):
  - requests historical BID and ASK ticks (`ProtoOAGetTickDataReq`) for a 10-minute window at the top of every UTC hour of the last 10 weekdays;
  - samples the spread every 2 seconds and keeps only hourly statistics; **no raw ticks are stored**;
  - covers every hour at once, Asian session and rollover included, so nothing depends on locally collected quotes or on the PC staying on;
  - checks the tick-delta convention against the requested window on the first response.
- **Cross-check.** Worst-hour spreads in pips, from a one-weekday trial against locally logged quotes:

  | | EURUSD | AUDUSD | USDCHF | NZDUSD | USDCAD | GBPUSD | USDJPY | XAUUSD |
  |---|---|---|---|---|---|---|---|---|
  | cTrader ticks | 0.2 | 0.2 | 0.3 | 0.4 | 0.4 | 0.5 | 0.7 | 1.7 |
  | Local quotes | 0.3 | 0.3 | 0.4 | 0.4 | 0.5 | 0.5 | 0.7 | 1.7 |

- **Full profile.** `data/broker/measured_costs_20260914_broker.json`: 10 weekdays (31 Aug–11 Sep), 4 parallel connections, 16.5 minutes, 0 failed windows.
  - Every FX hour is 0.0–0.4 pips at the 90th percentile, **except 21:00 UTC, the 17:00 New York rollover, at 10–18 pips** (median 6–13).
  - Gold is 1.1–1.9 pips and closed at 21:00.
- **Consequence for daily strategies.** Their signal falls exactly at rollover. Charging that hour would have put every FX trade over the risk model's 2-pip spread cap, so the test would have rejected every trade and measured nothing.
  - **Decision, made before any daily result existed:** execution is assumed one hour after rollover (22:00–23:00 UTC in the measured period), charging the worst 90th percentile of those hours.
  - **Spreads charged (pips):** AUDUSD 0.3, EURUSD 0.3, GBPUSD 0.6, USDCAD 0.6, USDCHF 0.6, USDJPY 0.7, NZDUSD 1.5, XAUUSD 1.9.
  - **Limitation:** the entry price is still the daily close; price movement in that hour is not modelled.
  - **Safeguard:** the pipeline now refuses to run if any charged spread exceeds the cap.
- **Local quote logs reduced.** Both changes took effect at the 14 Sep 12:54 restart: the 11 quote files went from 150–300 MB each to about 32 MB, and `data/` from about 2.2 GB to 0.44 GB.
  - **Storage guard:** trims each raw quote file past 64 MB to its newest 32 MB, at most about 0.7 GB for 11 symbols. Before, all of them grew about 1.4 GB per trading day until `data/` reached 4.5 GB.
  - **Paper engine:** reads only the last 64 KB of each file for the latest quote. Before, it read every whole file into memory every 30 seconds.

### Cause 2 — too few trades per test

- **Long daily history, fetched from cTrader when needed and never stored.**
  - The broker serves EURUSD daily bars from 2002.
  - **Data finding:** before 2011 the daily history has six bars per week, from 2011 five. The portfolio series therefore uses 2011-01-01 to 2026-09-12 and states why in its preregistration.
  - **In-memory fetch:** each run fetches that fixed range into memory (`hafnot_download_historical_data.py --stdout`, called by `fetch_portfolio_data`); nothing is written. 15.7 years of one symbol takes about 25 seconds.
  - **Fingerprint:** the preregistration pins a SHA-256 of each symbol's bars. Two fetches of XAUUSD gave identical fingerprints, so a later run can verify it sees the same history.
  - **Earlier download removed:** a download into `data/historical/bars_long/` was stopped and its files deleted.
  - **Checks on the fetched history** (all 8 symbols, 2011–2026): no OHLC-invalid bars and no duplicates. Two problems were found:
    - **GBPUSD 2011–2015 contains extra weekend bars.** About 100 in total: one-hour Sunday-open stubs dated Saturday night, and flat after-close bars with almost no volume. Left in, each would count as a trading day in every lookback and ATR. A declared rule merges each stub into the next trading day and drops flat ones. It applies to every symbol, and the counts are recorded in the preregistration.
    - **XAUUSD history has two gaps:** 25 days (2012-09-19 to 2012-10-14) and 92 days (2013-11-19 to 2014-02-19). XAUUSD therefore starts on 2014-02-20, declared with the reason. The pipeline now refuses any undeclared daily gap longer than 5 days.
- **`app/quant/portfolio_pipeline.py`** tests one parameter set with every costable symbol pooled:
  - **Splits:** calendar-aligned train, validation and locked slices shared by all symbols.
  - **Training:** neighbourhood selection and PLATEAU on pooled trades, plus a **breadth** gate: at least 4 symbols with 10+ trades, and at least half of them positive, so one symbol cannot carry the result.
  - **Walk-forward:** calendar windows of 4 years in-sample and 1 year out-of-sample, stepping a year: 7 windows. The first design (6 + 2 years) would have left only 2 windows over this range, below the minimum of 3, and failed every strategy automatically. It was corrected before anything ran, and a test now checks the window count.
  - **Accounting:** fixed risk per trade, trades ordered by exit time.
  - **Preregistration:** pins every data file's hash and the cost profile's hash.
  - **Locked data:** one look.
  - 11 tests: breadth rejection, stage gating, refusal on changed data, no re-runs, the single locked look.

### Cause 3 — hypotheses with an economic reason

- **`donchian-trend`:** buy a daily close above the prior N-day high, sell below the low.
- **`time-series-momentum`:** buy when the close is above the close N days earlier, sell when below.
- Both use a stop of 2×ATR(20) and a target of 2, 3 or 4× the risk, because the live safety gate requires reward:risk of at least 1.5.
- Grids: channel 20/55/100 and lookback 63/126/252, each × target 2/3/4. 12 tests.
- Series **`portfolio-d1-v1`** pools both families across EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD and XAUUSD. It refuses to run without a full-day cost profile. 4 tests.

**Known limitations, written into the preregistration:**
- Swaps are not modelled; no historical swap rates exist. Mean holding time is recorded.
- Entries fall in the rollover hour.
- Positions are limited per symbol, not by the live rule of one across all symbols.
- The engine has no trailing exit.

### Next steps

1. ~~Measure the spread profile from cTrader ticks~~ — done 14 Sep.
2. Preregister and run `portfolio-d1-v1` (started 14 Sep).
3. Report whatever it shows. With several thousand pooled trades, the same gates can now tell a +0.10R edge from noise, and a rejection is informative.

**Test suite: 406 passed.**

---

## 7k. Result: `portfolio-d1-v1` — daily trend following, 8 symbols pooled — 2 of 2 rejected

**Setup.**
- **Data:** daily bars 2011-01-01 to 2026-09-12, fetched from cTrader into memory; nothing stored. About 4,075 bars per FX pair; XAUUSD 3,241 (from 2014-02-20).
- **Weekend-bar rule:** merged 80 and dropped 24 bars for GBPUSD; 7–12 merged per other symbol.
- **Costs:** measured spreads for one hour after rollover, 0.3–1.9 pips.
- **Runtime:** both experiments preregistered, then run in 1 minute.

**Results.** Both stopped at TRAIN, so the validation, walk-forward and locked data remain untouched.

| Family | Profitable combos | Pooled trades per combo | Expectancy range (R) | Chosen params | Chosen expectancy | Symbols positive |
|---|---|---|---|---|---|---|
| donchian-trend | 0 of 9 | 199–561 | −0.251 to −0.023 | channel 100, target 2R | −0.023R | 3 of 8 |
| time-series-momentum | 1 of 9 | 313–698 | −0.159 to +0.002 | lookback 63, target 2R | −0.029R | 3 of 8 |

**It is not the costs.** On the same trades, the chosen parameters were already negative before costs:

| Family | Before costs | Costs per trade | After costs |
|---|---|---|---|
| donchian-trend | −0.008R | 0.016R | −0.023R |
| time-series-momentum | −0.016R | 0.013R | −0.029R |

**What the numbers say.**
- **Break-even win rate:** at a 2R target it is 33%; the observed rate was 33%.
- **No broad effect:** EURUSD and USDJPY were positive for both families; NZDUSD, USDCAD, USDCHF and XAUUSD were negative for both.
- **Size of edge ruled out:** with 257–698 pooled trades, the standard error is roughly 0.05–0.09R. An edge above about +0.1R per trade in 2011–2018 is unlikely for these rules; a smaller one cannot be excluded.

**The limitation that matters.** These rules exit at a fixed target of 2–4R, because the backtest engine has no trailing exit and the live safety gate requires a take-profit. The documented returns of trend following come from a few very large winners that a fixed target cuts off. So this series tested *trend entries with capped exits*, not trend following as it is usually traded. That remains untested, and it would need a trailing exit in the engine.

**Registry.** 73 experiments, **0 accepted**.

**What is still honestly open.**
1. **Trend following with a trailing exit.** Keep a distant take-profit, so the safety gate's rule is still met, plus an ATR trailing stop. That needs an engine change and would be a new preregistered series, counted.
2. **Carry.** It needs historical interest-rate differentials, which cTrader does not provide.

Until something validates, the live system correctly keeps every symbol at NO_TRADE.

---

## 7l. Result: `portfolio-d1-v2-trailing` — trend following with a trailing exit — 2 of 2 rejected

**What changed from 7k.**
- **Engine:** gained trailing exits. The stop is fixed at entry, trails the best price since entry, and is checked before each bar moves it; a gap beyond it fills at the open. Trades still open at the end of a slice are closed at its last close rather than dropped, for this series only.
- **Unchanged fixed exits:** they exit exactly as before. Donchian's recorded v1 result recomputes to the same 257 trades and −0.0235R.
- **Everything else identical:** same data, costs, gates and execution rule as portfolio-d1-v1. The grids were channel or lookback × trail 2/3/4 ATR, with a distant 10R cap the safety gate requires.
- 11 new tests.

**Results.**

| Family | Stopped at | Training (2011–2018) | Validation (2018–2022) |
|---|---|---|---|
| donchian-trend-trailing | VALIDATION | 6 of 9 combos profitable (PLATEAU). Chosen channel 100, trail 4 ATR: 132 trades, **+0.122R**, PF 1.37, drawdown 4.6%, 5 of 7 eligible symbols positive, mean hold 36 days | 92 trades, 38% wins, **−0.058R**, PF 0.84 |
| time-series-momentum-trailing | TRAIN | 3 of 9 combos profitable (ISOLATED_PEAK); chosen +0.066R | not reached |

**What the numbers say.**
- **Trailing exits did what trend following claims in training:** Donchian went from −0.023R with fixed targets to +0.122R, with broad support across symbols.
- **They did not survive new data.** In validation, EURUSD (−0.38R), USDCHF, AUDUSD and NZDUSD lost; GBPUSD and USDCAD gained.
- **This is the in-sample-good, out-of-sample-bad pattern** the validation stage exists to catch. The locked 2022–2026 data remains untouched.

**Registry.** 75 experiments, **0 accepted**.

---

## 7m. DEMO execution checks and code cleanup (2026-09-14)

### DEMO order execution

**Verified against the DEMO server, read-only, with no order sent**
(`python hafnot_verify_demo_execution.py`):

| Check | Result |
|---|---|
| Account is DEMO | VERIFIED (`isLive=false`) |
| Application and DEMO account authentication | VERIFIED |
| Reading open positions and orders (RECONCILE) | VERIFIED — 0 positions, 0 orders |
| Volume normalization | VERIFIED — 0.01 lot EURUSD becomes volume 100,000, the broker minimum |

**Five defects in the never-run order code, found and fixed before any order was sent.** Each was confirmed against the installed protobuf definitions or the broker's own symbol data:
1. **Volume 0.** Volume limits were read from `ProtoOALightSymbol`, which has no lot size or limits, so every value was 0. The full symbol is now fetched with `ProtoOASymbolByIdReq`.
2. **100 times the size.** Volume was lots × lotSize × 100, but lotSize is already in hundredths of a unit.
3. **Close could not be sent.** `ProtoOAClosePositionReq` requires a volume the code never set; the position's volume is now read first.
4. **No fill price.** `ORDER_ACCEPTED` was taken as the outcome; the worker now waits for `ORDER_FILLED`.
5. **No result was ever read.** The client looked for `x.request.request.json.result.json` while the worker wrote `x.request.json.result.json`. The read-only verification run exposed it.

**Pinned by tests.** Sizing and stop-distance units are tested against the broker's real EURUSD and XAUUSD specifications, along with the client–worker result filename (9 tests).

**Verified with one real DEMO round trip** (details in "Second DEMO order attempt" below):

| Check | Result |
|---|---|
| Order submission | VERIFIED — 0.01 lot EURUSD market BUY, volume 100,000 |
| Fill | VERIFIED — position 241508471 filled at 1.15347 |
| Stop-loss and take-profit attached | VERIFIED — relative distances accepted: 1.14847 (−50 pips) and 1.16347 (+100 pips) |
| Position tracking | VERIFIED — RECONCILE showed the position with the expected volume, stop and target |
| Close and fill confirmation | VERIFIED — ORDER_ACCEPTED then ORDER_FILLED at 1.15366 for the full volume; protective orders cancelled |
| Flat afterwards | VERIFIED — 0 positions, 0 orders |
| Commission | VERIFIED — −3 cents per side at 0.01 lot (moneyDigits 2): $3 per lot per side, below the $7 round turn the backtests assume |
| Slippage | **NOT MEASURED** — the quote at the moment of sending was not captured |

`python hafnot_verify_demo_execution.py --send` performs the round trip in one run: one 0.01-lot EURUSD market BUY with a 50-pip stop and a 100-pip target, closed straight away. It refuses if any position is already open. It has not yet completed end to end in a single run: the verified round trip above was finished by the worker's CLOSE_POSITION action after the parsing fix.

### Unused code archived

- **Moved, not deleted:** 64 files to `archive_superseded/unreferenced_20260914/`, with a `MANIFEST.md`. They were old ad-hoc test scripts, diagnostics, old desktop-app tools, five backup copies of the paper engine and superseded workers.
- **Two independent checks per file:**
  - no import path from the runtime, any launcher, any documented command or the tests;
  - no mention by name or module path in any code, script, document or config file. 26 candidates that were mentioned somewhere were left in place.
- **Three files restored.** Pytest collects `app/**/test_*.py`, and those files held 12 passing tests. The suite count exposed it (415 instead of 427) before anything else was done.
- **Afterwards:**
  - all 215 remaining Python files compile;
  - the runtime, research, monitoring and execution modules import cleanly;
  - the running system was unaffected: feeds under 1 s old, `data/` at 0.59 GB.

### First DEMO order attempt (user-run, 14 Sep 13:55 local)

- **Command:** the user ran `python hafnot_verify_demo_execution.py --send`.
- **Outcome:** the four read-only checks passed again. The broker then refused the order with `TRADE permission required`.
- **Verified afterwards:** 0 open positions and 0 orders, so nothing was opened.
- **Cause:** `app/openapi/auth/oauth.py` always requests the OAuth scope `accounts` (read-only), so the stored token cannot trade on any account. This was a deliberate safety default.
- **What is required:** trading needs a token authorized with scope `trading`, granted by the user in the cTrader consent page. Order submission, fills, stops, tracking and closing remain **NOT VERIFIED** until then.
- **Tooling changed so this cannot recur silently:**
  - `oauth.py` takes `--scope accounts|trading`, still read-only by default. With `trading` it warns to approve only the DEMO account, and it saves the scope with the token.
  - `hafnot_verify_demo_execution.py` reports the token scope and refuses `--send` with instructions when the token cannot trade (4 tests).
- **Test suite: 434 passed.**

### Second DEMO order attempt (user-run, 14 Sep 14:00 local, after re-authorizing with scope `trading`)

- **The order worked.** The broker accepted and filled it: position 241508471, EURUSD BUY 0.01 lot at 1.15347, stop 1.14847, target 1.16347.
- **A sixth defect then ended the run before the close.** The worker read `moneyDigits` from the execution event, which has no such field; it exists only on the deal and the position.
- **Found at once by a read-only RECONCILE,** which showed the open position.
- **Fixed and proven before touching the account again.** Event parsing is now a function, `execution_details`. It was checked on sample `ProtoOAExecutionEvent` messages for an accepted order, a fill with order, position and deal, and a closing fill carrying only a deal, and is now a permanent test run under `.ctrader_venv`.
- **Round trip completed.** The worker's CLOSE_POSITION then closed the position:
  - accepted, then filled at 1.15366 for volume 100,000;
  - the protective orders were cancelled;
  - a follow-up RECONCILE showed 0 positions and 0 orders.
- **Net effect on the DEMO account:** about +1.9 pips before commission, 3 cents commission per side.
- **Test suite: 435 passed.**

### Credentials found in `.env.example`

- **The file held the real cTrader client ID and client secret,** identical to `.env`. The release builder excluded only `.env` by name, so a ZIP would have shipped them.
- **Fixed:**
  - both values replaced with placeholders; the real values remain only in `.env`;
  - `hafnot_build_release_zip.py` now checks the **content** of every file it would include against the credential values in `.env` and the OAuth token file, and refuses to build on any match (3 tests).
- **Verified afterwards:** no file in the project other than `.env` and the token file contains a credential value.
- **Existing ZIPs on the Desktop, found by the same scan:**
  - `HAFNOT_FINAL_CANONICAL (2).zip` contains `.env`, the OAuth token file and the old `.env.example`;
  - `HAFNOT_FINAL_CANONICAL55.zip` contains the old `.env.example`.
- **Recommended to the user:** they were left untouched as the user's files. If either was ever shared, or synced somewhere untrusted, rotate the cTrader application secret and re-authorize to replace the OAuth tokens.

**Test suite: 430 passed.**

---

## 7n. Result: `portfolio-d1-v3-multiasset` — trend following across 16 markets — 2 of 2 rejected

**Design (preregistered before any result).**
- **Families:** the two trailing trend families from §7l, unchanged.
- **Gates:** unchanged. Execution at 22–23 UTC, $50 fixed risk on $10k.
- **Universe (16 markets), chosen by data quality and trading hours only:**
  - FX majors (7);
  - metals: XAUUSD, XAGUSD, XPTUSD;
  - US indices: US500, NAS100, US30, US2000;
  - energies: WTI crude, natural gas.
- **Excluded:**
  - Treasuries, corn, wheat and soybeans: too little history;
  - copper: a 33-month gap;
  - sugar, coffee and Brent: closed at the execution hour; Brent reopens 20:00 New York and gave 0 ticks at 21–23 UTC;
  - VIX;
  - non-USD instruments.
- **Declared later starts, each checked against the broker's history:**
  - XAUUSD and XAGUSD 2014-02-20: gaps of 25 and 92 days;
  - XPTUSD 2016-04-19: a 22-day gap;
  - US2000 2015-10-22: a 315-day gap;
  - NATGAS 2016-05-23: gaps of 304, 6 and 89 days.
  - A drafted US500 later start was dropped: its stated reason (uneven bars per year) proved false on checking.
- **Costs:**
  - **Spread:** measured per market from broker ticks at 21–23 UTC over 10 weekdays, 0 failed windows (`measured_costs_20260914_multiasset_broker.json`).
  - **Commission:** from the broker's specs. FX is $6 per lot round trip (DEMO-confirmed); metals, indices and energies are $0.
  - **Spread cap:** max(2 pips, 2 × the market's charged spread).
  - **Platinum:** charged its real 105.8-pip execution-hour spread.
- **Research only:** the new instruments are registered in memory by the research run. The paper engine still refuses them.
- **Preregistration hygiene:** the new pinned-profile code first recorded the cost profile as an absolute path. v1 and v2 therefore no longer re-verified; a field-by-field diff showed only that path differed. The path is now recorded relative to the project, and v1 and v2 re-verify identically. The first v3 preregistration was replaced before any v3 run (moved aside, not deleted).

**Results.**

| Family | Stopped at | Training (2011–2018) | Validation (2018–2022) | Walk-forward | Locked 2022–2026 |
|---|---|---|---|---|---|
| donchian-trend-trailing | WALK_FORWARD | channel 100, trail 4 ATR: **+0.172R**, 8 of 9 combos profitable (PLATEAU), 6 of 8 eligible markets positive | 122 trades, **+0.060R**, PF 1.18 | **3 of 7** windows positive, mean −0.007R — failed | not reached |
| time-series-momentum-trailing | LOCKED_OUT_OF_SAMPLE | lookback 63, trail 4 ATR: **+0.088R**, PLATEAU, 10 of 13 eligible markets positive | 263 trades, **+0.089R**, PF 1.26 | 5 of 7 windows positive, mean +0.066R — passed | 247 trades, **−0.098R**, PF 0.74, drawdown 16.5% — **failed** |

**What the numbers say.**
- **Adding markets helped until the last test.**
  - Both families passed validation. Neither did on FX and gold alone.
  - Time-series momentum was the first strategy in this project to pass walk-forward.
- **It then lost on the untouched 2022–2026 data.**
  - Losing markets: every FX major, and crude.
  - Winning markets: US500, US2000 and natural gas.
  - The locked slice has now been used for this family and cannot be reused.
- **Several markets barely traded.**
  - XPTUSD had 0 trades in every stage.
  - NAS100, US30, XAGUSD and XAUUSD had few trades, and none in the locked slice.
  - **VERIFIED cause:** a $50 risk is less than one minimum lot. The rejection reasons were tallied for time-series momentum (lookback 63, trail 4 ATR) over each market's full history. Counts are signal-bars, since the strategy signals on every bar while a trend lasts:

    | Market | Trades | Below minimum lot | `INVALID_PRICE` | Position already open |
    |---|---|---|---|---|
    | XPTUSD | 0 | 2,052 | 569 | 0 |
    | XAGUSD | 10 | 2,292 | 601 | 272 |
    | XAUUSD | 22 | 2,597 | 37 | 521 |
    | US30 | 5 | 2,722 | 96 | 251 |
    | NAS100 | 25 | 1,514 | 343 | 1,190 |
    | US500 (control) | 87 | 1 | 141 | 3,760 |

  - `INVALID_PRICE` is the risk model refusing a stop or target at or below zero (`risk.py`). A short's distant 10R target sits 40 ATR away with a 4-ATR trail and can fall below zero in volatile markets. So some short signals were refused by the 10R cap, not by the market.
  - **Consequence:** at $10k and 0.5% risk these contracts cannot be traded at this stop distance. This series is in effect a test of FX, US500, US2000, WTI and natural gas.
- **Still unmodelled:** swaps, which matter for trades held about 39 days, and slippage.

**Registry.** 77 experiments, **0 accepted**. Family-wise false-positive probability at α 0.05 is 0.98. With no winner chosen, selection bias does not arise.

**Test suite: 449 passed.**

---

## 7o. Trader-style market structure on H4, with a multiple-testing guard (2026-09-14) — 2 of 2 rejected

**Why.** The user asked for the bot to analyse the market the way a discretionary trader does, and to keep testing, if necessary 1,000 ideas, until one is profitable. Testing until something passes guarantees a false winner: at α 0.05, the 77 experiments already run imply 3.85 zero-edge rules expected to look significant. So a guard was built first.

**Multiple-testing guard** (`app/quant/multiple_testing.py`).
- **Rule.** The locked slice's per-trade R must be significantly above zero at 0.05 / N (Bonferroni). N counts every experiment in the registry, including the one being judged. The test is a one-sided t with normal approximation and at least 30 trades, applied on top of the ordinary out-of-sample gate.
- **Scope.** Opt-in per series (`require_multiple_testing_significance`), so earlier preregistrations stay byte-identical. The rule is written into the preregistration.
- **Result record.** The locked result stores the p-value, the N used and the mean R the sample needed.
- **What it demands.** At N = 78, 250 trades with a spread of 1.3R need a mean of about +0.26R. As N grows, the bar rises.
- **Limitations.**
  - Overlapping trades are treated as independent, so the guard is a floor, not a proof.
  - Passing still earns only a paper-forward trial.

**Strategies** (closed H4 bars, OHLC only).
- **Swings** (`app/quant/market_structure.py`). A swing high is above the `swing_bars` bars before it and at least as high as those after. It is **confirmed only after those later bars close**, and tracked incrementally.
- **`market-structure-pullback`.**
  - Structure: higher highs and higher lows (or the mirror).
  - Entry: a pullback into the latest higher low, within 0.5 ATR, rejected by a bullish close above that zone and below the latest high.
  - Stop 0.5 ATR beyond the low; target `target_r` × risk.
- **`structure-break-retest`.**
  - Setup: the first close beyond the latest swing high, within the last 20 bars, with every close since holding beyond it.
  - Entry: price retests the level (within 0.5 ATR) and a bullish candle closes back above it; SELL mirrors this.
  - Stop 0.5 ATR beyond the level.
- **Tests.** Confirmation timing, catch-up and restart, BUY rules and the SELL mirror.

**Execution and data rules.**
- **Rollover filter.** Broker H4 bars close at 01, 05, 09, 13, 17 and 21 UTC in summer; the 21 UTC close is the 17:00 New York rollover. A new filter, `exclude_new_york_hours` (DST-aware), drops signals decided in New York hour 17. The strategy still sees every bar, so structure tracking is not broken.
- **H4 gap check.** It now covers H4 as well as D1. The broker's XAUUSD **H4** history has a 92-day hole (2020-06-30 to 2020-09-30) that its D1 history does not.
- **GBPUSD.** 2011–2015 shows about 25 extra H4 bars a year, and its Sunday open starts at 18:00 UTC rather than 22:00.

**Disclosure — data seen before preregistration.** To size the run time, both strategies were backtested once with their default parameters on EURUSD H4, 2011-01-01 to 2018-11-06 (the training slice only):
- market-structure-pullback: 204 trades, −0.075R;
- structure-break-retest: 402 trades, −0.119R.

The defaults sit inside the grids to be preregistered. Validation, walk-forward and locked data were not touched.

**Costs.**
- **Profile.** H4 entries happen at five times of day. A 24-hour profile for the 16 markets was measured from broker ticks, 10 weekdays (31 Aug – 11 Sep), with 0 failed windows (`measured_costs_20260914_multiasset24h_broker.json`).
- **Charged spread.** Worst p90 over the decision hours 01, 05, 09, 13 and 17 UTC, in pips:

  | Market | Spread |
  |---|---|
  | EURUSD | 0.0 |
  | AUDUSD, USDCHF | 0.2 |
  | GBPUSD, NZDUSD, USDCAD, US2000 | 0.3 |
  | USDJPY, US500, NATGAS | 0.4 |
  | NAS100 | 1.1 |
  | XAUUSD | 1.5 |
  | US30 | 2.1 |
  | WTI | 2.8 |
  | XAGUSD | 4.4 |
  | XPTUSD | 47.5 |

- **Commission and slippage.** Commission per broker spec; slippage 0.1 pip per side (RiskConfig).
- **Series.** `portfolio-h4-v1-structure`:
  - same 16 markets as §7n;
  - declared H4 starts: XAUUSD 2020-09-30, XAGUSD 2014-02-19, XPTUSD 2016-04-19, US2000 2015-10-21, NATGAS 2016-05-22;
  - same gates, plus the multiple-testing guard.

**Results.** Both families were rejected at TRAIN (2011-01-01 to 2018-11-06), so validation, walk-forward and locked data were never used. XAUUSD contributed no training trades, because its H4 history starts 2020-09-30.

| Family | Profitable combos | Pooled training trades per combo | Expectancy range | Best combo | Eligible markets positive |
|---|---|---|---|---|---|
| market-structure-pullback | **0 of 9** (NO_EDGE) | 1,161–2,179 | −0.072R to −0.189R | swing 5, target 2R: 1,229 trades, −0.072R, PF 0.89 | 4 of 14 |
| structure-break-retest | **0 of 9** (NO_EDGE) | 2,417–3,971 | −0.022R to −0.118R | swing 2, target 4R: 3,150 trades, −0.022R, PF 0.97 | 4 of 15 |

**What the numbers say.**
- **Not a small-sample verdict.** Each combination had thousands of trades, so an edge of a few hundredths of R would have shown. Every combination lost, in both families.
- **Pullback strategy by market** (chosen combination): only USDCHF (+0.04R), US30 (+0.02R), NZDUSD and US2000 (about 0) were not negative. NATGAS (−0.43R), USDJPY (−0.18R) and AUDUSD (−0.17R) lost most.
- **Break-retest by market:** positive on NAS100 (+0.14R), NZDUSD (+0.10R), crude (+0.08R) and US30 (+0.06R), negative elsewhere. At 4 of 15 markets that is no broader than chance.
- **Conclusion.** Mechanical versions of the two most common chart setups, "buy the higher low" and "break and retest", did not pay on this broker's prices after measured costs. The multiple-testing guard was not reached.

**Registry.** 79 experiments, **0 accepted**. The Bonferroni threshold is now 0.00063 per experiment.

**Test suite: 473 passed.**

---

## 7p. Idea batch (2026-09-14/15): currency strength, weekday-hour seasonality, shock-day continuation — 3 of 3 rejected

**Why these three.** They do not come from reading the same single-market chart everyone reads: one is relative to other currencies, one is a calendar effect, and one reacts to news. Every series requires the multiple-testing guard (§7o).

**Engine and pipeline additions.** Each is inactive unless used, so earlier results are unchanged.
- **`exit_after_bars` (engine).**
  - A trade not closed by its stop or target closes at the close of that many bars after entry (`TIME`).
  - The stop and target are still checked first on each bar.
- **`bar_features` (portfolio pipeline).** A named cross-market feature is attached to copies of the bars after the preregistration check, so the pinned fingerprints stay those of the fetched bars. It is declared in the preregistration.
  - `currency_strength` attaches each bar's symbol and the seven USD majors' closes for the same daily bar.

**Series.**

| Series | Strategy | Markets, bars | Grid | Exits |
|---|---|---|---|---|
| `portfolio-d1-v4-currency-strength` | `currency-strength-momentum` | FX7, D1 | lookback 21/63/126 × trail 2/3/4 ATR; top 2 | Rank the eight currencies by log return against USD. Long a top-2 currency stronger than USD, short a bottom-2 currency weaker than USD. Trailing stop, 10R cap. |
| `portfolio-h4-v2-seasonality` | `weekday-hour-seasonality` | 16 markets, H4 | lookback 26/52/104 weeks × min t 1.0/1.5/2.0 | Trade the next bar in the direction of its New York weekday-hour slot's average return when that is significant. Exit after one bar; stop 1 ATR. |
| `portfolio-d1-v5-shock-continuation` | `shock-day-continuation` | 16 markets, D1 | shock 1.5/2.0/2.5 × ATR × target 2/3/4R | A day with true range ≥ shock × ATR closing in its top or bottom quarter. Follow it; stop at the day's far extreme. |

**Series settings.**
- **Currency strength and shock-day** use §7n's costs and execution rule.
- **Seasonality** uses §7o's costs, execution hours and rollover filter.
  - It gets 3,200 H4 bars of warm-up (about two years), so the 104-week lookback is filled at the start of every evaluated slice.

**Declared limitations.**
- **News:** no historical news calendar is available from the broker, so "news" days are identified by price alone.
- **Seasonality:** its one-bar trades pay a full round-trip cost every four hours of exposure.

**Results — currency strength and shock-day continuation.** Both passed training and validation, then failed walk-forward, so their locked 2022–2026 data was never used.

| Series / family | Training (2011–2018) | Validation (2018–2022) | Walk-forward (7 yearly windows) |
|---|---|---|---|
| currency-strength-momentum | 5 of 9 combos profitable (PLATEAU). Chosen lookback 126, trail 4 ATR: 191 trades, **+0.045R**, PF 1.13; 5 of 7 pairs positive | 115 trades, **+0.056R**, PF 1.17, drawdown 4.7% | **2 of 7** windows positive, mean **−0.081R** — failed |
| shock-day-continuation | 8 of 9 combos profitable (PLATEAU). Chosen shock 2.5 ATR, target 4R: 112 trades, **+0.271R**, PF 1.37; 3 of 4 eligible markets positive | 74 trades, **+0.376R**, PF 1.53, drawdown 5.6% | **3 of 7** windows positive, mean **−0.202R** — failed |

**What the numbers say.**
- **Currency strength.**
  - A weak but broad training edge (+0.045R) held up in validation.
  - It lost in most yearly re-selection windows.
  - The edge is not stable across time.
- **Shock-day continuation looked the strongest of anything tested in this project before walk-forward.** The walk-forward shows why it is not trusted:
  - its chosen setting traded only 112 times in 8 years across 16 markets, and only 74 times in validation;
  - few eligible markets (4) carry that result;
  - re-selected year by year, it lost on average.

  A handful of large winners inflated the single validation number. This is exactly the "one lucky period" pattern that walk-forward exists to catch.
- **Consequence.** Neither reached the locked slice or the multiple-testing guard.
- **Illustration** (an estimate, not a recorded result). Take a locked result shaped like shock-day's validation: 74 trades, 28.4% winners, PF 1.53, fixed exits. Its trades sit near +3.9R and −1R, a standard deviation of about 2.2R. At N = 81 (p ≤ 0.00062, z ≈ 3.23) that needs a mean of about +0.82R, so its +0.38R would not have qualified.

**Results — weekday-hour seasonality.**
- **First run.** Started 14 Sep; the machine was shut down while it computed. Nothing was recorded, and no locked data was consumed.
- **Re-run.** 15 Sep, against the same preregistration, which re-verified identically. Rejected at TRAIN (2011–2018), so validation, walk-forward and locked data were never used.

| Combos profitable | Pooled training trades per combo | Expectancy | Profit factor | Win rate | Eligible markets positive |
|---|---|---|---|---|---|
| **0 of 9** (NO_EDGE) | 6,622–36,644 | −0.038R to −0.055R | 0.79–0.84 | 44–45% | 6 of 15 |

- **What it says.** Every combination lost across tens of thousands of one-bar trades, whatever the lookback (26–104 weeks) or the significance threshold (t ≥ 1.0–2.0). Stricter thresholds cut trades five-fold without turning the result positive.
- **Interpretation, not measured.** Any weekday-and-hour effect in these markets is smaller than the cost of trading it with four-hour holds. This series did not measure returns before costs.

**Registry after §7p.** 82 experiments, **0 accepted**.

---

## 7q. Liquidity levels on 15-minute bars (2026-09-15) — 2 of 2 rejected

**Request.** The user asked for every timeframe (D1, H4, H1, M15, M5) to be analysed, including:
- trend following, continuation and pullbacks;
- liquidity at yesterday's and last week's highs and lows and at swing points, where stops rest;
- support and resistance, price action, SMC/ICT;
- order flow, footprint and heatmaps.

**What cannot be tested here, and was not faked.**
- **Order flow, footprint, heatmaps and depth of market** need traded volume at each price or order-book history. Spot FX and CFDs have no central exchange volume. cTrader trendbars carry only a tick count, and the Open API offers no historical depth of market.
- **5-minute bars.** About 570,000 bars a symbol since 2019, held in memory for ten markets, exceed this PC. The 15-minute test uses daily and weekly levels and a daily bias, so it still spans timeframes.

**Already tested in this project.**
- The SMC "liquidity sweep + fair value gap" setup: 15 experiments, all rejected.
- H4 swing pullbacks and break-retests: §7o, rejected.

**Engine speed-up, verified before use.**
- **Change.** The engine used to copy the visible bars on every bar, making each replay quadratic in bar count. It now passes a read-only view with the same contents; indexing past the decision bar raises an error.
- **Verification.** The recorded `portfolio-d1-v1` Donchian training result was recomputed with the new engine: **257 trades, −0.023481997178838535R, identical**, on data whose fingerprints still matched the preregistration.
- **A bug caught first.** The first version returned an empty list for a reversed slice. Tests caught it before any experiment ran with it, and it was fixed.
- **Data probe.** EURUSD M15, 2019-01-01 to 2026-09-12: 191,599 bars in 127 s, no gaps longer than four days.
- **Gap check** now also covers H1, M15 and M5.

**Liquidity levels** (`app/quant/liquidity_levels.py`).
- **Trading days** run 17:00 to 17:00 New York (DST-aware). A bar belongs to the day it opens in, and weekend stubs belong to Monday.
- **Levels:** the previous completed day's and week's high and low, plus completed daily closes for a bias.
- **Bias:** the last daily close against the mean of `bias_days` closes.

**Strategies** (15-minute bars).

| Family | Setup | Stop | Grid |
|---|---|---|---|
| `liquidity-sweep-reversal` | The stop hunt, with the bias. At yesterday's or last week's low (bias up): the prior bar closed above, it is the day's first trade below the level, and the bar closes back above. The high mirrors it. | 0.1 ATR beyond the sweep extreme | bias 10/20/50 days × target 2/3/4R |
| `liquidity-run-continuation` | Take liquidity, retest, continue. A fresh close through yesterday's or last week's high with the bias, within 16 bars today. Every close since holds beyond it. The bar retests within 0.25 ATR and closes bullish beyond the level. | 0.5 ATR beyond the level | same grid |

**Series `portfolio-m15-v1-liquidity`.**
- **Markets:** the 7 USD majors, XAUUSD, US500 and NAS100.
- **Data:** 2019-01-01 to 2026-09-12. XAUUSD starts 2020-09-30, after its 92-day H4 gap; the M15 fetch is gap-checked too.
- **Warm-up:** 5,000 bars, about 52 trading days, so the 50-day bias is filled.
- **Walk-forward:** 2-year in-sample and 6-month out-of-sample windows.
- **Decisions:** New York hours 17 and 18 (the rollover and the thin hour after it) are dropped.
- **Spread charged:** the worst p90 of the other 22 UTC hours. EURUSD and AUDUSD 0.2; GBPUSD, USDCHF and USDCAD 0.3; NZDUSD, USDJPY and US500 0.4; NAS100 1.1; XAUUSD 1.7 pips.
- **Commission:** per broker spec.
- **Guard:** the multiple-testing guard applies.

**Data fetched.** 140,355–191,599 M15 bars a market, 10 markets, held in memory: the run's process used about 0.45 GB. Every market passed the gap check.

**Results.** Both families were rejected at TRAIN (2019-01-01 to 2022-11-06), so validation, walk-forward and locked data were never used.

| Family | Profitable combos | Pooled training trades per combo | Expectancy | Profit factor | Win rate | Markets positive (chosen combo) |
|---|---|---|---|---|---|---|
| liquidity-sweep-reversal | **0 of 9** (NO_EDGE) | 915–1,848 | −0.149R to −0.176R | 0.75–0.81 | 20–31% | 2 of 10: NAS100 +0.08R, XAUUSD +0.01R |
| liquidity-run-continuation | **0 of 9** (NO_EDGE) | 5,553–7,616 | −0.099R to −0.121R | 0.84–0.87 | 20–33% | 2 of 10: NAS100 +0.15R, GBPUSD +0.07R |

**What the numbers say.**
- **Neither strategy paid, whatever the bias length (10–50 days) or target (2–4R).** Both the "stop hunt" reversal at yesterday's and last week's extremes and the "take liquidity, retest, continue" trade lost across every combination, with a daily-trend filter and hundreds to thousands of trades.
- **Win rates sat below what each target needs to break even.** A 2R target needs 33% winners and a 4R target needs 20%, before costs. Both families were at or below that line.
- **The only positive market in both was NAS100.** One market in ten is what chance would give.

**Registry.** 84 experiments, **0 accepted**.

---

## 7r. Gross-edge diagnostic (2026-09-15): do the strategies lose because of costs, or before them?

**Method** (`hafnot_gross_edge_diagnostic.py`).
- For each finished portfolio experiment, the parameters its preregistered rule chose were re-run on its **training slice only**, data it had already used, twice:
  - with the preregistered costs ("net");
  - with spread, slippage and commission set to zero ("gross").
- Position sizing and the broker's lot limits were unchanged.
- No validation, walk-forward or locked data was touched, nothing was recorded, and no parameter was chosen from the output. It is a diagnostic, not an experiment.
- **Check:** every net figure reproduced the recorded training result exactly (trade count and expectancy), with the current engine.

| Series | Strategy (chosen parameters) | Trades | Net R | Gross R | Cost per trade (R) |
|---|---|---|---|---|---|
| portfolio-d1-v1 | donchian-trend | 257 | −0.023 | −0.014 | 0.010 |
| portfolio-d1-v1 | time-series-momentum | 698 | −0.029 | −0.020 | 0.009 |
| portfolio-d1-v2-trailing | donchian-trend-trailing | 132 | +0.122 | +0.128 | 0.006 |
| portfolio-d1-v2-trailing | time-series-momentum-trailing | 305 | +0.066 | +0.070 | 0.004 |
| portfolio-d1-v3-multiasset | donchian-trend-trailing | 183 | +0.172 | +0.179 | 0.007 |
| portfolio-d1-v3-multiasset | time-series-momentum-trailing | 420 (424 gross) | +0.088 | +0.087 | ≈0 |
| portfolio-h4-v1-structure | market-structure-pullback | 1,229 (1,316 gross) | −0.072 | −0.040 | 0.032 |
| portfolio-h4-v1-structure | structure-break-retest | 3,589 (3,639 gross) | −0.041 | +0.007 | 0.048 |
| portfolio-d1-v4-currency-strength | currency-strength-momentum | 191 | +0.045 | +0.050 | 0.005 |
| portfolio-h4-v2-seasonality | weekday-hour-seasonality | 6,953 | −0.038 | **+0.045** | **0.082** |
| portfolio-d1-v5-shock-continuation | shock-day-continuation | 112 (116 gross) | +0.271 | +0.240 | — |
| portfolio-m15-v1-liquidity | liquidity-sweep-reversal | 1,670 (1,804 gross) | −0.154 | +0.009 | 0.163 |
| portfolio-m15-v1-liquidity | liquidity-run-continuation | 7,180 (7,183 gross) | −0.104 | +0.020 | 0.124 |

*Where trade counts differ, zero costs changed position sizes. That can change which orders clear the broker's minimum lot and when the one-position-per-symbol slot frees up. The rejection reasons were not tallied for this diagnostic. The extra trades change the gross average, which is why shock-day's gross is below its net.*

**What it shows.**
- **Daily strategies pay about 0.005–0.010R a trade in costs.**
  - The fixed-target trend families lost before costs too.
  - The trailing trend, currency-strength and shock-day families were positive in training with or without costs.
  - They failed later, on new data (§7l, §7n, §7p). **Costs are not what sank the daily strategies; instability across time is.**
- **H4 structure strategies pay 0.03–0.05R a trade.**
  - Break-retest is about zero before costs (+0.007R).
  - The pullback loses before costs (−0.040R).
  - Cheaper execution would not make either worthwhile.
- **M15 liquidity strategies pay 0.12–0.16R a trade.**
  - A 15-minute stop is small, so the same spread and commission are a large fraction of the risk.
  - Before costs, the stop-hunt reversal made +0.009R and the break-retest-continue +0.020R: essentially nothing.
  - These setups have no edge for costs to take away; zero-cost trading would not rescue them.

---

## 7s. Day-window weekday seasonality (2026-09-15) — 1 of 1 rejected

**Why, and the selection-bias disclosure.**
- **Origin.** §7r found one-bar weekday-hour seasonality at +0.045R before costs and −0.038R after, on its training slice. The user asked for the recommended follow-up to be tested.
- **This test was chosen after looking at that training data.** It is preregistered as a new series, counted in the registry, and judged by the multiple-testing guard like every other.

**A design flaw caught before running.**
- **The first idea:** keep the one-bar signal and simply hold for a day.
- **Why that was wrong:** the signal forecasts only the next four hours, so holding six bars adds five bars of noise. Risk in price grows about 2.5×, so costs in R shrink, but the one-bar edge in R shrinks by the same factor, and the sign stays negative.
- **The test as run:** the signal itself measures the full next 24 hours.

**Rules** (`weekday-day-window-seasonality`, the same module with `hold_bars` = 6).
- **Signal.** At an H4 close, the next bar's New York (weekday, hour) slot and the log returns of the **six-bar windows** that began in that slot over the last `lookback_weeks` weeks give a t-statistic. BUY at t ≥ `min_t`, SELL at t ≤ −`min_t`.
- **Exit:** at the close of the sixth bar (one trading day).
- **Stop:** 2.5 × H4 ATR, from √6 ≈ 2.45 × the one-bar ATR used before, fixed before any run. The cap is 10R.
- **Unchanged from §7p:** grid (lookback 26/52/104 weeks × min t 1.0/1.5/2.0), 16 markets, costs, rollover filter, 3,200-bar warm-up and the multiple-testing guard.
- **Module change, backward-compatible.** Window returns are recorded under the window's first bar once its last bar has closed. With `hold_bars` = 1 this is each bar's own return, exactly as before; tests pin it. **Verified before this series ran:** the recorded §7p training result recomputes identically after the change (6,953 trades, −0.038R, `hafnot_gross_edge_diagnostic.py --series portfolio-h4-v2-seasonality`).
- **Not modelled.** Each trade holds through one rollover, and some over a weekend; swaps are not modelled.

**Results.** Rejected at TRAIN (2011-01-01 to 2018-11-06) with parameter sensitivity ISOLATED_PEAK, so validation, walk-forward and locked data were never used.

| lookback \ min t | 1.0 | 1.5 | 2.0 |
|---|---|---|---|
| 26 weeks | 12,142 trades, −0.007R | 6,603 trades, **+0.006R**, PF 1.02 | 3,053 trades, −0.008R |
| 52 weeks | 11,965 trades, −0.013R | 6,526 trades, −0.007R | 3,002 trades, −0.011R |
| 104 weeks | 10,684 trades, −0.016R | 5,633 trades, −0.011R | 2,604 trades, **+0.010R**, PF 1.04 |

**What it says.**
- **Holding the full-day window did what it was meant to.** Net expectancy moved from −0.038R (one-bar, §7p) to about zero, with win rates of 48–50%.
- **About zero is not an edge.**
  - Only 2 of 9 combinations were positive, at +0.006R and +0.010R, and they are not neighbours in the grid.
  - The neighbourhood rule chose lookback 26, min t 1.5: +0.006R, PF 1.02.
  - 11 of 15 eligible markets were slightly positive, the largest GBPUSD at +0.07R; XPTUSD (−0.17R) and XAGUSD (−0.13R) lost most.
- **Conclusion.** The +0.045R gross one-bar result of §7r does not survive as a tradable daily-hold strategy after costs, and this series closes that lead.

**Registry.** 85 experiments, **0 accepted**.

---

## 7t. FX carry with modelled swaps and outside interest rates (2026-09-15) — 1 of 1 rejected

**Why.** After 85 price-only experiments, the next test needed information the chart does not contain. The user approved an outside source for non-price data ("yes", 2026-09-15). Price data still comes only from cTrader.

**Outside data** (`app/quant/external_rates.py`).
- **Source.** FRED (Federal Reserve Bank of St. Louis), OECD 3-month interbank rates, monthly averages, % a year:
  - `IR3TIB01{US,EZ,GB,JP,CH,AU,NZ,CA}M156N`.
- **Handling.** Fetched into memory on every run, nothing stored. The SHA-256 fingerprint is pinned in the preregistration.
- **Coverage, checked 2026-09-15.** All eight have values every month since 2010, except:
  - USD April 2020 is missing;
  - EUR and GBP end at January 2026; the others run to May or June 2026.
- **As-of rule.** A month's value counts as known two months later (publication lag). A date uses the latest known month. A rate more than three months old is unavailable. So:
  - EURUSD and GBPUSD stop signalling after April 2026;
  - the missing April 2020 is bridged by March only while that is at most three months old;
  - nothing is filled in.

**Swaps, never modelled before** (`app/quant/swap_model.py`).
- **Why it matters.** Carry's return is mostly the nightly interest, so a spot-only backtest would measure the wrong thing.
- **Model.**
  - Annual % = base rate − quote rate − markup for a long (the mirror for a short).
  - USD per rollover = notional × % / 360: units × price for XXXUSD, units for USDXXX.
- **Broker schedule, read from the broker** (`hafnot_fetch_symbol_specs.py` now saves these fields):
  - swaps are quoted in pips, charged every 24 hours at 21:00 UTC, with no separate weekend charge;
  - the triple-swap day is **Wednesday for six pairs and Thursday for USDCAD**.
- **Markup per pair.** From the broker's current swap_long and swap_short: −(long + short) / 2, as % a year at the last daily close.
  - Cross-check on 14 Sep: the broker's swaps imply base−quote differentials close to FRED's latest rates (AUDUSD +0.63% vs +0.69%, USDCAD +1.47% vs +1.50%, NZDUSD −0.90% vs −1.09%). Markups were 0.7–1.5% a year, highest for USDJPY and USDCHF.
- **Nights without rates.** A night without an as-of rate is charged the markup only.
- **Rollover counting.**
  - Entries at a daily close execute after that rollover.
  - A trade pays each later close before its exit bar, plus the exit bar's close for time and end-of-data exits.
  - The cost model now keeps the engine's exit reason for this.
- **Limitations.**
  - One measured markup is applied to all history; the broker's historical swaps are not available.
  - 3-month interbank rates stand in for the broker's overnight funding rates.

**Strategy** (`fx-carry`, series `portfolio-d1-v6-carry`).
- **Rules.** FX7, daily bars. BUY a pair when as-of base − quote ≥ `min_diff_pct`; SELL when ≤ −`min_diff_pct`. Exit after 21 bars (about a month) or at a `stop_atr` × ATR stop; qualifying pairs are re-entered.
- **Grid:** min differential 0.5/1.0/2.0% × stop 3/5/8 ATR.
- **Settings as §7p** (broker commissions, 22–23 UTC execution costs, and the other gates), plus the multiple-testing guard.

**Checks before and after the run.**
- **Specs re-fetched** on 15 Sep with the new swap fields.
- **Markups used**, % a year: EURUSD 0.90, GBPUSD 0.71, AUDUSD 0.78, NZDUSD 0.87, USDJPY 1.47, USDCHF 1.37, USDCAD 0.74.
- **The trade-building change altered nothing.** After it (swap fields, exit reason), the recorded `portfolio-d1-v1` training results still reproduce exactly: Donchian 257 trades, −0.023R; time-series momentum 698 trades, −0.029R.

**Results.** Rejected at TRAIN (2011-01-01 to 2018-11-06), so validation, walk-forward and locked data were never used.

| min differential \ stop | 3 ATR | 5 ATR | 8 ATR |
|---|---|---|---|
| 0.5% | 464 trades, −0.065R | 327 trades, −0.048R | 82 trades, −0.063R |
| 1.0% | 288 trades, −0.039R | 215 trades, −0.011R | 42 trades, −0.092R |
| 2.0% | 169 trades, −0.035R | 127 trades, **−0.008R**, PF 0.97, 53% winners | 30 trades, −0.035R |

- **Combinations:** 0 of 9 were profitable (NO_EDGE).
- **Markets:** only 3 pairs had at least 10 trades with the chosen setting, and 1 of those was positive.

**Where the result came from** (chosen setting, training slice, recomputed to match the record exactly: 127 trades, −0.0078R).

| | Swaps earned (after markup) | Price moves and trading costs | Total |
|---|---|---|---|
| All trades, about 20 nights each | **+0.031R** | −0.039R | −0.008R |
| AUDUSD (40 trades) | +0.039R | −0.157R | −0.118R |
| NZDUSD (57) | +0.028R | −0.039R | −0.011R |
| USDCHF (16) | +0.027R | +0.029R | +0.055R |
| EURUSD (8) | +0.033R | +0.268R | +0.302R |
| USDJPY (6) | +0.015R | +0.160R | +0.175R |

**What it says.**
- **The carry itself was real in this model.** Holding the higher-yielding currency earned about +0.03R a trade in swaps after the broker's markup.
- **Exchange-rate moves took more than that.** Most qualifying trades in 2011–2018 were long AUD and NZD while they fell against the dollar, which is the classic carry-crash risk. The few long-USD trades against JPY, CHF and EUR gained, but were too few to matter.
- **Interpretation, not measured.** A carry signal from the rate differential alone, held a month, did not beat price risk plus costs on seven USD pairs. A diversified cross-currency carry basket is outside the USD-pair universe available here.

**Registry.** 86 experiments, **0 accepted**.

---

## 7u. US equity index anomalies, with modelled financing and a "just buy" benchmark (2026-09-15) — 3 of 3 rejected

**Why.** The user asked for testing to continue until a real edge is found. Two of the most documented calendar and reversal effects are in US equity indices, which behave unlike FX:
- **turn of the month;**
- **short-term dips in a long-term uptrend.**

**Tradability, checked before designing.** At a $50 risk the broker's minimum position (0.1 lot, $0.10 a point) must fit inside the stop. Median daily ATR shows:
- **NAS100:** a 3-ATR stop needs $76–155 a trade from 2020 on.
- **US30:** a 3-ATR stop needs $55–192 a trade from 2016 on.
- **US500 and US2000:** a 3-ATR stop needs $5–28 a trade in every year.

Trades in NAS100 and US30 would be refused, so the series uses **US500 and US2000 only**. Its breadth gate requires both markets to have enough trades and **both** to be positive.

**Index financing, read from the broker** (specs re-fetched 15 Sep).
- **Broker figures.** Swap type PERCENTAGE: long −6.15% a year, short +1.15% a year, charged daily at 21:00 UTC, triple on **Friday**, the same for all four indices.
- **What they imply.** A 3.65% benchmark rate plus a 2.50% markup; FRED's latest USD 3-month rate is 3.77%.
- **Model** (`swap_model.IndexFinancingModel`). A long pays the as-of USD rate + 2.50%; a short earns the USD rate − 2.50%. Both are % a year of notional per rollover / 360. A night without an as-of USD rate refuses the calculation.

**Families** (daily bars, long only, exits at a fixed number of bars or a 3-ATR stop, 10R cap).

| Family | Rule | Grid |
|---|---|---|
| `index-dip-in-uptrend` | Close above its 200-day mean and below each of the previous `dip_days` closes | dip 2/3/5 days × hold 3/5/10 bars |
| `turn-of-month-long` | Buy at the close of the k-th last calendar weekday of the month; holidays not modelled | k 1/2/3 × hold 3/4/6 bars |
| `index-unconditional-long` (**benchmark**) | Buy at every close while flat | hold 3/5/10 bars × stop 2/3/4 ATR |

**How to read the results.** US indices rose strongly over 2011–2026, so a long-only rule can look profitable because the market rose. The benchmark is preregistered and counted like any strategy: a timing rule shows timing skill only if it beats the benchmark over the same slices. If the benchmark passes too, the profit is the equity risk premium, a real but different thing, with its drawdowns.

**Other settings.** Costs as §7n: 22–23 UTC execution spreads, US500 0.4 and US2000 0.3 points; broker commission $0. External rates as §7t. Walk-forward, locked slice and multiple-testing guard unchanged.

**Results.** No family reached walk-forward, so the locked 2022–2026 data was never used.

| Family | Training (2011–2018) | Validation (2018-11 to 2022-10) | Stopped at |
|---|---|---|---|
| index-dip-in-uptrend | **9 of 9 combos profitable** (PLATEAU). Chosen dip 5 days, hold 10: 139 trades, **+0.088R**, PF 1.34, 60% winners. US500 +0.111R (101 trades), US2000 +0.028R (38) | 78 trades, **+0.028R**, PF 1.08, drawdown 2.6%. US500 +0.095R (47), US2000 −0.073R (31) | VALIDATION: PF 1.08 < 1.10 and expectancy 0.028R < 0.030R |
| turn-of-month-long | 3 of 9 combos profitable (ISOLATED_PEAK). Chosen last weekday, hold 6: 127 trades, +0.054R. US500 +0.080R, US2000 −0.012R, so breadth failed | not reached | TRAIN |
| index-unconditional-long (benchmark) | 9 of 9 combos profitable (PLATEAU). Chosen hold 10, stop 4 ATR: 286 trades, +0.034R, PF 1.18 | 213 trades, **−0.020R**, PF 0.91 | VALIDATION |

**What the numbers say.**
- **Dip-in-uptrend is the closest this project has come to an edge, and it is still rejected.**
  - It was positive in every training combination.
  - It stayed positive in validation.
  - It **beat the "just buy" benchmark in both slices**: +0.088R vs +0.034R in training, +0.028R vs −0.020R in validation.
  - The chosen benchmark used a 4-ATR stop against the dip rule's fixed 3 ATR. The benchmark's 3-ATR, 10-bar combination made +0.051R in training; its validation figure exists only for the chosen combination.
  - It missed both validation thresholds narrowly, and **US2000 lost in validation**, so the edge rests on US500 alone.
- **Turn of the month did not hold across neighbouring settings or both indices** in this broker's 2011–2018 data.
- **Simply buying and holding for days lost after costs and financing in 2018–2022.** A long bias alone was not enough.
- **No changes made after seeing these results.** Rejected families are not re-tuned: dropping US2000 or relaxing a gate would be chosen after seeing validation data. The honest follow-up for the dip rule is new data. The locked 2022–2026 slice stays unused, and any later look at this idea needs a new preregistration, or forward paper trading on data that does not exist yet.

**Registry.** 89 experiments, **0 accepted**.

---

## 7v. Forward paper tracking of the index dip rule (registered 2026-09-15 07:34:52 UTC)

**Why.**
- **Where it came from.** §7u's dip-in-uptrend rule was the closest result in the project: positive in every training combination, positive in validation, and ahead of its "just buy" benchmark in both, but it missed the validation thresholds.
- **Why forward data.** Re-tuning it on data already seen would be curve-fitting. The honest test is prices that did not exist when the rule was fixed. The user chose this together with continued research.

**What was registered** (`data/research/forward/index-dip-forward-20260915.json`, written once; `--register` refuses to overwrite it):
- **Rules.** The dip rule with the parameters its preregistered selection chose (dip 5 days, hold 10 bars, 3-ATR stop, 200-day trend), and the benchmark with its chosen parameters (hold 10 bars, 4-ATR stop).
- **Markets and costs.** US500 and US2000, with the same costs, spreads and index financing as the backtest.
- **Start.** 2026-09-15 07:34:52 UTC. Only trades entered on daily bars that open after it count, and a bar must have closed.
- **Verdict rule, fixed at registration.** All four must hold:
  - at least 30 closed trades of the dip rule;
  - it passes the out-of-sample gate;
  - its forward expectancy beats the benchmark's;
  - it passes the multiple-testing guard counting 90 experiments.
- **No orders.** The only broker access is historical trendbars.

**How it runs** (`python hafnot_forward_tracker.py`).
- **Each run** fetches the bars from cTrader into memory and recomputes every forward trade from the start, so skipped days lose nothing.
- **Open trades** are shown marked at the last close but are not scored.
- **Output.** A small ledger with the bars' and rates' fingerprints is written beside the registration.
- **First run** 07:34:54 UTC: 0 trades (no bar after the start had closed); verdict COLLECTING.

**What to expect.** The dip rule traded about 12 times a year per market in backtests, so 30 closed trades take roughly 1.5 years across the two markets. Passing the guard at N = 90 needs a large average result; the report will say so plainly, pass or fail.

---

## 7w. Index VIX spike, with outside implied-volatility data (2026-09-15) — built, not run

**Status.** Built and tested, but **not preregistered or run**: the user paused, then asked to focus on forex only. Nothing about it is recorded in the registries, and it can be run later unchanged with `python hafnot_run_research_pipeline.py --series portfolio-d1-v8-vix-spike`.

**Why, and the disclosure.**
- **The idea.** Research continues alongside §7v. This test adds information the price chart does not contain: the VIX, the market's option-implied volatility.
- **Disclosure.** It was **chosen after seeing the dip-in-uptrend results on the same two indices and the same training and validation slices** (§7u). A fear spike and a price dip often coincide. It is counted in the registry and judged by the multiple-testing guard; the locked 2022–2026 slice has not been used by any index family.

**Data.**
- **cTrader's own VIX history starts only in January 2020** (1,724 daily bars), too short for training, validation, walk-forward and a locked slice.
- **So the signal uses FRED `VIXCLS` instead.** It is the CBOE close, daily from 1990: 3,979 values since 2011, with its 116 missing weekdays being US market holidays. It is fetched into memory and fingerprinted.
- **As-of rule** (`app/quant/external_daily.py`). A close dated D is known from D + 1 calendar day. A date uses the latest known close, and one more than 5 days old is unavailable.
- **What bars carry.** Each bar gets only its last 60 known values (`bar_features` "fred_daily"), never the series itself.
- **Prices** still come from cTrader.

**Rule** (`index-vix-spike`, series `portfolio-d1-v8-vix-spike`).
- **Entry.** BUY US500 or US2000 at the daily close when the latest known VIX close is at least `spike_pct` above the mean of the 20 closes before it.
- **Exit.** At the close `hold_bars` later, or at a 3-ATR stop (10R cap).
- **Grid:** spike 20/35/50% × hold 5/10/20 bars.
- **Other settings, identical to §7u:** markets, index financing, costs, both-markets breadth, walk-forward, locked slice and multiple-testing guard.

**Gold, considered and dropped.** A gold versus real-interest-rate test was considered (FRED `DFII10`, daily since 2003). §7n already verified that XAUUSD trades at a $50 risk are mostly refused below the broker's minimum lot, so it was not built.

---

## 7x. Month-end London fix flows in FX (2026-09-15) — 2 of 2 rejected

**Why.**
- **Scope.** The user asked to continue with forex only.
- **What is new.** Every earlier FX family used a single market's prices, interest rates or the calendar alone. This one uses a documented flow mechanism.
- **The mechanism.** Investors reset the currency hedges on their foreign equity holdings at month-end, largely at the WM/Reuters London 4pm fix. When US equities outperformed foreign equities that month, foreign holders of US stocks must sell dollars to stay hedged. The dollar therefore tends to weaken into the fix on the month's last trading day, and to strengthen when US equities underperformed.

**Data checks** (all from cTrader, in memory).
- **FX hourly bars.** EURUSD H1, 2011-01-01 to 2026-09-12: 97,492 bars, no gaps over 4 days, fetched in 211 s.
- **Equity index daily bars**, signal inputs only and never traded:

  | Index | Starts | Notes |
  |---|---|---|
  | US500 | 2011 | |
  | EUSTX50 | 2014-07-09 | two 6-day Christmas closures |
  | UK100 | 2014-07-17 | |
  | AUS200 | 2014-07-06 | |
  | JPN225 | 2014-07-16 | listed as `JPN225`; the name `JP225` fails |

- **Excluded currencies.**
  - CHF: SWI20 starts 2020-10-29.
  - CAD: CA60 starts 2020-04-28.
  - NZD: the broker lists no New Zealand index.
- **Data start.** 2014-08-01, the first month with a previous month-end close for every index.

**Rule** (`month-end-fix-flow`, series `portfolio-h1-v1-month-end-fix`; pairs EURUSD, GBPUSD, AUDUSD, USDJPY).
- **Day.** The last calendar weekday of the month (London date); holidays not modelled.
- **Entry.** At the close of the hourly bar ending `hours_before_fix` hours before 16:00 London (DST-aware). Compute US500 month-to-date return minus the pair's foreign index month-to-date return, in points.
  - Month-to-date returns use only daily closes completed before the bar opened (a daily bar counts as closed 24 h after it opens).
  - Above `threshold_pct` the dollar is expected to weaken: BUY XXXUSD, SELL USDJPY. Below −`threshold_pct`, the reverse.
- **Exit.** At the close of the bar ending 16:00 London, unless a 3 × ATR(24) stop is hit (10R cap).
- **Grid:** threshold 0/1/2 points × 2/4/6 hours before the fix.
- **Costs.** Worst p90 spread of 09:00–16:00 UTC from the 24-hour profile; broker commission. Trades close before the rollover, so no swaps.
- **Not modelled:** any extra widening at the fix itself beyond the profile.

**Control, preregistered and counted** (`mid-month-fix-placebo`). The identical rule on the last weekday on or before the 15th, when no month-end rebalancing happens. If the control also passes, the month-end result reflects a general link between equities and currencies, not month-end flows.

**Gates.** Unchanged, with the multiple-testing guard.

**Data fetched.** 75,362–75,405 H1 bars a pair, 2014-08-01 to 2026-09-12, plus the five indices' daily bars, all fingerprinted in the preregistrations.

**Results.** Neither family reached walk-forward, so the locked slice (2023-09 to 2026-09) was never used.

| Family | Training (2014-08 to 2020-08) | Validation (2020-08 to 2023-09) | Stopped at |
|---|---|---|---|
| month-end-fix-flow | **9 of 9 combos profitable** (PLATEAU), +0.018R to +0.101R. Chosen threshold 1 point, 4 hours: 224 trades, **+0.071R**, PF 1.29, 56% winners. GBPUSD +0.141R, USDJPY +0.091R, AUDUSD +0.059R, EURUSD −0.006R | 116 trades, **−0.217R**, PF 0.48, 36% winners, drawdown 15.2%. Every pair lost: GBPUSD −0.327R, USDJPY −0.231R, AUDUSD −0.165R, EURUSD −0.132R | VALIDATION: PF, expectancy and drawdown |
| mid-month-fix-placebo (control) | **0 of 9 combos profitable**, −0.049R to −0.134R; all four pairs negative | not reached | TRAIN |

**What the numbers say.**
- **The control did its job in training.** The month-end rule made money in every combination while the identical rule on a mid-month day lost in every one, so the training profit was specific to month-end, as the flow hypothesis predicts.
- **The effect did not survive into 2020–2023; it reversed.** Every pair lost, by about a fifth of the risk per trade. A documented, well-publicised flow that later runs the other way is consistent with others trading ahead of it or with changed hedging practice, but this series cannot tell which.
- **No changes after seeing validation.** The rule is not re-tuned (no shorter windows, other thresholds or dropped pairs), and the locked slice stays unused.

**Registry.** 91 experiments, **0 accepted**.

---

## 7y. FX positioning from the CFTC Commitments of Traders (2026-09-15) — 2 of 2 rejected

**Why.** Forex only, as the user asked. Weekly hedge-fund positioning in currency futures is information discretionary FX traders watch and that no chart shows. Two opposite readings are tested; each is preregistered and counted:
1. **Crowded trades reverse.** Fade extreme positioning.
2. **Informed money persists.** Follow large changes in positioning.

**Data** (`app/quant/external_cot.py`; outside non-price data approved 2026-09-15).
- **Source.** CFTC Traders in Financial Futures, futures only: leveraged-funds net position as a fraction of open interest, (long − short) / open interest, for the CME contracts EUR 099741, GBP 096742, JPY 097741, CHF 092741, CAD 090741, AUD 232741 and NZD 112741.
- **Handling.** Fetched into memory from cftc.gov on every run and fingerprinted.
- **Checked 2026-09-15.**
  - **Coverage.** All seven have a report every week from 2011 to 2026-09-08 (52–53 a year, no gap over 8 days, no unreadable rows). Report dates are Tuesdays, or Mondays in holiday weeks.
  - **Name changes.** Market names changed over time ("BRITISH POUND STERLING" became "BRITISH POUND", "NEW ZEALAND DOLLAR" became "NZ DOLLAR"), so contracts are matched by code.
  - **Date header.** It changed in 2013, so dates are read by their value.
  - **Files before 2011.**
    - Single-year files for 2008–2009 return 404, and the 2010 file starts in July 2010.
    - Earlier years come from the `fin_fut_txt_2006_2016.zip` archive, whose dates carry a time ("1/10/2012 12:00:00 AM").
    - Single-year files take precedence where both hold a report.
  - **Real fetch through the pipeline code** (2006–2026, SHA-256 `5adf48c9…`). All seven currencies have 1,054–1,057 weekly reports from 2006-06-13 to 2026-09-08. The only gap over 8 days is NZD's 28 days in June–July 2006, long before any evaluated date. Net positions range from −0.69 to +0.74 of open interest.
- **As-of rule.** A report dated D is known from D + 6 calendar days (the following Monday); one older than 13 days is unavailable. Delayed publication during US government shutdowns (for example December 2018 to January 2019) is **not modelled**.

**Rules** (series `portfolio-d1-v9-cot-positioning`, the seven USD majors, daily bars; each bar carries only the last 160 known reports per currency).

| Family | Rule | Grid |
|---|---|---|
| `cot-crowding-reversal` | Rank the latest net position among the last 156 weeks. In the top `extreme` share, sell the currency against USD; in the bottom share, buy it | extreme 5/10/20% × hold 5/10/20 bars |
| `cot-positioning-momentum` | The change over `change_weeks` reports, divided by that change's standard deviation over the previous 104 reports. At ≥ +1 buy the currency; at ≤ −1 sell it | change 1/4/13 weeks × hold 5/10/20 bars |

**Both families.**
- **Exits.** At the close after the hold, or at a 3 × ATR(20) stop (10R cap).
- **Costs and gates.** Swaps modelled from as-of FRED rates and the broker's markups, with the triple-swap day read from the broker (as §7t). Broker commission and 22–23 UTC spreads apply. The gates include the multiple-testing guard.

**Results.** Neither family reached walk-forward, so the locked slice was never used.

| Family | Training (2011–2018) | Validation (2018-11 to 2022-10) | Stopped at |
|---|---|---|---|
| cot-crowding-reversal | 6 of 9 combos profitable (PLATEAU): extremes of 5% and 10% at +0.010R to +0.047R, 20% slightly negative. Chosen extreme 5%, hold 20 bars: 158 trades, **+0.047R**, PF 1.12. Positive: USDCHF +0.365R, GBPUSD +0.232R, AUDUSD +0.221R, USDCAD +0.210R. Negative: EURUSD −0.287R, USDJPY −0.273R, NZDUSD −0.064R | 49 trades, **−0.173R**, PF 0.61, 37% winners, drawdown 5.4%. USDCHF 23 trades −0.405R; the other pairs 1–9 trades each | VALIDATION: PF and expectancy |
| cot-positioning-momentum | **0 of 9 combos profitable** (NO_EDGE), −0.009R to −0.075R, 351–946 trades each; 2 of 7 pairs positive | not reached | TRAIN |

**What the numbers say.**
- **Following large changes in hedge-fund positioning lost in every combination.** Their weekly moves carried no tradable information for the following days or weeks in these seven pairs.
- **Fading extreme positioning looked modestly profitable in training, but the edge was uneven.**
  - Only 4 of 7 pairs were positive, and it weakened at the less extreme 20% threshold.
  - In validation it traded rarely (49 times in four years) and lost, driven by USDCHF.
  - That is too thin and too unstable to trust.
- **No changes after seeing validation.** Thresholds are not re-tuned and pairs are not dropped; the locked slice stays unused.

**Registry.** 93 experiments, **0 accepted**.- **Weekday-hour seasonality is the one clear case where costs flip the sign:** +0.045R before costs, −0.038R after. One-bar holds pay a full round trip every four hours (0.082R a trade). This is a training-slice figure for one chosen combination, not a validated edge.
- **Selection bias warning.** Any new test inspired by this table — for example the same seasonality signal held longer to spread the cost — would be chosen after looking at training data. It would have to be preregistered as a new series, counted in the registry, and judged by the multiple-testing guard like every other.

---

## 8. Final principle, restated

A strategy earns the right to trade only through evidence. On the evidence gathered,
**none has.** The honest output is `NO_TRADE`, and the system now enforces that in code
rather than relying on discipline.
