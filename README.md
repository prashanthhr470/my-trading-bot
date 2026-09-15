# HAFNOT AI Trading Agent

An AI-assisted forex/gold trading research and paper-trading system for
cTrader (Pepperstone DEMO). This README reflects the project's actual,
verified state as of this consolidation - not aspirational status. See
`FINAL_ACCEPTANCE_REPORT.md` for the full honest PASS/FAIL breakdown.

**Live trading is disabled everywhere in this project.** `DRY_RUN`,
`PAPER_TRADING`, and related safety flags are hardcoded `True`/enforced at
process start in the canonical runtime, not just defaulted. Do not remove
these without understanding exactly what you are doing.

---

## 1. What actually works right now

- A deterministic, fail-closed decision pipeline: market data -> technical
  analysis -> AI reasoning (advisory only) -> validator -> decision gate ->
  risk management -> trade plan -> execution safety gate -> **paper-only**
  fill. Invalid or low-confidence input always resolves to WAIT/NO_TRADE.
- Real, working native cTrader OpenAPI market data (auth, 11-symbol
  subscription, Level-II depth) writing to `data\openapi\*.jsonl`.
- A 24/7 process supervisor (`hafnot_final_runtime.py`) with a Windows
  singleton lock, market-freshness watchdog, and auto-restart.
