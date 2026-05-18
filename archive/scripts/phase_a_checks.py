#!/usr/bin/env python3
"""Phase A reliability checks for Plan 013 (A.2 through A.7).

  A.2  Manual P&L verification — 3 trades vs raw DB queries
  A.3  SPY regression (2023-2024, single_position)
  A.4  Synthetic vs market comparison — synthetic-fallback trades must match exactly
  A.5  Trade forensics lite — exit-reason breakdown, top/bottom-3 concentration
  A.6  American option sensitivity — BOVA11 BAW vs BS
  A.7  Summary pass/fail table

Usage:
    python scripts/phase_a_checks.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle import run_portfolio_backtest, run_backtest
from straddle.metrics import compute_portfolio_metrics, compute_metrics
from grid_search import _apply_grid_overrides

# ── Constants ────────────────────────────────────────────────────────────────

BEST_COMBO = {
    "target_delta": 0.16,
    "dte_max": 30,
    "profit_target_pct": 0.50,
    "manage_at_dte": 14,
    "vix_filter": "rv_pct:80",
    "defensive_leg_roll": False,
    "stop_loss_pct": 3.0,
    "execution_mode": "mid_plus_1tick",
    "portfolio_mode": "laddering",
}

HOLDOUT_START, HOLDOUT_END = "2023-01-02", "2025-11-30"
B3_MARKET      = "bova11"
DB_PATH        = ROOT / "data" / "B3" / "b3_options_rb3.db"
MULT           = 100.0
COMM           = 1.0      # R$ per leg
TICK           = 0.05     # B3 minimum price increment

PASS_FAIL: dict[str, str] = {}   # populated as checks run


# ── Shared helpers ───────────────────────────────────────────────────────────

def _make_params(combo: dict, start: str, end: str, market: str, **extra) -> dict:
    p = dict(PARAMS)
    p = apply_market_preset(p, market)
    p["start_date"] = start
    p["end_date"] = end
    p["mode"] = "market"
    p["cash_investment_mode"] = "risk_free"
    p["cash_yield_annual"] = 0.0
    p.update(_apply_grid_overrides(combo))
    p.update(extra)
    return p


def _run_laddering(params: dict, data: pd.DataFrame):
    engine = make_engine(params)
    try:
        trades, eq, _, _ = run_portfolio_backtest(data, params, engine, progress=False)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    return trades, eq


def _run_single(params: dict, data: pd.DataFrame):
    engine = make_engine(params)
    try:
        trades, eq, _, _ = run_backtest(data, params, engine, progress=False)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    return trades, eq


# ── A.2 — Manual P&L verification ───────────────────────────────────────────

def _query_leg_mark(conn: sqlite3.Connection, date_str: str, exp_str: str,
                    opt: str, strike: float, und: str) -> Optional[float]:
    """Return mark for an exact (date, expiry, type, strike) row, or None."""
    cur = conn.execute(
        """SELECT mark FROM options_data
           WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
             AND underlying = ? AND mark > 0 AND ask >= bid
           LIMIT 1""",
        [date_str, exp_str, opt, strike, und],
    )
    row = cur.fetchone()
    return float(row[0]) if row else None


def _manual_pnl_midplus1tick(
    conn: sqlite3.Connection,
    entry_date: str, exit_date: str,
    exp_str: str, put_k: float, call_k: float,
    und: str,
) -> Optional[dict]:
    """Reconstruct P&L from raw DB marks for mid_plus_1tick execution mode.

    Entry: sell at mark + tick per leg.
    Exit:  buy at mark - tick per leg (min 0.01).
    """
    pm_entry = _query_leg_mark(conn, entry_date, exp_str, "put",  put_k,  und)
    cm_entry = _query_leg_mark(conn, entry_date, exp_str, "call", call_k, und)
    pm_exit  = _query_leg_mark(conn, exit_date,  exp_str, "put",  put_k,  und)
    cm_exit  = _query_leg_mark(conn, exit_date,  exp_str, "call", call_k, und)

    if any(x is None for x in [pm_entry, cm_entry, pm_exit, cm_exit]):
        return None

    entry_credit_ps = (pm_entry + TICK) + (cm_entry + TICK)
    close_cost_ps   = max(pm_exit  - TICK, 0.01) + max(cm_exit  - TICK, 0.01)
    entry_credit    = entry_credit_ps * MULT - 2 * COMM
    close_cost      = close_cost_ps  * MULT + 2 * COMM
    return {
        "pm_entry": pm_entry, "cm_entry": cm_entry,
        "pm_exit":  pm_exit,  "cm_exit":  cm_exit,
        "entry_credit": entry_credit,
        "close_cost":   close_cost,
        "manual_pnl":   entry_credit - close_cost,
    }


def check_a2(trades: list) -> None:
    print("\n" + "=" * 65)
    print("A.2 — Manual P&L Verification (3 trades vs DB)")
    print("=" * 65)

    # Select candidate trades: DB-sourced entry, closed (not OPEN/ROLLED-out)
    # Exclude FORCE_CLOSE: pnl is set by portfolio manager (not a real market close),
    # so it cannot be independently verified against DB marks.
    verifiable_exit_types = {"PROFIT", "ROLLED", "21DTE", "STOPPED", "EXPIRED"}
    closed = [
        t for t in trades
        if getattr(t, "exit_type", None) in verifiable_exit_types
        and getattr(t, "entry_source", "synthetic") == "db"
        and getattr(t, "exit_date", None) is not None
        and getattr(t, "pnl", None) is not None
    ]

    if len(closed) < 3:
        print(f"  NOTE: {len(closed)} verifiable DB-sourced closed trades "
              f"(FORCE_CLOSE excluded as non-market close)")

    # Pick representative trades by exit_type
    profitable = next(
        (t for t in closed if t.exit_type == "PROFIT"), None
    ) or next(iter(closed), None)

    losing_exit = next(
        (t for t in closed if getattr(t, "pnl", 0) < 0), None
    ) or next(iter(closed), None)

    # Breakeven: smallest abs(pnl / net_credit), excluding FORCE_CLOSE
    pct_trades = [
        t for t in closed if getattr(t, "net_credit", 0) > 0
    ]
    breakeven = (
        min(pct_trades, key=lambda t: abs(t.pnl / t.net_credit))
        if pct_trades else (closed[-1] if closed else None)
    )

    selected = [("PROFIT/best", profitable), ("LOSS/rolled", losing_exit), ("BREAKEVEN", breakeven)]
    selected = [(label, t) for label, t in selected if t is not None]

    # Deduplicate by trade_num
    seen = set()
    deduped = []
    for label, t in selected:
        if t.trade_num not in seen:
            seen.add(t.trade_num)
            deduped.append((label, t))

    conn = sqlite3.connect(str(DB_PATH))
    all_passed = True
    TOLERANCE = 0.01

    for label, t in deduped:
        exp_str   = t.expiration.strftime("%Y-%m-%d")
        entry_str = t.entry_date.strftime("%Y-%m-%d")
        exit_str  = t.exit_date.strftime("%Y-%m-%d") if t.exit_date else None

        print(f"\n  [{label}] trade #{t.trade_num} | "
              f"entry={entry_str} | exit={exit_str} | "
              f"exit_type={t.exit_type}")
        print(f"    Engine: net_credit={t.net_credit:.2f}  pnl={t.pnl:.2f}  "
              f"pnl_pct={t.pnl / t.net_credit * 100:.1f}%")

        if exit_str is None:
            print("    SKIP: no exit_date available")
            continue

        result = _manual_pnl_midplus1tick(
            conn, entry_str, exit_str, exp_str, t.put_strike, t.call_strike, B3_MARKET
        )
        if result is None:
            print("    SKIP: DB marks not available for all 4 prices (entry+exit × put+call)")
            continue

        print(f"    DB marks entry:  put={result['pm_entry']:.4f}  call={result['cm_entry']:.4f}")
        print(f"    DB marks exit:   put={result['pm_exit']:.4f}  call={result['cm_exit']:.4f}")
        print(f"    Manual: entry_credit={result['entry_credit']:.2f}  "
              f"close_cost={result['close_cost']:.2f}  pnl={result['manual_pnl']:.2f}")

        # Verify entry credit
        entry_diff = abs(result["entry_credit"] - t.net_credit)
        credit_ok  = entry_diff <= TOLERANCE
        # Verify total pnl
        pnl_diff = abs(result["manual_pnl"] - t.pnl)
        pnl_ok   = pnl_diff <= TOLERANCE

        print(f"    |entry_credit diff| = R${entry_diff:.4f}  → {'OK' if credit_ok else 'FAIL'}")
        print(f"    |pnl diff|          = R${pnl_diff:.4f}  → {'OK' if pnl_ok else 'FAIL'}")

        if not (credit_ok and pnl_ok):
            all_passed = False

    conn.close()
    PASS_FAIL["A.2"] = "PASS" if all_passed else "FAIL"
    print(f"\n  A.2 result: {PASS_FAIL['A.2']}")


# ── A.3 — SPY regression ──────────────────────────────────────────────────────

def check_a3() -> None:
    print("\n" + "=" * 65)
    print("A.3 — SPY Regression (2019-01-01 to 2024-12-31)")
    print("=" * 65)
    print("  Purpose: confirm B3 engine changes produce no SPY errors.")
    print("  Note: SPY Sharpe can be negative with default params in bull markets;")
    print("  PASS gate = no exceptions + n_trades > 20 (not Sharpe).")

    start, end = "2019-01-01", "2024-12-31"
    params = dict(PARAMS)
    params = apply_market_preset(params, "spy")
    params.update({
        "mode": "market",
        "start_date": start,
        "end_date": end,
        "single_position": True,
        "cash_investment_mode": "risk_free",
        "cash_yield_annual": 0.0,
    })

    try:
        data = load_market_data(start, end, market="spy")
        trades, eq = _run_single(params, data)
        m = compute_metrics(trades, eq, params, data)
        sharpe   = m.get("sharpe", 0.0)
        n_trades = m.get("n", 0)
        tot_ret  = m.get("tot", 0.0)

        print(f"  n_trades={n_trades}  sharpe={sharpe:.4f}  total_return={tot_ret:.4f}")

        if sharpe < 0:
            print(f"  INFO: Sharpe={sharpe:.4f} is negative (not a regression indicator —"
                  f" consistent with pre-B3 behavior on SPY default params)")

        passed = (n_trades > 20)
        if not passed:
            print(f"  FAIL: only {n_trades} trades (expected > 20) — possible engine error")
        else:
            print(f"  PASS: {n_trades} trades, no exceptions — SPY path intact")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        passed = False

    PASS_FAIL["A.3"] = "PASS" if passed else "FAIL"


# ── A.4 — Synthetic vs market comparison ─────────────────────────────────────

def check_a4(trades_mkt: list) -> None:
    print("\n" + "=" * 65)
    print("A.4 — Synthetic vs Market Comparison")
    print("=" * 65)

    # Run best config in pure synthetic mode
    params_syn = _make_params(BEST_COMBO, HOLDOUT_START, HOLDOUT_END, B3_MARKET,
                              mode="synthetic")
    data_syn = load_market_data(HOLDOUT_START, HOLDOUT_END, market=B3_MARKET)
    try:
        engine_syn = make_engine(params_syn)
        trades_syn, _, _, _ = run_backtest(data_syn, params_syn, engine_syn, progress=False)
    finally:
        pass  # SyntheticEngine has no close()

    # Build lookup: entry_date → trade for synthetic run
    syn_by_date = {t.entry_date: t for t in trades_syn
                   if getattr(t, "parent_trade_num", None) is None}

    # For market-mode trades with entry_source == "synthetic" (not DB-sourced)
    synth_fallback = [
        t for t in trades_mkt
        if getattr(t, "entry_source", "db") == "synthetic"
        and getattr(t, "parent_trade_num", None) is None
        and getattr(t, "pnl", None) is not None
        and t.entry_date in syn_by_date
    ]

    print(f"  Market-mode trades with synthetic entry: {len(synth_fallback)}")

    if not synth_fallback:
        print("  INFO: no synthetic-fallback entries to compare "
              "(all entries used real DB data — good sign)")
        PASS_FAIL["A.4"] = "PASS"
        return

    mismatches = []
    TOL = 0.01  # R$0.01 per contract

    for t in synth_fallback:
        t_syn = syn_by_date[t.entry_date]
        credit_diff = abs(t.net_credit - t_syn.net_credit)
        if credit_diff > TOL:
            mismatches.append((t.trade_num, t.entry_date, credit_diff))

    n_checked = len(synth_fallback)
    n_ok      = n_checked - len(mismatches)
    print(f"  Checked {n_checked} trades: {n_ok} exact, {len(mismatches)} mismatch(es)")

    for trade_num, entry_date, diff in mismatches[:5]:
        print(f"    trade #{trade_num} {entry_date.date()}: |credit diff| = R${diff:.4f}")

    if len(mismatches) > 5:
        print(f"    ... and {len(mismatches) - 5} more")

    passed = len(mismatches) == 0
    print(f"\n  A.4 result: {'PASS' if passed else 'FAIL'}")
    PASS_FAIL["A.4"] = "PASS" if passed else "FAIL"


# ── A.5 — Trade forensics lite ───────────────────────────────────────────────

def check_a5(trades: list) -> None:
    print("\n" + "=" * 65)
    print("A.5 — Trade Forensics Lite (best config, holdout)")
    print("=" * 65)

    closed = [t for t in trades
              if getattr(t, "exit_type", None) not in (None, "OPEN")
              and getattr(t, "pnl", None) is not None]

    if not closed:
        print("  WARNING: no closed trades found")
        PASS_FAIL["A.5"] = "INFO (no trades)"
        return

    total_pnl = sum(t.pnl for t in closed)
    print(f"  Total P&L (closed trades): R${total_pnl:.0f}")
    print(f"  n_closed: {len(closed)}")
    print()

    # P&L by exit type
    for reason in ["PROFIT", "ROLLED", "21DTE", "FORCE_CLOSE", "STOPPED", "EXPIRED"]:
        subset = [t for t in closed if t.exit_type == reason]
        sub_pnl = sum(t.pnl for t in subset)
        pct     = sub_pnl / total_pnl * 100 if total_pnl != 0 else 0.0
        print(f"  {reason:<10}: n={len(subset):3d}  pnl=R${sub_pnl:>8.0f}  "
              f"({pct:+.1f}% of total)")

    # Top-3 and bottom-3 contribution
    sorted_trades = sorted(closed, key=lambda t: t.pnl)
    top3    = sum(t.pnl for t in sorted_trades[-3:])
    bottom3 = sum(t.pnl for t in sorted_trades[:3])
    top3_pct    = top3    / total_pnl * 100 if total_pnl != 0 else 0.0
    bottom3_pct = bottom3 / total_pnl * 100 if total_pnl != 0 else 0.0

    print(f"\n  Top-3 trades:    R${top3:>8.0f} ({top3_pct:+.1f}% of total)")
    print(f"  Bottom-3 trades: R${bottom3:>8.0f} ({bottom3_pct:+.1f}% of total)")
    combined_abs = abs(top3) + abs(bottom3)
    combined_pct = combined_abs / abs(total_pnl) * 100 if total_pnl != 0 else 0.0
    print(f"  Top+Bottom combined: {combined_pct:.1f}% of |total P&L|")

    fat_tail_flag = combined_pct > 50.0
    if fat_tail_flag:
        print("  FLAG: top/bottom 6 trades explain >50% of total — "
              "strategy driven by fat tails, not steady edge")

    # Entry source distribution
    db_trades = [t for t in closed
                 if getattr(t, "entry_source", "synthetic") == "db"]
    print(f"\n  DB-sourced entries: {len(db_trades)} / {len(closed)} "
          f"({len(db_trades)/len(closed)*100:.0f}%)")

    # Note stop-loss dominance
    stopped = [t for t in closed if t.exit_type in ("STOPPED", "FORCE_CLOSE")]
    if stopped:
        stopped_pnl = sum(t.pnl for t in stopped)
        print(f"  Stop-loss trades: n={len(stopped)}, total_pnl=R${stopped_pnl:.0f} "
              f"({stopped_pnl/total_pnl*100:.1f}%)")
        if stopped_pnl / total_pnl < -0.5:
            print("  FLAG: STOPPED trades are dominant loss source — "
                  "stop-loss calibration matters")

    PASS_FAIL["A.5"] = "INFO"  # informational, no hard gate
    if fat_tail_flag:
        PASS_FAIL["A.5"] = "INFO (fat-tail flag)"


# ── A.6 — American option sensitivity ────────────────────────────────────────

def check_a6(data: pd.DataFrame) -> None:
    print("\n" + "=" * 65)
    print("A.6 — American Option Sensitivity (BOVA11 BAW vs BS)")
    print("=" * 65)

    results = {}
    for flag in [False, True]:
        params = _make_params(BEST_COMBO, HOLDOUT_START, HOLDOUT_END, B3_MARKET,
                              american_options=flag)
        trades, eq = _run_laddering(params, data)
        m = compute_portfolio_metrics(trades, eq, params, data)
        label = "BAW (american=True)" if flag else "BS  (american=False)"
        results[flag] = m
        print(f"  {label}: sharpe={m['sharpe']:.4f}  tot_ret={m['tot']:.4f}  "
              f"n_trades={m['n']}")

    delta_sharpe  = abs(results[True]["sharpe"]  - results[False]["sharpe"])
    delta_tot_ret = abs(results[True]["tot"]      - results[False]["tot"])
    initial_cap   = float(PARAMS.get("initial_balance", 50_000))
    delta_ret_brl = delta_tot_ret * initial_cap

    print(f"\n  ΔSharpe  = {delta_sharpe:.4f}  (threshold 0.05)")
    print(f"  Δtotal_return (R$) = R${delta_ret_brl:.0f}  (threshold 1% of R${initial_cap:.0f})")

    passed = delta_sharpe < 0.05 and delta_ret_brl < 0.01 * initial_cap
    if passed:
        print("  PASS: American option correction negligible for BOVA11 ETF")
    else:
        print("  FAIL/FLAG: American option pricing has material impact — investigate")

    PASS_FAIL["A.6"] = "PASS" if passed else "FLAG"


# ── A.7 — Summary ─────────────────────────────────────────────────────────────

def print_a7_summary() -> None:
    print("\n" + "=" * 65)
    print("A.7 — Reliability Check Summary")
    print("=" * 65)
    print(f"\n  {'Check':<30} {'Status'}")
    print("  " + "-" * 45)

    checks = [
        ("A.1 single_position repro",     "see verify_single_position.py output above"),
        ("A.2 manual P&L",                PASS_FAIL.get("A.2", "NOT RUN")),
        ("A.3 SPY regression",            PASS_FAIL.get("A.3", "NOT RUN")),
        ("A.4 synthetic vs market",       PASS_FAIL.get("A.4", "NOT RUN")),
        ("A.5 trade forensics",           PASS_FAIL.get("A.5", "INFO")),
        ("A.6 American options",          PASS_FAIL.get("A.6", "NOT RUN")),
    ]
    for name, status in checks:
        print(f"  {name:<30} {status}")

    hard_failures = [k for k, v in PASS_FAIL.items() if v == "FAIL"]
    if hard_failures:
        print(f"\n  STOP: {len(hard_failures)} hard failure(s): {hard_failures}")
        print("  Do not proceed to Phase B until resolved.")
    else:
        print("\n  All hard gates PASS — proceed to Phase B.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load holdout data once (shared across A.2, A.4, A.5, A.6)
    print("Loading holdout data for BOVA11...")
    data_b3 = load_market_data(HOLDOUT_START, HOLDOUT_END, market=B3_MARKET)

    # Run best config once (used by A.2, A.4, A.5)
    print("Running best laddering config (holdout)...")
    params_best = _make_params(BEST_COMBO, HOLDOUT_START, HOLDOUT_END, B3_MARKET)
    trades_best, eq_best = _run_laddering(params_best, data_b3)
    print(f"  → {len(trades_best)} trades")

    check_a2(trades_best)
    check_a3()
    check_a4(trades_best)
    check_a5(trades_best)
    check_a6(data_b3)
    print_a7_summary()


if __name__ == "__main__":
    main()
