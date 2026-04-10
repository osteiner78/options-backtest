"""Portfolio management: PortfolioManager, Reg-T margin, and portfolio backtest engine.

Implements a multi-position portfolio approach for the SPY short strangle strategy:

- **PortfolioManager** — central ledger tracking cash, margin, open positions, and equity curve.
- **calculate_reg_t_strangle_margin** — standard Regulation T margin for naked short strangles.
- **run_portfolio_backtest** — chronological simulation loop with laddering, daily marking,
  cash yield, and portfolio-level reporting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from straddle.strategy import Trade, get_monthly_expiration


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
    entry_spy_price: float = 0.0  # SPY price at entry (for margin recalc)


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
    open_positions: Dict[int, PortfolioPosition] = field(init=False, default_factory=dict)
    equity_curve: List[Dict[str, Any]] = field(init=False, default_factory=list)
    next_trade_num: int = field(init=False, default=1)
    last_entry_date: Optional[pd.Timestamp] = field(init=False, default=None)
    entry_cooldown_days: int = 3  # minimum trading days between new entries
    last_unrealized_pnl: float = field(init=False, default=0.0)  # cached from daily loop

    def __post_init__(self) -> None:
        self.available_cash = self.starting_capital

    def get_total_equity(self) -> float:
        """Return available_cash + last computed unrealized P&L from open positions."""
        return self.available_cash + self.last_unrealized_pnl

    def get_available_bpr_capacity(self) -> float:
        """Return remaining BPR capacity: (starting_capital × max_bpr_allocation) − utilized_bpr."""
        return (self.starting_capital * self.max_bpr_allocation) - self.utilized_bpr

    def record_daily_state(self, date: pd.Timestamp, unrealized_pnl: float = 0.0) -> None:
        """Append the current portfolio state to the equity_curve list."""
        self.equity_curve.append({
            "date": date,
            "total_equity": self.available_cash + unrealized_pnl,
            "utilized_bpr": self.utilized_bpr,
            "available_cash": self.available_cash,
            "open_positions": len(self.open_positions),
        })

    def add_position(self, trade: Trade, bpr: float, spy_price: float) -> None:
        """Add a new trade to open_positions and deduct its BPR."""
        pos = PortfolioPosition(
            trade=trade,
            entry_bpr=bpr,
            current_bpr=bpr,
            entry_spy_price=spy_price,
        )
        self.open_positions[trade.trade_num] = pos
        self.utilized_bpr += bpr

    def remove_position(self, trade_num: int) -> Optional[PortfolioPosition]:
        """Remove a trade from open_positions and release its BPR."""
        pos = self.open_positions.pop(trade_num, None)
        if pos is not None:
            self.utilized_bpr -= pos.current_bpr
        return pos

    def recalculate_all_bpr(
        self,
        data: pd.DataFrame,
        eval_date: pd.Timestamp,
        engine,
    ) -> float:
        """Recalculate Reg-T margin for all open positions.

        Returns the total utilized_bpr after recalculation.
        Uses today's EOD ask prices (synthetic mid × 1.05 as proxy for ask).
        """
        total_bpr = 0.0
        row = data.loc[eval_date]
        spy_close = float(row["spy_close"])

        for pos in self.open_positions.values():
            t = pos.trade
            dte_rem = max((t.expiration - eval_date).days, 1)
            vix_d = float(row["vix_close"])
            r_d = float(row.get("risk_free_rate", 0.045))

            # Get per-leg marks (mid prices) from engine
            put_mid = engine.get_leg_mark(
                t.active_put_strike, spy_close, dte_rem, vix_d, r_d, "put",
                eval_date=eval_date, expiration=t.expiration,
            )
            call_mid = engine.get_leg_mark(
                t.active_call_strike, spy_close, dte_rem, vix_d, r_d, "call",
                eval_date=eval_date, expiration=t.expiration,
            )

            # Use mid × 1.05 as proxy for ask (consistent with close_fill_adj)
            put_ask = put_mid * 1.05
            call_ask = call_mid * 1.05

            pos.current_bpr = calculate_reg_t_strangle_margin(
                spy_close,
                t.active_put_strike,
                t.active_call_strike,
                put_ask,
                call_ask,
            )
            total_bpr += pos.current_bpr

        self.utilized_bpr = total_bpr
        return total_bpr

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

    def get_unrealized_pnl(self, data: pd.DataFrame, eval_date: pd.Timestamp, engine) -> float:
        """Sum of unrealized P&L across all open positions at today's marks."""
        total = 0.0
        row = data.loc[eval_date]
        spy_close = float(row["spy_close"])
        vix_d = float(row["vix_close"])
        r_d = float(row.get("risk_free_rate", 0.045))

        for pos in self.open_positions.values():
            t = pos.trade
            dte_rem = max((t.expiration - eval_date).days, 1)
            mid_d = engine.get_daily_mark(
                t.active_put_strike, t.active_call_strike,
                spy_close, dte_rem, vix_d, r_d,
                eval_date=eval_date, expiration=t.expiration,
            )
            close_cost = mid_d * 1.05 * 100.0 + 2.0 * 1.0  # ask fill + commission
            total += t.net_credit - close_cost

        return total


