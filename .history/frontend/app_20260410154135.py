"""Streamlit frontend for the SPY Short Strangle Backtest.

Usage:
    pip install -e ".[frontend]"
    streamlit run frontend/app.py
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from straddle import (
    PARAMS,
    compute_metrics,
    compute_portfolio_metrics,
    load_market_data,
    make_engine,
    run_backtest,
    run_portfolio_backtest,
)

# ── Page config ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SPY Short Strangle Backtest",
    page_icon="📊",
    layout="wide",
)

# ── Session state for saved runs ─────────────────────────────────────────

if "saved_runs" not in st.session_state:
    st.session_state.saved_runs = []


# ── Sidebar: Parameters ──────────────────────────────────────────────────

st.sidebar.title("⚙️ Parameters")

# Strategy indicator
st.sidebar.info("📌 **Strategy:** Short Straddle")

# ── Backtest parameters ──────────────────────────────────────────────────

st.sidebar.header("📅 Backtest")
start_date = st.sidebar.date_input(
    "Start Date",
    value=pd.to_datetime(PARAMS["start_date"]),
)
end_date = st.sidebar.date_input(
    "End Date",
    value=pd.to_datetime(PARAMS["end_date"]),
)

initial_balance = st.sidebar.number_input(
    "Initial Balance ($)",
    value=int(PARAMS["initial_balance"]),
    min_value=10_000,
    step=5_000,
)

# ── Strategy parameters ──────────────────────────────────────────────────

st.sidebar.header("📐 Strategy")
target_delta = st.sidebar.slider(
    "Target Delta",
    min_value=0.05,
    max_value=0.30,
    value=PARAMS["target_delta"],
    step=0.01,
    format="%.2f",
)
dte_min = st.sidebar.number_input("Min DTE", value=PARAMS["dte_min"], min_value=14, max_value=60)
dte_max = st.sidebar.number_input("Max DTE", value=PARAMS["dte_max"], min_value=21, max_value=90)

# Profit target (0–100%)
profit_target_pct = st.sidebar.slider(
    "Profit Target (% of premium)",
    min_value=0,
    max_value=100,
    value=int(PARAMS["profit_target_pct"] * 100),
    step=5,
    format="%d%%",
)

# Stop loss toggle
stop_loss_enabled = st.sidebar.checkbox(
    "Enable Stop Loss",
    value=PARAMS.get("stop_loss_enabled", False),
)
stop_loss_pct = st.sidebar.slider(
    "Stop Loss (% of premium)",
    min_value=50,
    max_value=500,
    value=int(PARAMS["stop_loss_pct"] * 100),
    step=25,
    format="%d%%",
    disabled=not stop_loss_enabled,
)

# Single position
single_position = st.sidebar.checkbox(
    "Single position (no overlap)",
    value=PARAMS["single_position"],
)

# Portfolio mode
st.sidebar.header("💼 Portfolio Mode")
portfolio_mode = st.sidebar.radio(
    "Backtest Mode",
    options=["Single Position", "Portfolio (Laddering)"],
    index=0,
    horizontal=False,
    help="Single Position: one trade at a time. Portfolio: multiple concurrent positions with laddering.",
)
is_portfolio = portfolio_mode == "Portfolio (Laddering)"

if is_portfolio:
    max_bpr_allocation = st.sidebar.slider(
        "Max BPR Allocation (%)",
        min_value=10,
        max_value=80,
        value=int(PARAMS.get("max_bpr_allocation", 0.30) * 100),
        step=5,
        format="%d%%",
        help="Maximum percentage of starting capital used as margin.",
    )
    cash_yield_annual = st.sidebar.number_input(
        "Cash Yield Annual (%)",
        value=float(PARAMS.get("cash_yield_annual", 4.0) * 100),
        min_value=0.0,
        max_value=10.0,
        step=0.25,
        format="%.2f",
        help="Annual risk-free rate earned on uninvested cash.",
    )
    entry_cooldown_days = st.sidebar.number_input(
        "Entry Cooldown (days)",
        value=int(PARAMS.get("entry_cooldown_days", 3)),
        min_value=1,
        max_value=10,
        help="Minimum trading days between new entries.",
    )

# VIX entry filter
st.sidebar.header("🌡️ VIX Entry Filter")
vix_filter_enabled = st.sidebar.checkbox(
    "Enable VIX entry filter",
    value=PARAMS["vix_entry_filter_enabled"],
)
vix_entry_max = st.sidebar.number_input(
    "Max VIX for entry",
    value=PARAMS["vix_entry_max"],
    min_value=10.0,
    max_value=80.0,
    step=1.0,
    disabled=not vix_filter_enabled,
)

# Defensive leg rolls
st.sidebar.header("🛡️ Defensive Leg Rolls")
defensive_roll = st.sidebar.checkbox(
    "Enable defensive leg roll",
    value=PARAMS["defensive_leg_roll_enabled"],
    help="Roll untested side when tested side delta exceeds threshold",
)
defensive_trigger_delta = st.sidebar.slider(
    "Defensive trigger delta",
    min_value=0.20,
    max_value=0.50,
    value=PARAMS.get("defensive_trigger_delta", 0.30),
    step=0.01,
    format="%.2f",
    disabled=not defensive_roll,
)
leg_roll_target_delta = st.sidebar.slider(
    "Leg roll target delta",
    min_value=0.05,
    max_value=0.30,
    value=PARAMS.get("leg_roll_target_delta", 0.16),
    step=0.01,
    format="%.2f",
    disabled=not defensive_roll,
)

# ── Roll management ──────────────────────────────────────────────────────

st.sidebar.header("🔄 Roll Management")
manage_at_dte = st.sidebar.number_input(
    "Manage at DTE",
    value=PARAMS["manage_at_dte"],
    min_value=7,
    max_value=45,
)
roll_for_credit = st.sidebar.checkbox(
    "Roll at 21 DTE for credit",
    value=PARAMS["roll_for_credit"],
)
max_rolls = st.sidebar.number_input(
    "Max Rolls",
    value=PARAMS["max_rolls"],
    min_value=0,
    max_value=10,
)

# ── Advanced (collapsed) ─────────────────────────────────────────────────

with st.sidebar.expander("🔧 Advanced — Pricing"):
    mode = st.radio(
        "Pricing Mode",
        options=["synthetic", "market"],
        index=0 if PARAMS["mode"] == "synthetic" else 1,
        horizontal=True,
    )
    risk_free_rate = st.number_input(
        "Risk-free rate (%)",
        value=float(PARAMS.get("risk_free_rate", 4.0) * 100),
        min_value=0.0,
        max_value=20.0,
        step=0.25,
        format="%.2f",
    )
    put_slope = st.number_input(
        "Put slope",
        value=float(PARAMS.get("put_slope", 0.0)),
        step=0.01,
        format="%.2f",
    )
    call_slope = st.number_input(
        "Call slope",
        value=float(PARAMS.get("call_slope", 0.0)),
        step=0.01,
        format="%.2f",
    )

# ── Build params dict ────────────────────────────────────────────────────

def build_params() -> dict:
    p = dict(PARAMS)
    p.update({
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_balance": float(initial_balance),
        "target_delta": float(target_delta),
        "dte_min": int(dte_min),
        "dte_max": int(dte_max),
        "profit_target_pct": float(profit_target_pct) / 100.0,
        "stop_loss_enabled": bool(stop_loss_enabled),
        "stop_loss_pct": float(stop_loss_pct) / 100.0,
        "roll_for_credit": bool(roll_for_credit),
        "manage_at_dte": int(manage_at_dte),
        "max_rolls": int(max_rolls),
        "single_position": bool(single_position) and not is_portfolio,
        "vix_entry_filter_enabled": bool(vix_filter_enabled),
        "vix_entry_max": float(vix_entry_max),
        "defensive_leg_roll_enabled": bool(defensive_roll),
        "defensive_trigger_delta": float(defensive_trigger_delta),
        "leg_roll_target_delta": float(leg_roll_target_delta),
        "mode": mode,
        "risk_free_rate": float(risk_free_rate) / 100.0,
        "put_slope": float(put_slope),
        "call_slope": float(call_slope),
    })
    if is_portfolio:
        p.update({
            "max_bpr_allocation": float(max_bpr_allocation) / 100.0,
            "cash_yield_annual": float(cash_yield_annual) / 100.0,
            "entry_cooldown_days": int(entry_cooldown_days),
        })
    return p


# ── Main area ────────────────────────────────────────────────────────────

st.title("📊 SPY Short Strangle Backtest")
st.caption("Monthly short strangle · 30–45 DTE · configurable profit target & stop")

# Run button
col1, col2 = st.columns([1, 4])
with col1:
    run_clicked = st.button("🚀 Run Backtest", type="primary", width='stretch')

if run_clicked:
    params = build_params()

    with st.spinner("Loading market data..."):
        data = load_market_data(
            start_date=params["start_date"],
            end_date=params["end_date"],
        )

    with st.spinner(f"Running backtest ({params['mode']} mode)..."):
        engine = make_engine(params)
        if is_portfolio:
            trades, equity_df, portfolio = run_portfolio_backtest(
                data, params, engine
            )
            equity_curve = equity_df["total_equity"] if not equity_df.empty else pd.Series(dtype=float)
            skipped_entries = 0
            skipped_vix = 0
        else:
            trades, equity_curve, skipped_entries, skipped_vix = run_backtest(
                data, params, engine
            )
            equity_df = None
            portfolio = None

    if is_portfolio and equity_df is not None and not equity_df.empty:
        metrics = compute_portfolio_metrics(trades, equity_df, params, data)
    else:
        metrics = compute_metrics(trades, equity_curve, params, data)

    # Store in session state
    st.session_state.last_result = {
        "trades": trades,
        "equity_curve": equity_curve,
        "equity_df": equity_df,
        "portfolio": portfolio,
        "metrics": metrics,
        "params": params,
        "data": data,
        "skipped_entries": skipped_entries,
        "skipped_vix": skipped_vix,
        "is_portfolio": is_portfolio,
    }

# Display results if available
if "last_result" in st.session_state:
    result = st.session_state.last_result
    trades = result["trades"]
    equity_curve = result["equity_curve"]
    equity_df = result.get("equity_df")
    portfolio = result.get("portfolio")
    metrics = result["metrics"]
    params = result["params"]
    data = result["data"]
    skipped_entries = result.get("skipped_entries", 0)
    skipped_vix = result.get("skipped_vix", 0)
    is_portfolio = result.get("is_portfolio", False)

    # ── Save run button ──────────────────────────────────────────────────
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("💾 Save This Run", width='stretch'):
            run_label = (
                f"{params['start_date']} → {params['end_date']} "
                f"({params['mode']}, {len(trades)} trades)"
            )
            st.session_state.saved_runs.append({
                "label": run_label,
                "metrics": metrics,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            })
            st.success(f"Saved: {run_label}")

    # ── Performance Summary ──────────────────────────────────────────────
    st.header("📈 Performance Summary")

    if is_portfolio and equity_df is not None and not equity_df.empty:
        final_balance = float(equity_df["total_equity"].iloc[-1])
    else:
        final_balance = params["initial_balance"] + sum(t.pnl for t in trades)
    total_return = (final_balance - params["initial_balance"]) / params["initial_balance"]

    # Row 1: Initial & Final Balance
    st.subheader("Account")
    col1, col2 = st.columns(2)
    col1.metric("Initial Balance", f"${params['initial_balance']:,.0f}")
    col2.metric("Final Balance", f"${final_balance:,.0f}")

    # Portfolio-specific stats
    if is_portfolio:
        st.subheader("💼 Portfolio Stats")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Peak Positions", metrics.get("peak_positions", 0))
        col2.metric("Avg Positions", f"{metrics.get('avg_positions', 0):.1f}")
        col3.metric("Avg BPR Util", f"{metrics.get('avg_bpr_util', 0):.1f}%")
        col4.metric("Peak BPR Util", f"{metrics.get('peak_bpr_util', 0):.1f}%")
        col1, col2 = st.columns(2)
        col1.metric("Cash Yield Earned", f"${metrics.get('cash_yield_earned', 0):,.0f}")

    # Row 2: Return metrics grouped
    st.subheader("Returns & Risk")
    years = (
        pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
    ).days / 365.25
    ann_return = (final_balance / params["initial_balance"]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    mdd = metrics.get("mdd", 0)
    calmar = ann_return / abs(mdd) if mdd else float("nan")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Return", f"{total_return*100:.1f}%")
    col2.metric("Annual Return", f"{ann_return*100:.1f}%")
    col3.metric("Sharpe Ratio", f"{metrics.get('sharpe', 0):.2f}")
    col4.metric("Max Drawdown", f"{mdd*100:.1f}%")
    col5.metric("Calmar", f"{calmar:.2f}" if not np.isnan(calmar) else "—")

    # Row 3: Trade stats grouped
    st.subheader("Trade Statistics")
    if is_portfolio:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Trades Executed", len(trades))
        col2.metric("Win Rate", f"{metrics.get('wr', 0)*100:.1f}%")
        col3.metric("Avg P&L", f"${metrics.get('avg_pnl', 0):,.0f}")
        col4.metric("Max Drawdown", f"{metrics.get('mdd', 0)*100:.1f}%")
    else:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Trades Executed", len(trades))
        col2.metric("Skipped (Single Pos)", skipped_entries)
        col3.metric("Skipped (VIX High)", skipped_vix)
        col4.metric("Win Rate (Chain)", f"{metrics.get('wr_chain', 0)*100:.1f}%")
        col5.metric("Avg P&L", f"${metrics.get('avg_pnl', 0):,.0f}")

    # Row 4: SPY benchmark (separate)
    st.subheader("📊 SPY Benchmark")
    col1, col2, col3 = st.columns(3)
    col1.metric("SPY Return", f"{metrics.get('spy_total_return', 0)*100:.1f}%")
    spy_years = (
        pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
    ).days / 365.25
    spy_cagr = (1 + metrics.get('spy_total_return', 0)) ** (1.0 / spy_years) - 1.0 if spy_years > 0 else 0.0
    col2.metric("SPY CAGR", f"{spy_cagr*100:.1f}%")
    col3.metric("SPY Sharpe", f"{metrics.get('spy_sharpe', 0):.2f}")

    # ── Exit Breakdown ───────────────────────────────────────────────────
    st.header("📊 Exit Breakdown")
    exit_types = {}
    total_trades_for_pct = len(trades) if trades else 1
    for t in trades:
        et = t.exit_type or "UNKNOWN"
        if et not in exit_types:
            exit_types[et] = {"count": 0, "total_pnl": 0.0}
        exit_types[et]["count"] += 1
        exit_types[et]["total_pnl"] += t.pnl

    exit_df = pd.DataFrame([
        {
            "Exit Type": k,
            "Count": v["count"],
            "% of Trades": f"{v['count']/total_trades_for_pct*100:.1f}%",
            "Total P&L": f"${v['total_pnl']:,.2f}",
            "Avg P&L": f"${v['total_pnl']/v['count']:,.2f}",
        }
        for k, v in exit_types.items()
    ])
    st.dataframe(exit_df, width='stretch', hide_index=True)

    # ── Charts ───────────────────────────────────────────────────────────
    st.header("📉 Charts")

    # Equity curve
    st.subheader("Equity Curve")
    if is_portfolio and equity_df is not None and not equity_df.empty:
        # Portfolio mode: use the equity_df directly
        chart_data = equity_df[["total_equity"]].copy()
        chart_data.columns = ["Total Portfolio"]
        if "available_cash" in equity_df.columns:
            chart_data["Cash"] = equity_df["available_cash"]
        st.line_chart(chart_data, width='stretch')
    else:
        eq_dates = [pd.Timestamp(params["start_date"])] + list(equity_curve.index)
        eq_vals = [params["initial_balance"]] + list(equity_curve.values)
        eq_df = pd.DataFrame({"Date": eq_dates, "Strangle": eq_vals})

        # SPY B&H for comparison
        spy_eq = data.loc[
            pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
            "spy_close",
        ]
        spy_eq = spy_eq / float(spy_eq.iloc[0]) * params["initial_balance"]
        spy_df = pd.DataFrame({"Date": spy_eq.index, "SPY B&H": spy_eq.values})

        chart_df = eq_df.merge(spy_df, on="Date", how="outer").sort_values("Date").ffill()
        st.line_chart(chart_df.set_index("Date"), width='stretch')

    # P&L per trade (bar chart with dates on x-axis, colored by exit type)
    st.subheader("P&L per Trade")
    if trades:
        pnl_data = []
        for t in trades:
            pnl_data.append({
                "Date": t.entry_date,
                "P&L": t.pnl,
                "Exit Type": t.exit_type or "UNKNOWN",
            })
        pnl_df = pd.DataFrame(pnl_data)

        # Color mapping for exit types
        exit_colors = {
            "PROFIT": "#2ecc71",
            "STOP": "#e74c3c",
            "21DTE": "#3498db",
            "EXPIRY": "#f39c12",
            "ROLLED": "#9b59b6",
            "UNKNOWN": "#95a5a6",
        }

        fig = go.Figure()
        for etype, color in exit_colors.items():
            mask = pnl_df["Exit Type"] == etype
            if mask.any():
                fig.add_trace(go.Bar(
                    x=pnl_df.loc[mask, "Date"],
                    y=pnl_df.loc[mask, "P&L"],
                    name=etype,
                    marker_color=color,
                ))

        fig.update_layout(
            barmode="overlay",
            xaxis_title="Date",
            yaxis_title="P&L ($)",
            legend_title="Exit Type",
            hovermode="x unified",
            xaxis=dict(
                tickformat="%b %Y",
                tickmode="auto",
                nticks=20,
            ),
        )
        st.plotly_chart(fig, width='stretch')

    # Cumulative P&L chart
    st.subheader("Cumulative P&L")
    if trades:
        cum_pnl = []
        running = 0.0
        for t in trades:
            running += t.pnl
            cum_pnl.append({"Date": t.entry_date, "Cumulative P&L": running})
        cum_df = pd.DataFrame(cum_pnl)

        fig_cum = go.Figure()
        fig_cum.add_trace(go.Scatter(
            x=cum_df["Date"],
            y=cum_df["Cumulative P&L"],
            mode="lines",
            name="Cumulative P&L",
            line=dict(color="#3498db", width=2),
            fill="tozeroy",
            fillcolor="rgba(52,152,219,0.15)",
        ))
        fig_cum.update_layout(
            xaxis_title="Date",
            yaxis_title="Cumulative P&L ($)",
            hovermode="x unified",
            xaxis=dict(
                tickformat="%b %Y",
                tickmode="auto",
                nticks=20,
            ),
        )
        st.plotly_chart(fig_cum, width='stretch')

    # ── VIX Regime Table ─────────────────────────────────────────────────
    st.header("🌡️ VIX Regime")

    # Define VIX ranges dynamically from PARAMS
    vix_low = params.get("vix_low", 15)
    vix_high = params.get("vix_high", 25)

    vix_ranges = [
        ("Low", 0, vix_low),
        ("Normal", vix_low, vix_high),
        ("Elevated", vix_high, 35),
        ("High", 35, 50),
        ("Extreme", 50, 200),
    ]

    vix_data = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "vix_close",
    ]

    regime_rows = []
    for label, lo, hi in vix_ranges:
        # Trades where entry VIX falls in this range
        regime_trades = [
            t for t in trades
            if lo <= (t.entry_vix or 0) < hi
        ]
        n_trades = len(regime_trades)
        if n_trades > 0:
            pnls = np.array([t.pnl for t in regime_trades])
            pnl_pcts = np.array([t.pnl_pct for t in regime_trades if t.pnl_pct is not None])
            entry_vixs = np.array([t.entry_vix for t in regime_trades if t.entry_vix is not None])
            # Max VIX during each trade's lifetime
            max_vixs = []
            for t in regime_trades:
                if t.daily_marks:
                    trade_vixs = []
                    for d, _ in t.daily_marks:
                        if d in vix_data.index:
                            trade_vixs.append(vix_data.loc[d])
                    if trade_vixs:
                        max_vixs.append(max(trade_vixs))
            avg_max_vix = np.mean(max_vixs) if max_vixs else float("nan")

            regime_rows.append({
                "VIX Range": f"{lo}–{hi}",
                "# Trades": n_trades,
                "Win Rate": f"{(pnls > 0).mean()*100:.1f}%" if n_trades else "—",
                "Avg Entry VIX": f"{entry_vixs.mean():.1f}" if len(entry_vixs) else "—",
                "Avg Max VIX": f"{avg_max_vix:.1f}" if not np.isnan(avg_max_vix) else "—",
                "Avg P&L $": f"${pnls.mean():,.2f}",
                "Avg P&L %": f"{pnl_pcts.mean()*100:.1f}%" if len(pnl_pcts) else "—",
                "Total P&L $": f"${pnls.sum():,.2f}",
            })
        else:
            regime_rows.append({
                "VIX Range": f"{lo}–{hi}",
                "# Trades": 0,
                "Win Rate": "—",
                "Avg Entry VIX": "—",
                "Avg Max VIX": "—",
                "Avg P&L $": "—",
                "Avg P&L %": "—",
                "Total P&L $": "—",
            })

    regime_df = pd.DataFrame(regime_rows)
    st.dataframe(regime_df, width='stretch', hide_index=True)

    # ── Trade Log ────────────────────────────────────────────────────────
    st.header("📋 Trade Log")

    # Filter controls
    col1, col2 = st.columns(2)
    with col1:
        filter_exit = st.multiselect(
            "Filter by Exit Type",
            options=sorted(set(t.exit_type for t in trades if t.exit_type)),
            default=None,
        )
    with col2:
        filter_date_range = st.date_input(
            "Filter by Entry Date",
            value=[
                pd.to_datetime(params["start_date"]),
                pd.to_datetime(params["end_date"]),
            ],
        )

    # Apply filters
    filtered_trades = trades
    if filter_exit:
        filtered_trades = [t for t in filtered_trades if t.exit_type in filter_exit]
    if filter_date_range and len(filter_date_range) == 2:
        start_f = pd.Timestamp(filter_date_range[0])
        end_f = pd.Timestamp(filter_date_range[1])
        filtered_trades = [t for t in filtered_trades if start_f <= t.entry_date <= end_f]

    # Build trade dataframe with expiry column after entry
    trade_df = pd.DataFrame([
        {
            "#": t.trade_num,
            "Entry": t.entry_date.strftime("%Y-%m-%d"),
            "Expiry": t.expiry_date.strftime("%Y-%m-%d") if hasattr(t, 'expiry_date') and t.expiry_date else "—",
            "Exit": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "Open",
            "DTE": t.entry_dte,
            "Put Strike": t.put_strike,
            "Call Strike": t.call_strike,
            "Credit": f"${t.net_credit:.0f}",
            "P&L": f"${t.pnl:+,.0f}" if t.pnl is not None else "—",
            "P&L %": f"{t.pnl_pct*100:+.0f}%" if t.pnl_pct is not None else "—",
            "Exit Type": t.exit_type or "—",
            "Entry VIX": f"{t.entry_vix:.1f}",
        }
        for t in filtered_trades
    ])

    # Color rows by exit type using styled dataframe
    exit_color_map = {
        "PROFIT": "#d4edda",
        "STOP": "#f8d7da",
        "21DTE": "#d1ecf1",
        "EXPIRY": "#fff3cd",
        "ROLLED": "#e2d5f1",
        "UNKNOWN": "#e2e3e5",
    }

    def highlight_exit_type(row):
        et = row.get("Exit Type", "—")
        bg = exit_color_map.get(et, "")
        if bg:
            return [f"background-color: {bg}"] * len(row)
        return [""] * len(row)

    styled_df = trade_df.style.apply(highlight_exit_type, axis=1)
    st.dataframe(styled_df, width='stretch', hide_index=True)

    # ── Saved Runs ───────────────────────────────────────────────────────
    if st.session_state.saved_runs:
        st.header("💾 Saved Runs")
        for run in st.session_state.saved_runs:
            st.caption(f"{run['timestamp']} — {run['label']}")
            m = run["metrics"]
            cols = st.columns(4)
            cols[0].metric("Return", f"{m.get('tot', 0)*100:.1f}%")
            cols[1].metric("Sharpe", f"{m.get('sharpe', 0):.2f}")
            cols[2].metric("Win Rate", f"{m.get('wr_chain', 0)*100:.1f}%")
            cols[3].metric("Trades", str(m.get('n', 0)))
        st.divider()

else:
    st.info("👈 Configure parameters in the sidebar and click **Run Backtest** to start.")
