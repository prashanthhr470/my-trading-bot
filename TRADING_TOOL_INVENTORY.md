# HAFNOT — Trading Tool Inventory

**As of:** 2026-09-12
**Method:** every entry below was checked against the code and data in this
repository — a static import-graph trace of the live runtime, inspection of
data sources, and the recorded experiment results. Nothing is listed as
"useful" on reputation.

**Headline:** no tool has yet been shown to improve robust out-of-sample
performance after costs. Several have been tested and rejected — including, on
2026-09-12, four new families across 4 symbols in a pre-registered pipeline
(16 of 16 rejected; none reached the locked out-of-sample stage). Many exist only
as code that nothing calls. Most macro, news, sentiment and order-flow tools
cannot be tested historically, because the historical data does not exist in
this project — and it is not fabricated.

### Legend

| Status | Meaning |
|---|---|
| **REJECTED** | Tested on real data; did not improve results. Not used for trading. |
| **NOT PROVEN** | Tested only as part of a strategy that failed; its own contribution was never isolated. |
| **UNTESTED** | Implemented, historical data exists, but no controlled experiment has been run. |
| **FORWARD-ONLY** | Cannot be backtested honestly; can only be evaluated on data collected from now on. |
| **NO DATA** | No data source exists in the project. |
| **NOT BUILT** | Not implemented. |
| **INFRASTRUCTURE** | Supports research or safety; not a trading signal, so "improves performance" does not apply. |

---

## 1. Price action and market structure

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| Swing highs / lows | `app/core/zones.py` `find_confirmed_swings` | Yes | NOT PROVEN | Component of liquidity-sweep-fvg (rejected); never isolated |
| Break of structure / change of character | `app/core/structure.py` | Yes | NOT PROVEN | Same |
| Fair value gap | `app/quant/core_strategy.py` | Yes | NOT PROVEN | Same |
| Support / resistance, range boundaries, consolidation | old `app/*_engine.py` modules | Yes | UNTESTED | Not in any registered strategy |
| Breakout (Asian range) | `app/quant/asian_range_breakout_strategy.py` | Yes | **REJECTED** | 8 symbols: IS −$6,070, OOS −$4,184; 0/9 parameter combinations profitable |
| Failed breakout reversal | `app/quant/failed_breakout_strategy.py` | Yes | **REJECTED** | Pipeline-v1, 4 symbols: 2 stopped at TRAIN, GBPUSD at VALIDATION (PF 0.60), EURUSD at WALK_FORWARD (5 of 11 windows positive) |
| Retest, pullback continuation | — | Yes | NOT BUILT | |

## 2. Volatility

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| ATR stop buffer | `core_strategy.py` (2.5×ATR) | Yes | NOT PROVEN | v1 fixed buffer and v2 ATR buffer both negative; not a controlled comparison |
| Volatility regime (ATR percentile high/normal/low) | `app/quant/regime_lookup.py`, `app/quant/signal_filters.py` | Yes | **REJECTED** as a filter | Pipeline-v2: excluding HIGH volatility, 16 experiments, 0 accepted. It improved failed breakout in training on 3 of 4 symbols, then validation failed (PF 0.69, 0.72, one with too few trades). Report §7h |
| Compression → expansion breakout | `app/quant/volatility_breakout_strategy.py` | Yes | **REJECTED** | Pipeline-v1, all 4 symbols stopped at TRAIN (at most 3/9 combinations profitable; 0/9 on EURUSD and GBPUSD) |
| Compression as a stand-alone filter | — | Yes | NOT PROVEN | Only tested as the entry precondition above |

