from __future__ import annotations

import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# ============================================================
# HARD HAFNOT STORAGE LIMIT
# ============================================================

MAX_BYTES = 5 * 1024 * 1024 * 1024

# Start cleanup before reaching the hard ceiling.
SOFT_LIMIT = 4.50 * 1024 * 1024 * 1024

# Cleanup target.
TARGET_LIMIT = 3.50 * 1024 * 1024 * 1024

# Files that contain valuable permanent intelligence.
PROTECTED_DIRS = {
    "ai",
    "journals",
    "paper",
    "performance",
}

# Files that must never be touched by this guard.
PROTECTED_NAMES = {
    "account.json",
}

# Disposable high-frequency market data.
EVENT_SUFFIX = "_market_events.jsonl"

# Keep the latest portion of each raw event file.
RAW_KEEP_BYTES = 32 * 1024 * 1024

# Raw event files are read only for their newest quote (app/paper/market_snapshot.py)
# and their modification time (the supervisor and status scripts). Spreads now come
# from broker tick history (hafnot_measure_costs.py), so a file is trimmed as soon as
# it passes this size instead of every file growing until data/ reaches the soft
# limit (they grew about 1.4 GB per trading day together).
RAW_TRIM_TRIGGER_BYTES = 64 * 1024 * 1024

# Logs are disposable.
LOG_RETENTION_SECONDS = 7 * 24 * 60 * 60


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def total_size() -> int:
    total = 0

    if not DATA.exists():
        return 0

    for p in DATA.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass

    return total


def is_protected(path: Path) -> bool:
    try:
        rel = path.relative_to(DATA)
    except ValueError:
        return True

    parts = {p.lower() for p in rel.parts}

    if parts & PROTECTED_DIRS:
        return True

    if path.name in PROTECTED_NAMES:
        return True

    # Never touch Python/source/config files.
    if path.suffix.lower() in {
        ".py",
        ".env",
        ".db",
        ".sqlite",
        ".sqlite3",
    }:
        return True

    return False


def trim_event_file(path: Path) -> None:
    """
    Keep only the newest RAW_KEEP_BYTES from a market event file.

    We retain complete JSONL records by finding the first newline
    after the byte boundary.
    """
    try:
        size = path.stat().st_size

        if size <= RAW_KEEP_BYTES:
            return

        with path.open("rb") as f:
            f.seek(max(0, size - RAW_KEEP_BYTES))

            # Discard partial first record.
            f.readline()

            data = f.read()

        if not data:
            return

        tmp = path.with_suffix(path.suffix + ".tmp")

        with tmp.open("wb") as f:
            f.write(data)

        try:
            os.replace(tmp, path)
        except PermissionError:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def delete_old_disposable_files(required_bytes: int) -> int:
    """
    Delete oldest disposable files until enough space is recovered.
    """
    candidates = []

    if not DATA.exists():
        return 0

    now = time.time()

    for p in DATA.rglob("*"):
        if not p.is_file():
            continue

        if is_protected(p):
            continue

        try:
            stat = p.stat()
        except OSError:
            continue

        # Raw market events are handled by trimming first.
        if p.name.endswith(EVENT_SUFFIX):
            continue

        age = now - stat.st_mtime

        # Logs older than 7 days are disposable.
        if "log" in p.name.lower() and age >= LOG_RETENTION_SECONDS:
            candidates.append((stat.st_mtime, stat.st_size, p))

        # Temporary/cache files are disposable.
        elif p.suffix.lower() in {
            ".tmp",
            ".cache",
            ".bak",
        }:
            candidates.append((stat.st_mtime, stat.st_size, p))

    candidates.sort(key=lambda x: x[0])

    recovered = 0

    for _, size, path in candidates:
        if recovered >= required_bytes:
            break

        try:
            path.unlink()
            recovered += size
            print(f"[STORAGE] Deleted: {path}")
        except OSError:
            pass

    return recovered


def enforce_storage() -> None:
    for p in DATA.rglob(f"*{EVENT_SUFFIX}") if DATA.exists() else ():
        if p.is_file() and file_size(p) > RAW_TRIM_TRIGGER_BYTES:
            trim_event_file(p)

    current = total_size()

    print(
        f"[STORAGE] HAFNOT data usage: "
        f"{current / (1024**3):.3f} GB / 5.000 GB"
    )

    # Trim every active high-frequency event file.
    if current >= SOFT_LIMIT:
        for p in DATA.rglob(f"*{EVENT_SUFFIX}"):
            if p.is_file():
                trim_event_file(p)

        current = total_size()

    # If still above target, delete disposable files.
    if current >= SOFT_LIMIT:
        required = int(current - TARGET_LIMIT)

        recovered = delete_old_disposable_files(required)

        if recovered:
            current = total_size()

    # Emergency protection.
    #
    # If something other than our normal data policy causes the
    # directory to approach 5 GB, aggressively trim raw events.
    if current >= MAX_BYTES * 0.95:
        for p in DATA.rglob(f"*{EVENT_SUFFIX}"):
            if p.is_file():
                trim_event_file(p)

        current = total_size()

    print(
        f"[STORAGE] After cleanup: "
        f"{current / (1024**3):.3f} GB / 5.000 GB"
    )


def main() -> None:
    print("=" * 64)
    print(" HAFNOT STORAGE GOVERNOR")
    print(" HARD LIMIT = 5 GB")
    print("=" * 64)

    while True:
        try:
            enforce_storage()
        except Exception as exc:
            print(f"[STORAGE ERROR] {type(exc).__name__}: {exc}")

        time.sleep(60)


if __name__ == "__main__":
    main()
