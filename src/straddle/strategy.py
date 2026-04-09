"""Strategy: Trade, LegRollEvent, evaluate_trade, run_backtest, calendar utils.

Contains all the mechanics of the SPY short strangle strategy:
entry/exit logic, position tracking, roll management, and defensive leg rolls.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd


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
) -> List[pd.Timestamp]:
    """One trade per calendar month: earliest trading day where a 3rd-Friday
    expiration falls in [dte_min, dte_max] (inclusive, calendar days).

    The 3rd Friday of next month is 44-51 calendar days from the 1st, so the
    1st of the month is almost never a valid entry by itself. A short forward
    scan (up to 15 calendar days) finds the day where DTE first enters the
    window. Entry date shifts by at most ~7 days from the 1st.
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
            if get_monthly_expiration(candidate, dte_min, dte_max) is not None:
                result.append(candidate)
                break
        # If no valid entry found in 15 days, month is skipped (edge case only)
    return result


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
        return self.put_mid_ps + self.call_mid_ps


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
    if len(trade.leg_rolls) >= params.get("max_leg_rolls_per_trade", 2):
        return False

    trigger_delta = params.get("defensive_trigger_delta", 0.30)
    target_delta = params.get("leg_roll_target_delta", 0.16)
    o_adj = params["open_fill_adj"]
    c_adj = params["close_fill_adj"]
    comm = params["commission_per_leg"]
    _real = getattr(engine, "uses_real_fills", False)
    eff_o_adj = 0.0 if _real else o_adj
    eff_c_adj = 0.0 if _real else c_adj

    # Read current per-leg deltas
    put_delta = engine.get_daily_delta(
        trade.active_put_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "put",
        eval_date=eval_date,
        expiration=trade.expiration,
    )
    call_delta = engine.get_daily_delta(
        trade.active_call_strike,
        S_d,
        dte_rem,
        vix_d,
        r_d,
        "call",
        eval_date=eval_date,
        expiration=trade.expiration,
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
        eval_date=eval_date,
        expiration=trade.expiration,
    )
    close_cost_ps = close_mark * (1.0 + eff_c_adj)

    # Find new untested leg at target_delta (closer to ATM)
    new_strike, new_open_mark = engine.find_strike_at_delta(
        S_d,
        T_d,
        r_d,
        vix_d,
        target_delta,
        untested_side,
        eval_date=eval_date,
        expiration=trade.expiration,
    )

    # Sanity: new strike must move toward ATM vs old strike
    if untested_side == "put" and new_strike <= untested_old_strike:
        return False
    if untested_side == "call" and new_strike >= untested_old_strike:
        return False

    new_credit_ps = new_open_mark * (1.0 + eff_o_adj)

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
        eval_date=eval_date,
        expiration=trade.expiration,
    )
    trade.current_baseline_mid = tested_mark + new_open_mark

    return True


# ── Trade evaluation ─────────────────────────────────────────────────────

