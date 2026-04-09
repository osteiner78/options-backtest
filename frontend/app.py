"""Streamlit frontend for the SPY Short Strangle Backtest.

Usage:
    pip install -e ".[frontend]"
    streamlit run frontend/app.py
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from straddle import (
    PARAMS,
    compute_metrics,
    load_market_data,
    make_engine,
    plot_backtest,
    run_backtest,
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

st.sidebar.header("📅 Date Range")
start_date = st.sidebar.date_input(
    "Start Date",
    value=pd.to_datetime(PARAMS["start_date"]),
)
end_date = st.sidebar.date_input(
    "End Date",
    value=pd.to_datetime(PARAMS["end_date"]),
)

st.sidebar.header("💰 Account")
initial_balance = st.sidebar.number_input(
    "Initial Balance ($)",
    value=int(PARAMS["initial_balance"]),
    min_value=10_000,
    step=5_000,
)

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

st.sidebar.header("🎯 Exit Rules")
profit_target_pct = st.sidebar.slider(
    "Profit Target (% of premium)",
    min_value=0.10,
    max_value=1.00,
    value=PARAMS["profit_target_pct"],
    step=0.05,
    format="%.0f%%",
)
stop_loss_pct = st.sidebar.slider(
    "Stop Loss (% of premium)",
    min_value=1.00,
    max_value=4.00,
    value=PARAMS["stop_loss_pct"],
    step=0.25,
    format="%.1fx",
)

st.sidebar.header("🔄 Roll Management")
roll_for_credit = st.sidebar.checkbox("Roll at 21 DTE for credit", value=PARAMS["roll_for_credit"])
manage_at_dte = st.sidebar.number_input("Manage at DTE", value=PARAMS["manage_at_dte"], min_value=7, max_value=45)
max_rolls = st.sidebar.number_input("Max Rolls", value=PARAMS["max_rolls"], min_value=0, max_value=10)
single_position = st.sidebar.checkbox("Single position (no overlap)", value=PARAMS["single_position"])

st.sidebar.header("📊 VIX Filter")
vix_filter_enabled = st.sidebar.checkbox("Enable VIX entry filter", value=PARAMS["vix_entry_filter_enabled"])
vix_entry_max = st.sidebar.number_input(
    "Max VIX for entry",
    value=PARAMS["vix_entry_max"],
    min_value=10.0,
    max_value=80.0,
    step=1.0,
    disabled=not vix_filter_enabled,
)

st.sidebar.header("🛡️ Defensive Leg Roll")
defensive_roll = st.sidebar.checkbox(
    "Enable defensive leg roll",
    value=PARAMS["defensive_leg_roll_enabled"],
    help="Roll untested side when tested side delta exceeds threshold",
)

st.sidebar.header("💲 Pricing Mode")
mode = st.sidebar.radio(
    "Pricing Mode",
    options=["synthetic", "market"],
    index=0 if PARAMS["mode"] == "synthetic" else 1,
    horizontal=True,
)

# ── Build params dict ────────────────────────────────────────────────────

def build_params() -> dict:
    params = dict(PARAMS)
    params.update({
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_balance": float(initial_balance),
        "target_delta": float(target_delta),
        "dte_min": int(dte_min),
        "dte_max": int(dte_max),
        "profit_target_pct": float(profit_target_pct),
        "stop_loss_pct": float(stop_loss_pct),
        "roll_for_credit": bool(roll_for_credit),
        "manage_at_dte": int(manage_at_dte),
        "max_rolls": int(max_rolls),
        "single_position": bool(single_position),
        "vix_entry_filter_enabled": bool(vix_filter_enabled),
        "vix_entry_max": float(vix_entry_max),
        "defensive_leg_roll_enabled": bool(defensive_roll),
        "mode": mode,
    })
    return params


# ── Main area ────────────────────────────────────────────────────────────

st.title("📊 SPY Short Strangle Backtest")
st.caption("Monthly 16Δ short strangle · 30–45 DTE · 50% profit target · 200% stop")

# Run button
col1, col2 = st.columns([1, 4])
with col1:
    run_clicked = st.button("🚀 Run Backtest", type="primary", use_container_width=True)

if run_clicked:
    params = build_params()

    with st.spinner("Loading market data..."):
        data = load_market_data(
            start_date=params["start_date"],
            end_date=params["end_date"],
        )

    with st.spinner(f"Running backtest ({params['mode']} mode)..."):
        engine = make_engine(params)
        try:
            trades, equity_curve, skipped_entries, skipped_vix = run_backtest(
                data, params, engine
            )
        finally:
            if hasattr(engine, "close"):
                engine.close()

    metrics = compute_metrics(trades, equity_curve, params, data)

    # Store in session state
    st.session_state.last_result = {
        "trades": trades,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "params": params,
        "data": data,
        "skipped_entries": skipped_entries,
        "skipped_vix": skipped_vix,
    }

# Display results if available
if "last_result" in st.session_state:
    result = st.session_state.last_result
    trades = result["trades"]
    equity_curve = result["equity_curve"]
    metrics = result["metrics"]
    params = result["params"]
    data = result["data"]

    # ── Save run button ──────────────────────────────────────────────────
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("💾 Save This Run", use_container_width=True):
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

    # ── Metrics Summary ──────────────────────────────────────────────────
    st.header("📈 Performance Summary")

    final_balance = params["initial_balance"] + sum(t.pnl for t in trades)
    total_return = (final_balance - params["initial_balance"]) / params["initial_balance"]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Trades", len(trades))
    col2.metric("Final Balance", f"${final_balance:,.0f}")
    col3.metric("Total Return", f"{total_return*100:.1f}%")
    col4.metric("Sharpe Ratio", f"{metrics.get('sharpe', 0):.2f}")
    col5.metric("Max Drawdown", f"{metrics.get('mdd', 0)*100:.1f}%")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Win Rate (Chain)", f"{metrics.get('wr_chain', 0)*100:.1f}%")
    col2.metric("Avg P&L", f"${metrics.get('avg_pnl', 0):,.0f}")
    col3.metric("SPY Return", f"{metrics.get('spy_total_return', 0)*100:.1f}%")
    col4.metric("SPY Sharpe", f"{metrics.get('spy_sharpe', 0):.2f}")
    col5.metric("Calmar", f"{metrics.get('calmar', 0):.2f}")

    # ── Exit Breakdown ───────────────────────────────────────────────────
    st.header("📊 Exit Breakdown")
    exit_types = {}
    for t in trades:
        et = t.exit_type or "UNKNOWN"
        if et not in exit_types:
            exit_types[et] = {"count": 0, "total_pnl": 0.0}
        exit_types[et]["count"] += 1
        exit_types[et]["total_pnl"] += t.pnl

    exit_df = pd.DataFrame([
        {"Exit Type": k, "Count": v["count"], "Total P&L": v["total_pnl"], "Avg P&L": v["total_pnl"] / v["count"]}
        for k, v in exit_types.items()
    ])
    st.dataframe(exit_df, use_container_width=True, hide_index=True)

    # ── Charts ───────────────────────────────────────────────────────────
    st.header("📉 Charts")

    # Equity curve
    st.subheader("Equity Curve")
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
    st.line_chart(chart_df.set_index("Date"), use_container_width=True)

    # P&L per trade
    st.subheader("P&L per Trade")
    pnl_df = pd.DataFrame([
        {"Trade #": t.trade_num, "P&L": t.pnl, "Exit Type": t.exit_type or "UNKNOWN"}
        for t in trades
    ])
    st.bar_chart(pnl_df.set_index("Trade #")[["P&L"]], use_container_width=True)

    # ── VIX Regime Table ─────────────────────────────────────────────────
    st.header("🌡️ VIX Regime")
    vix_data = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "vix_close",
    ]
    vix_stats = pd.DataFrame({
        "Metric": ["Min", "Mean", "Max", "Current"],
        "VIX": [
            vix_data.min(),
            vix_data.mean(),
            vix_data.max(),
            vix_data.iloc[-1],
        ],
    })
    st.dataframe(vix_stats, use_container_width=True, hide_index=True)

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

    trade_df = pd.DataFrame([
        {
            "#": t.trade_num,
            "Entry": t.entry_date.strftime("%Y-%m-%d"),
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
    st.dataframe(trade_df, use_container_width=True, hide_index=True)

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