## 3. Trend and momentum

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| EMA trend with pullback entry | `app/forex_v2/strategy.py` | Yes | **REJECTED** | 44 trades −$462; two 9-combination sweeps, 0% profitable |
| H4 trend confluence filter | `app/quant/mtf_confluence_strategy.py` | Yes | **REJECTED** | Negative on all 4 symbols |
| Regime filter (exclude RANGE) | `regime_lookup.py` + `core_strategy.py` | Yes | **REJECTED** | Trades 12→1 IS, 1→0 OOS, no quality gain; left OFF |
| Donchian / channel breakout, acceleration, trend persistence | — | Yes | NOT BUILT | |

## 4. Mean reversion

| Tool | Status |
|---|---|
| Z-score of close vs rolling mean (`app/quant/mean_reversion_strategy.py`) | **REJECTED** — pipeline-v1: 3 symbols stopped at TRAIN; GBPUSD passed validation (65 trades, PF 1.35) then failed walk-forward (6/11 windows positive, mean OOS expectancy −0.0095R) |
| Range-edge fade in low-efficiency markets (`app/quant/range_fade_strategy.py`) | **REJECTED** — pipeline-v1: 0 of 9 combinations profitable on every symbol |
| Volatility bands, session extremes, exhaustion | NOT BUILT |

## 5. Support, resistance and liquidity

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| Previous day / week high & low | `app/core/zones.py` | Yes | NOT PROVEN | Component of the rejected sweep strategy |
| Asian session high & low | `app/core/zones.py` | Yes | NOT PROVEN | Same |
| Equal highs / lows (numeric tolerance) | `app/core/zones.py` | Yes | NOT PROVEN | Same |
| Liquidity sweep with rejection | `core_strategy.py` | Yes | **REJECTED** | 1–13 trades per split; signs flip between periods; GBPUSD 2-trade "100% win rate" became −$359 over 5 years |

## 6. Session and time of day