# ── Phase 3: Portfolio Backtest Engine ───────────────────────────────────

def _find_45dte_expiration(
    eval_date: pd.Timestamp,
    data: pd.DataFrame,
    params: dict,
) -> Optional[pd.Timestamp]:
    """Find the monthly expiration closest to 45 DTE from eval_date."""
    # Scan forward for the next valid 3rd-Friday expiration
    for mo in range(0, 4):
        abs_mo = eval_date.month + mo
        exp = _get_third_friday(eval_date.year + (abs_mo - 1) // 12, (abs_mo - 1) % 12 + 1)
        dte = (exp - eval_date).days
        if 30 <= dte <= 60:  # Acceptable range around 45 DTE
            return exp
    return None


def _get_third_friday(year: int, month: int) -> pd.Timestamp:
    """3rd Friday of the given month."""
    first = pd.Timestamp(year=year, month=month, day=1)
    return first + pd.Timedelta(days=(4 - first.weekday()) % 7) + pd.Timedelta(weeks=2)


def run_portfolio_backtest(
    data: pd.DataFrame,
    params: dict,
    engine=None,
) -> Tuple[List[Trade], pd.DataFrame, PortfolioManager]:
    """Run a portfolio-style backtest with laddering and dynamic margin.

    This is a chronological simulation that steps forward one trading day at a time,
    managing multiple concurrent positions with Reg-T margin constraints.

    Args:
        data: DataFrame with SPY OHLC, VIX, and risk-free rate.
        params: Flat PARAMS dict.
        engine: Pricing engine. If None, creates SyntheticEngine.

    Returns:
        (trades, equity_df, portfolio) where:
        - trades: list of all closed Trade objects
        - equity_df: DataFrame of daily portfolio state
        - portfolio: the PortfolioManager instance with final state
    """
    from straddle.engines import SyntheticEngine, make_engine

    if engine is None:
        engine = make_engine(params)

    # ── Initialize portfolio ─────────────────────────────────────────────
    portfolio = PortfolioManager(
        starting_capital=params.get("initial_balance", 50_000),
        max_bpr_allocation=params.get("max_bpr_allocation", 0.30),
    )

    # ── Setup ────────────────────────────────────────────────────────────
    all_trading_dates = data.index
    start_ts = pd.Timestamp(params["start_date"])
    end_ts = pd.Timestamp(params["end_date"])
    sim_dates = all_trading_dates[(all_trading_dates >= start_ts) & (all_trading_dates <= end_ts)]

    trades: List[Trade] = []
    trade_num = 0
    comm_per_leg = params.get("commission_per_leg", 1.0)
    eff_o_adj = params.get("open_fill_adj", -0.05)
    _real = getattr(engine, "uses_real_fills", False)
    if _real:
        eff_o_adj = 0.0
    target_delta = params.get("target_delta", 0.16)
    profit_target_pct = params.get("profit_target_pct", 0.50)
    manage_at_dte = params.get("manage_at_dte", 21)
    roll_for_credit = params.get("roll_for_credit", True)
    max_rolls = params.get("max_rolls", 3)
    roll_dte_max = params.get("roll_dte_max", 60)
    dte_min = params.get("dte_min", 30)
    cash_yield_annual = params.get("cash_yield_annual", 0.04)  # 4% risk-free rate
    daily_cash_rate = cash_yield_annual / 252.0

    # Track which dates have been processed for entry (avoid re-entry on same day)
    entry_dates_used: set = set()

    # ── Main daily loop ─────────────────────────────────────────────────
    for eval_date in sim_dates:
        row = data.loc[eval_date]
        spy_close = float(row["spy_close"])
        vix_d = float(row["vix_close"])
        r_d = float(row.get("risk_free_rate", 0.045))

        # ── Step 1: Recalculate margin for all open positions ────────────
        portfolio.recalculate_all_bpr(data, eval_date, engine)

        # ── Step 2: Process exits for open positions ─────────────────────
        positions_to_close: List[int] = []

        for trade_num_open, pos in list(portfolio.open_positions.items()):
            t = pos.trade
            dte_rem = max((t.expiration - eval_date).days, 1)
            T_d = max(dte_rem / 365.0, 1e-7)

            # Get today's mark
            mid_d = engine.get_daily_mark(
                t.active_put_strike, t.active_call_strike,
                spy_close, dte_rem, vix_d, r_d,
                eval_date=eval_date, expiration=t.expiration,
            )

            # Record MTM
            close_cost = mid_d * 1.05 * 100.0 + 2.0 * comm_per_leg
            pnl = t.net_credit - close_cost
            pnl_pct = pnl / t.net_credit
            t.daily_marks.append((eval_date, pnl))

            # Check profit target: 50%+ profit relative to entry mid
            entry_mid_total = t.active_baseline_mid * 100.0
            mid_pct = mid_d / t.active_baseline_mid if t.active_baseline_mid > 0 else 1.0

            exit_type = None

            # Profit target
            if mid_pct <= (1.0 - profit_target_pct) and pnl > 0:
                exit_type = "PROFIT"

            # 21-DTE management
            elif dte_rem <= manage_at_dte:
                if roll_for_credit and t.roll_count < max_rolls:
                    # Attempt roll-for-credit
                    new_exp = get_monthly_expiration(eval_date, dte_min, roll_dte_max)
                    if new_exp is not None:
                        close_cost_old = mid_d * 1.05 * 100.0 + 2.0 * comm_per_leg
                        old_pnl = t.net_credit - close_cost_old

                        T_new = (new_exp - eval_date).days / 365.0
                        (new_put_k, new_call_k, new_put_mid, new_call_mid, _used_db) = (
                            engine.get_entry_marks(
                                spy_close, T_new, r_d, vix_d,
                                entry_date=eval_date, expiration=new_exp,
                            )
                        )
                        new_net_credit = (
                            new_put_mid * (1 + eff_o_adj) + new_call_mid * (1 + eff_o_adj)
                        ) * 100.0 - 2.0 * comm_per_leg

                        roll_credit_val = new_net_credit - close_cost_old

                        if roll_credit_val > 0 and new_net_credit > 0:
                            # Roll: close old, open new
                            t.exit_date = eval_date
                            t.exit_dte = dte_rem
                            t.exit_type = "ROLLED"
                            t.pnl = round(old_pnl, 2)
                            t.pnl_pct = old_pnl / t.net_credit
                            t.roll_credit = roll_credit_val
                            t.child_trade_num = trade_num + 1  # link to the new trade
                            portfolio.available_cash += old_pnl
                            portfolio.remove_position(t.trade_num)
                            trades.append(t)

                            # Open new trade
                            trade_num += 1
                            new_trade = Trade(
                                trade_num=trade_num,
                                entry_date=eval_date,
                                expiration=new_exp,
                                entry_dte=(new_exp - eval_date).days,
                                put_strike=new_put_k,
                                call_strike=new_call_k,
                                put_mid_ps=new_put_mid,
                                call_mid_ps=new_call_mid,
                                net_credit=new_net_credit,
                                entry_vix=vix_d,
                                used_market_data=_used_db,
                                parent_trade_num=t.trade_num,
                                roll_count=t.roll_count + 1,
                            )
                            new_trade.max_vix = vix_d
                            new_trade.daily_marks = [(eval_date, 0.0)]

                            # Estimate BPR for new trade
                            new_bpr = calculate_reg_t_strangle_margin(
                                spy_close, new_put_k, new_call_k,
                                new_put_mid * 1.05, new_call_mid * 1.05,
                            )
                            portfolio.add_position(new_trade, new_bpr, spy_close)
                            portfolio.last_entry_date = eval_date
                            continue  # Skip further processing for this position

                # Roll failed or not attempted — close flat
                exit_type = "21DTE"

            # Expiry
            elif eval_date >= t.expiration:
                exit_type = "EXPIRY"

            if exit_type:
                t.exit_date = eval_date
                t.exit_dte = dte_rem
                t.exit_type = exit_type
                t.pnl = round(pnl, 2)
                t.pnl_pct = pnl_pct
                portfolio.available_cash += pnl
                portfolio.remove_position(t.trade_num)
                trades.append(t)

        # ── Step 3: Process entries (laddering) ─────────────────────────
        # Estimate BPR for a new 45-DTE strangle at 16-delta
        T_est = 45 / 365.0
        (est_put_k, est_call_k, est_put_mid, est_call_mid, _) = engine.get_entry_marks(
            spy_close, T_est, r_d, vix_d,
            entry_date=eval_date,
        )
        est_bpr = calculate_reg_t_strangle_margin(
            spy_close, est_put_k, est_call_k,
            est_put_mid * 1.05, est_call_mid * 1.05,
        )

        if portfolio.can_enter_new_trade(est_bpr, eval_date, all_trading_dates):
            # Find expiration closest to 45 DTE
            new_exp = _find_45dte_expiration(eval_date, data, params)
            if new_exp is not None:
                entry_dte = (new_exp - eval_date).days
                T_new = entry_dte / 365.0

                (new_put_k, new_call_k, new_put_mid, new_call_mid, _used_db) = (
                    engine.get_entry_marks(
                        spy_close, T_new, r_d, vix_d,
                        entry_date=eval_date, expiration=new_exp,
                    )
                )
                new_net_credit = (
                    new_put_mid * (1 + eff_o_adj) + new_call_mid * (1 + eff_o_adj)
                ) * 100.0 - 2.0 * comm_per_leg

                if new_net_credit > 0:
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

                    # Calculate actual BPR
                    actual_bpr = calculate_reg_t_strangle_margin(
                        spy_close, new_put_k, new_call_k,
                        new_put_mid * 1.05, new_call_mid * 1.05,
                    )

                    portfolio.add_position(new_trade, actual_bpr, spy_close)
                    portfolio.available_cash += new_net_credit
                    portfolio.last_entry_date = eval_date

        # ── Step 4: Cash yield ───────────────────────────────────────────
        if portfolio.available_cash > 0:
            daily_interest = portfolio.available_cash * daily_cash_rate
            portfolio.available_cash += daily_interest

        # ── Step 5: Record daily state ───────────────────────────────────
        unrealized = portfolio.get_unrealized_pnl(data, eval_date, engine)
        portfolio.record_daily_state(eval_date, unrealized)

    # ── Phase 4: Final reporting ─────────────────────────────────────────
    equity_df = pd.DataFrame(portfolio.equity_curve)
    if not equity_df.empty:
        equity_df.set_index("date", inplace=True)

    return trades, equity_df, portfolio


# ── Phase 4: Portfolio Visualization ─────────────────────────────────────

def plot_portfolio_backtest(
    trades: List[Trade],
    equity_df: pd.DataFrame,
    portfolio: PortfolioManager,
    params: dict,
    output_dir: str = "reports",
) -> str:
    """Generate and save an interactive portfolio backtest plot.

    Creates a Plotly figure with two traces:
    - "Strategy Return": theoretical equity from options P&L only
    - "Total Portfolio Return": total_equity including cash and interest

    Saves as HTML in the reports/ directory with a timestamped filename.

    Args:
        trades: List of closed Trade objects.
        equity_df: DataFrame from run_portfolio_backtest.
        portfolio: The PortfolioManager instance.
        params: PARAMS dict.
        output_dir: Directory to save the HTML file.

    Returns:
        Path to the saved HTML file.
    """
    import plotly.graph_objects as go

    if equity_df.empty:
        return ""

    # Build strategy-only equity curve (options P&L only, starting from initial balance)
    strategy_equity = [portfolio.starting_capital]
    for t in sorted(trades, key=lambda x: x.exit_date or x.entry_date):
        if t.pnl is not None:
            strategy_equity.append(strategy_equity[-1] + t.pnl)

    strategy_dates = [pd.Timestamp(params["start_date"])] + [
        t.exit_date for t in sorted(trades, key=lambda x: x.exit_date or x.entry_date)
        if t.exit_date is not None
    ]

    # Total portfolio return from equity_df
    total_dates = equity_df.index.tolist()
    total_equity = equity_df["total_equity"].values.tolist()

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=strategy_dates,
        y=strategy_equity,
        mode="lines",
        name="Strategy Return",
        line=dict(color="#e67e22", width=2),
    ))

    fig.add_trace(go.Scatter(
        x=total_dates,
        y=total_equity,
        mode="lines",
        name="Total Portfolio Return",
        line=dict(color="#2c3e50", width=2),
    ))

    fig.update_layout(
        title=f"Portfolio Backtest: {params['start_date']} → {params['end_date']}",
        xaxis_title="Date",
        yaxis_title="Equity ($)",
        yaxis_tickprefix="$",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )

    # Save to HTML
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"portfolio_backtest_{timestamp}.html"
    filepath = output_path / filename

    fig.write_html(str(filepath))
    return str(filepath)
