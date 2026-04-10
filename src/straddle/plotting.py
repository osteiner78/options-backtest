"""Plotting: plot_backtest, plot_engine_comparison, and canonical gruvbox palette."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ── Canonical gruvbox palette ────────────────────────────────────────────
# Merged from the notebook's _C (cell 13) and GRV (cell 15) dicts.

GRUVBOX = {
    "bg": "#282828",
    "bg1": "#3c3836",
    "bg2": "#504945",
    "fg": "#ebdbb2",
    "fg_dim": "#a89984",
    "green": "#98971a",
    "red": "#cc241d",
    "yellow": "#d79921",
    "blue": "#458588",
    "bright_green": "#b8bb26",
    "bright_red": "#fb4934",
    "bright_yellow": "#fabd2f",
    "bright_blue": "#83a598",
    # Chart-specific colors
    "orange": "#fe8019",
    "purple": "#d3869b",
}

# Exit-type color map (used by both plot functions)
EXIT_COLORS = {
    "PROFIT": "#27ae60",
    "STOP": "#e74c3c",
    "21DTE": "#e67e22",
    "EXPIRY": "#2980b9",
    "ROLLED": "#9b59b6",
}

# Apply gruvbox style once at import
plt.style.use("seaborn-v0_8-whitegrid")


# ── Main backtest visualization ─────────────────────────────────────────

def plot_backtest(
    trades,
    equity_curve,
    data,
    params,
    output_path: str = "backtest_results.png",
) -> None:
    """Generate the full backtest visualization dashboard.

    Produces a 4-row, 2-column figure with:
    1. Equity curve (strangle vs SPY B&H, drawdown shading)
    2. P&L per trade (colored by exit type)
    3. Cumulative P&L
    4. Return distribution
    5. Exit type count
    6. Avg P&L by exit type
    7. VIX with entry points

    Args:
        trades: List of Trade objects from run_backtest.
        equity_curve: pd.Series of balance at each trade exit date.
        data: DataFrame from load_market_data.
        params: Flat PARAMS dict.
        output_path: File path for the saved PNG. Defaults to "backtest_results.png".
    """
    fig = plt.figure(figsize=(16, 22))
    fig.suptitle(
        f'SPY Short Strangle Backtest  [{params["start_date"]} → {params["end_date"]}]\n'
        f"16Δ | 30–45 DTE | 50% profit | 200% stop | 21 DTE close | $50k account",
        fontsize=13,
        fontweight="bold",
        y=0.99,
    )

    eq_dates = [pd.Timestamp(params["start_date"])] + list(equity_curve.index)
    eq_vals = [params["initial_balance"]] + list(equity_curve.values)
    eq_arr = np.array(eq_vals)
    pk_arr = np.maximum.accumulate(eq_arr)

    # 1. Equity curve
    ax1 = fig.add_subplot(4, 2, (1, 2))
    ax1.plot(eq_dates, eq_vals, color="#2c3e50", lw=2, label="Strangle", zorder=3)
    # SPY buy-and-hold normalised to same starting balance
    spy_eq = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "spy_close",
    ]
    spy_eq = spy_eq / float(spy_eq.iloc[0]) * params["initial_balance"]
    ax1.plot(
        spy_eq.index,
        spy_eq.values,
        color="#e67e22",
        lw=1.5,
        ls="--",
        alpha=0.8,
        label="SPY B&H",
        zorder=2,
    )
    ax1.axhline(params["initial_balance"], color="grey", ls="--", lw=0.8, alpha=0.7)
    for i in range(len(eq_dates) - 1):
        if eq_arr[i] < pk_arr[i]:
            ax1.fill_between(
                [eq_dates[i], eq_dates[i + 1]],
                [pk_arr[i], pk_arr[i + 1]],
                [eq_arr[i], eq_arr[i + 1]],
                alpha=0.25,
                color="#e74c3c",
                zorder=2,
            )
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_title("Equity Curve  (red = drawdown)", fontweight="bold")
    ax1.legend()

    # 2. P&L per trade
    ax2 = fig.add_subplot(4, 2, 3)
    ax2.bar(
        range(1, len(trades) + 1),
        [t.pnl for t in trades],
        color=[EXIT_COLORS.get(t.exit_type, "#95a5a6") for t in trades],
        edgecolor="none",
        alpha=0.85,
    )
    ax2.axhline(0, color="black", lw=0.8)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax2.set_title("P&L per Trade", fontweight="bold")
    ax2.set_xlabel("Trade #")
    ax2.legend(
        handles=[mpatches.Patch(color=c, label=l) for l, c in EXIT_COLORS.items()],
        fontsize=8,
    )

    # 3. Cumulative P&L
    ax3 = fig.add_subplot(4, 2, 4)
    cum = np.cumsum([t.pnl for t in trades])
    x = range(1, len(trades) + 1)
    ax3.plot(x, cum, color="#2980b9", lw=2)
    ax3.fill_between(x, cum, 0, where=cum >= 0, alpha=0.2, color="#27ae60")
    ax3.fill_between(x, cum, 0, where=cum < 0, alpha=0.2, color="#e74c3c")
    ax3.axhline(0, color="black", lw=0.8)
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x_, _: f"${x_:,.0f}"))
    ax3.set_title("Cumulative P&L", fontweight="bold")
    ax3.set_xlabel("Trade #")

    # 4. Return distribution
    ax4 = fig.add_subplot(4, 2, 5)
    pct_vals = [t.pnl_pct * 100 for t in trades]
    ax4.hist(
        pct_vals,
        bins=max(8, len(trades) // 2),
        color="#3498db",
        edgecolor="white",
        alpha=0.85,
    )
    ax4.axvline(0, color="black", lw=1)
    ax4.axvline(
        np.mean(pct_vals),
        color="#e74c3c",
        lw=1.5,
        ls="--",
        label=f"Mean {np.mean(pct_vals):.1f}%",
    )
    ax4.set_title("Return Distribution  (% of premium)", fontweight="bold")
    ax4.set_xlabel("P&L %")
    ax4.legend(fontsize=9)

    # 5. Exit type count
    ax5 = fig.add_subplot(4, 2, 6)
    cnts = {k: sum(1 for t in trades if t.exit_type == k) for k in EXIT_COLORS}
    bars = ax5.bar(
        cnts.keys(),
        cnts.values(),
        color=list(EXIT_COLORS.values()),
        edgecolor="none",
        alpha=0.85,
    )
    ax5.set_title("Exit Type Count", fontweight="bold")
    ax5.set_ylabel("# Trades")
    for bar, v in zip(bars, cnts.values()):
        if v:
            ax5.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.05,
                str(v),
                ha="center",
                va="bottom",
                fontweight="bold",
            )

    # 6. Avg P&L by exit type
    ax6 = fig.add_subplot(4, 2, 7)
    avgs = {
        k: (
            np.mean([t.pnl for t in trades if t.exit_type == k])
            if any(t.exit_type == k for t in trades)
            else 0
        )
        for k in EXIT_COLORS
    }
    ax6.bar(
        avgs.keys(),
        avgs.values(),
        color=list(EXIT_COLORS.values()),
        edgecolor="none",
        alpha=0.85,
    )
    ax6.axhline(0, color="black", lw=0.8)
    ax6.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax6.set_title("Avg P&L by Exit Type", fontweight="bold")

    # 7. VIX with entries
    ax7 = fig.add_subplot(4, 2, 8)
    vx = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "vix_close",
    ]
    ax7.plot(vx.index, vx.values, color="#7f8c8d", lw=0.8, alpha=0.8)
    ax7.axhline(
        params.get("vix_low", 15),
        color="#3498db",
        ls="--",
        lw=0.9,
        label=f'VIX={params.get("vix_low", 15)}',
    )
    ax7.axhline(
        params.get("vix_high", 25),
        color="#e74c3c",
        ls="--",
        lw=0.9,
        label=f'VIX={params.get("vix_high", 25)}',
    )
    ax7.scatter(
        [t.entry_date for t in trades],
        [t.entry_vix for t in trades],
        color="#2c3e50",
        s=35,
        zorder=5,
        label="Entry",
    )
    ax7.set_title("VIX with Entry Points", fontweight="bold")
    ax7.legend(fontsize=8)
    ax7.set_ylabel("VIX")

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"Saved: {output_path}")


# ── Engine comparison chart ──────────────────────────────────────────────

def plot_engine_comparison(
    trades_synthetic: list,
    trades_market: list,
    title: str = "Synthetic vs Market Engine — Strike & Credit Comparison (root trades)",
) -> None:
    """Side-by-side comparison of synthetic and market engine strikes and credits.

    Filters to root trades only (parent_trade_num is None) and trims to the
    shorter list for 1:1 comparison.

    Args:
        trades_synthetic: List of Trade objects from a synthetic engine run.
        trades_market: List of Trade objects from a market engine run.
        title: Chart title.
    """
    # Filter to root trades
    roots_syn = [t for t in trades_synthetic if t.parent_trade_num is None]
    roots_mkt = [t for t in trades_market if t.parent_trade_num is None]

    # Use the shorter list for 1:1 comparison
    n = min(len(roots_syn), len(roots_mkt))

    trade_nums = list(range(1, n + 1))
    syn_put_k = [ts.put_strike for ts in roots_syn[:n]]
    mkt_put_k = [tm.put_strike for tm in roots_mkt[:n]]
    syn_call_k = [ts.call_strike for ts in roots_syn[:n]]
    mkt_call_k = [tm.call_strike for tm in roots_mkt[:n]]
    syn_credit = [ts.net_credit for ts in roots_syn[:n]]
    mkt_credit = [tm.net_credit for tm in roots_mkt[:n]]

    C = GRUVBOX

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), facecolor=C["bg"])
    fig.suptitle(title, color=C["fg"], fontsize=13, fontweight="bold")

    for ax in (ax1, ax2):
        ax.set_facecolor(C["bg1"])
        ax.tick_params(colors=C["fg"])
        for spine in ax.spines.values():
            spine.set_color(C["bg2"])
        ax.xaxis.label.set_color(C["fg"])
        ax.yaxis.label.set_color(C["fg"])
        ax.grid(True, color=C["bg2"], linewidth=0.5)

    ax1.plot(trade_nums, syn_put_k, color=C["blue"], lw=1.5, label="Syn K put")
    ax1.plot(
        trade_nums,
        mkt_put_k,
        color=C["blue"],
        lw=1.5,
        label="Mkt K put",
        linestyle="--",
        alpha=0.8,
    )
    ax1.plot(trade_nums, syn_call_k, color=C["orange"], lw=1.5, label="Syn K call")
    ax1.plot(
        trade_nums,
        mkt_call_k,
        color=C["orange"],
        lw=1.5,
        label="Mkt K call",
        linestyle="--",
        alpha=0.8,
    )
    ax1.set_ylabel("Strike ($)", color=C["fg"])
    ax1.set_title(
        "Strikes per root trade  (solid = synthetic, dashed = market)",
        color=C["fg_dim"],
        fontsize=10,
    )
    ax1.legend(facecolor=C["bg2"], labelcolor=C["fg"], edgecolor=C["bg2"], fontsize=9)

    ax2.plot(trade_nums, syn_credit, color=C["green"], lw=1.5, label="Synthetic credit")
    ax2.plot(
        trade_nums,
        mkt_credit,
        color=C["yellow"],
        lw=1.5,
        label="Market credit",
        linestyle="--",
        alpha=0.8,
    )
    ax2.set_xlabel("Trade #", color=C["fg"])
    ax2.set_ylabel("Net credit ($)", color=C["fg"])
    ax2.set_title(
        "Net credit per root trade  (solid = synthetic, dashed = market)",
        color=C["fg_dim"],
        fontsize=10,
    )
    ax2.legend(facecolor=C["bg2"], labelcolor=C["fg"], edgecolor=C["bg2"], fontsize=9)

    plt.tight_layout()
    plt.show()

    # ── Summary statistics ────────────────────────────────────────────────
    pnl_syn = sum(t.pnl for t in trades_synthetic)
    pnl_mkt = sum(t.pnl for t in trades_market)
    print(
        f"Root trades     : syn={len(roots_syn)}  mkt={len(roots_mkt)}  "
        f"(syn total rows: {len(trades_synthetic)}  mkt total rows: {len(trades_market)})"
    )
    print(f"Total P&L       : synthetic ${pnl_syn:+,.2f}   market ${pnl_mkt:+,.2f}")
    print(
        f"Net credit avg  : synthetic ${sum(syn_credit)/len(syn_credit):.2f}   "
        f"market ${sum(mkt_credit)/len(mkt_credit):.2f}"
    )

    # DB vs synthetic fallback breakdown
    n_db = sum(1 for tm in roots_mkt if tm.used_market_data)
    n_synth = sum(1 for tm in roots_mkt if not tm.used_market_data)
    print(f"Entry marks     : {n_db}/{n} from DB,  {n_synth}/{n} synthetic fallback")
    print()
    for pct in (1, 3, 5, 10):
        count = sum(
            1
            for sc, mc in zip(syn_credit, mkt_credit)
            if abs(mc - sc) / max(sc, 0.01) < pct / 100
        )
        print(f"  Mkt credit within {pct:>2}% of synthetic: {count:>3}/{n}")
