"""Strategy: Trade, LegRollEvent, evaluate_trade, run_backtest, calendar utils.

Contains all the mechanics of the SPY short strangle strategy:
entry/exit logic, position tracking, roll management, and defensive leg rolls.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd
from tqdm import tqdm
from straddle.params import RISK_FREE_RATE_DEFAULT
from straddle.engines import PricingContext


# ── Calendar utilities ───────────────────────────────────────────────────

def get_third_friday(year: int, month: int) -> pd.Timestamp:
    """3rd Friday of the given month — standard SPY monthly expiration."""
    first = pd.Timestamp(year=year, month=month, day=1)
    return first + pd.Timedelta(days=(4 - first.weekday()) % 7) + pd.Timedelta(weeks=2)


def get_monthly_expiration(
    entry: pd.Timestamp, dte_min: int, dte_max: int
) -> Optional[pd.Timestamp]:
    """Nearest 3rd-Friday expiration with DTE strictly in [dte_min, dte_max].

    Returns None if no valid expiration exists for this entry date.
    The fallback (nearest regardless of window) was removed — it silently
    produced 46–51 DTE entries on most months, violating the strategy rules.
    """
    for mo in range(0, 5):
        abs_mo = entry.month + mo
        exp = get_third_friday(entry.year + (abs_mo - 1) // 12, (abs_mo - 1) % 12 + 1)
        dte = (exp - entry).days
        if dte_min <= dte <= dte_max:
            return exp
    return None


def get_entry_dates(
    data: pd.DataFrame, start_date: str, end_date: str, dte_min: int, dte_max: int
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """One trade per calendar month: earliest trading day where a 3rd-Friday
    expiration falls in [dte_min, dte_max] (inclusive, calendar days).

    The 3rd Friday of next month is 44-51 calendar days from the 1st, so the
    1st of the month is almost never a valid entry by itself. A short forward
    scan (up to 15 calendar days) finds the day where DTE first enters the
    window. Entry date shifts by at most ~7 days from the 1st.

    Returns:
        List of (entry_date, expiration) pairs. Returning the expiration here
        avoids calling get_monthly_expiration a second time in run_backtest.
    """
    result = []
    seen_month = None
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    for dt in data.loc[start_ts:end_ts].index:
        month_key = (dt.year, dt.month)
        if month_key == seen_month:
            continue  # already found entry for this month
        seen_month = month_key
        # Scan up to 15 calendar days from the 1st to find the earliest
        # trading day where a valid [dte_min, dte_max] expiry exists.
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        trading_days = data.loc[month_start : month_start + pd.Timedelta(days=15)].index
        for candidate in trading_days:
            if candidate < start_ts or candidate > end_ts:
                continue
            exp = get_monthly_expiration(candidate, dte_min, dte_max)
            if exp is not None:
                result.append((candidate, exp))
                break
        # If no valid entry found in 15 days, month is skipped (edge case only)
    return result


# ── Entry helper (short strangle + iron condor) ──────────────────────────

def build_entry(
    engine,
    S: float,
    T: float,
    r: float,
    vix: float,
    entry_dte: int,
    ctx: "PricingContext",
    params: dict,
) -> Optional[dict]:
    """Price the entry legs and return Trade(**kwargs), or None on non-positive credit.

    Short strangle: 2 legs (short put + short call at target_delta).
    Iron condor: 4 legs (+ long put + long call at wing_delta) — defined risk.

    Wing pricing note: ``find_strike_at_delta`` is used only to select the wing
    strike. The entry mark is then fetched via ``get_leg_mark`` so that market
    mode returns the ask (cost to buy) rather than the bid. Synthetic mode
    returns the BS mid; the "close"-side fill adjustment then models buyer
    slippage (pay ~5% above mid).
    """
    comm = params["commission_per_leg"]
    put_k, call_k, put_mid, call_mid, used_db = engine.get_entry_marks(
        S, T, r, vix, ctx=ctx
    )
    short_credit_ps = engine.apply_fill_adj(put_mid + call_mid, "open")

    kw = dict(
        put_strike=put_k,
        call_strike=call_k,
        put_mid_ps=put_mid,
        call_mid_ps=call_mid,
        used_market_data=used_db,
    )

    if params.get("strategy_mode", "short_strangle") == "iron_condor":
        wing_delta = params.get("wing_delta", 0.05)
        long_put_k, _ = engine.find_strike_at_delta(
            S, T, r, vix, wing_delta, "put", ctx=ctx
        )
        long_call_k, _ = engine.find_strike_at_delta(
            S, T, r, vix, wing_delta, "call", ctx=ctx
        )
        long_put_mid = engine.get_leg_mark(
            long_put_k, S, entry_dte, vix, r, "put", ctx=ctx
        )
        long_call_mid = engine.get_leg_mark(
            long_call_k, S, entry_dte, vix, r, "call", ctx=ctx
        )
        long_debit_ps = engine.apply_fill_adj(
            long_put_mid + long_call_mid, "close"
        )
        net_credit = (short_credit_ps - long_debit_ps) * 100.0 - 4.0 * comm
        kw["long_put_strike"] = long_put_k
        kw["long_call_strike"] = long_call_k
        kw["long_put_mid_ps"] = long_put_mid
        kw["long_call_mid_ps"] = long_call_mid
    else:
        net_credit = short_credit_ps * 100.0 - 2.0 * comm

    if net_credit <= 0.0:
        return None
    kw["net_credit"] = net_credit
    return kw


# ── Dataclasses ──────────────────────────────────────────────────────────

@dataclass
class LegRollEvent:
    """Records a single defensive leg roll during a trade's hold period."""

    event_date: pd.Timestamp
    side: str  # "put" or "call" — the UNTESTED side that was rolled
    old_strike: float
    new_strike: float
    close_cost_ps: float  # per-share cost to buy back the old leg (ask * fill_adj)
    new_credit_ps: float  # per-share credit for the new leg (bid * fill_adj)
    net_credit_dollar: float  # (new_credit - close_cost) * 100, after commission
    trigger_delta: float  # |delta| of the tested side that triggered this roll