| Tool | Where | Status | Evidence |
|---|---|---|---|
| London / New York entry windows | `core_strategy.py`, breakout strategy, `app/quant/signal_filters.py` | **REJECTED** as a filter | Pipeline-v2 compared the four newer families with and without a liquid-hours filter: 16 experiments, 0 accepted. Training gains on GBPUSD/EURUSD failed breakout did not survive validation (PF 0.58; 14 trades). Report §7h |
| Session labels (Tokyo / London / NY / overlap) | `app/core/sessions.py` | UNTESTED | Labels only; no weekend awareness (correct for labels, not for tradeability) |
| Per-session expectancy / volatility / spread study | — | NOT BUILT | |
| **Broker trading hours** (weekends, gold's daily break, holidays) | `app/core/market_hours.py` | INFRASTRUCTURE | Built from broker schedule data; 23 tests; stops the weekend restart loop |

## 7. Spread and execution conditions

| Tool | Where | Status | Evidence |
|---|---|---|---|
| Spread, slippage, commission in backtests | `app/forex_v2/risk.py` | INFRASTRUCTURE | Spread 1.2 pips assumed, 0.1-pip adverse slippage per side, $7/lot round-turn |
| Broker-verified pip size / lot size / minimum volume | `data/broker/symbol_specs.json` | INFRASTRUCTURE | XAUUSD pip size corrected from 0.01 to the broker's 0.1 |
| Spread cap | `RiskConfig.max_spread_pips` | INFRASTRUCTURE | Enforced before sizing |
| Realized spread vs backtest assumption | `app/monitoring/degradation_monitor.py` | INFRASTRUCTURE | Monitoring check; no validated strategy exists to apply it to |
| Spread percentile / abnormal-spread entry filter | — | NOT BUILT | |
| Cost stress testing (worse spread / slippage) | — | NOT BUILT | |
| Swap | fetched in symbol specs | NOT MODELLED in backtests | |

## 8–10. Fundamentals, news and sentiment

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| Economic calendar (Forex Factory) | `app/fundamental_engine.py` | **No** | FORWARD-ONLY | Scrapes the *current week only* (`ff_calendar_thisweek.json`); no archive |
| Pair-level fundamental strength / risk | `app/fundamental_pair_engine.py`, `app/fundamental_pair_risk.py` | No | NO DATA | ~3,200 lines referenced by nothing; their input snapshots do not exist |
| News risk block (live) | `app/live/confirmation_layer.py` | No | FORWARD-ONLY | Live-only by design |
| News feed | cTrader desktop app MCP (`get_news`) | No | NO DATA in practice | Depends on the desktop app's MCP server, which was not running |
| "Sentiment" | `app/sentiment_engine.py` | No | NO DATA | A keyword counter over news headlines, not positioning or sentiment data. Some mappings are questionable for FX ("hawkish" scored negative) |
| Central-bank rates, CPI, NFP, GDP, PMI history | — | — | NO DATA | No historical macro source in the project |

## 11. Intermarket and cross-asset

| Tool | Status |
|---|---|
| Bond yields / yield differentials, VIX, equity indices, DXY, commodities | NO DATA — no external market-data client exists (only Ollama, OAuth and the calendar scraper make HTTP calls) |

## 12. Statistical features

| Tool | Status |
|---|---|
| Z-scores, autocorrelation, skew / kurtosis, percentile position as *signals* | NOT BUILT |
| Sharpe / Sortino / payoff / streaks for *evaluation* | INFRASTRUCTURE — `app/forex_v2/metrics.extended_metrics`, withheld below 30 trades |

## 13. Volume, order flow and footprint

| Tool | Where | Historically testable | Status | Evidence |
|---|---|---|---|---|
| Tick volume per bar | `volume` field in historical bars | Yes | UNTESTED | Broker tick volume, **not** exchange volume |
| Level-2 depth (bid/ask book) | `app/openapi/market/multi_symbol_market_data.py` | **No** | FORWARD-ONLY | Genuine broker book, reconstructed from quote IDs — verified on 20,000 in-hours Friday events carrying real prices and sizes. Kept only in rolling event files the storage guard trims to 32 MB each. Every depth event also re-writes the top 100 levels per side, which is most of the ~2 GB of event logs. The XAUUSD stream has no depth events for the whole 15:00 UTC hour on Friday 2026-09-11 (supervisor restarted 16:19 UTC) |
| Forward research archive (spread, depth book, decision, session, `market_open`) | `app/core/research_archive.py` | No | FORWARD-ONLY | **Never ran until 2026-09-12; now live and collecting**, capped at 500 MB. Records whether the broker market was open, and names the strategy even when a decision was blocked. Open-market depth capture is verified from the worker's code, not yet observed in archive records — the market has been closed since collection began |
| Footprint, heatmap, order-book, order-flow signal engines | `app/openapi/footprint`, `heatmap`, `orderflow`, `signals` | No | FORWARD-ONLY, code only | Referenced by nothing in the runtime |
| Executed trade volume, true delta | — | — | NO DATA | cTrader provides neither; footprint would only ever be a depth-based proxy |

## 14. Multi-timeframe analysis

| Tool | Where | Status | Evidence |
|---|---|---|---|
| Higher-timeframe context without lookahead | `H4TrendLookup`, `RegimeLookup` | INFRASTRUCTURE | Only uses bars closed strictly before the decision; tested |
| As a filter | — | **REJECTED** | See the H4 confluence and regime filter results above |

## 15. Machine learning and AI

| Tool | Where | Status | Evidence |
|---|---|---|---|
| Machine-learning models | — | NOT BUILT | Correctly deferred until a deterministic baseline shows an edge |
| LLM decision layer (Ollama) | `app/ai/*` (~5,900 lines) | UNTESTED | Removed from the live paper engine on 2026-09-12 (it was loaded but never called). Never compared against the same strategy without AI. Fails closed when unreachable (tested) |

## 16. Strategy families

| Family | Status |
|---|---|
| A. Trend continuation | REJECTED (EMA trend, H1). REJECTED (daily Donchian trend and time-series momentum, 8 symbols pooled 2011–2018 training: 1 of 18 combinations profitable, negative before costs; report §7k). REJECTED with a trailing exit too: Donchian +0.122R in 2011–2018 training but −0.058R in 2018–2022 validation; momentum failed training (report §7l) |
| B. Trend pullback | REJECTED (EMA pullback entry) |
| C. Breakout | REJECTED (Asian range) |
| D. Failed breakout | REJECTED on 4 symbols (pipeline-v1) |
| E. Mean reversion | REJECTED on 4 symbols (pipeline-v1, z-score) |
| F. Range trading | REJECTED on 4 symbols (pipeline-v1, range fade) — no profitable parameter setting on any symbol |
| G. Session-based | REJECTED (the breakout is session-based; a liquid-hours filter added to 4 families, 16 experiments, 0 accepted — report §7h) |
| H. Volatility expansion | REJECTED on 4 symbols (pipeline-v1, compression breakout) — all stopped at TRAIN |
| I. Volatility contraction | NOT PROVEN — tested only as the precondition of H |
| J. Liquidity sweep / rejection | REJECTED |
| K. Fundamental regime filter | NO DATA |
| L. Cross-market regime filter | NO DATA |

---

## Research and safety infrastructure (supports every family above)

| Component | Status |
|---|---|
| Strategy registry, experiment registry (93 experiments, 0 accepted; selection-bias report) | Built |
| Costed backtest, 3-way split with enforced locked out-of-sample | Built |
| Walk-forward | Built; generalised on 2026-09-12 to any strategy, with pluggable parameter selection |
| Parameter robustness sweeps, overfitting defense, Monte Carlo | Built |
| **Research pipeline** — pre-registered train → validation → walk-forward → locked out-of-sample, choosing parameters by neighbourhood rather than a single peak | Built 2026-09-12: `app/quant/research_pipeline.py`, run with `hafnot_run_research_pipeline.py` |
| One position per symbol in backtests | Default since 2026-09-12. Earlier results allowed overlapping positions: breakout's recorded trade counts were about 25% too high. Conclusions unchanged |
| Promotion lifecycle with backward transitions; validated-baseline gate | Built |
| Degradation monitoring | Built; nothing to monitor until a strategy validates |
| Data integrity: `clean_bars`, dataset manifest | Built 2026-09-12; 324 duplicate bars removed, zero impact on measured results (XAUUSD H1 checked) |
| Portfolio / currency-concentration limits | Built 2026-09-12 (report §7g):<br>• one paper portfolio account at the backtests' 0.5% risk<br>• at most one open position across all symbols (the safety gate's limit)<br>• a 1% same-direction currency-exposure cap, re-checked under the account lock<br>• the risk model and safety gate now receive the real account state<br>The currency cap cannot bind while only one position is allowed. Single-symbol backtests do not model cross-symbol slot contention. |
| Costed paper P&L | Built 2026-09-12: paper closes are priced by the backtests' cost model (spread, slippage, commission); uncosted opens are refused |
| Bid-bar cost model (one full spread per round trip) | Built 2026-09-14: `run_costed_backtest(bid_bars=True)`; bid-based bars verified against raw quotes. The legacy model stays the default for reproducibility |
| Measured spread profile | Built 2026-09-14: `hafnot_measure_costs.py` fetches historical BID/ASK ticks from cTrader and keeps only hourly statistics (`app/quant/cost_profile.py`). Unusable until at least 22 weekday hours are covered, unless measured for named execution hours (`--hours`), when only those hours are charged and required |
| Portfolio research pipeline (pooled symbols, breadth gate, calendar walk-forward) | Built 2026-09-14: `app/quant/portfolio_pipeline.py`, series `portfolio-d1-v1`, `-v2-trailing`, `-v3-multiasset` (report §7j–§7n) |
| Research-only instruments beyond the FX majors and gold | Built 2026-09-14 (report §7n): `app/forex_v2/instrument_specs.py` builds contract, lot and commission data for USD-quoted indices, metals and energies from the broker's symbol specs. They are registered in memory only inside the research runner and `hafnot_measure_costs.py`, never by the runtime. The paper engine refuses any symbol outside `FX_USD_MAJOR_SPECS` (`canonical_signal_adapter.py`). The DEMO order worker has no symbol list of its own; its only order sources are the paper engine and `hafnot_verify_demo_execution.py`, which trades EURUSD only. Swaps and slippage for these instruments are not modelled |
| Multiple-testing guard | Built 2026-09-14 (report §7o): `app/quant/multiple_testing.py`. A series can require the locked slice to be significant at 0.05 / (every experiment recorded), so testing many ideas cannot yield a lucky winner |
| Market-structure strategies (swing highs/lows, pullback to the higher low, break and retest) | Built 2026-09-14 (report §7o): `app/quant/market_structure.py`, `market_structure_pullback_strategy.py`, `structure_break_retest_strategy.py`; rollover-hour filter `exclude_new_york_hours`. Tested 2026-09-14 on 16 markets (series `portfolio-h4-v1-structure`): both rejected at training, 0 of 9 combinations profitable each |
| Engine speed for intraday history | Built 2026-09-15 (report §7q): strategies receive a read-only view of the visible bars instead of a copy. Verified identical on a recorded result (257 trades, −0.0235R) |
| Liquidity levels and strategies (previous day/week high and low, New York trading days, daily bias) | Built 2026-09-15 (report §7q): `app/quant/liquidity_levels.py`, `liquidity_sweep_reversal_strategy.py`, `liquidity_run_continuation_strategy.py`; series `portfolio-m15-v1-liquidity` |
| Outside interest rates (`app/quant/external_rates.py`) | Built 2026-09-15 (report §7t): OECD 3-month rates for 8 currencies from FRED, fetched into memory, fingerprinted, used as of each date after a 2-month publication lag; stale rates unavailable. Outside non-price data approved by the user 2026-09-15 |
| Swap (overnight financing) model (`app/quant/swap_model.py`) | Built 2026-09-15 (report §7t): per-pair broker markup measured from current swaps, broker triple-swap weekday, rollovers counted from exit type; used only by series that set `swap_model`. Historical broker swaps unavailable |
| Outside daily series (`app/quant/external_daily.py`) and index VIX-spike strategy | Built 2026-09-15 (report §7w): FRED VIXCLS fetched into memory, known one day after its date, bars carry a 60-value window; `index_vix_spike_strategy.py`, series `portfolio-d1-v8-vix-spike` |
| CFTC positioning data and strategies | Built 2026-09-15 (report §7y): `app/quant/external_cot.py` (TFF leveraged funds by contract code, fetched into memory, known the Monday after each report), feature `cot_positioning`, `cot_crowding_strategy.py`, `cot_momentum_strategy.py`; series `portfolio-d1-v9-cot-positioning` |
| Month-end FX fix-flow strategy and signal-only feature symbols | Built 2026-09-15 (report §7x): `month_end_fix_strategy.py`; `PortfolioConfig.feature_symbols` fetches broker symbols as signal inputs only (fingerprinted, never traded); feature `month_end_equity`; series `portfolio-h1-v1-month-end-fix` with a mid-month control |
| Forward paper tracker (`hafnot_forward_tracker.py`) | Registered 2026-09-15 07:34:52 UTC (report §7v): the index dip-in-uptrend rule and its "just buy" benchmark on US500/US2000, scored only on daily bars opening after the start, with backtest costs and financing. No orders. Verdict needs 30 closed trades, the out-of-sample gate, beating the benchmark and the multiple-testing guard (N = 90) |
| Index anomaly strategies and benchmark | Built 2026-09-15 (report §7u): `index_dip_strategy.py`, `turn_of_month_strategy.py`, `index_unconditional_long_strategy.py`; percentage-type index financing in `swap_model.py`; series `portfolio-d1-v7-index-anomalies` (US500, US2000) |
| Day-window weekday seasonality | Built 2026-09-15 (report §7s): the seasonality strategy measures `hold_bars`-bar windows (one-bar behaviour unchanged); series `portfolio-h4-v3-seasonality-day-window` holds one trading day with a 2.5-ATR stop |
| Gross-edge diagnostic (`hafnot_gross_edge_diagnostic.py`) | Built 2026-09-15 (report §7r): chosen parameters of finished portfolio series re-run on training data with preregistered costs (checked against the record) and with zero costs; touches no unused data and records nothing |
| Order flow, footprint, heatmap, depth-of-market history | NOT POSSIBLE with this data: spot FX/CFDs have no central traded volume, trendbars carry tick counts only, and the Open API has no historical depth of market |
| Time exit in the backtest engine (`exit_after_bars`) | Built 2026-09-14 (report §7p): a trade the stop or target has not closed is closed after N bars; inactive unless a signal carries it |
| Cross-market bar features (`app/quant/bar_features.py`) | Built 2026-09-14 (report §7p): `currency_strength` attaches the seven USD majors' same-day closes to copies of each bar after the preregistration check |
| Currency strength, weekday-hour seasonality, shock-day continuation strategies | Built 2026-09-14 (report §7p): series `portfolio-d1-v4-currency-strength`, `portfolio-h4-v2-seasonality`, `portfolio-d1-v5-shock-continuation`, all with the multiple-testing guard |
| Long daily history | Fetched from cTrader into memory on each run and never stored (`fetch_portfolio_data`); a fingerprint is pinned in the preregistration. Research uses 2011-01-01 to 2026-09-12, because older daily bars have six per week |
| Local quote-log size | Built 2026-09-14: each raw quote file capped at 64 MB, and the paper engine reads only each file's last 64 KB. Takes effect after a restart |
| Live-vs-backtest slippage tracking | NOT BUILT — one DEMO fill exists, but the quote at the moment of sending was not captured, so slippage is unmeasured |
| DEMO order execution | VERIFIED 2026-09-14 with one 0.01-lot EURUSD round trip: submission, fill, relative stop/target attached, position tracking, close, flat afterwards, commission $3 per lot per side. 6 defects fixed (5 before any order, 1 found by the order itself). Slippage NOT measured. Needs a `trading`-scope token (report §7m) |
| Unused code | 64 files archived 2026-09-14 to `archive_superseded/unreferenced_20260914/` with a manifest (report §7m) |

