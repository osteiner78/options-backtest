"""Performance metrics computation.

Computes Sharpe, drawdown, win rate, exit breakdown, chain-collapsed stats,
and SPY benchmark metrics from backtest results.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from straddle.params import RISK_FREE_RATE_DEFAULT


# ── Internal Helpers ─────────────────────────────────────────────────────

def _compute_benchmark_stats(data: pd.DataFrame, params: dict) -> Dict:
    """Compute underlying benchmark total return and Sharpe."""
    # Note: underlying_close is unadjusted (actual market price), so
    # underlying_total_return reflects price appreciation only.
    underlying_window = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "underlying_close",
    ]
    if underlying_window.empty:
        return {"underlying_total_return": 0.0, "underlying_sharpe": 0.0}

    start_price = float(underlying_window.iloc[0])
    end_price = float(underlying_window.iloc[-1])
    underlying_total_return = (end_price - start_price) / start_price

    _daily = underlying_window.pct_change().dropna()
    if _daily.empty:
        return {"underlying_total_return": underlying_total_return, "underlying_sharpe": 0.0}

    _rf = data.loc[_daily.index, "risk_free_rate"] / 252
    underlying_sharpe = float(
        ((_daily - _rf).mean() / _daily.std(ddof=1)) * np.sqrt(252)
    )
    return {"underlying_total_return": underlying_total_return, "underlying_sharpe": underlying_sharpe}


def _compute_trade_stats(trades: List) -> Dict:
    """Basic trade-level statistics (count, win rate, avg P&L, exit breakdown)."""
    if not trades:
        return {}

    pnls = np.array([t.pnl for t in trades if t.pnl is not None])
    n = len(pnls)
    wr = float((pnls > 0).mean()) if n else float("nan")
    avg_pnl = float(pnls.mean()) if n else float("nan")

    def _get_stats(xt):
        ts = [t for t in trades if t.exit_type == xt]
        if not ts:
            return 0, float("nan"), float("nan")
        a = np.array([t.pnl for t in ts if t.pnl is not None])
        if len(a) == 0:
            return 0, float("nan"), float("nan")
        return len(ts), float((a > 0).mean()), float(a.mean())

    n_p, wr_p, avg_p = _get_stats("PROFIT")
    n_s, wr_s, avg_s = _get_stats("STOP")
    n_d, wr_d, avg_d = _get_stats("21DTE")
    n_e, wr_e, avg_e = _get_stats("EXPIRY")
    n_r, wr_r, avg_r = _get_stats("ROLLED")
    n_f, wr_f, avg_f = _get_stats("FORCE_CLOSE")

    return {
        "n": n,
        "wr": wr,
        "avg_pnl": avg_pnl,
        "n_p": n_p, "wr_p": wr_p, "avg_p": avg_p,
        "n_s": n_s, "wr_s": wr_s, "avg_s": avg_s,
        "n_d": n_d, "wr_d": wr_d, "avg_d": avg_d,
        "n_e": n_e, "wr_e": wr_e, "avg_e": avg_e,
        "n_r": n_r, "wr_r": wr_r, "avg_r": avg_r,
        "n_f": n_f, "wr_f": wr_f, "avg_f": avg_f,
    }


def _compute_chain_stats(trades: List) -> Dict:
    """Chain-collapsed win/loss stats (roll chains treated as single positions).

    A "chain" is a root trade plus all its ROLLED descendants, with the P&L
    summed across the chain. This gives the strategic view — "how often does
    a monthly entry, rolls included, end profitable?" — which is usually what
    the user cares about more than per-leg win rate.
    """
    if not trades:
        return {
            "n_chains": 0,
            "wr_chain": float("nan"),
            "avg_chain": float("nan"),
            "max_streak_chain": 0,
        }

    by_num = {t.trade_num: t for t in trades}
    chain_pnls = []
    for t in trades:
        if t.parent_trade_num is not None:
            continue
        chain_pnl = t.pnl or 0.0
        cur = t
        while cur.child_trade_num is not None:
            cur = by_num.get(cur.child_trade_num)
            if not cur:
                break
            chain_pnl += (cur.pnl or 0.0)
        chain_pnls.append(chain_pnl)

    chain_pnls = np.array(chain_pnls)

    streak = max_streak = 0
    for cp in chain_pnls:
        streak = streak + 1 if cp < 0 else 0
        max_streak = max(max_streak, streak)

    return {
        "n_chains": len(chain_pnls),
        "wr_chain": float((chain_pnls > 0).mean()) if len(chain_pnls) else float("nan"),
        "avg_chain": float(chain_pnls.mean()) if len(chain_pnls) else float("nan"),
        "max_streak_chain": max_streak,
    }


def _compute_equity_stats(
    equity_series: pd.Series, params: dict, data: Optional[pd.DataFrame] = None,
) -> Dict:
    """Compute returns, Sharpe, and MDD from an equity curve series."""
    init = float(params.get("initial_balance", 50_000))
    if equity_series.empty or init <= 0:
        return {"init": init, "final": init, "tot": 0.0, "ann": 0.0, "sharpe": 0.0, "mdd": 0.0}

    final = float(equity_series.iloc[-1])
    years = (
        pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
    ).days / 365.25
    
    ann = (final / init) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    tot_ret = (final - init) / init

    # Sharpe from daily percentage returns (correct for a compounding account)
    daily_pct = equity_series.pct_change().dropna()

    # Use data-driven daily risk-free rate when available (B3 CDI, US IRX).
    # Falls back to params value (or 4.5% default) when data is absent.
    if data is not None and "risk_free_rate" in data.columns:
        rf_series = data.loc[daily_pct.index, "risk_free_rate"]
        rf_daily = rf_series / 252.0
    else:
        rf_daily = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT) / 252

    if len(daily_pct) > 1 and daily_pct.std() > 0:
        sharpe = float((daily_pct.mean() - rf_daily.mean()) / daily_pct.std(ddof=1) * np.sqrt(252))
    else:
        sharpe = float("nan")

    # Max drawdown
    eq_vals = equity_series.values
    pk = np.maximum.accumulate(eq_vals)
    mdd = float(((eq_vals - pk) / pk).min()) if len(eq_vals) else 0.0

    return {
        "init": init,
        "final": final,
        "tot": tot_ret,
        "ann": ann,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": ann / abs(mdd) if mdd and mdd != 0 else 0.0,
    }


def _compute_mtm_equity(trades: list, params: dict) -> pd.Series:
    """Build a daily MTM equity curve from individual trade daily_marks.

    For each trade, compute daily P&L deltas from consecutive marks;
    sum across all trades open on each day; accumulate into equity.
    """
    init = float(params.get("initial_balance", 50_000))
    if not trades:
        return pd.Series(dtype=float)

    records: list[dict] = []
    for t in trades:
        marks = getattr(t, "daily_marks", []) or []
        for date, mark in marks:
            records.append({"date": date, "trade": t.trade_num, "mark": mark})

    if not records:
        return pd.Series(dtype=float)

    df = pd.DataFrame(records).sort_values(["trade", "date"])
    df["prev"] = df.groupby("trade")["mark"].shift(1).fillna(0.0)
    df["delta"] = df["mark"] - df["prev"]

    daily_pnl = df.groupby("date")["delta"].sum().sort_index()
    equity = init + daily_pnl.cumsum()
    return equity


def _compute_sharpe_from_daily_pnl(
    daily_pnl: pd.Series, init: float, rf_annual: float = 0.045,
) -> float:
    """Sharpe ratio from a daily absolute-P&L series.

    Computes daily percentage returns from the running-equity curve, subtracts
    the risk-free rate, and annualises via sqrt(252). The running-equity
    denominator corrects the systematic downward bias from the initial-balance
    method (I-10 fix).
    """
    if len(daily_pnl) < 2:
        return 0.0
    equity = init + daily_pnl.cumsum()
    daily_ret = equity.pct_change().dropna()
    if daily_ret.std(ddof=1) <= 0:
        return 0.0
    rf_daily = rf_annual / 252.0
    return float((daily_ret.mean() - rf_daily) / daily_ret.std(ddof=1) * np.sqrt(252))


def _compute_mdd_from_daily_pnl(daily_pnl: pd.Series, init: float) -> float:
    """Max drawdown from a daily absolute-P&L series."""
    cum = init + daily_pnl.cumsum()
    pk = np.maximum.accumulate(cum.values)
    dd = (cum.values - pk) / pk
    return float(dd.min()) if len(dd) else 0.0


def _compute_exit_stats(trades: List) -> List[Dict]:
    """Per-exit-type breakdown: count, pct of total, win%, avg P&L, total P&L.

    Returned as a list (not dict) so the frontend renders in a stable order.
    TOTAL row is appended last.
    """
    if not trades:
        return []

    exit_types = ["PROFIT", "ROLLED", "21DTE", "STOP", "EXPIRY", "FORCE_CLOSE"]
    total_n = len(trades)
    rows: List[Dict] = []

    for xt in exit_types:
        ts = [t for t in trades if t.exit_type == xt]
        pnls = np.array([t.pnl for t in ts if t.pnl is not None])
        n = len(ts)
        rows.append({
            "type": xt,
            "count": n,
            "pct": float(n / total_n) if total_n else 0.0,
            "win_pct": float((pnls > 0).mean()) if len(pnls) else None,
            "avg_pnl": float(pnls.mean()) if len(pnls) else None,
            "total_pnl": float(pnls.sum()) if len(pnls) else 0.0,
        })

    all_pnls = np.array([t.pnl for t in trades if t.pnl is not None])
    rows.append({
        "type": "TOTAL",
        "count": total_n,
        "pct": 1.0,
        "win_pct": float((all_pnls > 0).mean()) if len(all_pnls) else None,
        "avg_pnl": float(all_pnls.mean()) if len(all_pnls) else None,
        "total_pnl": float(all_pnls.sum()) if len(all_pnls) else 0.0,
    })
    return rows


def _compute_vix_regime_stats(trades: List) -> List[Dict]:
    """VIX-regime breakdown: count, win%, avg P&L, total P&L per bucket.

    Buckets match the frontend labels: LOW 0–15, NORMAL 15–25, ELEVATED 25–35,
    HIGH >35. Classified by the trade's entry_vix.
    """
    if not trades:
        return []

    regimes = [
        ("LOW",      0.0,   15.0,  "0-15"),
        ("NORMAL",   15.0,  25.0,  "15-25"),
        ("ELEVATED", 25.0,  35.0,  "25-35"),
        ("HIGH",     35.0,  float("inf"), ">35"),
    ]
    rows: List[Dict] = []

    for name, lo, hi, label in regimes:
        ts = [t for t in trades if lo <= t.entry_vix < hi]
        pnls = np.array([t.pnl for t in ts if t.pnl is not None])
        n = len(ts)
        rows.append({
            "regime": name,
            "range": label,
            "count": n,
            "win_pct": float((pnls > 0).mean()) if len(pnls) else None,
            "avg_pnl": float(pnls.mean()) if len(pnls) else None,
            "total_pnl": float(pnls.sum()) if len(pnls) else 0.0,
        })

    all_pnls = np.array([t.pnl for t in trades if t.pnl is not None])
    rows.append({
        "regime": "TOTAL",
        "range": "",
        "count": len(trades),
        "win_pct": float((all_pnls > 0).mean()) if len(all_pnls) else None,
        "avg_pnl": float(all_pnls.mean()) if len(all_pnls) else None,
        "total_pnl": float(all_pnls.sum()) if len(all_pnls) else 0.0,
    })
    return rows


# ── Public API ───────────────────────────────────────────────────────────

def compute_metrics(trades, equity_curve, params, data) -> dict:
    """Compute comprehensive performance metrics from backtest results."""
    if not trades:
        return {}

    # Basic trade stats
    results = _compute_trade_stats(trades)
    
    # Custom stats for single-position mode
    pnls = np.array([t.pnl for t in trades if t.pnl is not None])
    pcts = np.array([t.pnl_pct for t in trades if t.pnl_pct is not None])
    results["avg_pct"] = float(pcts.mean()) if len(pcts) else float("nan")

    streak = max_streak = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        max_streak = max(max_streak, streak)
    results["max_streak"] = max_streak

    # equity_curve is the daily MTM series built by run_backtest from daily_marks
    eq_stats = _compute_equity_stats(equity_curve, params, data)
    results.update(eq_stats)

    results.update(_compute_chain_stats(trades))

    # Stop regime breakdown
    def _regime_stats(regime):
        ts = [t for t in trades if t.exit_type == "STOP" and t.stop_regime == regime]
        if not ts: return 0, float("nan")
        a = np.array([t.pnl for t in ts if t.pnl is not None])
        return len(ts), float(a.mean()) if len(a) else float("nan")

    for reg in ["ORDERLY", "NORMAL", "VIOLENT", "GAP"]:
        count, avg = _regime_stats(reg)
        results[f"n_stop_{reg.lower()}"] = count
        results[f"avg_stop_{reg.lower()}"] = avg

    # Defensive leg roll stats
    all_lr_events = [ev for t in trades for ev in t.leg_rolls]
    results["n_lr_trades"] = sum(1 for t in trades if t.leg_rolls)
    results["n_lr_events"] = len(all_lr_events)
    results["avg_lr_per_trade"] = float(len(all_lr_events) / len(trades)) if trades else 0.0
    results["lr_total_credit"] = float(sum(ev.net_credit_dollar for ev in all_lr_events))

    # Source tracking stats
    entry_db_count = sum(1 for t in trades if getattr(t, 'entry_source', 'unknown') == 'db')
    exit_db_count = sum(
        1 for t in trades
        if t.exit_type is not None and getattr(t, 'exit_source', 'unknown') == 'db'
    )
    mtm_db_pct_list = []
    for t in trades:
        total = getattr(t, 'mtm_total_days', 0)
        source_days = getattr(t, 'mtm_source_days', 0)
        if total > 0:
            mtm_db_pct_list.append(source_days / total)

    results["entry_db_count"] = entry_db_count
    results["entry_db_total"] = len(trades)
    results["entry_db_pct"] = entry_db_count / len(trades) * 100.0 if trades else 0.0
    results["exit_db_count"] = exit_db_count
    results["mtm_avg_db_pct"] = float(np.mean(mtm_db_pct_list)) * 100.0 if mtm_db_pct_list else 0.0

    # Structured stats for API consumers
    results["exit_stats"] = _compute_exit_stats(trades)
    results["vix_regime_stats"] = _compute_vix_regime_stats(trades)

    # Benchmark
    results.update(_compute_benchmark_stats(data, params))
    return results


def compute_portfolio_metrics(
    trades: list,
    equity_df: pd.DataFrame,
    params: dict,
    data: pd.DataFrame,
) -> dict:
    """Compute performance metrics for a portfolio-mode backtest."""
    if equity_df.empty:
        return {}

    # Equity stats from the provided total_equity column (correct for total_return)
    results = _compute_equity_stats(equity_df["total_equity"], params, data)

    # Recompute Sharpe, MDD, Calmar from trade-level daily MTM marks.
    # The portfolio equity curve mixes cash flows with unrealized P&L,
    # producing noisy daily returns. Trade daily_marks are built directly
    # from engine.get_daily_mark() each day and give clean MTM P&L deltas.
    mtm_equity = _compute_mtm_equity(trades, params)
    if not mtm_equity.empty and len(mtm_equity) > 1:
        daily_pnl = mtm_equity.diff().dropna()
        init = float(params.get("initial_balance", 50_000))
        results["sharpe"] = _compute_sharpe_from_daily_pnl(
            daily_pnl, init,
            rf_annual=params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT),
        )
        results["mdd"] = _compute_mdd_from_daily_pnl(daily_pnl, init)
        ann = float(results.get("ann", 0.0))
        mdd = float(results.get("mdd", 0.0))
        results["calmar"] = ann / abs(mdd) if mdd and mdd != 0 else 0.0
    
    # Include all trades so exit breakdown counts (including ROLLED) are correct.
    results.update(_compute_trade_stats(trades))
    results.update(_compute_chain_stats(trades))

    # Portfolio-level specifics
    results["peak_positions"] = int(equity_df["open_positions"].max()) if "open_positions" in equity_df.columns else 0
    results["avg_positions"] = float(equity_df["open_positions"].mean()) if "open_positions" in equity_df.columns else 0.0

    if "utilized_bpr" in equity_df.columns and equity_df["utilized_bpr"].max() > 0:
        init = float(params.get("initial_balance", 50_000))
        max_bpr_cap = init * params.get("max_bpr_allocation", 0.30)
        results["avg_bpr_util"] = float(equity_df["utilized_bpr"].mean() / max_bpr_cap * 100) if max_bpr_cap > 0 else 0.0
        results["peak_bpr_util"] = float(equity_df["utilized_bpr"].max() / max_bpr_cap * 100) if max_bpr_cap > 0 else 0.0
    else:
        results["avg_bpr_util"] = 0.0
        results["peak_bpr_util"] = 0.0

    realized_pnl = sum(t.pnl for t in trades if t.pnl is not None)
    results["cash_yield_earned"] = results["final"] - results["init"] - realized_pnl

    # Source tracking stats (same as compute_metrics)
    entry_db_count = sum(1 for t in trades if getattr(t, 'entry_source', 'unknown') == 'db')
    exit_db_count = sum(
        1 for t in trades
        if t.exit_type is not None and getattr(t, 'exit_source', 'unknown') == 'db'
    )
    mtm_db_pct_list = []
    for t in trades:
        total = getattr(t, 'mtm_total_days', 0)
        source_days = getattr(t, 'mtm_source_days', 0)
        if total > 0:
            mtm_db_pct_list.append(source_days / total)

    results["entry_db_count"] = entry_db_count
    results["entry_db_total"] = len(trades)
    results["entry_db_pct"] = entry_db_count / len(trades) * 100.0 if trades else 0.0
    results["exit_db_count"] = exit_db_count
    results["mtm_avg_db_pct"] = float(np.mean(mtm_db_pct_list)) * 100.0 if mtm_db_pct_list else 0.0

    # Structured stats for API consumers
    results["exit_stats"] = _compute_exit_stats(trades)
    results["vix_regime_stats"] = _compute_vix_regime_stats(trades)

    # Benchmark
    results.update(_compute_benchmark_stats(data, params))
    return results