@dataclass
class Trade:
    trade_num: int
    entry_date: pd.Timestamp
    expiration: pd.Timestamp
    entry_dte: int
    put_strike: float
    call_strike: float
    put_mid_ps: float  # per-share put mid at open (before fill adj)
    call_mid_ps: float
    net_credit: float  # dollar credit after fill adj and open commission
    entry_vix: float
    exit_date: Optional[pd.Timestamp] = None
    exit_dte: Optional[int] = None
    exit_type: Optional[str] = None  # PROFIT | STOP | 21DTE | EXPIRY | ROLLED
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None  # pnl / net_credit
    stop_regime: Optional[str] = None  # ORDERLY | NORMAL | VIOLENT | GAP
    overshoot_used: Optional[float] = None
    max_vix: Optional[float] = None  # peak VIX during the hold period
    used_market_data: bool = False  # True if entry marks came from DB (market mode)
    # Roll lineage fields (populated only when roll_for_credit=True)
    parent_trade_num: Optional[int] = (
        None  # trade_num of the trade this one was rolled from
    )
    child_trade_num: Optional[int] = (
        None  # trade_num of the trade this one was rolled into
    )
    roll_count: int = (
        0  # number of times the original position has been rolled (0 = not a roll)
    )
    roll_credit: Optional[float] = (
        None  # net credit received on the roll transaction, None if not rolled
    )
    # True daily mark-to-market series: list of (date, position_value_dollar) tuples.
    # position_value_dollar = net P&L if the trade were closed at that day's mark.
    # Entry day is always (entry_date, 0.0). Exit day equals realized pnl.
    daily_marks: List[Tuple[pd.Timestamp, float]] = field(default_factory=list)
    # Defensive leg roll fields
    leg_rolls: List["LegRollEvent"] = field(default_factory=list)
    # Effective strikes after leg rolls (None = use original put_strike / call_strike)
    current_put_strike: Optional[float] = None
    current_call_strike: Optional[float] = None
    # Baseline mid for profit-target after leg roll(s) (None = put_mid_ps + call_mid_ps)
    current_baseline_mid: Optional[float] = None
    # Iron-condor wings — None for a plain short strangle.
    # When populated, all four legs are priced and risk is defined.
    long_put_strike: Optional[float] = None
    long_call_strike: Optional[float] = None
    long_put_mid_ps: Optional[float] = None
    long_call_mid_ps: Optional[float] = None

    @property
    def is_iron_condor(self) -> bool:
        return self.long_put_strike is not None

    @property
    def active_put_strike(self) -> float:
        return (
            self.current_put_strike
            if self.current_put_strike is not None
            else self.put_strike
        )

    @property
    def active_call_strike(self) -> float:
        return (
            self.current_call_strike
            if self.current_call_strike is not None
            else self.call_strike
        )

    @property
    def active_baseline_mid(self) -> float:
        if self.current_baseline_mid is not None:
            return self.current_baseline_mid
        base = self.put_mid_ps + self.call_mid_ps
        if self.is_iron_condor:
            base -= (self.long_put_mid_ps or 0.0) + (self.long_call_mid_ps or 0.0)
        return base