## What would most increase the chance of finding a real edge

1. ~~Build the untested, historically testable families first~~ — done 2026-09-12:
   mean reversion, compression breakout, failed breakout and range fade were
   pre-registered and tested on 4 symbols. All 16 experiments were rejected
   (report §7e). Simple price-only rules on H1 have now failed in eight designs.
2. ~~Isolate session and volatility components~~ — done 2026-09-12 as fixed
   filters on the four families: 32 experiments, 0 accepted (report §7h).
3. **Get more trades per hypothesis** (report §7i, the main finding). At the
   current per-symbol trade counts, a genuine +0.05R edge passes validation only
   about half the time, and a zero-edge strategy passes 37% of the time. Pool one
   parameter set across all costable symbols, and download longer and daily history.
4. **Test slow hypotheses with an economic reason** (daily trend-following, carry)
   once daily history exists. Carry also needs historical interest rates.
5. **Replace the uniform 1.2-pip cost assumption with measured per-symbol costs.**
   FX majors are overcharged by about 0.3–0.6 pip and gold undercharged by about
   0.6 pip (bid-based bars verified; spreads measured from broker quotes).
6. **Verify DEMO execution** (needs explicit approval) to measure real fills.
7. **Let the forward archive accumulate** before evaluating order flow or depth,
   and find a historical macro/news source or accept forward-only validation.