def evaluate_trade(
    trade: Trade,
    data: pd.DataFrame,
    engine,
    params: dict,
    balance: float,
) -> tuple:
    """Run the daily eval loop for a single open trade.

    Iterates from the trade's entry_date to its expiration, checking exit
    conditions each day. On exit, sets trade.exit_*, trade.pnl, trade.pnl_pct.

    Return signature: (closed_trade, new_trade_or_None, new_balance)
      - new_trade_or_None is None for normal exits (PROFIT / STOP / 21DTE / EXPIRY).
      - When a roll succeeds, new_trade_or_None is the follow-on Trade (trade_num=None;
        caller assigns trade_num and links child_trade_num before continuing).

    All params are read from the params dict explicitly -- no closure.
    """
    r_default = params.get("risk_free_rate", 0.045)
    prof = params["profit_target_pct"]
    stop = params["stop_loss_pct"]
    manage_at_dte = params["manage_at_dte"]
    o_adj = params["open_fill_adj"]
    c_adj = params["close_fill_adj"]
    comm = params["commission_per_leg"]
    _real = getattr(engine, "uses_real_fills", False)
    eff_o_adj = 0.0 if _real else o_adj
    eff_c_adj = 0.0 if _real else c_adj
    use_price_stop = params.get("use_price_stop", False)
    roll_for_credit = params.get("roll_for_credit", False)
    max_rolls = params.get("max_rolls", 3)
    ov_orderly = params.get("overshoot_orderly", 0.25)
    ov_normal = params.get("overshoot_normal", 0.50)
    ov_violent = params.get("overshoot_violent", 0.80)
    rng_orderly = params.get("range_threshold_orderly", 0.015)
    rng_violent = params.get("range_threshold_violent", 0.030)

    # NOTE: net_credit is read as trade.net_credit each time — not captured as a
    # local — because attempt_defensive_leg_roll mutates trade.net_credit in place
    # when a leg roll fires.  A stale local would discard collected leg roll credit.
    # put_k / call_k are similarly NOT cached; use trade.active_put/call_strike.
    expiration = trade.expiration

    exited = False
    for eval_date in data.loc[trade.entry_date : expiration].index[1:]:
        row_d = data.loc[eval_date]
        S_d = float(row_d["spy_close"])
        vix_d = float(row_d["vix_close"])
        r_d = float(row_d.get("risk_free_rate", r_default))
        trade.max_vix = max(trade.max_vix, vix_d)
        dte_rem = (expiration - eval_date).days
        T_d = max(dte_rem / 365.0, 1e-7)

        # Defensive leg roll: check trigger and execute if conditions met.
        # When a roll fires, active strikes are updated on the trade object.
        # The mid_d computation below automatically reads the new strikes.
        attempt_defensive_leg_roll(
            trade, eval_date, S_d, vix_d, r_d, dte_rem, T_d, data, engine, params
        )

        mid_d = engine.get_daily_mark(
            trade.active_put_strike,  # may differ from put_k after a leg roll
            trade.active_call_strike,  # may differ from call_k after a leg roll
            S_d,
            dte_rem,
            vix_d,
            r_d,
            eval_date=eval_date,
            expiration=expiration,
        )

        close_cost = mid_d * (1.0 + eff_c_adj) * 100.0 + 2.0 * comm
        pnl = trade.net_credit - close_cost
        pnl_pct = pnl / trade.net_credit

        # Record today's MTM value for the Sharpe calculation.
        # pnl here is the net P&L if we closed at today's mark — exactly
        # what we want. This is appended before any exit logic so the final
        # (exit) day captures the realized fill, not the trigger mark.
        trade.daily_marks.append((eval_date, pnl))

        # ── Profit target ────────────────────────────────────────────────────
        # Trigger:  raw mid-to-mid decay  (mid_d / entry_mid <= 50%)
        # Fill:     fill-adjusted close_cost  (mid * (1+eff_c_adj) + commissions)
        # After a leg roll, active_baseline_mid reflects the new combined mid.
        entry_mid_ps = trade.active_baseline_mid
        mid_pct = mid_d / entry_mid_ps

        exit_type = None

        # ── Price stop (optional -- canonical tastytrade rules have no price stop) ──
        if use_price_stop and pnl_pct <= -stop:
            exit_type = "STOP"
            # Overshoot blend in mid space (no fill adj, no commission).
            entry_mid_total = (trade.put_mid_ps + trade.call_mid_ps) * 100.0
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
            rt_cost = (
                entry_mid_total * abs(eff_o_adj)
                + close_mid_for_slip * eff_c_adj
                + 4.0 * comm
            )
            pnl = fill_pnl_mid - rt_cost
            pnl_pct = pnl / trade.net_credit
            trade.stop_regime = regime
            trade.overshoot_used = overshoot_frac

        elif mid_pct <= (1.0 - prof) and pnl > 0:
            # Guard pnl > 0: after a leg roll active_baseline_mid is reset to
            # the elevated vol-spike mark, so "50% of new baseline" can exceed
            # the cumulative credit collected. Without leg rolls this guard is
            # always satisfied (mid_pct<=0.5 implies pnl>0 for any realistic credit).
            exit_type = "PROFIT"

        elif dte_rem <= manage_at_dte:
            # ── 21-DTE management: attempt roll-for-credit or close flat ────
            if roll_for_credit and trade.roll_count < max_rolls:
                # Use roll_dte_max (default 60): at 21 DTE the next monthly
                # 3rd Friday is ~49 days out, past the entry dte_max of 45.
                _roll_dte_max = params.get("roll_dte_max", 60)
                new_exp = get_monthly_expiration(
                    eval_date, params["dte_min"], _roll_dte_max
                )
                if new_exp is not None:
                    # Cost to close current strangle
                    close_cost_old = mid_d * (1.0 + eff_c_adj) * 100.0 + 2.0 * comm
                    old_pnl = trade.net_credit - close_cost_old

                    # Price the new strangle.
                    # The roll target may be 49–56 DTE — outside entry dte_max=45 but
                    # inside roll_dte_max=60. This is intentional: strike selection is
                    # delta-based (not DTE-based), so the DB query (date, expiration,
                    # opt, target_delta) is valid. Strikes will be slightly wider than
                    # a standard ~45 DTE entry because vol × √T is larger at longer
                    # DTE. Do not 'fix' this by clamping to dte_max=45 — there is no
                    # qualifying expiration that close to roll date.
                    T_new = (new_exp - eval_date).days / 365.0
                    (new_put_k, new_call_k, new_put_mid, new_call_mid, _new_used_db) = (
                        engine.get_entry_marks(
                            S_d,
                            T_new,
                            r_d,
                            vix_d,
                            entry_date=eval_date,
                            expiration=new_exp,
                        )
                    )
                    new_net_credit = (
                        new_put_mid * (1 + eff_o_adj) + new_call_mid * (1 + eff_o_adj)
                    ) * 100.0 - 2.0 * comm

                    roll_credit_val = new_net_credit - close_cost_old

                    if roll_credit_val > 0 and new_net_credit > 0:
                        # Roll succeeds -- close old, open new
                        trade.exit_date = eval_date
                        trade.exit_dte = dte_rem
                        trade.exit_type = "ROLLED"
                        trade.pnl = round(old_pnl, 2)
                        trade.pnl_pct = old_pnl / trade.net_credit
                        trade.roll_credit = roll_credit_val
                        balance += old_pnl

                        new_trade = Trade(
                            trade_num=None,  # assigned by run_backtest
                            entry_date=eval_date,
                            expiration=new_exp,
                            entry_dte=(new_exp - eval_date).days,
                            put_strike=new_put_k,
                            call_strike=new_call_k,
                            put_mid_ps=new_put_mid,
                            call_mid_ps=new_call_mid,
                            net_credit=new_net_credit,
                            entry_vix=vix_d,
                            used_market_data=_new_used_db,
                            parent_trade_num=trade.trade_num,
                            roll_count=trade.roll_count + 1,
                        )
                        new_trade.max_vix = vix_d
                        new_trade.daily_marks = [
                            (eval_date, 0.0)
                        ]  # entry seed for Sharpe MTM series
                        return trade, new_trade, balance
                    # roll_credit <= 0 or new_net_credit <= 0: fall through to 21DTE

            # Roll not attempted or failed -- close flat
            exit_type = "21DTE"

        if exit_type:
            trade.exit_date = eval_date
            trade.exit_dte = dte_rem
            trade.exit_type = exit_type
            trade.pnl = round(pnl, 2)
            trade.pnl_pct = pnl_pct
            balance += pnl
            exited = True
            break

    if not exited:
        last = data.index[data.index <= expiration][-1]
        S_e = float(data.loc[last, "spy_close"])
        intr = max(trade.active_put_strike - S_e, 0.0) + max(
            S_e - trade.active_call_strike, 0.0
        )
        cc = intr * (1.0 + eff_c_adj) * 100.0 + 2.0 * comm
        pnl = trade.net_credit - cc
        trade.exit_date = expiration
        trade.exit_dte = 0
        trade.exit_type = "EXPIRY"
        trade.pnl = round(pnl, 2)
        trade.pnl_pct = pnl / trade.net_credit
        balance += pnl

    return trade, None, balance