# ── Defensive leg roll ───────────────────────────────────────────────────

def attempt_defensive_leg_roll(
    trade: Trade,
    eval_date: pd.Timestamp,
    S_d: float,
    vix_d: float,
    r_d: float,
    dte_rem: int,
    T_d: float,
    data: pd.DataFrame,
    engine,
    params: dict,
) -> bool:
    """Check trigger and execute a defensive leg roll if conditions are met.

    When the tested side's |delta| breaches defensive_trigger_delta (default 0.30),
    the UNTESTED (profitable) side is bought back and a new leg is sold at
    leg_roll_target_delta, collecting additional credit and flattening delta.
    The tested side stays in place.

    Returns True if a roll fired (caller must re-read active strikes and
    recompute mid_d for this iteration). Returns False if no roll.
    """
    if not params.get("defensive_leg_roll_enabled", False):
        return False
    # Defensive leg rolls are not supported in iron-condor mode: rolling only the
    # short leg without adjusting its matching wing creates a variable-width
    # vertical whose risk characteristics differ from the original spread.
    if trade.is_iron_condor:
        return False
    if len(trade.leg_rolls) >= params.get("max_leg_rolls_per_trade", 2):
        return False

    trigger_delta = params.get("defensive_trigger_delta", 0.30)
    target_delta = params.get("leg_roll_target_delta", 0.16)
    comm = params["commission_per_leg"]

    ctx = PricingContext(eval_date=eval_date, expiration=trade.expiration)

    # Read current per-leg deltas
    put_delta = engine.get_daily_delta(
        trade.active_put_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "put",
        ctx=ctx,
    )
    call_delta = engine.get_daily_delta(
        trade.active_call_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "call",
        ctx=ctx,
    )

    # Determine which side (if any) is tested
    tested_side = None
    trigger_d = None
    if abs(put_delta) >= trigger_delta:
        tested_side = "put"
        trigger_d = abs(put_delta)
    elif abs(call_delta) >= trigger_delta:
        tested_side = "call"
        trigger_d = abs(call_delta)

    if tested_side is None:
        return False

    # Roll the UNTESTED side (the profitable one)
    untested_side = "call" if tested_side == "put" else "put"
    untested_old_strike = (
        trade.active_call_strike if untested_side == "call" else trade.active_put_strike
    )

    # Cost to buy back old untested leg (ask fill)
    close_mark = engine.get_leg_mark(
        untested_old_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        untested_side,
        ctx=ctx,
    )
    close_cost_ps = engine.apply_fill_adj(close_mark, "close")

    # Find new untested leg at target_delta (closer to ATM)
    new_strike, new_open_mark = engine.find_strike_at_delta(
        S_d,
        T_d,
        r_d,
        vix_d,
        target_delta,
        untested_side,
        ctx=ctx,
    )

    # Sanity: new strike must move toward ATM vs old strike
    if untested_side == "put" and new_strike <= untested_old_strike:
        return False
    if untested_side == "call" and new_strike >= untested_old_strike:
        return False

    new_credit_ps = engine.apply_fill_adj(new_open_mark, "open")

    # Net credit must be positive (roll for credit only)
    net_credit_dollar = (new_credit_ps - close_cost_ps) * 100.0 - 2.0 * comm
    if net_credit_dollar <= 0:
        return False

    # ── Execute: record event, update trade state ────────────────────────
    event = LegRollEvent(
        event_date=eval_date,
        side=untested_side,
        old_strike=untested_old_strike,
        new_strike=new_strike,
        close_cost_ps=close_cost_ps,
        new_credit_ps=new_credit_ps,
        net_credit_dollar=net_credit_dollar,
        trigger_delta=trigger_d,
    )
    trade.leg_rolls.append(event)

    if untested_side == "put":
        trade.current_put_strike = new_strike
    else:
        trade.current_call_strike = new_strike

    # Add roll credit to net_credit so profit-target % references cumulative premium
    trade.net_credit += net_credit_dollar

    # Recompute baseline mid: tested-side mark + new untested mark
    tested_old_strike = (
        trade.active_put_strike if tested_side == "put" else trade.active_call_strike
    )
    tested_mark = engine.get_leg_mark(
        tested_old_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        tested_side,
        ctx=ctx,
    )
    trade.current_baseline_mid = tested_mark + new_open_mark

    return True


