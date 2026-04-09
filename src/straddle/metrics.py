"""Performance metrics computation.

Computes Sharpe, drawdown, win rate, exit breakdown, chain-collapsed stats,
and SPY benchmark metrics from backtest results.
"""

import numpy as np
import pandas as pd


def compute_metrics(trades, equity_curve, params, data) -> dict:
    """Compute comprehensive performance metrics from backtest results.

    Sharpe is computed from true daily mark-to-market changes recorded in
    Trade.daily_marks, NOT from realized P&L spread evenly across holding days.
    The MTM approach correctly captures single-day jump risk (e.g. vol spikes
    on 2018-02-05, 2020-03-12).

    SPY benchmark stats (total return, Sharpe) are included in the return dict
    so that the caller gets a self-contained metrics object.

    Args:
        trades: List of Trade objects from run_backtest.
        equity_curve: pd.Series of balance at each trade exit date.
        params: Flat PARAMS dict.
        data: DataFrame from load_market_data (for SPY benchmark and MTM series).

    Returns:
        Dict with all metrics (overview, win/loss, exit breakdown, stop regimes,
        chain-collapsed stats, leg roll stats, SPY benchmark).
    """
    if not trades:
        return {}
    pnls = np.array([t.pnl for t in trades])
    pcts = np.array([t.pnl_pct for t in trades])
    n = len(trades)

    def _stats(xt):
        ts = [t for t in trades if t.exit_type == xt]
        if not ts:
            return 0, float("nan"), float("nan")
        a = np.array([t.pnl for t in ts])
        return len(ts), float((a > 0).mean()), float(a.mean())

    streak = max_streak = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        max_streak = max(max_streak, streak)

    init = params["initial_balance"]
    final = init + float(pnls.sum())
    years = (
        pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
    ).days / 365.25
    ann = (final / init) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    # Build a true mark-to-market daily P&L series.
    # Days with no open position contribute 0 — omitting them would
    # overstate Sharpe by excluding flat/idle periods.
    # Each day's P&L = change in position mark vs the prior day.
    all_days = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"])
    ].index
    daily_pnl = pd.Series(0.0, index=all_days)
    for t in trades:
        marks = t.daily_marks
        if not marks or len(marks) < 2:
            # Fallback for any trade missing MTM data
            if t.exit_date in daily_pnl.index:
                daily_pnl[t.exit_date] += t.pnl
            continue
        for i in range(1, len(marks)):
            prev_date, prev_val = marks[i - 1]
            this_date, this_val = marks[i]
            day_change = this_val - prev_val
            if this_date in daily_pnl.index:
                daily_pnl[this_date] += day_change
    d = daily_pnl.values
    rf = params["risk_free_rate"] / 252
    sharpe = (
        float((d.mean() - rf) / d.std(ddof=1) * np.sqrt(252))
        if len(d) > 1
        else float("nan")
    )

    eq = equity_curve.values
    pk = np.maximum.accumulate(eq)
    mdd = float(((eq - pk) / pk).min()) if len(eq) else 0.0

    n_p, wr_p, avg_p = _stats("PROFIT")
    n_s, wr_s, avg_s = _stats("STOP")
    n_d, wr_d, avg_d = _stats("21DTE")
    n_e, wr_e, avg_e = _stats("EXPIRY")
    n_r, wr_r, avg_r = _stats("ROLLED")

    # ── Chain-collapsed win/loss (root trades only) ───────────────────────
    # ROLLED rows are mid-chain accountancy entries, not independent outcomes.
    # A logical position = root trade + all descendants. Win = chain P&L > 0.
    by_num = {t.trade_num: t for t in trades}
    chain_pnls = []
    for t in trades:
        if t.parent_trade_num is not None:
            continue  # skip rolled descendants -- counted via their root
        chain_pnl = t.pnl
        cur = t
        while cur.child_trade_num is not None:
            cur = by_num[cur.child_trade_num]
            chain_pnl += cur.pnl
        chain_pnls.append(chain_pnl)
    chain_pnls = np.array(chain_pnls)
    n_chains = len(chain_pnls)
    wr_chain = float((chain_pnls > 0).mean()) if n_chains else float("nan")
    avg_chain = float(chain_pnls.mean()) if n_chains else float("nan")

    streak_chain = max_streak_chain = 0
    for cp in chain_pnls:
        streak_chain = streak_chain + 1 if cp < 0 else 0
        max_streak_chain = max(max_streak_chain, streak_chain)

    # Stop regime breakdown
    def _regime_stats(regime):
        ts = [t for t in trades if t.exit_type == "STOP" and t.stop_regime == regime]
        if not ts:
            return 0, float("nan")
        a = np.array([t.pnl for t in ts])
        return len(ts), float(a.mean())

    n_stop_orderly, avg_stop_orderly = _regime_stats("ORDERLY")
    n_stop_normal, avg_stop_normal = _regime_stats("NORMAL")
    n_stop_violent, avg_stop_violent = _regime_stats("VIOLENT")
    n_stop_gap, avg_stop_gap = _regime_stats("GAP")

    # ── Defensive leg roll stats ─────────────────────────────────────────
    n_lr_trades = sum(1 for t in trades if t.leg_rolls)
    all_lr_events = [ev for t in trades for ev in t.leg_rolls]
    n_lr_events = len(all_lr_events)
    avg_lr_per_trade = float(n_lr_events / len(trades)) if trades else 0.0
    avg_lr_per_rolled = (
        float(n_lr_events / n_lr_trades) if n_lr_trades else float("nan")
    )
    lr_total_credit = float(sum(ev.net_credit_dollar for ev in all_lr_events))

    # ── SPY benchmark stats ──────────────────────────────────────────────
    # Note: spy_close is unadjusted (actual market price), so spy_total_return
    # reflects price appreciation only -- dividends (~1.3%/yr) are excluded.
    spy_window = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "spy_close",
    ]
    spy_start_price = float(spy_window.iloc[0])
    spy_end_price = float(spy_window.iloc[-1])
    spy_total_return = (spy_end_price - spy_start_price) / spy_start_price

    # SPY daily returns for Sharpe (excess of daily risk-free rate)
    _spy_daily = spy_window.pct_change().dropna()
    _spy_rf = data.loc[_spy_daily.index, "risk_free_rate"] / 252
    spy_sharpe = float(
        ((_spy_daily - _spy_rf).mean() / _spy_daily.std(ddof=1)) * np.sqrt(252)
    )

    return dict(
        n=n,
        init=init,
        final=final,
        tot=(final - init) / init,
        ann=ann,
        sharpe=sharpe,
        mdd=mdd,
        calmar=ann / abs(mdd) if mdd else float("nan"),
        wr=float((pnls > 0).mean()),
        avg_pnl=float(pnls.mean()),
        avg_pct=float(pcts.mean()),
        max_streak=max_streak,
        n_p=n_p,
        wr_p=wr_p,
        avg_p=avg_p,
        n_s=n_s,
        wr_s=wr_s,
        avg_s=avg_s,
        n_d=n_d,
        wr_d=wr_d,
        avg_d=avg_d,
        n_e=n_e,
        wr_e=wr_e,
        avg_e=avg_e,
        n_r=n_r,
        wr_r=wr_r,
        avg_r=avg_r,
        n_stop_orderly=n_stop_orderly,
        avg_stop_orderly=avg_stop_orderly,
        n_stop_normal=n_stop_normal,
        avg_stop_normal=avg_stop_normal,
        n_stop_violent=n_stop_violent,
        avg_stop_violent=avg_stop_violent,
        n_stop_gap=n_stop_gap,
        avg_stop_gap=avg_stop_gap,
        # chain-collapsed
        n_chains=n_chains,
        wr_chain=wr_chain,
        avg_chain=avg_chain,
        max_streak_chain=max_streak_chain,
        # leg roll
        n_lr_trades=n_lr_trades,
        n_lr_events=n_lr_events,
        avg_lr_per_trade=avg_lr_per_trade,
        avg_lr_per_rolled=avg_lr_per_rolled,
        lr_total_credit=lr_total_credit,
        # SPY benchmark
        spy_total_return=spy_total_return,
        spy_sharpe=spy_sharpe,
    )
