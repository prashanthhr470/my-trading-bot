from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.core import process_tree
from app.core.market_hours import assess_stale_feeds, open_symbols
from app.monitoring.health import HealthMonitor

HEALTH = HealthMonitor()

# Market-closure tracking. Quiet feeds during a broker-scheduled closure
# (weekends, XAUUSD's daily break, holidays) are expected, not an outage:
# they are logged once on entry, then at most every
# MARKET_CLOSED_LOG_INTERVAL_SECONDS, instead of triggering a worker
# restart every ~100 seconds as they previously did.
market_closed_logged = False
last_market_closed_log = 0.0
MARKET_CLOSED_LOG_INTERVAL_SECONDS = 1800


# ======================================================================
# HAFNOT FINAL SINGLE SUPERVISOR
# ======================================================================

ROOT = Path(__file__).resolve().parent

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

CTRADER_WORKER = ROOT / "hafnot_ctrader_worker.py"

PAPER_ENGINE = (
    ROOT
    / "app"
    / "paper"
    / "multi_symbol_paper.py"
)

STORAGE_GUARD = ROOT / "hafnot_storage_guard.py"

# Supplies the CLOSED OHLC bars the decision pipeline needs (see
# hafnot_live_bar_feed.py's docstring for why neither the live M1
# trendbar stream nor the desktop app's MCP server can do this). Runs
# under .ctrader_venv, like the market worker.
LIVE_BAR_FEED = ROOT / "hafnot_live_bar_feed.py"
CTRADER_PYTHON = ROOT / ".ctrader_venv" / "Scripts" / "python.exe"

RUNTIME_DIR = ROOT / "data" / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

LOG = RUNTIME_DIR / "hafnot_final_runtime.log"

# ======================================================================
# GRACEFUL SHUTDOWN
# ======================================================================

shutdown_requested = False


def request_shutdown(signum, frame) -> None:

    global shutdown_requested

    shutdown_requested = True

    print()
    print("=" * 78)
    print(" HAFNOT SHUTDOWN REQUESTED")
    print("=" * 78)
    print()
    print("[SHUTDOWN] Waiting for supervisor cleanup...")
    print()


# ======================================================================
# MARKET HEALTH
# ======================================================================

MARKET_STARTUP_TIMEOUT_SECONDS = 120

# A feed is considered stale only if its event file has not changed
# for this long. This is intentionally conservative.
MARKET_STALE_SECONDS = 90

MARKET_HEALTH_CHECK_SECONDS = 10


# ======================================================================
# HARD SAFETY
# ======================================================================

os.environ["PYTHONPATH"] = str(ROOT)

os.environ["DRY_RUN"] = "true"
os.environ["PAPER_TRADING"] = "true"
os.environ["LIVE_EXECUTION"] = "false"
os.environ["BROKER_ORDERS"] = "0"
os.environ["AI_DIRECT_EXECUTION"] = "false"
os.environ["READ_ONLY"] = "true"


# ======================================================================
# SINGLETON
# ======================================================================

MUTEX_NAME = "Global\\HAFNOT_SINGLE_RUNTIME_MUTEX"

_kernel32 = ctypes.windll.kernel32

_mutex = _kernel32.CreateMutexW(
    None,
    False,
    MUTEX_NAME,
)

if not _mutex:
    raise RuntimeError("Unable to create HAFNOT runtime mutex.")

ERROR_ALREADY_EXISTS = 183

if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:

    print("=" * 78)
    print(" HAFNOT RUNTIME ALREADY RUNNING")
    print("=" * 78)
    print()
    print("Another HAFNOT runtime owns the singleton lock.")
    print("This instance will exit without launching anything.")
    print()

    sys.exit(0)


# ======================================================================
# VALIDATION
# ======================================================================

if not PYTHON.exists():
    raise RuntimeError(f"Main Python missing: {PYTHON}")

if not CTRADER_WORKER.exists():
    raise RuntimeError(f"cTrader worker missing: {CTRADER_WORKER}")

if not PAPER_ENGINE.exists():
    raise RuntimeError(f"Paper engine missing: {PAPER_ENGINE}")


# ======================================================================
# ENVIRONMENT
# ======================================================================

CHILD_ENV = os.environ.copy()

CHILD_ENV["PYTHONPATH"] = str(ROOT)