# ── Trade evaluation ─────────────────────────────────────────────────────

@dataclass
class TradeStepResult:
    """Outcome of a single day's evaluation for an open trade."""

    exited: bool
    exit_type: Optional[str] = None
    new_trade: Optional[Trade] = None  # Populated if exit_type == "ROLLED"
    pnl: float = 0.0
    pnl_pct: float = 0.0
    close_cost: float = 0.0
    mid_d: float = 0.0  # Per-share mid price at EOD
    put_mid_d: float = 0.0  # Per-share mid for put leg
    call_mid_d: float = 0.0  # Per-share mid for call leg


def evaluate_trade_step(
    trade: Trade,
    eval_date: pd.Timestamp,
    data: pd.DataFrame,
    engine,
    params: dict,
) -> TradeStepResult:
    """Evaluate a single day for an open trade.

    Checks for defensive leg rolls, profit targets, stop-losses (with overshoot),
    21-DTE management, and expiration.

    Returns a TradeStepResult indicating if the trade should continue or exit.
    """
    r_default = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
    prof = params["profit_target_pct"]
    stop = params["stop_loss_pct"]
    manage_at_dte = params["manage_at_dte"]
    comm = params["commission_per_leg"]
    use_price_stop = params.get("use_price_stop", False)
    roll_for_credit = params.get("roll_for_credit", False)
    max_rolls = params.get("max_rolls", 3)
    ov_orderly = params.get("overshoot_orderly", 0.25)
    ov_normal = params.get("overshoot_normal", 0.50)
    ov_violent = params.get("overshoot_violent", 0.80)
    rng_orderly = params.get("range_threshold_orderly", 0.015)
    rng_violent = params.get("range_threshold_violent", 0.030)

    expiration = trade.expiration
    row_d = data.loc[eval_date]
    S_d = float(row_d["spy_close"])
    vix_d = float(row_d["vix_close"])
    r_d = float(row_d.get("risk_free_rate", r_default))
    trade.max_vix = max(trade.max_vix or 0, vix_d)
    dte_rem = (expiration - eval_date).days
    T_d = max(dte_rem / 365.0, 1e-7)

    # 1. Defensive leg roll
    attempt_defensive_leg_roll(
        trade, eval_date, S_d, vix_d, r_d, dte_rem, T_d, data, engine, params
    )

    ctx = PricingContext(eval_date=eval_date, expiration=expiration)

    # 2. Daily marks
    put_mid_d = engine.get_leg_mark(
        trade.active_put_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "put",
        ctx=ctx,
    )
    call_mid_d = engine.get_leg_mark(
        trade.active_call_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "call",
        ctx=ctx,
    )
    short_mid_d = put_mid_d + call_mid_d

    if trade.is_iron_condor:
        # Long wings are SOLD to close → quote sell-side (bid in market mode;
        # BS mid in synthetic mode, with sell-side fill adjustment applied below).
        long_put_mid_d = engine.get_leg_mark(
            trade.long_put_strike, S_d, dte_rem, vix_d, r_d, "put",
            ctx=ctx, buy_or_sell="sell",
        )
        long_call_mid_d = engine.get_leg_mark(
            trade.long_call_strike, S_d, dte_rem, vix_d, r_d, "call",
            ctx=ctx, buy_or_sell="sell",
        )
        long_mid_d = long_put_mid_d + long_call_mid_d
        mid_d = short_mid_d - long_mid_d
        # Per-leg fill adjustment: shorts pay ask on buy-back (+c_adj),
        # longs receive bid on sale (+o_adj, which is negative). Applying a
        # single "close" adjustment to the net mid incorrectly pushed both
        # directions the same way, under-stating the close cost in synthetic
        # mode. Market mode apply_fill_adj is a no-op — bid/ask is already
        # baked into the marks above.
        close_cost = (
            engine.apply_fill_adj(short_mid_d, "close")
            - engine.apply_fill_adj(long_mid_d, "open")
        ) * 100.0 + 4.0 * comm
    else:
        mid_d = short_mid_d
        close_cost = engine.apply_fill_adj(mid_d, "close") * 100.0 + 2.0 * comm
    pnl = trade.net_credit - close_cost
    pnl_pct = pnl / trade.net_credit

    # Record MTM (this is added even if we exit; evaluation happens at EOD)
    trade.daily_marks.append((eval_date, pnl))

    # 3. Check Exits
    exit_type = None
    entry_mid_ps = trade.active_baseline_mid

    # A. Optional Price Stop
    # Disabled in iron-condor mode — the long wings already cap max loss, so an
    # extra price stop would only introduce slippage with no risk benefit.
    if use_price_stop and not trade.is_iron_condor and pnl_pct <= -stop:
        exit_type = "STOP"
        entry_mid_total = trade.active_baseline_mid * 100.0
        eod_mid_dollar = mid_d * 100.0
        mid_pnl_raw = entry_mid_total - eod_mid_dollar
        stop_loss_dollar_mid = -stop * entry_mid_total

        prev_idx = data.index.get_loc(eval_date)
        spy_hi = float(row_d.get("spy_high", S_d))
        spy_lo = float(row_d.get("spy_low", S_d))
        spy_prev_close = (
            float(data.iloc[prev_idx - 1]["spy_close"]) if prev_idx > 0 else S_d
        )
        daily_range_pct = (
            (spy_hi - spy_lo) / spy_prev_close if spy_prev_close > 0 else 0.0
        )

        spy_open = float(row_d.get("spy_open", S_d))
        vix_prev_raw = (
            float(data.iloc[prev_idx - 1]["vix_close"]) / 100.0
            if prev_idx > 0
            else vix_d / 100.0
        )
        gap_pct = (
            abs(spy_open - spy_prev_close) / spy_prev_close
            if spy_prev_close > 0
            else 0.0
        )

        r_open = float(row_d.get("risk_free_rate", r_default))
        open_mid = engine.get_gap_open_mark(
            spy_open,
            vix_prev_raw,
            gap_pct,
            trade.active_put_strike,
            trade.active_call_strike,
            T_d,
            r_open,
            ctx=ctx,
        )

        open_mid_dollar = open_mid * 100.0
        open_mid_pnl_raw = entry_mid_total - open_mid_dollar
        open_pnl_pct_mid = open_mid_pnl_raw / entry_mid_total

        if open_pnl_pct_mid <= -stop:
            overshoot_frac = 1.0
            regime = "GAP"
            reference_loss = open_mid_pnl_raw
            close_mid_for_slip = open_mid_dollar
        elif daily_range_pct >= rng_violent:
            overshoot_frac = ov_violent
            regime = "VIOLENT"
            reference_loss = mid_pnl_raw
            close_mid_for_slip = eod_mid_dollar
        elif daily_range_pct >= rng_orderly:
            overshoot_frac = ov_normal
            regime = "NORMAL"
            reference_loss = mid_pnl_raw
            close_mid_for_slip = eod_mid_dollar
        else:
            overshoot_frac = ov_orderly
            regime = "ORDERLY"
            reference_loss = mid_pnl_raw
            close_mid_for_slip = eod_mid_dollar

        fill_pnl_mid = stop_loss_dollar_mid + overshoot_frac * (
            reference_loss - stop_loss_dollar_mid
        )
        
        # Round-trip cost: (open_fill_adj + close_fill_adj) * marks + commissions
        # We use apply_fill_adj to get the delta vs mid
        open_slip = abs(engine.apply_fill_adj(entry_mid_ps, "open") - entry_mid_ps)
        close_slip = abs(engine.apply_fill_adj(close_mid_for_slip/100.0, "close") - close_mid_for_slip/100.0)
        
        rt_cost = (
            open_slip * 100.0
            + close_slip * 100.0
            + 4.0 * comm
        )
        pnl = fill_pnl_mid - rt_cost
        pnl_pct = pnl / trade.net_credit
        trade.stop_regime = regime
        trade.overshoot_used = overshoot_frac
        # Update close_cost based on the overshoot logic
        close_cost = trade.net_credit - pnl

    # B. Profit Target — "captured ≥ prof of net premium".
    # Uses pnl_pct directly (apples-to-apples: both net_credit and close_cost
    # are execution-side prices in market mode — bid at entry, ask at close).
    # The prior `mid_d / entry_mid_ps` ratio mixed sides (bid at entry, ask at
    # close) and was biased upward by the bid-ask spread, under-triggering the
    # target in market mode.
    elif pnl_pct >= prof:
        exit_type = "PROFIT"

    # C. 21-DTE / Roll
    elif dte_rem <= manage_at_dte:
        # VIX filter applies to rolls too: if VIX is above the entry threshold,
        # close flat instead of rolling into a new position.
        _vix_blocks_roll = (
            params.get("vix_entry_filter_enabled", False)
            and vix_d > params.get("vix_entry_max", 30.0)
        )
        if roll_for_credit and trade.roll_count < max_rolls and not _vix_blocks_roll:
            _roll_dte_max = params.get("roll_dte_max", 60)
            new_exp = get_monthly_expiration(eval_date, params.get("dte_min", 30), _roll_dte_max)
            if new_exp is not None:
                close_cost_old = close_cost
                old_pnl = trade.net_credit - close_cost_old
                T_new = (new_exp - eval_date).days / 365.0
                roll_ctx = PricingContext(eval_date=eval_date, expiration=new_exp)
                new_entry_dte = (new_exp - eval_date).days
                kw = build_entry(
                    engine, S_d, T_new, r_d, vix_d, new_entry_dte, roll_ctx, params
                )

                roll_credit_val = (kw["net_credit"] - close_cost_old) if kw else 0.0

                if kw is not None and roll_credit_val > 0:
                    trade.exit_date = eval_date
                    trade.exit_dte = dte_rem
                    trade.exit_type = "ROLLED"
                    trade.pnl = round(old_pnl, 2)
                    trade.pnl_pct = old_pnl / trade.net_credit
                    trade.roll_credit = roll_credit_val

                    new_trade = Trade(
                        trade_num=None,
                        entry_date=eval_date,
                        expiration=new_exp,
                        entry_dte=new_entry_dte,
                        entry_vix=vix_d,
                        parent_trade_num=trade.trade_num,
                        roll_count=trade.roll_count + 1,
                        **kw,
                    )
                    new_trade.max_vix = vix_d
                    new_trade.daily_marks = [(eval_date, 0.0)]
                    return TradeStepResult(
                        exited=True,
                        exit_type="ROLLED",
                        new_trade=new_trade,
                        pnl=trade.pnl,
                        pnl_pct=trade.pnl_pct,
                        close_cost=close_cost_old,
                        mid_d=mid_d,
                        put_mid_d=put_mid_d,
                        call_mid_d=call_mid_d,
                    )
        exit_type = "21DTE"

    # D. Expiry
    elif eval_date >= expiration:
        exit_type = "EXPIRY"

    if exit_type:
        return TradeStepResult(
            exited=True,
            exit_type=exit_type,
            pnl=round(pnl, 2),
            pnl_pct=pnl_pct,
            close_cost=close_cost,
            mid_d=mid_d,
            put_mid_d=put_mid_d,
            call_mid_d=call_mid_d,
        )

    return TradeStepResult(
        exited=False,
        close_cost=close_cost,
        mid_d=mid_d,
        put_mid_d=put_mid_d,
        call_mid_d=call_mid_d,
    )


