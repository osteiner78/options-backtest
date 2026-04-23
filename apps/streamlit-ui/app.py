"""Streamlit frontend for the SPY Short Strangle Backtest.

Usage:
    pip install -e ".[frontend]"
    streamlit run apps/streamlit-ui/app.py
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

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

# ── Compact UI styles ─────────────────────────────────────────────────────
st.markdown("""
<style>
/* Smaller metric labels and values */
[data-testid="stMetricLabel"] p { font-size: 0.72rem !important; }
[data-testid="stMetricValue"]   { font-size: 1.0rem  !important; }
[data-testid="stMetricDelta"]   { font-size: 0.68rem !important; }

/* Reduce top padding in main area */
.main .block-container,
div[data-testid="stAppViewBlockContainer"] { padding-top: 0.25rem !important; }
header[data-testid="stHeader"] { height: 2rem !important; min-height: 2rem !important; }

/* Reduce sidebar top padding */
section[data-testid="stSidebar"] > div:first-child { padding-top: 0.25rem !important; }

/* Tighten sidebar element spacing */
section[data-testid="stSidebar"] .stSlider       { margin-bottom: 0 !important; padding-bottom: 0 !important; }
section[data-testid="stSidebar"] .stNumberInput  { margin-bottom: 0 !important; }
section[data-testid="stSidebar"] .stCheckbox     { margin-bottom: 0 !important; }
section[data-testid="stSidebar"] .stRadio        { margin-bottom: 0 !important; }
section[data-testid="stSidebar"] h2              { margin-top: 0.4rem !important; margin-bottom: 0.1rem !important; font-size: 1.1rem !important; }
section[data-testid="stSidebar"] .stMarkdown p  { font-size: 0.78rem !important; }
section[data-testid="stSidebar"] hr             { margin: 0.3rem 0 !important; }