CHILD_ENV["DRY_RUN"] = "true"
CHILD_ENV["PAPER_TRADING"] = "true"
CHILD_ENV["LIVE_EXECUTION"] = "false"
CHILD_ENV["BROKER_ORDERS"] = "0"
CHILD_ENV["AI_DIRECT_EXECUTION"] = "false"
CHILD_ENV["READ_ONLY"] = "true"


# ======================================================================
# LOGGING
# ======================================================================

def log_line(text: str) -> None:

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    with LOG.open(
        "a",
        encoding="utf-8",
    ) as fp:

        fp.write(
            f"[{timestamp}] {text}\n"
        )


# ======================================================================
# SIGNAL HANDLERS
# ======================================================================

signal.signal(
    signal.SIGINT,
    request_shutdown,
)

signal.signal(
    signal.SIGTERM,
    request_shutdown,
)


# ======================================================================
# PROCESS START
# ======================================================================

def start_child(
    name: str,
    executable: Path,
    script: Path,
) -> subprocess.Popen:

    log_line(
        f"[START] {name}: {script}"
    )

    process = subprocess.Popen(
        [
            str(executable),
            "-u",
            str(script),
        ],
        cwd=str(ROOT),
        env=CHILD_ENV.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    log_line(
        f"[PASS] {name} PID={process.pid}"
    )

    return process


# ======================================================================
# PROCESS STOP
# ======================================================================

def stop_child(
    name: str,
    process: subprocess.Popen | None,
    timeout: float = 20,
) -> None:

    if process is None:
        return

    if process.poll() is not None:
        return

    log_line(
        f"[STOP] {name} PID={process.pid}"
    )

    # Snapshot the tree first: once this process is gone its children can
    # no longer be found. Stopping only the top of the cTrader worker's
    # chain left multi_symbol_market_data.py running with its own broker
    # connection (see app/core/process_tree.py).
    try:
        tree = process_tree.descendants(process.pid)
    except Exception as exc:
        tree = []
        log_line(
            f"[WARN] {name}: could not list child processes ({exc}); "
            "children may survive"
        )

    try:
        _stop_top_process(name, process, timeout)
    finally:
        try:
            leftovers = process_tree.terminate_survivors(tree)
        except Exception as exc:
            leftovers = []
            log_line(
                f"[WARN] {name}: could not stop child processes ({exc})"
            )

        if leftovers:
            log_line(
                f"[STOP] {name}: stopped {len(leftovers)} leftover child "
                "process(es): "
                + ", ".join(f"{r.exe} PID={r.pid}" for r in leftovers)
            )


def _stop_top_process(
    name: str,
    process: subprocess.Popen,
    timeout: float,
) -> None:

    try:
        process.send_signal(
            signal.CTRL_BREAK_EVENT
        )

        process.wait(
            timeout=timeout
        )

        log_line(
            f"[PASS] {name} stopped gracefully"
        )

        return

    except Exception:
        pass

    if process.poll() is None:

        log_line(
            f"[WARN] {name} did not stop gracefully; terminating"
        )

        process.terminate()

        try:
            process.wait(
                timeout=10
            )
        except subprocess.TimeoutExpired:

            log_line(
                f"[WARN] {name} did not terminate; killing"
            )

            process.kill()
            process.wait()


# ======================================================================
# MARKET SYMBOLS
# ======================================================================

required_symbols = [
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "GBPJPY",
    "AUDJPY",
    "GBPAUD",
]

event_files = {
    symbol: (
        ROOT
        / "data"
        / "openapi"
        / f"{symbol.lower()}_market_events.jsonl"
    )
    for symbol in required_symbols
}


# ======================================================================
# MARKET FRESHNESS
# ======================================================================

def event_file_mtime(
    path: Path,
) -> float | None:

    try:

        if not path.exists():
            return None

        if path.stat().st_size <= 0:
            return None

        return path.stat().st_mtime

    except OSError:
        return None


def market_freshness() -> tuple[
    bool,
    dict[str, float],
]:

    now = time.time()

    ages: dict[str, float] = {}

    healthy = True

    for symbol, path in event_files.items():

        modified = event_file_mtime(
            path
        )

        if modified is None:

            healthy = False
            ages[symbol] = float("inf")
            continue

        age = max(
            0.0,
            now - modified,
        )

        ages[symbol] = age

        if age > MARKET_STALE_SECONDS:
            healthy = False

    return healthy, ages


def fresh_symbol_count(
    restart_after: float,
    symbols: list[str] | None = None,
) -> int:

    count = 0

    for symbol, path in event_files.items():

        if symbols is not None and symbol not in symbols:
            continue

        modified = event_file_mtime(
            path
        )

        if (
            modified is not None
            and modified >= restart_after
        ):
            count += 1

    return count


def wait_for_fresh_market_data(
    ctrader: subprocess.Popen,
    started_after: float,
    symbols: list[str] | None = None,
) -> bool:
    """
    `symbols`: which feeds must be fresh. None - the default, used by both
    startup and outage recovery - means every required symbol whose market
    is not positively closed per the broker schedule. Waiting on a feed the
    broker has closed (XAUUSD during its daily break, or every feed at the
    weekend) would otherwise either time out and crash the supervisor, or
    be falsely satisfied by the reconnect burst the worker writes into the
    event files.
    """

    target = (
        open_symbols(required_symbols)
        if symbols is None
        else list(symbols)
    )

    if not target:

        log_line(
            "[INFO] No open markets to wait for - broker schedule shows "
            "every watched market closed."
        )

        return True

    deadline = (
        time.time()
        + MARKET_STARTUP_TIMEOUT_SECONDS
    )

    while time.time() < deadline:

        if ctrader.poll() is not None:

            raise RuntimeError(
                "cTrader worker stopped during market startup. "
                f"Exit code={ctrader.returncode}"
            )

        available = fresh_symbol_count(
            started_after,
            target,
        )

        if available == len(target):

            _, ages = market_freshness()

            if all(ages[symbol] <= MARKET_STALE_SECONDS for symbol in target):

                log_line(
                    f"[PASS] {len(target)} MARKET FEED(S) FRESH "
                    + " ".join(
                        f"{symbol}={ages[symbol]:.1f}s"
                        for symbol in target
                    )
                )

                return True

        time.sleep(2)

    return False


# ======================================================================
# MAIN
# ======================================================================

print("=" * 78)
print(" HAFNOT FINAL 24/7 PAPER RUNTIME")
print("=" * 78)
print()

print("Main Python      :", PYTHON)
print("cTrader Worker   :", CTRADER_WORKER)
print("Paper Engine     :", PAPER_ENGINE)
print()
print("Market           : MULTI-SYMBOL")
print("cTrader          : DEMO / READ-ONLY")
print("Paper Trading    : TRUE")
print("Live Execution   : FALSE")
print("Broker Orders    : 0")
print("AI Direct Exec   : FALSE")
print("Read Only        : TRUE")
print("Dry Run          : TRUE")
print()
print("Market watchdog  :", MARKET_STALE_SECONDS, "seconds")
print("Singleton        : ACTIVE")
print()
print("=" * 78)
print()


log_line("=" * 70)
log_line("HAFNOT FINAL SUPERVISOR STARTED")
log_line(f"MAIN PYTHON={PYTHON}")
log_line(f"CTRADER WORKER={CTRADER_WORKER}")
log_line(f"PAPER ENGINE={PAPER_ENGINE}")
log_line(
    f"MARKET STALE TIMEOUT={MARKET_STALE_SECONDS}s"
)


# ======================================================================
# STORAGE GOVERNOR
# ======================================================================

storage = None

if STORAGE_GUARD.exists():

    storage = start_child(
        "Storage Governor",
        PYTHON,
        STORAGE_GUARD,
    )


# ======================================================================
# START CTRADER
# ======================================================================

print("[START] cTrader supervisor")

ctrader_started_after = time.time()

ctrader = start_child(
    "cTrader Worker",
    PYTHON,
    CTRADER_WORKER,
)

print(
    "[PASS] cTrader supervisor PID =",
    ctrader.pid,
)

print()

# ======================================================================
# LIVE BAR FEED
# ======================================================================

bar_feed = None

if LIVE_BAR_FEED.exists() and CTRADER_PYTHON.exists():

    print("[START] Live bar feed")

    bar_feed = start_child(
        "Live Bar Feed",
        CTRADER_PYTHON,
        LIVE_BAR_FEED,
    )

    print("[PASS] Live bar feed PID =", bar_feed.pid)

else:

    log_line(
        "[WARN] Live bar feed NOT started (script or .ctrader_venv missing) - "
        "the paper engine will report WAIT for missing bars."
    )

    print("[WARN] Live bar feed NOT started - paper engine will WAIT on missing bars.")

print()

print(
    "[MARKET] Required symbols:",
    ", ".join(required_symbols),
)

print(
    "[WAIT] Waiting for FRESH market data..."
)


ready = wait_for_fresh_market_data(
    ctrader,
    ctrader_started_after,
)


if not ready:

    stop_child(
        "cTrader Worker",
        ctrader,
    )

    raise RuntimeError(
        f"Timed out waiting for "
        f"{len(open_symbols(required_symbols))} open-market feed(s) "
        "(closed markets per the broker schedule are not waited on)."
    )


print(
    # Honest about what was waited on: at a weekend start every market is
    # closed, nothing was waited for, and "all feeds fresh" would be false.
    (
        f"[PASS] {len(open_symbols(required_symbols))} OPEN MARKET FEED(S) FRESH"
        if open_symbols(required_symbols)
        else "[PASS] ALL WATCHED MARKETS CLOSED PER BROKER SCHEDULE - "
             "NOT WAITING FOR FEEDS"
    )
)

print()


# ======================================================================
# START PAPER ENGINE
# ======================================================================

print("[START] HAFNOT paper engine")

paper = start_child(
    "Paper Engine",
    PYTHON,
    PAPER_ENGINE,
)

print(
    "[PASS] Paper engine PID =",
    paper.pid,
)

print()

print("=" * 78)
print(" HAFNOT IS RUNNING 24/7")
print("=" * 78)
print()

print("cTrader market data : RUNNING")
print(f"{len(required_symbols)} symbols          : ACTIVE")
print("Paper engine        : RUNNING")
print(
    "Storage governor    :",
    "RUNNING" if storage else "NOT INSTALLED",
)
print("Market freshness    : ACTIVE")
print("Live execution      : FALSE")
print("Broker orders       : 0")
print()
print("Runtime log:")
print(LOG)
print()


log_line(
    f"[PASS] Paper engine PID={paper.pid}"
)


# ======================================================================
# HEALTH SUPERVISION
# ======================================================================

while not shutdown_requested:

    time.sleep(
        MARKET_HEALTH_CHECK_SECONDS
    )

    if shutdown_requested:
        break


    # --------------------------------------------------------------
    # PROCESS HEALTH
    # --------------------------------------------------------------

    if ctrader.poll() is not None:

        code = ctrader.returncode

        log_line(
            f"[FAIL] cTrader worker exited code={code}"
        )

        stop_child(
            "Paper Engine",
            paper,
        )

        raise RuntimeError(
            "cTrader worker stopped unexpectedly. "
            f"Exit code={code}"
        )


    if paper.poll() is not None:

        code = paper.returncode

        log_line(
            f"[FAIL] Paper engine exited code={code}"
        )

        raise RuntimeError(
            "HAFNOT paper engine stopped unexpectedly. "
            f"Exit code={code}"
        )


    # --------------------------------------------------------------
    # MARKET FRESHNESS
    # --------------------------------------------------------------

    market_ok, ages = market_freshness()

    stale_now = [
        symbol
        for symbol, age in ages.items()
        if age > MARKET_STALE_SECONDS
    ]

    stale_assessment = (
        assess_stale_feeds(stale_now)
        if stale_now
        else None
    )

    # True when every quiet feed is explained by a broker-scheduled
    # closure (weekend, XAUUSD's daily break, a holiday). Deliberately
    # does not `continue` - storage and health reporting below must keep
    # running during partial closures such as gold's daily hour.
    scheduled_closure = (
        stale_assessment is not None
        and not stale_assessment.requires_recovery
    )

    if scheduled_closure:

        now_seconds = time.time()

        if (
            not market_closed_logged
            or now_seconds - last_market_closed_log
            >= MARKET_CLOSED_LOG_INTERVAL_SECONDS
        ):

            log_line(
                "[MARKET CLOSED] Broker schedule explains every quiet feed "
                "- holding, not restarting: "
                + ", ".join(stale_assessment.expected_closed)
            )

            if not market_closed_logged:

                print()
                print(
                    "[MARKET CLOSED] Quiet feeds match the broker schedule "
                    "- holding, not restarting."
                )
                print()

            market_closed_logged = True
            last_market_closed_log = now_seconds

    elif market_closed_logged and not stale_now:

        log_line(
            "[MARKET OPEN] All feeds fresh again after scheduled closure."
        )

        market_closed_logged = False

    if not market_ok and not scheduled_closure:

        # Only feeds stale while their market is OPEN - or whose schedule
        # is unknown - count as an outage.
        stale = list(stale_assessment.unexpected)

        details = " ".join(
            f"{symbol}={ages[symbol]:.1f}s"
            for symbol in required_symbols
        )

        log_line(
            "[FAIL] STALE MARKET FEED "
            + details
        )

        print()
        print("=" * 78)
        print(" HAFNOT MARKET DATA STALE - NOT READY")
        print("=" * 78)
        print(
            "Stale symbols:",
            ", ".join(stale),
        )
        print()

        # Fail closed: paper processing stops first.
        stop_child(
            "Paper Engine",
            paper,
        )

        # Stop the stale bridge and restart cleanly.
        stop_child(
            "cTrader Worker",
            ctrader,
        )

        log_line(
            "[RECOVERY] Restarting cTrader worker"
        )

        restart_after = time.time()

        ctrader = start_child(
            "cTrader Worker",
            PYTHON,
            CTRADER_WORKER,
        )

        print(
            "[RECOVERY] Waiting for fresh market data..."
        )

        recovered = wait_for_fresh_market_data(
            ctrader,
            restart_after,
        )

        if not recovered:

            stop_child(
                "cTrader Worker",
                ctrader,
            )

            raise RuntimeError(
                "Market recovery failed: "
                "fresh feeds did not return."
            )

        log_line(
            "[PASS] MARKET RECOVERY COMPLETE"
        )

        print(
            "[PASS] Fresh market data recovered."
        )

        print(
            "[RECOVERY] Restarting paper engine..."
        )

        paper = start_child(
            "Paper Engine",
            PYTHON,
            PAPER_ENGINE,
        )

        print(
            "[PASS] Paper engine restarted "
            f"PID={paper.pid}"
        )

        continue


    # --------------------------------------------------------------
    # STORAGE HEALTH
    # --------------------------------------------------------------

    if storage is not None:

        if storage.poll() is not None:

            code = storage.returncode

            log_line(
                f"[WARN] Storage governor exited code={code}"
            )

            storage = None


    # --------------------------------------------------------------
    # HONEST HEALTH STATUS (written for CHECK_HAFNOT_STATUS.ps1 / any
    # external tool to read without importing this process)
    # --------------------------------------------------------------

    HEALTH.report(
        "ctrader_worker",
        "READY" if ctrader.poll() is None else "ERROR",
    )
    HEALTH.report(
        "paper_engine",
        "READY" if paper.poll() is None else "ERROR",
    )
    HEALTH.report(
        "live_bar_feed",
        "READY" if (bar_feed is not None and bar_feed.poll() is None) else "DEGRADED",
        "not started" if bar_feed is None else "",
    )
    HEALTH.report(
        "storage_governor",
        "READY" if (storage is None or storage.poll() is None) else "DEGRADED",
        "not installed" if storage is None else "",
    )
    HEALTH.report(
        "market_data_freshness",
        "READY" if market_ok else "WAITING_FOR_DATA",
        " ".join(f"{s}={ages[s]:.1f}s" for s in required_symbols),
    )

    try:
        HEALTH.write()
    except Exception as exc:
        log_line(f"[WARN] Could not write health status: {exc}")

    # --------------------------------------------------------------
    # HEALTH LOG
    # --------------------------------------------------------------

    health_text = (
        f"[HEALTH {time.strftime('%H:%M:%S')}] READY\n"
        f"cTrader={ctrader.pid} | "
        f"Paper={paper.pid} | "
        f"Storage={storage.pid if storage else 'none'}\n"
        + " ".join(
            f"{symbol}={ages[symbol]:.1f}s"
            for symbol in required_symbols
        )
    )

    print()
    print(health_text)
    print()

    log_line(
        f"[HEALTH] "
        f"cTrader={ctrader.pid} "
        f"paper={paper.pid} "
        f"storage={storage.pid if storage else 'none'} "
        + " ".join(
            f"{symbol}={ages[symbol]:.1f}s"
            for symbol in required_symbols
        )
    )


# ======================================================================
# GRACEFUL CLEANUP
# ======================================================================

print()
print("[STOP] Paper Engine")

stop_child(
    "Paper Engine",
    paper,
)

print("[STOP] cTrader Worker")

stop_child(
    "cTrader Worker",
    ctrader,
)

if bar_feed is not None:

    print("[STOP] Live Bar Feed")

    stop_child(
        "Live Bar Feed",
        bar_feed,
    )

if storage is not None:

    print("[STOP] Storage Governor")

    stop_child(
        "Storage Governor",
        storage,
    )

log_line(
    "[PASS] All HAFNOT child processes stopped"
)

print()
print("[PASS] All HAFNOT child processes stopped")
print("[EXIT] HAFNOT supervisor stopped safely")
print()