def evaluate_trade(
    trade: Trade,
    data: pd.DataFrame,
    engine,
    params: dict,
    end_date: Optional[pd.Timestamp] = None,
) -> tuple:
    """Run the daily eval loop for a single open trade.

    Iterates from the trade's entry_date to its expiration, checking exit
    conditions each day via ``evaluate_trade_step``.

    If ``end_date`` is provided and the trade's expiration falls beyond it,
    the trade is force-closed at mid on the last in-range trading day (marked
    as ``EXPIRY``). This matches the portfolio-mode behavior and prevents a
    silent truncation of the equity curve when the backtest window ends while
    a chain is still open.

    Returns:
        (closed_trade, new_trade_or_None)
        new_trade is populated when exit_type == "ROLLED".
    """
    expiration = trade.expiration

    force_close_at: Optional[pd.Timestamp] = None
    if end_date is not None and expiration > end_date:
        in_range = data.index[data.index <= end_date]
        if len(in_range) == 0:
            return trade, None
        force_close_at = in_range[-1]
        # Edge case: trade was rolled onto (or started after) the force-close
        # day. No time remains for profit/stop/roll to fire, so close flat.
        if trade.entry_date >= force_close_at:
            trade.exit_date = force_close_at
            trade.exit_dte = (expiration - force_close_at).days
            trade.exit_type = "FORCE_CLOSE"
            trade.pnl = 0.0
            trade.pnl_pct = 0.0
            return trade, None

    for eval_date in data.loc[trade.entry_date : expiration].index[1:]:
        if force_close_at is not None and eval_date > force_close_at:
            break
        res = evaluate_trade_step(trade, eval_date, data, engine, params)

        if res.exited:
            trade.exit_date = eval_date
            trade.exit_dte = (expiration - eval_date).days
            trade.exit_type = res.exit_type
            trade.pnl = res.pnl
            trade.pnl_pct = res.pnl_pct
            return trade, res.new_trade

        if force_close_at is not None and eval_date == force_close_at:
            # Reached the last in-range day with no organic exit — force-close
            # at mid using the marks already computed this step.
            trade.exit_date = eval_date
            trade.exit_dte = (expiration - eval_date).days
            trade.exit_type = "FORCE_CLOSE"
            trade.pnl = res.pnl
            trade.pnl_pct = res.pnl_pct
            return trade, None

    # Fallback: loop ended without an intra-period exit — price at expiration
    last = data.index[data.index <= expiration][-1]
    S_e = float(data.loc[last, "spy_close"])
    intr = max(trade.active_put_strike - S_e, 0.0) + max(
        S_e - trade.active_call_strike, 0.0
    )
    if trade.is_iron_condor:
        intr -= max(trade.long_put_strike - S_e, 0.0) + max(
            S_e - trade.long_call_strike, 0.0
        )
        n_comm = 4
    else:
        n_comm = 2
    comm = params["commission_per_leg"]
    cc = engine.apply_fill_adj(intr, "close") * 100.0 + n_comm * comm
    pnl = trade.net_credit - cc
    trade.exit_date = expiration
    trade.exit_dte = 0
    trade.exit_type = "EXPIRY"
    trade.pnl = round(pnl, 2)
    trade.pnl_pct = pnl / trade.net_credit

    return trade, None


