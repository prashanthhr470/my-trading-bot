"""
HAFNOT paper trading results - plain-English summary.

Reads:
  - data\\journals\\multi_symbol_24x7.jsonl for the latest decision per symbol
    (so you see activity even before any trade has actually opened).
  - data\\paper\\*_account.json for equity/trade history once a symbol has
    opened at least one paper position.

Writes MY_RESULTS.html (a simple, auto-refreshing webpage) every time it
runs, in addition to printing to the terminal.

Usage:
    .venv\\Scripts\\python.exe hafnot_show_results.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAPER_DIR = ROOT / "data" / "paper"
JOURNAL_FILE = ROOT / "data" / "journals" / "multi_symbol_24x7.jsonl"
HTML_FILE = ROOT / "MY_RESULTS.html"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def latest_decisions() -> dict:
    """Most recent CYCLE event per symbol from the journal."""

    latest: dict[str, dict] = {}

    if not JOURNAL_FILE.exists():
        return latest

    try:
        with JOURNAL_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if record.get("event") != "CYCLE":
                    continue
                symbol = record.get("symbol")
                if not symbol:
                    continue
                latest[symbol] = record
    except Exception:
        pass

    return latest


def account_summaries() -> list[dict]:
    account_files = sorted(PAPER_DIR.glob("*_account.json")) if PAPER_DIR.exists() else []
    rows = []

    for path in account_files:
        symbol = path.stem.replace("_account", "").upper()
        data = load_json(path)
        if not data:
            continue

        starting = float(data.get("starting_equity", 0.0))
        equity = float(data.get("equity", starting))
        closed_trades = data.get("closed_trades", [])
        open_positions = data.get("positions", {})

        results = [t.get("result_r") for t in closed_trades if t.get("result_r") is not None]
        wins = [r for r in results if r > 0]
        win_rate = (len(wins) / len(results) * 100.0) if results else None

        rows.append({
            "symbol": symbol,
            "starting": starting,
            "equity": equity,
            "profit_loss": equity - starting,
            "trade_count": len(closed_trades),
            "win_rate": win_rate,
            "open_now": bool(open_positions),
        })

    return rows


def print_console(decisions: dict, accounts: list[dict]) -> None:

    print()
    print("=" * 78)
    print(" HAFNOT PAPER TRADING RESULTS (practice money only)")
    print("=" * 78)
    print()

    if not decisions:
        print("No activity yet - the bot hasn't completed a single analysis")
        print("cycle. If you just started it, wait a few more minutes and")
        print("try again. If it's been 10+ minutes, run:")
        print("  .\\CHECK_HAFNOT_STATUS.ps1")
        print("and check the RUNTIME HEALTH section for errors.")
        return

    print("LATEST DECISION PER SYMBOL:")
    print("-" * 78)
    print(f"{'SYMBOL':<10} {'PRICE':>12} {'DECISION':>18} {'AS OF':>25}")
    print("-" * 78)

    for symbol in sorted(decisions.keys()):
        record = decisions[symbol]
        price = record.get("ask") or record.get("bid") or 0.0
        decision = record.get("decision", "?")
        as_of = str(record.get("timestamp", ""))[:19].replace("T", " ")
        print(f"{symbol:<10} {price:>12,.5f} {decision:>18} {as_of:>25}")

    print()

    if not accounts:
        print("No paper trade has actually OPENED yet - every decision so far")
        print("has been WAIT (not enough evidence to trade). This is normal")
        print("and expected; it means the safety rules are working, not that")
        print("anything is broken. Balance is untouched at $10,000 per symbol.")
        print()
        print("Check back later - trades only happen when a real setup appears.")
        return

    print("ACCOUNT SUMMARY (only shown once a symbol has opened a trade):")
    print("-" * 78)
    print(f"{'SYMBOL':<10} {'EQUITY':>12} {'PROFIT/LOSS':>14} {'TRADES':>8} {'WIN RATE':>10} {'OPEN NOW':>10}")
    print("-" * 78)

    total_current = 0.0
    total_starting = 0.0
    total_trades = 0

    for row in accounts:
        total_current += row["equity"]
        total_starting += row["starting"]
        total_trades += row["trade_count"]
        win_rate_str = f"{row['win_rate']:.0f}%" if row["win_rate"] is not None else "N/A"
        print(
            f"{row['symbol']:<10} "
            f"${row['equity']:>10,.2f} "
            f"{'+' if row['profit_loss'] >= 0 else ''}{row['profit_loss']:>12,.2f} "
            f"{row['trade_count']:>8} "
            f"{win_rate_str:>10} "
            f"{('YES' if row['open_now'] else 'no'):>10}"
        )

    print("-" * 78)
    total_pl = total_current - total_starting
    print(f"{'TOTAL':<10} ${total_current:>10,.2f} {'+' if total_pl >= 0 else ''}{total_pl:>12,.2f} {total_trades:>8}")
    print()
    print("This is PRACTICE money only - nothing here is real cash,")
    print("and none of this reflects a proven or validated strategy yet.")

    if total_trades < 30:
        print()
        print(f"[NOTE] Only {total_trades} trade(s) closed so far - far too few")
        print("       to draw any real conclusion. Let it run much longer")
        print("       (days, not minutes) before trusting these numbers.")


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def write_html(decisions: dict, accounts: list[dict]) -> None:

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %I:%M:%S %p")

    decision_colors = {
        "BUY_CANDIDATE": "#1a7f37",
        "SELL_CANDIDATE": "#cf222e",
        "WAIT": "#6e7781",
        "NO_TRADE": "#6e7781",
    }

    rows_html = ""
    for symbol in sorted(decisions.keys()):
        record = decisions[symbol]
        price = record.get("ask") or record.get("bid") or 0.0
        decision = record.get("decision", "?")
        as_of = str(record.get("timestamp", ""))[:19].replace("T", " ") + " UTC"
        color = decision_colors.get(decision, "#6e7781")
        rows_html += (
            f"<tr><td>{_esc(symbol)}</td>"
            f"<td class='num'>{price:,.5f}</td>"
            f"<td><span class='pill' style='background:{color}'>{_esc(decision)}</span></td>"
            f"<td class='muted'>{_esc(as_of)}</td></tr>"
        )

    if not decisions:
        decisions_section = "<p class='muted'>No activity yet — check back in a few minutes.</p>"
    else:
        decisions_section = f"""
        <table>
          <thead><tr><th>Symbol</th><th>Price</th><th>Latest Decision</th><th>As Of</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        """

    if not accounts:
        accounts_section = """
        <div class="callout">
          No paper trade has opened yet — every decision so far has been WAIT.
          That means the safety rules are working correctly, not that anything
          is broken. Balance is untouched at $10,000 per symbol.
        </div>
        """
        total_line = ""
    else:
        acc_rows = ""
        total_current = 0.0
        total_starting = 0.0
        total_trades = 0
        for row in accounts:
            total_current += row["equity"]
            total_starting += row["starting"]
            total_trades += row["trade_count"]
            pl = row["profit_loss"]
            pl_class = "profit" if pl >= 0 else "loss"
            win_rate_str = f"{row['win_rate']:.0f}%" if row["win_rate"] is not None else "N/A"
            acc_rows += (
                f"<tr><td>{_esc(row['symbol'])}</td>"
                f"<td class='num'>${row['equity']:,.2f}</td>"
                f"<td class='num {pl_class}'>{'+' if pl >= 0 else ''}{pl:,.2f}</td>"
                f"<td class='num'>{row['trade_count']}</td>"
                f"<td class='num'>{win_rate_str}</td>"
                f"<td>{'Yes' if row['open_now'] else '—'}</td></tr>"
            )
        total_pl = total_current - total_starting
        total_pl_class = "profit" if total_pl >= 0 else "loss"
        accounts_section = f"""
        <table>
          <thead><tr><th>Symbol</th><th>Equity</th><th>Profit/Loss</th><th>Trades</th><th>Win Rate</th><th>Open Now</th></tr></thead>
          <tbody>{acc_rows}</tbody>
          <tfoot><tr><td>TOTAL</td><td class="num">${total_current:,.2f}</td>
          <td class="num {total_pl_class}">{'+' if total_pl >= 0 else ''}{total_pl:,.2f}</td>
          <td class="num">{total_trades}</td><td></td><td></td></tr></tfoot>
        </table>
        """
        total_line = f"<p class='muted'>Only {total_trades} trade(s) closed so far — far too few to draw any real conclusion yet.</p>" if total_trades < 30 else ""

    html = f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="20">
<title>HAFNOT Results</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; background:#f6f8fa; color:#1f2328; margin:0; padding:32px; }}
  .wrap {{ max-width: 820px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color:#6e7781; margin-bottom: 24px; }}
  .card {{ background:#fff; border:1px solid #d0d7de; border-radius:8px; padding:20px; margin-bottom:20px; }}
  table {{ width:100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align:left; padding:8px; border-bottom:2px solid #d0d7de; color:#57606a; font-size:12px; text-transform:uppercase; }}
  td {{ padding:8px; border-bottom:1px solid #eaeef2; }}
  tfoot td {{ font-weight:bold; border-top:2px solid #d0d7de; border-bottom:none; }}
  .num {{ text-align:right; font-variant-numeric: tabular-nums; }}
  .profit {{ color:#1a7f37; }}
  .loss {{ color:#cf222e; }}
  .pill {{ color:#fff; padding:3px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
  .muted {{ color:#6e7781; font-size:13px; }}
  .callout {{ background:#fff8c5; border:1px solid #d4a72c; border-radius:6px; padding:14px; font-size:14px; }}
  .banner {{ background:#ddf4ff; border:1px solid #54aeff; border-radius:6px; padding:12px 16px; font-size:13px; margin-bottom:20px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>HAFNOT Paper Trading Results</h1>
  <div class="subtitle">Practice money only — updates automatically every 20 seconds. Last updated: {generated_at}</div>

  <div class="banner">This is PRACTICE trading (fake money). Nothing here is real cash, and no strategy has been proven profitable yet.</div>

  <div class="card">
    <h2 style="font-size:16px;margin-top:0;">Latest analysis per symbol</h2>
    {decisions_section}
  </div>

  <div class="card">
    <h2 style="font-size:16px;margin-top:0;">Account summary</h2>
    {accounts_section}
    {total_line}
  </div>
</div>
</body></html>
"""

    HTML_FILE.write_text(html, encoding="utf-8")


def main() -> None:
    decisions = latest_decisions()
    accounts = account_summaries()
    print_console(decisions, accounts)
    write_html(decisions, accounts)
    print()
    print(f"[SAVED] A webpage version was also written to: {HTML_FILE}")


if __name__ == "__main__":
    main()