- A real backtesting/validation framework (`app\quant\`) with realistic
  spread/slippage/commission costing, in-sample/out-of-sample splitting,
  walk-forward validation, Monte Carlo trade resampling, parameter
  robustness sweeps, and a strategy promotion pipeline - all tested against
  real (not fabricated) price data. See `hafnot_research_xauusd_demo.py`.
- A storage governor that caps `data\` at 5GB and trims high-frequency
  capture files automatically.

## 2. What does NOT work yet / needs your involvement

- **Real DEMO order execution is newly built and UNVERIFIED.** No prior
  version of this project could place any order at all. A native
  implementation now exists (`app\openapi\execution\`) but has not been
  tested against a live server - you must run
  `hafnot_demo_order_smoke_test.py` yourself and confirm it works before
  trusting it for anything.
- **The AI reasoning layer depends on a local Ollama instance** at
  `http://localhost:11434` with the `qwen3:0.6b` model pulled, and on **an
  external MCP server at `http://127.0.0.1:9876/mcp/`** that this project
  does not include, build, or document the origin of - it was already
  configured in a prior session and its exact identity is unknown. Without
  it, `get_spot_prices`/`get_trendbars`/`get_account`/`get_positions`/
  `get_news` tool calls fail (gracefully - the system falls back to
  WAIT/NO_TRADE, it does not crash) but the AI reasoning layer cannot do
  real analysis. If you don't have this MCP server, you need to set one up
  yourself and confirm it exposes exactly those tool names against the
  cTrader Open API.
- **No real historical dataset exists yet for rigorous validation.** Only
  ~6 months of XAUUSD H4-and-shorter bars are bundled
  (`data\xauusd_historical_batch10.json`). Run
  `hafnot_download_historical_data.py` yourself (needs your DEMO
  connection) to build a real multi-year, multi-symbol dataset before
  trusting any walk-forward/Monte Carlo conclusion.
- **No strategy has been validated.** The promotion pipeline
  (`app\quant\promotion.py`) exists and works, but nothing has been run
  through it far enough to reach `VALIDATED`. Do not treat anything in
  this repo as a proven-profitable strategy.
- The validation/costing framework only supports symbols with USD as one
  leg (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDJPY, USDCHF, USDCAD, XAUUSD).
  GBPJPY/AUDJPY/GBPAUD (part of the paper engine's trading universe) are
  NOT yet supported by the risk/costing model - it would need a
  currency-conversion extension.

---

## 3. Prerequisites

- Windows 10/11.
- **Two Python interpreters**: 3.14 for the main system, 3.12 for the
  native cTrader worker (the `ctrader_open_api`/Twisted stack does not
  support 3.14). If you don't already have Python 3.12 installed
  separately from your main Python, install it first
  (https://www.python.org/downloads/) - just don't guess, check
  `python --version` for what you already have, and get 3.12 specifically
  if missing.
- [Ollama](https://ollama.com) installed and running, with the model
  pulled: `ollama pull qwen3:0.6b`
- A cTrader Open API application (client ID/secret) and a Pepperstone
  **DEMO** account. Create the application at
  https://openapi.ctrader.com/apps
- Whatever MCP server the AI tool layer depends on (see section 2) -
  install/configure it yourself; this project does not provide it.

## 4. Setup (Windows PowerShell)

```powershell
# 1. Extract the ZIP anywhere, then from inside the extracted folder:

# 2. Create the two virtual environments
py -3.14 -m venv .venv
py -3.12 -m venv .ctrader_venv

# 3. Install dependencies
.venv\Scripts\python.exe -m pip install -r requirements.txt
.ctrader_venv\Scripts\python.exe -m pip install -r requirements-ctrader.txt

# 4. Configure credentials
copy .env.example .env
notepad .env   # fill in CTRADER_CLIENT_ID / CTRADER_CLIENT_SECRET etc.

# 5. One-time cTrader OAuth + DEMO account authorization
.ctrader_venv\Scripts\python.exe app\openapi\auth\oauth.py
.ctrader_venv\Scripts\python.exe app\openapi\auth\account_auth.py
# Select your DEMO account when prompted. Confirm data\ctrader_authorized_account.json
# shows "isLive": false afterward.
```

## 5. Run the tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

All 61 tests should pass. This verifies risk math, paper-account
bookkeeping, decision-gate safety logic, and the validation framework -
it does NOT verify live connectivity to anything (see section 8).

## 6. Run a single dry-run pipeline cycle (no supervisor, no loop)

```powershell
.venv\Scripts\python.exe batch7_final_integration.py
```

Requires your MCP server and Ollama to be running. Prints the full
pipeline trace for one XAUUSD cycle and a final PASS/FAIL acceptance
checklist. This never places an order regardless of what it decides.

## 7. Run the research/validation demonstration

```powershell
.venv\Scripts\python.exe hafnot_research_xauusd_demo.py
```

No external dependencies needed (Ollama/MCP/cTrader connection not
required) - this runs entirely against the bundled historical data file.
Read the "HONEST CONCLUSION" section it prints; do not skip it.

To pull a real multi-year dataset yourself:

```powershell
.ctrader_venv\Scripts\python.exe hafnot_download_historical_data.py --symbol EURUSD --period H1 --days 730
```

## 8. Run the 24/7 paper-trading supervisor

```powershell
.\START_HAFNOT.ps1
```

This is the ONE primary command for normal operation. It launches the
storage governor, the native cTrader market-data worker, the **live bar
feed**, and the multi-symbol paper engine as managed child processes and
supervises them from one terminal. Requires: `.env` configured, OAuth +
account authorization completed (section 4 step 5).

Check status from a second terminal any time:

```powershell
.\CHECK_HAFNOT_STATUS.ps1
.\WATCH_HAFNOT_HEALTH.ps1    # continuous watchdog with auto-restart
.\WATCH_HAFNOT_MARKET.ps1    # live market event tail
```

`CHECK_HAFNOT_STATUS.ps1` includes a **LIVE BAR FILES** section — the bars
the strategy actually reads, with their age. If those are missing or
stale, the strategy correctly reports `WAIT` and will not trade.

Health state (`READY` / `DEGRADED` / `WAITING_FOR_DATA` / `BLOCKED` /
`ERROR` per component, including `live_bar_feed`) is written continuously
to `data\runtime\health_status.json`.

### Stopping it

```powershell
.\STOP_HAFNOT.ps1
```

Use this rather than killing the supervisor alone. The supervisor starts
its children in separate process groups, so killing only it would leave
the paper engine and market worker running as orphans — and a later
`START_HAFNOT.ps1` would then run a *second* paper engine against the
same journal and account files. `STOP_HAFNOT.ps1` stops children first,
then the supervisor, and verifies nothing is left behind.

Ctrl+C in the supervisor's own terminal also shuts children down
gracefully.

### Restarting after a code change

Editing a `.py` file does **not** affect an already-running process. To
pick up changes: `.\STOP_HAFNOT.ps1` then `.\START_HAFNOT.ps1`.

### When the market is closed

Quiet feeds during a broker-scheduled closure are expected, not a fault.
The supervisor reads each symbol's real trading schedule (fetched into
`data\broker\symbol_specs.json` by `hafnot_fetch_symbol_specs.py`). When
every quiet feed is explained by a closure — weekends, XAUUSD's daily
16:59–18:01 New York break, broker holidays — it logs:

```
[MARKET CLOSED] Broker schedule explains every quiet feed - holding, not restarting: ...
```

at most once every 30 minutes, and restarts nothing. Starting HAFNOT while
markets are closed prints:

```
[PASS] ALL WATCHED MARKETS CLOSED PER BROKER SCHEDULE - NOT WAITING FOR FEEDS
```

When feeds return you'll see `[MARKET OPEN] All feeds fresh again after
scheduled closure.` A feed that goes quiet while its market is **open** still
triggers a worker restart, as it should.

If you add a symbol to the market worker, re-run the spec fetcher. A symbol
with no known schedule is deliberately treated as always open, so a missing
schedule can never hide a real outage — but it would also bring back the
restart loop for that symbol while its market is closed.

```powershell
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py
```

### Running 24/7 on a PC

HAFNOT cannot run while the computer sleeps. The supervisor log will simply
go silent — no error is recorded. For unattended operation, set Windows
power settings so the machine never sleeps while plugged in.

## 8b. Research, validation and monitoring commands

```powershell
# Standardised scorecard for every registered strategy
python hafnot_show_scorecards.py

# Selection / multiple-testing bias across all recorded experiments
python -c "from app.quant.experiment_registry import *; print_selection_bias_report(selection_bias_report())"

# Forward-performance degradation report (read-only)
python hafnot_check_degradation.py

# Verify broker symbol specifications (read-only, needs .ctrader_venv)
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py
# List every instrument the broker offers, grouped by asset class (writes nothing),
# or add specs for named instruments to data\broker\symbol_specs.json
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py --list
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py --symbols US500,SPOTCRUDE

# Pre-registered research pipeline: train -> validation -> walk-forward -> locked out-of-sample.
# Every experiment's hypothesis, grid and pass criteria are written to
# data\research\preregistrations\ before it runs; finished experiments are skipped.
python hafnot_run_research_pipeline.py
python hafnot_run_research_pipeline.py --family range-fade --symbol EURUSD
# Incremental filters: each family unchanged plus ONE fixed filter (liquid hours, or no high volatility),
# then a same-combination comparison against the unfiltered run on the training slice.
python hafnot_run_research_pipeline.py --series pipeline-v2-filters
python hafnot_run_research_pipeline.py --compare-filters
# Measured per-symbol spreads from cTrader's own bid/ask tick history; only hourly statistics are kept.
# An existing profile is never overwritten (research series pin its hash). Runs under .ctrader_venv.
.ctrader_venv\Scripts\python.exe hafnot_measure_costs.py
# Only chosen UTC hours, for instruments beyond the FX majors and gold (contract data from symbol_specs.json).
.ctrader_venv\Scripts\python.exe hafnot_measure_costs.py --hours 21,22,23 --symbols EURUSD,US500,SPOTCRUDE --output data\broker\measured_costs_<date>_<name>_broker.json
# Portfolio series: one parameter set pooled across symbols on long daily history.
# Each series names the cost profile it was preregistered with.
python hafnot_run_research_pipeline.py --series portfolio-d1-v1 --preregister-only
python hafnot_run_research_pipeline.py --series portfolio-d1-v1
python hafnot_run_research_pipeline.py --series portfolio-d1-v2-trailing
# 16 markets: FX majors, gold, silver, platinum, US indices, WTI crude, natural gas. Research only - the
# instruments are registered in memory by the research run alone; the live paper engine still refuses
# every instrument outside the FX majors and gold.
python hafnot_run_research_pipeline.py --series portfolio-d1-v3-multiasset
# Trader-style market structure on H4 (pullback to the higher low; break and retest), same 16 markets.
# Its locked result must also survive the multiple-testing guard (significant after counting every experiment run).
python hafnot_run_research_pipeline.py --series portfolio-h4-v1-structure
# Idea batch (report §7p), each with the multiple-testing guard:
#   currency strength (rank 8 currencies, FX7 D1), weekday-hour seasonality (16 markets H4, one-bar holds),
#   shock-day continuation (16 markets D1, price-identified news days).
python hafnot_run_research_pipeline.py --series portfolio-d1-v4-currency-strength
python hafnot_run_research_pipeline.py --series portfolio-h4-v2-seasonality
python hafnot_run_research_pipeline.py --series portfolio-d1-v5-shock-continuation
# Liquidity levels on 15-minute bars (report §7q): stop-hunt reversal and break-retest-continue at yesterday's and
# last week's high and low, with a daily bias; 10 markets, 2019-2026. Needs several GB of free memory and time.
python hafnot_run_research_pipeline.py --series portfolio-m15-v1-liquidity
# Weekday seasonality over full-day windows, held one day (report §7s; chosen after the §7r diagnostic, disclosed).
python hafnot_run_research_pipeline.py --series portfolio-h4-v3-seasonality-day-window
# FX carry (report §7t): outside interest rates from FRED (fetched into memory; approved 2026-09-15) and modelled
# overnight swaps. Re-fetch the FX specs first so the broker's triple-swap day is known.
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py --symbols EURUSD,GBPUSD,AUDUSD,NZDUSD,USDJPY,USDCHF,USDCAD
python hafnot_run_research_pipeline.py --series portfolio-d1-v6-carry
# US500/US2000 dip-in-uptrend and turn-of-month, with a "just buy" benchmark and modelled index financing (report §7u).
.\.ctrader_venv\Scripts\python.exe hafnot_fetch_symbol_specs.py --symbols US500,NAS100,US30,US2000
python hafnot_run_research_pipeline.py --series portfolio-d1-v7-index-anomalies
# Forward paper tracking of the index dip rule and its benchmark on prices after 2026-09-15 07:34 UTC (report §7v).
# Read-only: no orders. Run any day; it recomputes every forward trade from the registered start.
python hafnot_forward_tracker.py
# US500/US2000 after VIX spikes; VIX closes from FRED (outside data, fetched into memory) (report §7w).
python hafnot_run_research_pipeline.py --series portfolio-d1-v8-vix-spike
# FX month-end London 4pm fix flows from US-vs-foreign equity performance, with a mid-month control (report §7x).
python hafnot_run_research_pipeline.py --series portfolio-h1-v1-month-end-fix
# FX positioning from CFTC Commitments of Traders (fetched into memory from cftc.gov), with modelled swaps (report §7y).
python hafnot_run_research_pipeline.py --series portfolio-d1-v9-cot-positioning
# Diagnostic, not an experiment: re-runs each finished series' chosen parameters on its TRAINING slice with the
# preregistered costs and with zero costs, to show whether strategies lose before costs or because of them.
python hafnot_gross_edge_diagnostic.py
# DEMO order-execution checks. Read-only by default; --send places ONE 0.01-lot EURUSD round trip on the DEMO account.
python hafnot_verify_demo_execution.py

# Build the clean release ZIP (refuses to run if it would leak secrets)
python hafnot_build_release_zip.py
```

**Read `RESEARCH_AND_VALIDATION_REPORT.md` before trusting any result.**

Also:
- `TRADING_TOOL_INVENTORY.md` — which trading tools are tested, rejected,
  forward-only, or blocked by data that does not exist.
- `data\historical\manifest.json` — source, range, time zone and integrity checks
  for every research dataset.
- `data\research_archive\` — forward snapshots of spread, Level-2 depth and the
  strategy's decision, collected every 5 minutes per symbol while the paper engine
  runs (capped at 500 MB). This is the only way order-flow tools can ever be
  evaluated honestly, because no historical depth data exists.
It states, with evidence, that no strategy has yet passed validation and
that the system therefore returns `NO_TRADE` by design.

## 9. DEMO order execution smoke test (only when you're ready)

Read `hafnot_demo_order_smoke_test.py`'s docstring first. This places one
real (tiny) order on your DEMO account and immediately closes it, to
verify the order round-trip actually works. It does nothing unless you
explicitly set `DEMO_ORDER_EXECUTION_ENABLED=true` in `.env` first, and it
independently refuses to run against any non-DEMO account regardless of
that flag.

```powershell
.venv\Scripts\python.exe hafnot_demo_order_smoke_test.py
```

## 10. Project structure

```
app\                       Core pipeline modules
  agent\                   AI orchestration (orchestrator, tool registry, ctrader_tools)
  ai\                      AI provider (Ollama/Qwen3), validator, decision gate
  ctrader\                 MCP-based broker/data client (spot, trendbars, symbol specs)
  openapi\                 Native cTrader OpenAPI (auth, market data, execution, orderflow)
  paper\                   Paper trading engine and account bookkeeping
  forex_v2\                Tested, broker-independent risk/strategy/metrics building blocks
  quant\                   Backtesting, IS/OOS, walk-forward, Monte Carlo, robustness, promotion
  backtest\                Base anti-lookahead OHLC replay engine
  core\                    Data quality, kill switch, session awareness
  monitoring\              Health status reporting
  *.py                     Market structure, liquidity, S/R, fundamentals, risk, execution safety, trade plan

data\                      Runtime/journal/capture data (mostly gitignored)
tests\                     Automated pytest suite
archive_superseded\        Alternate launchers and the standalone ai_intelligence
                           subsystem kept for reference, NOT part of the canonical
                           runtime (see FINAL_ACCEPTANCE_REPORT.md for why)

hafnot_final_runtime.py            Canonical 24/7 supervisor (entry point)
hafnot_ctrader_worker.py           Spawns the native market-data engine
hafnot_storage_guard.py            Disk usage governor
batch7_final_integration.py        Single-cycle pipeline (FinalAgentPipeline)
hafnot_research_xauusd_demo.py     Validation framework demonstration
hafnot_download_historical_data.py Historical data downloader
hafnot_demo_order_smoke_test.py    DEMO order execution verification
START_HAFNOT.ps1 / CHECK_HAFNOT_STATUS.ps1 / WATCH_HAFNOT_*.ps1   Operational scripts
```

## 11. Safety model

- The AI is advisory only. It cannot bypass the decision gate, risk
  management, or execution safety gate - those are deterministic Python
  and structurally cannot be skipped (see `app\ai\decision_gate.py`,
  `app\execution_safety.py`).
- `DRY_RUN=True` is enforced with a hard `RuntimeError` if anything tries
  to set it otherwise (`app\agent\agent_runtime.py`, `batch7_final_integration.py`).
- Real order execution (`app\openapi\execution\`) requires an explicit,
  separate opt-in (`DEMO_ORDER_EXECUTION_ENABLED=true`) that the 24/7
  paper loop never sets on its own, plus an independent check that refuses
  to run against any account flagged `isLive=true`.
- A kill switch (`app\core\kill_switch.py`) exists: an operator can create
  `data\control\KILL_SWITCH` (any content) to immediately block new trade
  candidates; it also trips automatically after 5 consecutive paper
  losses.

## 12. If something looks wrong

Check `data\runtime\health_status.json` and `data\runtime\hafnot_final_runtime.log`
first. `WATCH_HAFNOT_HEALTH.ps1` will auto-restart the runtime if market
data goes stale for more than 15 minutes. See `FINAL_ACCEPTANCE_REPORT.md`
for a full list of known gaps and what still needs your verification.