# ── Backtest runner ──────────────────────────────────────────────────────

def run_backtest(
    data: pd.DataFrame, params: dict, engine=None
) -> tuple:
    """Run the full SPY short strangle backtest.

    Args:
        data: DataFrame with SPY OHLC, VIX, and risk-free rate (from load_market_data).
        params: Flat PARAMS dict (from straddle.params.PARAMS or custom).
        engine: Pricing engine instance. If None, it is created via make_engine(params).

    Returns:
        (trades, equity_curve, skipped_entries, skipped_vix)
        - trades: list of Trade objects (one per chain leg, including ROLLED descendants)
        - equity_curve: daily pd.Series of mark-to-market account equity
        - skipped_entries: count of skipped entries due to single_position barrier
        - skipped_vix: count of skipped entries due to VIX filter
    """
    from straddle.engines import make_engine

    created_engine = False
    if engine is None:
        engine = make_engine(params)
        created_engine = True

    try:
        r_default = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
        comm = params["commission_per_leg"]
        single_position = params.get("single_position", True)
        # latest_open_exit tracks when the current chain finishes.
        # Used to skip new monthly entries while a prior position is open.
        latest_open_exit = pd.Timestamp.min

        vix_filter_enabled = params.get("vix_entry_filter_enabled", False)
        vix_entry_max = params.get("vix_entry_max", 30.0)

        end_ts = pd.Timestamp(params["end_date"])

        trades: List[Trade] = []
        trade_num: int = 0
        skipped_entries: int = 0
        skipped_vix: int = 0

        entries = get_entry_dates(
            data,
            params["start_date"],
            params["end_date"],
            params["dte_min"],
            params["dte_max"],
        )
        for entry_date, expiration in tqdm(entries, desc="Running backtest", unit="trade"):
            if entry_date not in data.index:
                continue
            if single_position and entry_date < latest_open_exit:
                skipped_entries += 1
                continue  # prior chain still open; skip this monthly entry
            row = data.loc[entry_date]
            S = float(row["spy_close"])
            vix = float(row["vix_close"])
            if vix_filter_enabled and vix > vix_entry_max:
                skipped_vix += 1
                continue  # VIX too high; skip this entry

            entry_dte = (expiration - entry_date).days
            T = entry_dte / 365.0
            r = float(row.get("risk_free_rate", r_default))

            entry_ctx = PricingContext(eval_date=entry_date, expiration=expiration)
            kw = build_entry(engine, S, T, r, vix, entry_dte, entry_ctx, params)
            if kw is None:
                continue

            trade_num += 1
            trade = Trade(
                trade_num=trade_num,
                entry_date=entry_date,
                expiration=expiration,
                entry_dte=entry_dte,
                entry_vix=vix,
                **kw,
            )
            trade.max_vix = vix  # initialised; updated daily in evaluate_trade
            trade.daily_marks = [(entry_date, 0.0)]  # entry day: MTM value = 0

            # Iterative roll continuation -- follows the chain until a terminal exit
            active = trade
            while active is not None:
                closed, new_active = evaluate_trade(
                    active, data, engine, params, end_date=end_ts
                )
                trades.append(closed)
                if new_active is not None:
                    trade_num += 1
                    new_active.trade_num = trade_num
                    closed.child_trade_num = trade_num
                    active = new_active
                else:
                    active = None
            # Chain complete: update barrier so next monthly entry waits
            # until this chain (including any rolls) has fully exited.
            latest_open_exit = closed.exit_date

        # Build a daily equity series from each trade's daily_marks.
        # This replaces the sparse exit-date dict and gives metrics and plotting
        # a single canonical source they can use directly.
        all_days = data.loc[
            pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"])
        ].index
        daily_pnl = pd.Series(0.0, index=all_days)
        for t in trades:
            marks = t.daily_marks
            if not marks or len(marks) < 2:
                if t.exit_date is not None and t.exit_date in daily_pnl.index:
                    daily_pnl[t.exit_date] += t.pnl or 0.0
                continue
            for i in range(1, len(marks)):
                _, prev_val = marks[i - 1]
                this_date, this_val = marks[i]
                if this_date in daily_pnl.index:
                    daily_pnl[this_date] += this_val - prev_val

        equity_curve = daily_pnl.cumsum() + params["initial_balance"]
        return trades, equity_curve, skipped_entries, skipped_vix
    finally:
        if created_engine and hasattr(engine, "close"):
            engine.close()
