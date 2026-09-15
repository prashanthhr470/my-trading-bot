"""
Keeps MY_RESULTS.html continuously up to date by regenerating it every 20
seconds, forever, until you close its window. Launched by
"See My Results.bat" - you don't need to run this directly.
"""

from __future__ import annotations

import time

import hafnot_show_results as results


def main() -> None:
    print("Updating MY_RESULTS.html every 20 seconds. Close this window to stop.")
    while True:
        try:
            decisions = results.latest_decisions()
            accounts = results.account_summaries()
            results.write_html(decisions, accounts)
        except Exception as exc:
            print(f"[WARN] Update failed: {exc}")
        time.sleep(20)


if __name__ == "__main__":
    main()
