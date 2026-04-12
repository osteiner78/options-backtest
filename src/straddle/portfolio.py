"""Portfolio management: PortfolioManager, Reg-T margin, and portfolio backtest engine.

Implements a multi-position portfolio approach for the SPY short strangle strategy:

- **PortfolioManager** — central ledger tracking cash, margin, open positions, and equity curve.
- **calculate_reg_t_strangle_margin** — standard Regulation T margin for naked short strangles.
- **run_portfolio_backtest** — chronological simulation loop with laddering, daily marking,
  cash yield, and portfolio-level reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm
from straddle.params import RISK_FREE_RATE_DEFAULT

from straddle.strategy import (
    Trade, 
    get_monthly_expiration, 
    evaluate_trade_step, 
    TradeStepResult
)


# ── Phase 2: Reg-T Margin Engine ─────────────────────────────────────────

def calculate_reg_t_strangle_margin(
    underlying_price: float,
    put_strike: float,
    call_strike: float,
    put_ask_price: float,
    call_ask_price: float,
) -> float:
    """Calculate standard Regulation T margin for a short options strangle on an ETF.

    Follows standard broker rules for a naked short strangle:

    1. Naked margin for the Put:
       (20% × underlying_price − put OTM amount + put_ask_price) × 100
       where put OTM amount = max(underlying_price − put_strike, 0)

    2. Naked margin for the Call:
       (20% × underlying_price − call OTM amount + call_ask_price) × 100
       where call OTM amount = max(call_strike − underlying_price, 0)

    3. Total BPR for the strangle combo:
       MAX(put_naked_margin, call_naked_margin) + premium of the OTHER side

    4. Minimum margin floor: 10% × underlying_price × 100 + total premium

    Args:
        underlying_price: Current SPY price.
        put_strike: Strike of the short put.
        call_strike: Strike of the short call.
        put_ask_price: Per-share ask price of the put.
        call_ask_price: Per-share ask price of the call.

    Returns:
        Total combined BPR (Buying Power Reduction) required for 1 contract.
    """
    # OTM amounts
    put_otm = max(underlying_price - put_strike, 0.0)
    call_otm = max(call_strike - underlying_price, 0.0)

    # Naked margin requirements (per contract, ×100 shares)
    put_naked = (0.20 * underlying_price - put_otm + put_ask_price) * 100.0
    call_naked = (0.20 * underlying_price - call_otm + call_ask_price) * 100.0

    # Total BPR: higher naked margin + premium of the other side
    put_premium = put_ask_price * 100.0
    call_premium = call_ask_price * 100.0

    if put_naked >= call_naked:
        total_bpr = put_naked + call_premium
    else:
        total_bpr = call_naked + put_premium

    # Minimum margin floor: 10% of underlying + total premium
    min_floor = (0.10 * underlying_price * 100.0) + put_premium + call_premium

    return max(total_bpr, min_floor)


# ── Phase 1: Portfolio State Manager ─────────────────────────────────────

@dataclass
class PortfolioPosition:
    """Wrapper around a Trade with margin tracking for portfolio use."""

    trade: Trade
    entry_bpr: float  # margin requirement at entry (for reference)
    current_bpr: float = 0.0  # dynamically recalculated daily


@dataclass
class PortfolioManager:
    """Central ledger for the portfolio backtest.

    Tracks running cash, margin usage, open positions, and daily equity state.
    """

    starting_capital: float = 50_000.0
    max_bpr_allocation: float = 0.30

    # Runtime state
    available_cash: float = field(init=False)
    utilized_bpr: float = field(init=False, default=0.0)
    total_unrealized_liability: float = field(init=False, default=0.0)
    open_positions: Dict[int, PortfolioPosition] = field(init=False, default_factory=dict)
    equity_curve: List[Dict[str, Any]] = field(init=False, default_factory=list)
    next_trade_num: int = field(init=False, default=1)
    last_entry_date: Optional[pd.Timestamp] = field(init=False, default=None)
    entry_cooldown_days: int = 3  # minimum trading days between new entries

    def __post_init__(self) -> None:
        self.available_cash = self.starting_capital

    def reset_daily_aggregates(self) -> None:
        """Reset per-day accumulators before processing positions."""
        self.total_unrealized_liability = 0.0

    def get_total_equity(self) -> float:
        """Return available_cash + current unrealized mark-to-market on open positions."""
        return self.available_cash + self.total_unrealized_liability

    def get_available_bpr_capacity(self) -> float:
        """Return remaining BPR capacity: (starting_capital × max_bpr_allocation) − utilized_bpr."""
        return (self.starting_capital * self.max_bpr_allocation) - self.utilized_bpr

    def record_daily_state(self, date: pd.Timestamp, unrealized_liability: float = 0.0) -> None:
        """Append the current portfolio state to the equity_curve list.
        
        unrealized_liability is expected to be negative (cost to close).
        """
        self.equity_curve.append({
            "date": date,
            "total_equity": self.available_cash + unrealized_liability,
            "utilized_bpr": self.utilized_bpr,
            "available_cash": self.available_cash,
            "open_positions": len(self.open_positions),
        })

    def add_position(self, trade: Trade, bpr: float) -> None:
        """Add a new trade to open_positions and deduct its BPR."""
        pos = PortfolioPosition(
            trade=trade,
            entry_bpr=bpr,
            current_bpr=bpr,
        )
        self.open_positions[trade.trade_num] = pos
        self.utilized_bpr += bpr

    def remove_position(self, trade_num: int) -> Optional[PortfolioPosition]:
        """Remove a trade from open_positions and release its BPR."""
        pos = self.open_positions.pop(trade_num, None)
        if pos is not None:
            self.utilized_bpr -= pos.current_bpr
        return pos

    def can_enter_new_trade(
        self,
        estimated_bpr: float,
        eval_date: pd.Timestamp,
        all_trading_dates: pd.DatetimeIndex,
    ) -> bool:
        """Check if a new trade can be entered (BPR capacity + cooldown)."""
        if self.get_available_bpr_capacity() < estimated_bpr:
            return False
        if self.last_entry_date is None:
            return True
        # Count trading days since last entry
        days_since = all_trading_dates[
            (all_trading_dates > self.last_entry_date) & (all_trading_dates <= eval_date)
        ]
        return len(days_since) >= self.entry_cooldown_days


# ── Phase 3: Portfolio Backtest Engine ───────────────────────────────────

def run_portfolio_backtest(
    data: pd.DataFrame,
    params: dict,
    engine=None,
) -> Tuple[List[Trade], pd.DataFrame, PortfolioManager]:
    """Run a portfolio-style backtest with laddering and dynamic margin.

    This is a chronological simulation that steps forward one trading day at a time,
    managing multiple concurrent positions with Reg-T margin constraints.
    """
    from straddle.engines import make_engine, PricingContext

    created_engine = False
    if engine is None:
        engine = make_engine(params)
        created_engine = True

    try:
        # ── Initialize portfolio ─────────────────────────────────────────────
        portfolio = PortfolioManager(
            starting_capital=params.get("initial_balance", 50_000),
            max_bpr_allocation=params.get("max_bpr_allocation", 0.30),
        )

        # ── Setup ────────────────────────────────────────────────────────────
        all_trading_dates = data.index
        start_ts = pd.Timestamp(params["start_date"])
        end_ts = pd.Timestamp(params["end_date"])
        sim_dates = all_trading_dates[
            (all_trading_dates >= start_ts) & (all_trading_dates <= end_ts)
        ]

        trades: List[Trade] = []
        trade_num = 0
        comm_per_leg = params.get("commission_per_leg", 1.0)

        cash_yield_annual = params.get("cash_yield_annual", 0.04)
        daily_rf_rate = cash_yield_annual / 252.0
        cash_investment_mode = params.get("cash_investment_mode", "risk_free")
        spy_allocation_pct = params.get("spy_allocation_pct", 0.40)
        prev_spy_close: Optional[float] = None

        # ── Main daily loop ─────────────────────────────────────────────────
        for eval_date in tqdm(sim_dates, desc="Simulating portfolio", unit="day"):
            row = data.loc[eval_date]
            spy_close = float(row["spy_close"])
            vix_d = float(row["vix_close"])
            r_d = float(row.get("risk_free_rate", RISK_FREE_RATE_DEFAULT))

            # ── Step 1 & 2: Evaluate open positions and update state ─────────
            portfolio.reset_daily_aggregates()

            # We iterate over a copy because evaluate_trade_step might trigger an exit (remove)
            for trade_num_open, pos in list(portfolio.open_positions.items()):
                t = pos.trade

                # Use unified strategy logic
                res = evaluate_trade_step(t, eval_date, data, engine, params)

                if res.exited:
                    # Handle exit
                    t.exit_date = eval_date
                    t.exit_dte = (t.expiration - eval_date).days
                    t.exit_type = res.exit_type
                    t.pnl = res.pnl
                    t.pnl_pct = res.pnl_pct

                    # Accounting: subtract cost from cash and remove position
                    portfolio.available_cash -= res.close_cost
                    portfolio.remove_position(t.trade_num)
                    trades.append(t)

                    if res.new_trade is not None:
                        # Roll continuation
                        trade_num += 1
                        nt = res.new_trade
                        nt.trade_num = trade_num

                        # Calculate BPR for new trade using engine adjustment
                        new_bpr = calculate_reg_t_strangle_margin(
                            spy_close,
                            nt.put_strike,
                            nt.call_strike,
                            engine.apply_fill_adj(nt.put_mid_ps, "close"),
                            engine.apply_fill_adj(nt.call_mid_ps, "close"),
                        )
                        portfolio.available_cash += nt.net_credit
                        portfolio.add_position(nt, new_bpr)
                        portfolio.last_entry_date = eval_date

                        # Add new liability to daily total
                        portfolio.total_unrealized_liability -= (
                            engine.apply_fill_adj(nt.put_mid_ps + nt.call_mid_ps, "close") * 100.0
                            + 2.0 * comm_per_leg
                        )
                else:
                    # Still open: update liability and recalculate margin
                    portfolio.total_unrealized_liability -= res.close_cost

                    # Update BPR for margin utilization tracking
                    put_ask = engine.apply_fill_adj(res.put_mid_d, "close")
                    call_ask = engine.apply_fill_adj(res.call_mid_d, "close")

                    portfolio.utilized_bpr -= pos.current_bpr  # remove stale value
                    pos.current_bpr = calculate_reg_t_strangle_margin(
                        spy_close,
                        t.active_put_strike,
                        t.active_call_strike,
                        put_ask,
                        call_ask,
                    )
                    portfolio.utilized_bpr += pos.current_bpr  # add updated value

            # ── Step 3: Process entries (laddering) ─────────────────────────
            # Find the expiration first, then price it once — avoids calling
            # get_entry_marks twice (once with T_est=45/365 for a BPR guess,
            # then again with the real expiration). We price with the real
            # expiration from the start and use those marks for both the BPR
            # capacity check and the actual trade entry.
            new_exp = get_monthly_expiration(eval_date, params["dte_min"], params["dte_max"])
            if new_exp is not None:
                entry_dte = (new_exp - eval_date).days
                T_new = entry_dte / 365.0
                entry_ctx = PricingContext(eval_date=eval_date, expiration=new_exp)
                (new_put_k, new_call_k, new_put_mid, new_call_mid, _used_db) = (
                    engine.get_entry_marks(spy_close, T_new, r_d, vix_d, ctx=entry_ctx)
                )
                actual_bpr = calculate_reg_t_strangle_margin(
                    spy_close,
                    new_put_k,
                    new_call_k,
                    engine.apply_fill_adj(new_put_mid, "close"),
                    engine.apply_fill_adj(new_call_mid, "close"),
                )
                new_net_credit = engine.apply_fill_adj(new_put_mid + new_call_mid, "open") * 100.0 - 2.0 * comm_per_leg

                if portfolio.can_enter_new_trade(actual_bpr, eval_date, all_trading_dates) and new_net_credit > 0:
                    trade_num += 1
                    new_trade = Trade(
                        trade_num=trade_num,
                        entry_date=eval_date,
                        expiration=new_exp,
                        entry_dte=entry_dte,
                        put_strike=new_put_k,
                        call_strike=new_call_k,
                        put_mid_ps=new_put_mid,
                        call_mid_ps=new_call_mid,
                        net_credit=new_net_credit,
                        entry_vix=vix_d,
                        used_market_data=_used_db,
                    )
                    new_trade.max_vix = vix_d
                    new_trade.daily_marks = [(eval_date, 0.0)]

                    # Add new credit to cash and register position
                    portfolio.available_cash += new_net_credit
                    portfolio.add_position(new_trade, actual_bpr)
                    portfolio.last_entry_date = eval_date

                    # Update totals for daily state
                    portfolio.total_unrealized_liability -= (
                        engine.apply_fill_adj(new_put_mid + new_call_mid, "close") * 100.0
                        + 2.0 * comm_per_leg
                    )

            # ── Step 4: Cash return (risk-free / SPY / blend) ───────────────
            if portfolio.available_cash > 0:
                spy_daily_ret = (
                    (spy_close / prev_spy_close - 1.0) if prev_spy_close is not None else 0.0
                )
                if cash_investment_mode == "spy":
                    cash_daily_return = spy_daily_ret
                elif cash_investment_mode == "blend":
                    cash_daily_return = (
                        spy_allocation_pct * spy_daily_ret
                        + (1.0 - spy_allocation_pct) * daily_rf_rate
                    )
                else:  # "risk_free"
                    cash_daily_return = daily_rf_rate
                portfolio.available_cash *= (1.0 + cash_daily_return)

            prev_spy_close = spy_close

            # ── Step 5: Record daily state ───────────────────────────────────
            portfolio.record_daily_state(eval_date, portfolio.total_unrealized_liability)

        # ── Phase 4: Final reporting ─────────────────────────────────────────
        equity_df = pd.DataFrame(portfolio.equity_curve)
        if not equity_df.empty:
            equity_df.set_index("date", inplace=True)

        return trades, equity_df, portfolio
    finally:
        if created_engine and hasattr(engine, "close"):
            engine.close()


# ── Phase 4: Portfolio Visualization ─────────────────────────────────────

def plot_portfolio_backtest(
    trades: List[Trade],
    equity_df: pd.DataFrame,
    portfolio: PortfolioManager,
    params: dict,
    output_dir: str = "reports",
    data: pd.DataFrame = None,
) -> str:
    """Generate and save an interactive multi-panel portfolio backtest dashboard."""
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    if equity_df.empty:
        return ""

    # ── Setup ────────────────────────────────────────────────────────────
    total_dates = equity_df.index
    total_equity = equity_df["total_equity"].values
    available_cash = equity_df["available_cash"].values
    utilized_bpr = equity_df["utilized_bpr"].values
    open_positions = equity_df["open_positions"].values
    
    # Drawdown calculation
    pk = np.maximum.accumulate(total_equity)
    drawdown_pct = (total_equity - pk) / pk * 100.0

    # ── Build Dashboard ──────────────────────────────────────────────────
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.4, 0.2, 0.2, 0.2],
        subplot_titles=(
            "Equity Curve vs SPY Benchmark",
            "Drawdown (%)",
            "BPR Utilization (Margin Usage)",
            "Open Positions Count"
        )
    )

    # 1. Equity Curve
    fig.add_trace(
        go.Scatter(x=total_dates, y=total_equity, name="Portfolio Equity", line=dict(color="#2c3e50", width=2)),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(x=total_dates, y=available_cash, name="Available Cash", line=dict(color="#95a5a6", width=1, dash="dot")),
        row=1, col=1
    )
    
    # SPY benchmark
    if data is not None:
        spy_eq = data.loc[total_dates[0]:total_dates[-1], "spy_close"]
        if not spy_eq.empty:
            spy_eq = spy_eq / float(spy_eq.iloc[0]) * params["initial_balance"]
            fig.add_trace(
                go.Scatter(x=spy_eq.index, y=spy_eq.values, name="SPY B&H", line=dict(color="#e67e22", width=1.5, dash="dash"), opacity=0.7),
                row=1, col=1
            )

    # 2. Drawdown
    fig.add_trace(
        go.Scatter(x=total_dates, y=drawdown_pct, name="Drawdown %", fill="tozeroy", line=dict(color="#e74c3c", width=1)),
        row=2, col=1
    )

    # 3. BPR Utilization
    max_bpr_cap = params.get("initial_balance", 50_000) * params.get("max_bpr_allocation", 0.30)
    fig.add_trace(
        go.Scatter(x=total_dates, y=utilized_bpr, name="Utilized BPR", fill="tozeroy", line=dict(color="#3498db", width=1)),
        row=3, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=[total_dates[0], total_dates[-1]], 
            y=[max_bpr_cap, max_bpr_cap], 
            name="Max BPR Cap", 
            line=dict(color="#e74c3c", width=1, dash="dash")
        ),
        row=3, col=1
    )

    # 4. Open Positions
    fig.add_trace(
        go.Scatter(x=total_dates, y=open_positions, name="Open Positions", line=dict(color="#27ae60", width=2), mode="lines+markers", marker=dict(size=4)),
        row=4, col=1
    )

    # ── Layout ───────────────────────────────────────────────────────────
    fig.update_layout(
        height=1000,
        title_text=f"Portfolio Backtest Dashboard: {params['start_date']} → {params['end_date']}",
        template="plotly_white",
        showlegend=True,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    fig.update_yaxes(title_text="Equity ($)", row=1, col=1, tickprefix="$")
    fig.update_yaxes(title_text="DD %", row=2, col=1, ticksuffix="%")
    fig.update_yaxes(title_text="BPR ($)", row=3, col=1, tickprefix="$")
    fig.update_yaxes(title_text="Count", row=4, col=1)

    # Save to HTML
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"portfolio_backtest_{timestamp}.html"
    filepath = output_path / filename

    fig.write_html(str(filepath))
    return str(filepath)