</style>
""", unsafe_allow_html=True)

# ── Session state for saved runs ─────────────────────────────────────────

if "saved_runs" not in st.session_state:
    st.session_state.saved_runs = []


# ── Sidebar: Parameters ──────────────────────────────────────────────────

st.sidebar.title("Parameters")

# ── Backtest ─────────────────────────────────────────────────────────────

st.sidebar.header("Backtest")
start_date = st.sidebar.date_input("Start Date", value=pd.to_datetime(PARAMS["start_date"]))
end_date = st.sidebar.date_input("End Date", value=pd.to_datetime(PARAMS["end_date"]))
initial_balance = st.sidebar.number_input(
    "Initial Balance ($)", value=int(PARAMS["initial_balance"]), min_value=10_000, step=5_000,
)

st.sidebar.divider()

# ── Portfolio Mode ────────────────────────────────────────────────────────

st.sidebar.header("Portfolio Mode")
portfolio_mode = st.sidebar.radio(
    "Backtest Mode",
    options=["Single Position", "Portfolio (Laddering)"],
    index=1,  # default: Portfolio
    horizontal=False,
    help="Single Position: one trade at a time. Portfolio: multiple concurrent positions with laddering.",
)
is_portfolio = portfolio_mode == "Portfolio (Laddering)"

if is_portfolio:
    max_bpr_allocation = st.sidebar.slider(
        "Max BPR Allocation (%)",
        min_value=0, max_value=80,
        value=int(PARAMS.get("max_bpr_allocation", 0.30) * 100),
        step=5, format="%d%%",
        help="Maximum percentage of starting capital used as margin.",
    )
    entry_cooldown_days = st.sidebar.number_input(
        "Entry Cooldown (days)",
        value=int(PARAMS.get("entry_cooldown_days", 3)),
        min_value=1, max_value=10,
        help="Minimum trading days between new entries.",
    )
    cash_investment_mode = st.sidebar.radio(
        "Uninvested Cash",
        options=["risk_free", "spy", "blend"],
        format_func=lambda x: {"risk_free": "Risk-Free", "spy": "100 % SPY", "blend": "SPY + Risk-Free"}[x],
        index=["risk_free", "spy", "blend"].index(PARAMS.get("cash_investment_mode", "spy")),
        horizontal=True,
        help="How the cash not deployed in short positions is invested.",
    )
    if cash_investment_mode in ("risk_free", "blend"):
        cash_yield_annual = st.sidebar.number_input(
            "Risk-Free Rate (%)",
            value=float(PARAMS.get("cash_yield_annual", 0.04) * 100),
            min_value=0.0, max_value=10.0, step=0.25, format="%.2f",
        )
    else:
        cash_yield_annual = float(PARAMS.get("cash_yield_annual", 0.04) * 100)
    if cash_investment_mode == "blend":
        spy_allocation_pct = st.sidebar.slider(
            "SPY allocation (%)",
            min_value=10, max_value=90,
            value=int(PARAMS.get("spy_allocation_pct", 0.40) * 100),
            step=5, format="%d%%",
            help="Fraction of uninvested cash allocated to SPY; remainder earns the risk-free rate.",
        )
    else:
        spy_allocation_pct = int(PARAMS.get("spy_allocation_pct", 0.40) * 100)

st.sidebar.divider()

# ── Strategy ──────────────────────────────────────────────────────────────

st.sidebar.header("Strategy")
_strategy_labels = {
    "short_strangle": "Short Strangle",
    "iron_condor": "Iron Condor",
}
_mode_options = list(_strategy_labels.keys())
_default_mode = PARAMS.get("strategy_mode", "short_strangle")
strategy_mode = st.sidebar.radio(
    "Variant",
    options=_mode_options,
    format_func=lambda k: _strategy_labels[k],
    index=_mode_options.index(_default_mode) if _default_mode in _mode_options else 0,
    horizontal=True,
    help=(
        "Short Strangle: naked short put + short call (undefined risk). "
        "Iron Condor: adds long wings at `wing_delta` — defined risk, lower credit."
    ),
)
is_iron_condor = strategy_mode == "iron_condor"
target_delta = st.sidebar.slider(
    "Target Delta", min_value=0.05, max_value=0.30,
    value=PARAMS["target_delta"], step=0.01, format="%.2f",
)
if is_iron_condor:
    wing_delta = st.sidebar.slider(
        "Wing Delta (long legs)", min_value=0.02, max_value=0.10,
        value=float(PARAMS.get("wing_delta", 0.05)), step=0.01, format="%.2f",
        help="Delta for the long put/call wings that cap tail risk.",
    )
else:
    wing_delta = float(PARAMS.get("wing_delta", 0.05))
dte_min = st.sidebar.number_input("Min DTE", value=PARAMS["dte_min"], min_value=14, max_value=60)
dte_max = st.sidebar.number_input("Max DTE", value=PARAMS["dte_max"], min_value=21, max_value=90)
profit_target_pct = st.sidebar.slider(
    "Profit Target (% of premium)",
    min_value=0, max_value=100,
    value=int(PARAMS["profit_target_pct"] * 100),
    step=5, format="%d%%",
)
stop_loss_enabled = st.sidebar.checkbox(
    "Enable Stop Loss",
    value=PARAMS.get("use_price_stop", False) and not is_iron_condor,
    disabled=is_iron_condor,
    help=(
        "Disabled for iron condors — the long wings already cap maximum loss."
        if is_iron_condor else None
    ),
)
stop_loss_pct = st.sidebar.slider(
    "Stop Loss (% of premium)",
    min_value=50, max_value=500,
    value=int(PARAMS["stop_loss_pct"] * 100),
    step=25, format="%d%%",
    disabled=not stop_loss_enabled or is_iron_condor,
)
single_position = st.sidebar.checkbox(
    "Single position (no overlap)", value=PARAMS["single_position"],
    help=(
        "Skip new monthly entries while a prior trade or roll chain is still open. "
        "Disable for portfolio/laddering mode where concurrent positions are allowed."
    ),
)

st.sidebar.divider()

# ── Roll Management ───────────────────────────────────────────────────────

st.sidebar.header("Roll Management")
manage_at_dte = st.sidebar.number_input(
    "Manage at DTE", value=PARAMS["manage_at_dte"], min_value=7, max_value=45,
    help="Close or roll the position when this many calendar days remain until expiration. Tastytrade standard: 21 DTE.",
)
roll_for_credit = st.sidebar.checkbox(
    "Roll at 21 DTE for credit", value=PARAMS["roll_for_credit"],
    help=(
        "When checked, roll the strangle at manage_at_dte into a new 45-DTE expiration, "
        "collecting net credit. When unchecked, close the position flat."
    ),
)
max_rolls = st.sidebar.number_input(
    "Max Rolls", value=PARAMS["max_rolls"], min_value=0, max_value=10,
    help="Maximum consecutive rolls per original position chain. After this limit, the position is closed flat at the next manage_at_dte.",
)

st.sidebar.divider()

# ── Defensive Leg Rolls ───────────────────────────────────────────────────

st.sidebar.header("🛡️ Defensive Leg Rolls")
defensive_roll = st.sidebar.checkbox(
    "Enable defensive leg roll", value=PARAMS["defensive_leg_roll_enabled"],
    help="Roll untested side when tested side delta exceeds threshold",
)
defensive_trigger_delta = st.sidebar.slider(
    "Trigger delta", min_value=0.20, max_value=0.50,
    value=PARAMS.get("defensive_trigger_delta", 0.30),
    step=0.01, format="%.2f", disabled=not defensive_roll,
)
leg_roll_target_delta = st.sidebar.slider(
    "Target delta", min_value=0.05, max_value=0.30,
    value=PARAMS.get("leg_roll_target_delta", 0.16),
    step=0.01, format="%.2f", disabled=not defensive_roll,
)

st.sidebar.divider()

# ── VIX Filter ────────────────────────────────────────────────────────────

st.sidebar.header("VIX Filter")
vix_filter_enabled = st.sidebar.checkbox(
    "Enable VIX filter", value=PARAMS["vix_entry_filter_enabled"],
    help="Applies to both new monthly entries and 21-DTE roll continuations. "
         "When VIX exceeds the threshold, new entries are skipped and rolls "
         "are closed flat instead of being rolled into a new position.",
)
vix_entry_max = st.sidebar.number_input(
    "Max VIX for entry / roll", value=PARAMS["vix_entry_max"],
    min_value=10.0, max_value=80.0, step=1.0, disabled=not vix_filter_enabled,
)


# ── Advanced (collapsed) ──────────────────────────────────────────────────

with st.sidebar.expander("🔧 Advanced — Pricing"):
    mode = st.radio(
        "Pricing Mode", options=["synthetic", "market"],
        index=0 if PARAMS["mode"] == "synthetic" else 1, horizontal=True,
    )
    risk_free_rate = st.number_input(
        "Risk-free rate (%)", value=float(PARAMS.get("risk_free_rate", 4.5) * 100),
        min_value=0.0, max_value=20.0, step=0.25, format="%.2f",
    )
    put_slope = st.number_input(
        "Put slope", value=float(PARAMS.get("put_slope", 0.30)), step=0.01, format="%.2f",
    )
    call_slope = st.number_input(
        "Call slope", value=float(PARAMS.get("call_slope", 0.10)), step=0.01, format="%.2f",
    )

# ── Build params dict ────────────────────────────────────────────────────

def build_params() -> dict:
    p = dict(PARAMS)
    p.update({
        "start_date": str(start_date),
        "end_date": str(end_date),
        "initial_balance": float(initial_balance),
        "strategy_mode": strategy_mode,
        "wing_delta": float(wing_delta),
        "target_delta": float(target_delta),
        "dte_min": int(dte_min),
        "dte_max": int(dte_max),
        "profit_target_pct": float(profit_target_pct) / 100.0,
        "use_price_stop": bool(stop_loss_enabled) and not is_iron_condor,
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
            "cash_investment_mode": cash_investment_mode,
            "spy_allocation_pct": float(spy_allocation_pct) / 100.0,
        })
    return p


# ── Main area ────────────────────────────────────────────────────────────

st.title("📊 SPY Short Strangle Backtest")
st.caption("Monthly short strangle · 30–45 DTE · configurable profit target & stop")

# Run button
col1, col2 = st.columns([1, 4])
with col1:
    run_clicked = st.button("🚀 Run Backtest", type="primary", width='stretch')
with col2:
    _wing_txt = f" · wings @ {wing_delta:.2f}Δ" if is_iron_condor else ""
    st.caption(
        f"Next run: **{_strategy_labels[strategy_mode]}**{_wing_txt} · "
        f"{'portfolio' if is_portfolio else 'single position'} · {mode} pricing"
    )

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
            trades, equity_df, portfolio, skipped_vix = run_portfolio_backtest(
                data, params, engine
            )
            equity_curve = equity_df["total_equity"] if not equity_df.empty else pd.Series(dtype=float)
            skipped_entries = 0
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

    # ── Shared derived values ────────────────────────────────────────────
    if is_portfolio and equity_df is not None and not equity_df.empty:
        final_balance = float(equity_df["total_equity"].iloc[-1])
    else:
        final_balance = float(equity_curve.iloc[-1]) if len(equity_curve) > 0 else params["initial_balance"]

    years = (
        pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
    ).days / 365.25
    ann_return = (final_balance / params["initial_balance"]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    mdd = metrics.get("mdd", 0)
    calmar = ann_return / abs(mdd) if mdd else float("nan")

    spy_cagr = (1 + metrics.get("spy_total_return", 0)) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    spy_final = params["initial_balance"] * (1 + metrics.get("spy_total_return", 0))

    # SPY MDD and Calmar computed from raw price series
    spy_window = data.loc[
        pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]),
        "spy_close",
    ]
    if not spy_window.empty:
        _pk = np.maximum.accumulate(spy_window.values)
        spy_mdd = float(((spy_window.values - _pk) / _pk).min())
        spy_calmar = spy_cagr / abs(spy_mdd) if spy_mdd != 0 else float("nan")
    else:
        spy_mdd = 0.0
        spy_calmar = float("nan")

    # ── 1. Account & Portfolio ───────────────────────────────────────────
    st.header("💼 Account & Portfolio")

    col1, col2, col3 = st.columns(3)
    col1.metric("Initial Balance", f"${params['initial_balance']:,.0f}")
    col2.metric("Final Balance — Portfolio", f"${final_balance:,.0f}",
                delta=f"{metrics.get('tot', 0)*100:.1f}%")
    col3.metric("Final Balance — SPY B&H", f"${spy_final:,.0f}",
                delta=f"{metrics.get('spy_total_return', 0)*100:.1f}%")

    if is_portfolio:
        col1, col2, col3 = st.columns(3)
        col1.metric("Avg BPR Util", f"{metrics.get('avg_bpr_util', 0):.1f}%")
        col2.metric(
            "Peak BPR Util",
            f"{metrics.get('peak_bpr_util', 0):.1f}%",
            help=(
                "Peak BPR can exceed 100% of the cap: existing positions' margin requirements "
                "grow as the market moves against them. The cap only gates new entries."
            ),
        )
        col3.metric("Cash Yield Earned", f"${metrics.get('cash_yield_earned', 0):,.0f}")

    # ── 2. Performance Summary ───────────────────────────────────────────
    st.header("📈 Performance Summary")

    def _fmt_calmar(v):
        return f"{v:.2f}" if not np.isnan(v) else "—"

    _blank_row = {"Total Return": "", "Annual Return": "", "Sharpe": "", "Max Drawdown": "", "Calmar": ""}

    perf_rows = {"Portfolio": {
        "Total Return": f"{metrics.get('tot', 0)*100:.1f}%",
        "Annual Return": f"{ann_return*100:.1f}%",
        "Sharpe": f"{metrics.get('sharpe', 0):.2f}",
        "Max Drawdown": f"{mdd*100:.1f}%",
        "Calmar": _fmt_calmar(calmar),
    }}

    if is_portfolio:
        _init = params["initial_balance"]
        _short_pnl = sum(t.pnl for t in trades if t.pnl is not None)
        _cash_yield_total = metrics.get("cash_yield_earned", 0.0)
        _cash_mode = params.get("cash_investment_mode", "risk_free")
        _spy_alloc = params.get("spy_allocation_pct", 0.0)

        if _cash_mode == "spy":
            _spy_cash = _cash_yield_total
            _rf_cash = 0.0
        elif _cash_mode == "risk_free":
            _spy_cash = 0.0
            _rf_cash = _cash_yield_total
        else:  # blend
            _spy_cash = _cash_yield_total * _spy_alloc
            _rf_cash = _cash_yield_total * (1 - _spy_alloc)

        def _tot(pnl):
            return pnl / _init if _init else 0.0

        def _ann(tot):
            return (1 + tot) ** (1 / years) - 1 if years > 0 and tot > -1 else 0.0

        _short_label = (
            "  o/w iron condors"
            if params.get("strategy_mode") == "iron_condor"
            else "  o/w short strangles"
        )
        perf_rows[_short_label] = {
            "Total Return": f"{_tot(_short_pnl)*100:.1f}%",
            "Annual Return": f"{_ann(_tot(_short_pnl))*100:.1f}%",
            "Sharpe": "—", "Max Drawdown": "—", "Calmar": "—",
        }
        perf_rows["  o/w SPY"] = {
            "Total Return": f"{_tot(_spy_cash)*100:.1f}%",
            "Annual Return": f"{_ann(_tot(_spy_cash))*100:.1f}%",
            "Sharpe": "—", "Max Drawdown": "—", "Calmar": "—",
        }
        perf_rows["  o/w risk-free"] = {
            "Total Return": f"{_tot(_rf_cash)*100:.1f}%",
            "Annual Return": f"{_ann(_tot(_rf_cash))*100:.1f}%",
            "Sharpe": "—", "Max Drawdown": "—", "Calmar": "—",
        }

    perf_rows["SPY B&H"] = {
        "Total Return": f"{metrics.get('spy_total_return', 0)*100:.1f}%",
        "Annual Return": f"{spy_cagr*100:.1f}%",
        "Sharpe": f"{metrics.get('spy_sharpe', 0):.2f}",
        "Max Drawdown": f"{spy_mdd*100:.1f}%",
        "Calmar": _fmt_calmar(spy_calmar),
    }

    perf_df = pd.DataFrame(perf_rows).T.reset_index().rename(columns={"index": ""})

    _bold_labels = {"Portfolio", "SPY B&H"}

    def _bold_perf(row):
        return ["font-weight: bold"] * len(row) if row[""] in _bold_labels else [""] * len(row)

    st.dataframe(
        perf_df.style.apply(_bold_perf, axis=1).hide(axis="index"),
        width='stretch',
    )

    # ── 3. Trade Statistics ───────────────────────────────────────────────
    st.header("📋 Trade Statistics")

    _primary_trades = [t for t in trades if t.parent_trade_num is None]
    _rolled_trades = [t for t in trades if t.parent_trade_num is not None]

    def _trade_row(label, subset):
        pnls = [t.pnl for t in subset if t.pnl is not None]
        n = len(subset)
        wr = f"{sum(1 for p in pnls if p > 0) / len(pnls) * 100:.1f}%" if pnls else "—"
        avg = f"${sum(pnls) / len(pnls):,.0f}" if pnls else "—"
        return {"": label, "# Trades": n, "Win Rate": wr, "Avg P&L": avg}

    stats_rows = [
        _trade_row("All Executed", trades),
        _trade_row("  Primary", _primary_trades),
        _trade_row("  Rolled", _rolled_trades),
    ]

    def _bold_all_executed(row):
        return ["font-weight: bold"] * len(row) if row[""] == "All Executed" else [""] * len(row)

    st.dataframe(
        pd.DataFrame(stats_rows).style.apply(_bold_all_executed, axis=1),
        hide_index=True, width='stretch',
    )

    if is_portfolio:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Peak Positions", metrics.get("peak_positions", 0))
        col2.metric("Avg Positions", f"{metrics.get('avg_positions', 0):.1f}")
        col3.metric("Max Consec. Losses", metrics.get("max_streak", 0))
        col4.metric("Skipped — VIX filter", skipped_vix)
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Skipped — single position", skipped_entries)
        col2.metric("Skipped — VIX filter", skipped_vix)
        col3.metric("Max Consec. Losses", metrics.get("max_streak", 0))

    # ── Charts ───────────────────────────────────────────────────────────
    st.header("📉 Charts")

    def _add_year_separators(fig, start, end):
        """Add subtle vertical year-boundary lines to a Plotly figure."""
        s_year = pd.Timestamp(start).year + 1
        e_year = pd.Timestamp(end).year + 1
        for yr in range(s_year, e_year):
            fig.add_vline(
                x=f"{yr}-01-01",
                line=dict(color="rgba(150,150,150,0.25)", width=1, dash="dot"),
            )
        return fig

    # Equity curve
    st.subheader("Equity Curve")
    if is_portfolio and equity_df is not None and not equity_df.empty:
        _total_dates = equity_df.index
        _total_equity = equity_df["total_equity"].values
        _pk_eq = np.maximum.accumulate(_total_equity)
        _drawdown = (_total_equity - _pk_eq) / _pk_eq * 100.0

        # Chart 1: Equity vs SPY B&H
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=_total_dates, y=_total_equity, name="Portfolio Equity",
            line=dict(color="#2c3e50", width=2),
        ))
        if "available_cash" in equity_df.columns:
            fig_eq.add_trace(go.Scatter(
                x=_total_dates, y=equity_df["available_cash"].values, name="Available Cash",
                line=dict(color="#95a5a6", width=1, dash="dot"),
                visible="legendonly",
            ))
        _spy_eq = data.loc[_total_dates[0]:_total_dates[-1], "spy_close"]
        if not _spy_eq.empty:
            _spy_norm = _spy_eq / float(_spy_eq.iloc[0]) * params["initial_balance"]
            fig_eq.add_trace(go.Scatter(
                x=_spy_norm.index, y=_spy_norm.values, name="SPY B&H",
                line=dict(color="#e67e22", width=1.5, dash="dash"), opacity=0.7,
            ))
        _add_year_separators(fig_eq, params["start_date"], params["end_date"])
        fig_eq.update_layout(
            title="Equity Curve vs SPY Benchmark",
            yaxis=dict(title="Equity ($)", tickprefix="$", hoverformat="$,.0f"),
            hovermode="x unified", template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_eq, width='stretch')

        # Chart 2: Drawdown
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=_total_dates, y=_drawdown, name="Drawdown %",
            fill="tozeroy", line=dict(color="#e74c3c", width=1),
        ))
        _add_year_separators(fig_dd, params["start_date"], params["end_date"])
        fig_dd.update_layout(
            title="Drawdown (%)",
            yaxis=dict(title="DD %", ticksuffix="%", hoverformat=".2f"),
            hovermode="x unified", template="plotly_white",
        )
        st.plotly_chart(fig_dd, width='stretch')

        # Chart 3: BPR Utilization
        if "utilized_bpr" in equity_df.columns:
            _max_bpr_cap = params.get("initial_balance", 50_000) * params.get("max_bpr_allocation", 0.30)
            fig_bpr = go.Figure()
            fig_bpr.add_trace(go.Scatter(
                x=_total_dates, y=equity_df["utilized_bpr"].values, name="Utilized BPR",
                fill="tozeroy", line=dict(color="#3498db", width=1),
            ))
            fig_bpr.add_trace(go.Scatter(
                x=[_total_dates[0], _total_dates[-1]], y=[_max_bpr_cap, _max_bpr_cap],
                name="Max BPR Cap", line=dict(color="#e74c3c", width=1, dash="dash"),
            ))
            _add_year_separators(fig_bpr, params["start_date"], params["end_date"])
            fig_bpr.update_layout(
                title="BPR Utilization (Margin Usage)",
                yaxis=dict(title="BPR ($)", tickprefix="$", hoverformat="$,.0f"),
                hovermode="x unified", template="plotly_white",
            )
            st.plotly_chart(fig_bpr, width='stretch')

        # Chart 4: Open Positions
        if "open_positions" in equity_df.columns:
            fig_pos = go.Figure()
            fig_pos.add_trace(go.Scatter(
                x=_total_dates, y=equity_df["open_positions"].values, name="Open Positions",
                line=dict(color="#27ae60", width=2), mode="lines+markers", marker=dict(size=4),
            ))
            _add_year_separators(fig_pos, params["start_date"], params["end_date"])
            fig_pos.update_layout(
                title="Open Positions Count",
                yaxis=dict(title="Count", hoverformat=",.0f"),
                hovermode="x unified", template="plotly_white",
            )
            st.plotly_chart(fig_pos, width='stretch')

        # Portfolio Allocation (100% stacked area)
        st.subheader("Portfolio Allocation")
        _alloc_dates = equity_df.index
        _avail_cash = equity_df["available_cash"].values
        _util_bpr = equity_df["utilized_bpr"].values if "utilized_bpr" in equity_df.columns else np.zeros(len(_alloc_dates))

        _cash_mode = params.get("cash_investment_mode", "risk_free")
        _spy_alloc_pct = params.get("spy_allocation_pct", 0.0)
        if _cash_mode == "spy":
            _spy_alloc_vals = _avail_cash
            _rf_alloc_vals = np.zeros(len(_alloc_dates))
        elif _cash_mode == "risk_free":
            _spy_alloc_vals = np.zeros(len(_alloc_dates))
            _rf_alloc_vals = _avail_cash
        else:  # blend
            _spy_alloc_vals = _avail_cash * _spy_alloc_pct
            _rf_alloc_vals = _avail_cash * (1 - _spy_alloc_pct)

        fig_alloc = go.Figure()
        fig_alloc.add_trace(go.Scatter(
            x=_alloc_dates, y=_util_bpr,
            name="Short Strangles (BPR)", stackgroup="one", groupnorm="percent",
            line=dict(width=0), fillcolor="rgba(155,89,182,0.75)",
        ))
        fig_alloc.add_trace(go.Scatter(
            x=_alloc_dates, y=_spy_alloc_vals,
            name="SPY", stackgroup="one", groupnorm="percent",
            line=dict(width=0), fillcolor="rgba(231,76,60,0.65)",
        ))
        fig_alloc.add_trace(go.Scatter(
            x=_alloc_dates, y=_rf_alloc_vals,
            name="Risk-Free", stackgroup="one", groupnorm="percent",
            line=dict(width=0), fillcolor="rgba(52,152,219,0.65)",
        ))
        _add_year_separators(fig_alloc, params["start_date"], params["end_date"])
        fig_alloc.update_layout(
            yaxis=dict(title="Allocation (%)", ticksuffix="%", hoverformat=".1f"),
            hovermode="x unified", template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_alloc, width='stretch')

    else:
        eq_df = pd.DataFrame({"Date": equity_curve.index, "Strangle": equity_curve.values})
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

        exit_colors = {
            "PROFIT": "#2ecc71",
            "STOP": "#e74c3c",
            "21DTE": "#3498db",
            "EXPIRY": "#f39c12",
            "ROLLED": "#9b59b6",
            "FORCE_CLOSE": "#7f8c8d",
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

        _add_year_separators(fig, params["start_date"], params["end_date"])
        fig.update_layout(
            barmode="overlay",
            xaxis=dict(title="Date", tickformat="%b %Y", tickmode="auto", nticks=20),
            yaxis=dict(title="P&L ($)", hoverformat="$,.0f"),
            legend_title="Exit Type",
            hovermode="x unified",
        )
        st.plotly_chart(fig, width='stretch')

    # Exit breakdown
    st.subheader("Exit Breakdown")
    exit_types = {}
    total_trades_for_pct = len(trades) if trades else 1
    for t in trades:
        et = t.exit_type or "UNKNOWN"
        if et not in exit_types:
            exit_types[et] = {"count": 0, "wins": 0, "total_pnl": 0.0}
        exit_types[et]["count"] += 1
        _pnl = t.pnl or 0.0
        exit_types[et]["total_pnl"] += _pnl
        if _pnl > 0:
            exit_types[et]["wins"] += 1

    _exit_order = ["PROFIT", "ROLLED", "21DTE"]
    _sorted_keys = _exit_order + [k for k in exit_types if k not in _exit_order]

    exit_rows = []
    for k in _sorted_keys:
        if k not in exit_types:
            continue
        v = exit_types[k]
        c = v["count"]
        wr = f"{v['wins']/c*100:.1f}%" if c else "—"
        exit_rows.append({
            "Exit Type": k,
            "Count": c,
            "% of Trades": f"{c/total_trades_for_pct*100:.1f}%",
            "Win Rate": wr,
            "Total P&L": f"${v['total_pnl']:,.0f}",
            "Avg P&L": f"${v['total_pnl']/c:,.0f}" if c else "—",
        })

    _total_count = sum(v["count"] for v in exit_types.values())
    _total_wins = sum(v["wins"] for v in exit_types.values())
    _total_pnl_all = sum(v["total_pnl"] for v in exit_types.values())
    exit_rows.append({
        "Exit Type": "Total",
        "Count": _total_count,
        "% of Trades": "100.0%",
        "Win Rate": f"{_total_wins/_total_count*100:.1f}%" if _total_count else "—",
        "Total P&L": f"${_total_pnl_all:,.0f}",
        "Avg P&L": f"${_total_pnl_all/_total_count:,.0f}" if _total_count else "—",
    })

    exit_df = pd.DataFrame(exit_rows)

    def _bold_total(row):
        weight = "font-weight: bold" if row["Exit Type"] == "Total" else ""
        return [weight] * len(row)

    st.dataframe(exit_df.style.apply(_bold_total, axis=1), width='stretch', hide_index=True)

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
        _add_year_separators(fig_cum, params["start_date"], params["end_date"])
        fig_cum.update_layout(
            xaxis=dict(title="Date", tickformat="%b %Y", tickmode="auto", nticks=20),
            yaxis=dict(title="Cumulative P&L ($)", hoverformat="$,.0f"),
            hovermode="x unified",
        )
        st.plotly_chart(fig_cum, width='stretch')

    # VIX with entry points
    st.subheader("VIX with Entry Points")
    # Extend VIX series to cover all entry dates (trades near end_date may extend beyond)
    _all_entry_dates = [t.entry_date for t in trades]
    _vix_end = max(
        pd.Timestamp(params["end_date"]),
        max(_all_entry_dates) if _all_entry_dates else pd.Timestamp(params["end_date"]),
    )
    _vix_series = data.loc[pd.Timestamp(params["start_date"]) : _vix_end, "vix_close"]
    fig_vix = go.Figure()
    fig_vix.add_trace(go.Scatter(
        x=_vix_series.index, y=_vix_series.values,
        name="VIX", line=dict(color="#95a5a6", width=0.8), opacity=0.8,
    ))
    # Regime threshold lines — boundaries for the VIX Regime table
    _vix_low = params.get("vix_low", 15)
    _vix_high = params.get("vix_high", 25)
    fig_vix.add_hline(
        y=_vix_low, line=dict(color="#3498db", width=1, dash="dash"),
        annotation_text="Regime: Low / Normal", annotation_position="bottom right",
    )
    fig_vix.add_hline(
        y=_vix_high, line=dict(color="#e67e22", width=1, dash="dash"),
        annotation_text="Regime: Normal / Elevated", annotation_position="top right",
    )
    # VIX entry filter line (if enabled)
    if params.get("vix_entry_filter_enabled", False):
        _vix_filter_max = params.get("vix_entry_max", 30.0)
        fig_vix.add_hline(
            y=_vix_filter_max, line=dict(color="#e74c3c", width=1.5, dash="dot"),
            annotation_text=f"VIX filter ({_vix_filter_max:.0f})",
            annotation_position="top left",
        )
    # All entry dots (blue, filled) — show every trade entry including rolled continuations
    if trades:
        fig_vix.add_trace(go.Scatter(
            x=[t.entry_date for t in trades],
            y=[t.entry_vix for t in trades],
            mode="markers", name="Entry",
            marker=dict(color="#2980b9", size=10, symbol="circle",
                        line=dict(color="#1a5276", width=1)),
            customdata=[t.trade_num for t in trades],
            hovertemplate="Trade #%{customdata}<br>%{x|%b %d, %Y}<br>VIX: %{y:.1f}<extra></extra>",
        ))
    # Skipped entries (open red circles) — portfolio mode only
    if is_portfolio and portfolio is not None and portfolio.vix_blocked_dates:
        _skip_dates = [d for d, v in portfolio.vix_blocked_dates]
        _skip_vix = [v for d, v in portfolio.vix_blocked_dates]
        fig_vix.add_trace(go.Scatter(
            x=_skip_dates, y=_skip_vix,
            mode="markers", name="Skipped (VIX filter)",
            marker=dict(color="rgba(0,0,0,0)", size=10, symbol="circle",
                        line=dict(color="#e74c3c", width=2)),
            hovertemplate="%{x|%b %d, %Y}<br>VIX: %{y:.1f} — skipped<extra></extra>",
        ))
    _add_year_separators(fig_vix, params["start_date"], _vix_end)
    fig_vix.update_layout(
        yaxis=dict(title="VIX", hoverformat=".1f"),
        hovermode="closest", template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_vix, width='stretch')

    # Returns distribution
    st.subheader("Returns Distribution")
    _pct_vals = [t.pnl_pct * 100 for t in trades if t.pnl_pct is not None]
    if _pct_vals:
        _mean_pct = float(np.mean(_pct_vals))
        _exit_hist_colors = {
            "PROFIT": "#2ecc71", "STOP": "#e74c3c", "21DTE": "#3498db",
            "EXPIRY": "#f39c12", "ROLLED": "#9b59b6", "FORCE_CLOSE": "#7f8c8d",
            "UNKNOWN": "#95a5a6",
        }
        fig_hist = go.Figure()
        for etype, color in _exit_hist_colors.items():
            _vals = [t.pnl_pct * 100 for t in trades if t.pnl_pct is not None and t.exit_type == etype]
            if _vals:
                fig_hist.add_trace(go.Histogram(
                    x=_vals, name=etype, marker_color=color, opacity=0.75,
                    nbinsx=max(10, len(_pct_vals) // 4),
                ))
        fig_hist.add_vline(x=0, line=dict(color="white", width=1.5))
        fig_hist.add_vline(
            x=_mean_pct, line=dict(color="#fabd2f", width=1.5, dash="dash"),
            annotation_text=f"Mean {_mean_pct:.1f}%", annotation_position="top right",
        )
        fig_hist.update_layout(
            barmode="stack",
            xaxis=dict(title="P&L (% of premium)", hoverformat=".1f"),
            yaxis=dict(title="# Trades"),
            hovermode="x unified", template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_hist, width='stretch')

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

    # Filter controls (outside expander so they're always visible)
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

    # Build trade dataframe
    trade_df = pd.DataFrame([
        {
            "#": t.trade_num,
            "Entry": t.entry_date.strftime("%Y-%m-%d"),
            "Expiry": t.expiration.strftime("%Y-%m-%d") if t.expiration else "—",
            "DTE": t.entry_dte,
            "VIX": f"{t.entry_vix:.1f}",
            "Put K": int(t.put_strike),
            "Call K": int(t.call_strike),
            "Credit": f"${t.net_credit:.0f}",
            "Exit": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "Open",
            "Exit Type": t.exit_type or "—",
            "Days": (t.exit_date - t.entry_date).days if t.exit_date else None,
            "P&L": f"${t.pnl:+,.0f}" if t.pnl is not None else "—",
            "P&L %": f"{t.pnl_pct*100:+.0f}%" if t.pnl_pct is not None else "—",
        }
        for t in filtered_trades
    ])

    # Color the Exit Type cell by exit type; all other cells inherit theme default
    exit_color_map = {
        "PROFIT":      "#2ecc71",
        "STOP":        "#e74c3c",
        "21DTE":       "#3498db",
        "EXPIRY":      "#e67e22",
        "ROLLED":      "#9b59b6",
        "FORCE_CLOSE": "#7f8c8d",
        "UNKNOWN":     "#95a5a6",
    }

    def color_exit_type(val):
        color = exit_color_map.get(val, "")
        return f"color: {color}; font-weight: bold" if color else ""

    with st.expander(f"Show all {len(trade_df)} trades", expanded=False):
        if not trade_df.empty and "Exit Type" in trade_df.columns:
            styled_df = (
                trade_df.style
                .map(color_exit_type, subset=["Exit Type"])
                .hide(axis="index")
            )
            st.table(styled_df)
        else:
            st.table(trade_df)

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