# ── Backtest runner ──────────────────────────────────────────────────────

def run_backtest(
    data: pd.DataFrame, params: dict, engine=None
) -> tuple:
    """Run the full SPY short strangle backtest.

    Args:
        data: DataFrame with SPY OHLC, VIX, and risk-free rate (from load_market_data).
        params: Flat PARAMS dict (from straddle.params.PARAMS or custom).
        engine: Pricing engine instance. If None, a SyntheticEngine is created.

    Returns:
        (trades, equity_curve, skipped_entries, skipped_vix)
        - trades: list of Trade objects (one per chain leg, including ROLLED descendants)
        - equity_curve: pd.Series of balance at each trade exit date
        - skipped_entries: count of skipped entries due to single_position barrier
        - skipped_vix: count of skipped entries due to VIX filter
    """
    r_default = params.get("risk_free_rate", 0.045)
    if engine is None:
        from straddle.engines import SyntheticEngine

        engine = SyntheticEngine(params)
    o_adj = params["open_fill_adj"]
    _real = getattr(engine, "uses_real_fills", False)
    eff_o_adj = 0.0 if _real else o_adj
    comm = params["commission_per_leg"]
    balance = params["initial_balance"]
    single_position = params.get("single_position", True)
    # latest_open_exit tracks when the current chain finishes.
    # Used to skip new monthly entries while a prior position is open.
    latest_open_exit = pd.Timestamp.min

    vix_filter_enabled = params.get("vix_entry_filter_enabled", False)
    vix_entry_max = params.get("vix_entry_max", 30.0)

    trades: List[Trade] = []
    equity: dict = {}
    trade_num: int = 0
    skipped_entries: int = 0
    skipped_vix: int = 0

    for entry_date in get_entry_dates(
        data,
        params["start_date"],
        params["end_date"],
        params["dte_min"],
        params["dte_max"],
    ):
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

        expiration = get_monthly_expiration(
            entry_date, params["dte_min"], params["dte_max"]
        )
        if expiration is None:
            continue
        entry_dte = (expiration - entry_date).days
        T = entry_dte / 365.0
        r = float(row.get("risk_free_rate", r_default))

        put_k, call_k, put_mid, cal_mid, _used_db = engine.get_entry_marks(
            S, T, r, vix, entry_date=entry_date, expiration=expiration
        )

        net_credit = (
            put_mid * (1 + eff_o_adj) + cal_mid * (1 + eff_o_adj)
        ) * 100.0 - 2.0 * comm
        if net_credit <= 0.0:
            continue

        trade_num += 1
        trade = Trade(
            trade_num=trade_num,
            entry_date=entry_date,
            expiration=expiration,
            entry_dte=entry_dte,
            put_strike=put_k,
            call_strike=call_k,
            put_mid_ps=put_mid,
            call_mid_ps=cal_mid,
            net_credit=net_credit,
            entry_vix=vix,
            used_market_data=_used_db,
        )
        trade.max_vix = vix  # initialised; updated daily in evaluate_trade
        trade.daily_marks = [(entry_date, 0.0)]  # entry day: MTM value = 0

        # Iterative roll continuation -- follows the chain until a terminal exit
        active = trade
        while active is not None:
            closed, new_active, balance = evaluate_trade(
                active, data, engine, params, balance
            )
            equity[closed.exit_date] = round(balance, 2)
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

    return trades, pd.Series(equity).sort_index(), skipped_entries, skipped_vix