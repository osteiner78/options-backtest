"""PaperTradingEngine orchestrator.

Ties together the strategy evaluator, IBKR client, state store, and notifier.
All IBKR interaction is injected via the ibkr argument — pass MockIBKRClient
for offline/dry-run operation, IBKRClient for live paper trading.

Lifecycle per daily cycle (4:30 PM ET):
  1. Snapshot market data (IBKR delayed + Yahoo risk-free).
  2. Build a lookback DataFrame for the evaluator (≥10 trading days + today).
  3. For each open trade: deep-copy → evaluate → persist bookkeeping → maybe signal.
     Rule: one signal per trade per cycle (leg-roll wins over exit).
  4. If should_enter_today: enqueue entry signal.
  5. Record equity snapshot, tick heartbeat.

process_approved_signals (every 5 s):
  - In dry_run mode: no-op (signals stay approved, UI can still display them).
  - In live mode: revalidate → IBKR → fill → mutate canonical trade → notify.
"""

import copy
import json
import math
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from straddle.engines import PricingContext, make_engine
from straddle.paper_trading.config import PaperConfig
from straddle.paper_trading.ibkr_client import Fill, FillTimeout, is_quote_sane
from straddle.paper_trading.notifications import Notifier
from straddle.paper_trading.state import (
    PaperTrade,
    PendingSignal,
    SignalStatus,
    SignalType,
    StateStore,
)
from straddle.strategy import (
    LegRollEvent,
    Trade,
    TradeStepResult,
    build_entry,
    evaluate_trade_step,
    get_monthly_expiration,
)


def today_naive_ny() -> pd.Timestamp:
    """Return today's date in America/New_York as a tz-naive Timestamp."""
    return pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)


class PaperTradingEngine:
    def __init__(
        self,
        params: dict,
        config: PaperConfig,
        ibkr,
        store: StateStore,
        notifier: Notifier,
        pricing_engine,
        *,
        dry_run: bool = False,
        data_loader: Optional[Callable] = None,
    ) -> None:
        self._params = params
        self._config = config
        self._ibkr = ibkr
        self._store = store
        self._notifier = notifier
        self._engine = pricing_engine
        self._dry_run = dry_run

        if data_loader is None:
            from straddle.data import load_market_data
            self._data_loader = load_market_data
        else:
            self._data_loader = data_loader

    # ── Public API ────────────────────────────────────────────────────────────

    def run_daily_cycle(self, today: pd.Timestamp) -> None:
        market_row = self._snapshot_market(today)
        data_df = self._build_lookback_df(today, market_row)

        for pt in self._store.load_open_trades():
            trade = _paper_trade_to_trade(pt, self._store.load_leg_rolls(pt.trade_num))
            snapshot = copy.deepcopy(trade)
            n_rolls_before = len(snapshot.leg_rolls)

            res = evaluate_trade_step(snapshot, today, data_df, self._engine, self._params)

            self._persist_daily_mark(pt, snapshot.daily_marks[-1])
            self._persist_max_vix(pt, snapshot.max_vix)

            if len(snapshot.leg_rolls) > n_rolls_before:
                self._enqueue_signal_leg_roll(pt, trade, snapshot, market_row)
            elif res.exited:
                self._enqueue_signal_exit(pt, trade, snapshot, res, market_row)

        if self._should_enter_today(today, market_row):
            self._enqueue_entry_signal(today, market_row, data_df)

        self._store.record_equity(
            today,
            nlv=self._calc_nlv(market_row),
            cash=0.0,
            source="MTM",
        )
        self._store.tick_heartbeat(
            last_eval_at=today,
            ibkr_connected=self._ibkr.is_connected,
            dry_run=self._dry_run,
        )

    def process_approved_signals(self) -> None:
        if self._dry_run:
            return
        for sig in self._store.list_signals(status=SignalStatus.APPROVED):
            try:
                self._execute_signal(sig)
            except Exception as exc:
                self._store.update_signal_status(
                    sig.id, SignalStatus.FAILED, error_msg=str(exc)
                )
                self._notifier.notify("error", "Signal execution failed", str(exc))

    def run_intraday_check(self) -> None:
        if not self._config.intraday_enabled:
            return
        market_row = self._snapshot_market(pd.Timestamp.now().normalize())
        for pt in self._store.load_open_trades():
            if self._intraday_stop_triggered(pt, market_row):
                self._enqueue_signal_intraday_stop(pt, market_row)

    def fire_manual_entry(
        self,
        expiration: str,
        put_strike: Optional[float] = None,
        call_strike: Optional[float] = None,
        qty: int = 1,
    ) -> int:
        """Enqueue a manual entry signal. Returns signal id."""
        today = today_naive_ny()
        market_row = self._snapshot_market(today)
        data_df = self._build_lookback_df(today, market_row)

        exp_ts = pd.Timestamp(expiration)
        T = max((exp_ts - today).days / 365.0, 1e-7)
        S = market_row["spy_close"]
        r = market_row["risk_free_rate"]
        vix = market_row["vix_close"]
        entry_dte = (exp_ts - today).days

        ctx = PricingContext(eval_date=today, expiration=exp_ts)

        if put_strike is None or call_strike is None:
            kw = build_entry(self._engine, S, T, r, vix, entry_dte, ctx, self._params)
            if kw is None:
                raise ValueError("build_entry returned None — no valid strangle for this expiration")
            put_strike = put_strike or kw["put_strike"]
            call_strike = call_strike or kw["call_strike"]
        else:
            kw = {
                "put_strike": put_strike,
                "call_strike": call_strike,
                "put_mid_ps": self._engine.get_leg_mark(put_strike, S, entry_dte, vix, r, "put", ctx=ctx),
                "call_mid_ps": self._engine.get_leg_mark(call_strike, S, entry_dte, vix, r, "call", ctx=ctx),
                "net_credit": 0.0,
                "used_market_data": False,
            }

        put_q = self._get_quote(put_strike, exp_ts.strftime("%Y%m%d"), "P", S, T, r, vix)
        call_q = self._get_quote(call_strike, exp_ts.strftime("%Y%m%d"), "C", S, T, r, vix)
        limit_price = put_q["bs_mid"] + call_q["bs_mid"]

        payload = {
            "entry_date": str(today.date()),
            "expiration": str(exp_ts.date()),
            "put_strike": put_strike,
            "call_strike": call_strike,
            "put_mid_ps": kw["put_mid_ps"],
            "call_mid_ps": kw["call_mid_ps"],
            "net_credit": kw.get("net_credit", 0.0),
            "entry_dte": entry_dte,
            "entry_vix": vix,
            "limit_price": limit_price,
            "put_ibkr_mid": put_q["ibkr_mid"],
            "call_ibkr_mid": call_q["ibkr_mid"],
            "put_bs_mid": put_q["bs_mid"],
            "call_bs_mid": call_q["bs_mid"],
            "quote_source": put_q["source"],
            "qty": qty,
            "manual": True,
        }

        sig = PendingSignal(
            signal_type=SignalType.MANUAL,
            payload_json=json.dumps(payload),
        )
        return self._store.enqueue_signal(sig)

    # ── Market data ───────────────────────────────────────────────────────────

    def _snapshot_market(self, today: pd.Timestamp) -> dict:
        spy_close = vix_close = None

        if self._ibkr.is_connected:
            try:
                spy_close = self._ibkr.get_spy_close()
                vix_close = self._ibkr.get_vix_close()
            except Exception as exc:
                self._notifier.notify("warning", "IBKR market data failed", str(exc))

        risk_free_rate = self._params.get("risk_free_rate", 0.05)

        if spy_close is None or vix_close is None:
            lookback_start = str((today - pd.Timedelta(days=7)).date())
            lookback_end = str((today - pd.Timedelta(days=1)).date())
            try:
                hist = self._data_loader(lookback_start, lookback_end)
                if not hist.empty:
                    row = hist.iloc[-1]
                    if spy_close is None:
                        spy_close = float(row["spy_close"])
                    if vix_close is None:
                        vix_close = float(row["vix_close"])
                    rf = float(row.get("risk_free_rate", risk_free_rate))
                    if not math.isnan(rf):
                        risk_free_rate = rf
            except Exception as exc:
                raise RuntimeError(f"Cannot get market data for {today}") from exc

        if spy_close is None or vix_close is None:
            raise RuntimeError(f"Market data unavailable for {today}")

        return {
            "spy_close": spy_close,
            "spy_open": spy_close,
            "spy_high": spy_close,
            "spy_low": spy_close,
            "vix_close": vix_close,
            "risk_free_rate": risk_free_rate,
        }

    def _build_lookback_df(self, today: pd.Timestamp, market_row: dict) -> pd.DataFrame:
        lookback_start = str((today - pd.Timedelta(days=30)).date())
        lookback_end = str((today - pd.Timedelta(days=1)).date())
        try:
            hist = self._data_loader(lookback_start, lookback_end)
        except Exception:
            hist = pd.DataFrame()

        today_row = pd.DataFrame([{
            "spy_open": market_row["spy_open"],
            "spy_high": market_row["spy_high"],
            "spy_low": market_row["spy_low"],
            "spy_close": market_row["spy_close"],
            "vix_close": market_row["vix_close"],
            "risk_free_rate": market_row["risk_free_rate"],
        }], index=[today])

        combined = pd.concat([hist, today_row])
        combined = combined[~combined.index.duplicated(keep="last")]
        return combined.sort_index()

    # ── Quote (hybrid IBKR / BS) ─────────────────────────────────────────────

    def _get_quote(
        self,
        strike: float,
        expiration_yyyymmdd: str,
        right: str,
        S: float,
        T_years: float,
        r: float,
        vix: float,
    ) -> dict:
        """Return {limit_price, ibkr_mid, bs_mid, source}.

        Prefers IBKR mid when sane; falls back to BS+skew.
        Both prices are always computed so the UI can show the spread.
        """
        ctx = PricingContext(
            expiration=pd.Timestamp(expiration_yyyymmdd),
            eval_date=pd.Timestamp(expiration_yyyymmdd) - pd.Timedelta(days=int(T_years * 365)),
        )
        dte = max(int(T_years * 365), 1)
        bs_mid = float(self._engine.get_leg_mark(strike, S, dte, vix, r, right.lower(), ctx=ctx))

        ibkr_mid = None
        source = "bs"
        limit_price = bs_mid

        if self._ibkr.is_connected:
            quote = self._ibkr.get_option_quote(strike, expiration_yyyymmdd, right)
            if quote and quote.get("sane"):
                ibkr_mid = quote["mid"]
                source = "ibkr"
                limit_price = ibkr_mid

        return {"limit_price": limit_price, "ibkr_mid": ibkr_mid, "bs_mid": bs_mid, "source": source}

    # ── Entry signal ──────────────────────────────────────────────────────────

    def _should_enter_today(self, today: pd.Timestamp, market_row: dict) -> bool:
        if self._store.load_open_trades():
            return False

        month_start = today.replace(day=1)
        next_month = month_start + pd.DateOffset(months=1)
        if self._store.load_trades_in_range(month_start, next_month):
            return False

        dte_min = self._params["dte_min"]
        dte_max = self._params["dte_max"]
        if get_monthly_expiration(today, dte_min, dte_max) is None:
            return False

        if self._params.get("vix_entry_filter_enabled", False):
            vix = market_row["vix_close"]
            vix_low = self._params.get("vix_low", 0.0)
            vix_high = self._params.get("vix_high", 999.0)
            if not (vix_low <= vix <= vix_high):
                return False

        return True

    def _enqueue_entry_signal(
        self, today: pd.Timestamp, market_row: dict, data_df: pd.DataFrame
    ) -> None:
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]

        dte_min = self._params["dte_min"]
        dte_max = self._params["dte_max"]
        expiration = get_monthly_expiration(today, dte_min, dte_max)
        if expiration is None:
            return

        entry_dte = (expiration - today).days
        T = max(entry_dte / 365.0, 1e-7)
        ctx = PricingContext(eval_date=today, expiration=expiration)

        kw = build_entry(self._engine, S, T, r, vix, entry_dte, ctx, self._params)
        if kw is None:
            return

        exp_str = expiration.strftime("%Y%m%d")
        put_q = self._get_quote(kw["put_strike"], exp_str, "P", S, T, r, vix)
        call_q = self._get_quote(kw["call_strike"], exp_str, "C", S, T, r, vix)
        limit_price = put_q["limit_price"] + call_q["limit_price"]

        payload = {
            "entry_date": str(today.date()),
            "expiration": str(expiration.date()),
            "put_strike": kw["put_strike"],
            "call_strike": kw["call_strike"],
            "put_mid_ps": kw["put_mid_ps"],
            "call_mid_ps": kw["call_mid_ps"],
            "net_credit": kw["net_credit"],
            "entry_dte": entry_dte,
            "entry_vix": vix,
            "limit_price": limit_price,
            "put_ibkr_mid": put_q["ibkr_mid"],
            "call_ibkr_mid": call_q["ibkr_mid"],
            "put_bs_mid": put_q["bs_mid"],
            "call_bs_mid": call_q["bs_mid"],
            "quote_source": put_q["source"],
            "qty": 1,
            "manual": False,
        }

        self._store.enqueue_signal(PendingSignal(
            signal_type=SignalType.ENTRY,
            payload_json=json.dumps(payload),
        ))

    # ── Exit / leg-roll signals ───────────────────────────────────────────────

    def _enqueue_signal_exit(
        self,
        pt: PaperTrade,
        trade: Trade,
        snapshot: Trade,
        res: TradeStepResult,
        market_row: dict,
    ) -> None:
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        exp_str = trade.expiration.strftime("%Y%m%d")
        T = max((trade.expiration - pd.Timestamp.now().normalize()).days / 365.0, 1e-7)

        if res.exit_type == "ROLLED" and res.new_trade is not None:
            self._enqueue_signal_roll(pt, trade, snapshot, res, market_row)
            return

        put_q = self._get_quote(trade.active_put_strike, exp_str, "P", S, T, r, vix)
        call_q = self._get_quote(trade.active_call_strike, exp_str, "C", S, T, r, vix)

        payload = {
            "trade_num": pt.trade_num,
            "exit_type": res.exit_type,
            "put_strike": trade.active_put_strike,
            "call_strike": trade.active_call_strike,
            "expiration": exp_str,
            "pnl": res.pnl,
            "pnl_pct": res.pnl_pct,
            "close_cost": res.close_cost,
            "limit_price": put_q["limit_price"] + call_q["limit_price"],
            "put_ibkr_mid": put_q["ibkr_mid"],
            "call_ibkr_mid": call_q["ibkr_mid"],
            "put_bs_mid": put_q["bs_mid"],
            "call_bs_mid": call_q["bs_mid"],
            "stop_regime": snapshot.stop_regime,
            "overshoot_used": snapshot.overshoot_used,
        }

        self._store.enqueue_signal(PendingSignal(
            signal_type=SignalType.CLOSE,
            trade_num=pt.trade_num,
            payload_json=json.dumps(payload),
        ))

    def _enqueue_signal_roll(
        self,
        pt: PaperTrade,
        trade: Trade,
        snapshot: Trade,
        res: TradeStepResult,
        market_row: dict,
    ) -> None:
        nt = res.new_trade
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]

        close_exp = trade.expiration.strftime("%Y%m%d")
        open_exp = nt.expiration.strftime("%Y%m%d")
        T_open = max((nt.expiration - pd.Timestamp.now().normalize()).days / 365.0, 1e-7)

        cp_q = self._get_quote(trade.active_put_strike, close_exp, "P", S, 0.01, r, vix)
        cc_q = self._get_quote(trade.active_call_strike, close_exp, "C", S, 0.01, r, vix)
        op_q = self._get_quote(nt.put_strike, open_exp, "P", S, T_open, r, vix)
        oc_q = self._get_quote(nt.call_strike, open_exp, "C", S, T_open, r, vix)

        payload = {
            "trade_num": pt.trade_num,
            "close_put_strike": trade.active_put_strike,
            "close_call_strike": trade.active_call_strike,
            "close_expiration": close_exp,
            "open_put_strike": nt.put_strike,
            "open_call_strike": nt.call_strike,
            "open_expiration": open_exp,
            "pnl": res.pnl,
            "pnl_pct": res.pnl_pct,
            "roll_credit": snapshot.roll_credit,
            "limit_price": (op_q["limit_price"] + oc_q["limit_price"]
                            - cp_q["limit_price"] - cc_q["limit_price"]),
            "new_trade": {
                "put_strike": nt.put_strike,
                "call_strike": nt.call_strike,
                "put_mid_ps": nt.put_mid_ps,
                "call_mid_ps": nt.call_mid_ps,
                "net_credit": nt.net_credit,
                "entry_dte": nt.entry_dte,
                "entry_vix": nt.entry_vix,
            },
        }

        self._store.enqueue_signal(PendingSignal(
            signal_type=SignalType.ROLL,
            trade_num=pt.trade_num,
            payload_json=json.dumps(payload),
        ))

    def _enqueue_signal_leg_roll(
        self,
        pt: PaperTrade,
        trade: Trade,
        snapshot: Trade,
        market_row: dict,
    ) -> None:
        new_event = snapshot.leg_rolls[-1]
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        exp_str = trade.expiration.strftime("%Y%m%d")
        T = max((trade.expiration - pd.Timestamp.now().normalize()).days / 365.0, 1e-7)

        new_k = new_event.new_strike
        old_k = new_event.old_strike
        side = new_event.side
        right = "P" if side == "put" else "C"

        close_q = self._get_quote(old_k, exp_str, right, S, T, r, vix)
        open_q = self._get_quote(new_k, exp_str, right, S, T, r, vix)

        payload = {
            "trade_num": pt.trade_num,
            "side": side,
            "old_strike": old_k,
            "new_strike": new_k,
            "expiration": exp_str,
            "debit_paid": new_event.close_cost_ps * 100 - new_event.new_credit_ps * 100,
            "net_credit_delta": new_event.net_credit_dollar,
            "close_ibkr_mid": close_q["ibkr_mid"],
            "close_bs_mid": close_q["bs_mid"],
            "open_ibkr_mid": open_q["ibkr_mid"],
            "open_bs_mid": open_q["bs_mid"],
            "limit_price": close_q["limit_price"] - open_q["limit_price"],
            "new_put_strike": snapshot.active_put_strike,
            "new_call_strike": snapshot.active_call_strike,
            "current_baseline_mid": snapshot.current_baseline_mid,
        }

        self._store.enqueue_signal(PendingSignal(
            signal_type=SignalType.LEG_ROLL,
            trade_num=pt.trade_num,
            payload_json=json.dumps(payload),
        ))

    def _enqueue_signal_intraday_stop(self, pt: PaperTrade, market_row: dict) -> None:
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        exp_str = pt.expiration.strftime("%Y%m%d")
        T = max((pt.expiration - pd.Timestamp.now().normalize()).days / 365.0, 1e-7)

        put_q = self._get_quote(pt.put_strike, exp_str, "P", S, T, r, vix)
        call_q = self._get_quote(pt.call_strike, exp_str, "C", S, T, r, vix)

        payload = {
            "trade_num": pt.trade_num,
            "exit_type": "STOP",
            "put_strike": pt.put_strike,
            "call_strike": pt.call_strike,
            "expiration": exp_str,
            "limit_price": put_q["limit_price"] + call_q["limit_price"],
            "put_bs_mid": put_q["bs_mid"],
            "call_bs_mid": call_q["bs_mid"],
            "intraday": True,
        }

        self._store.enqueue_signal(PendingSignal(
            signal_type=SignalType.CLOSE,
            trade_num=pt.trade_num,
            payload_json=json.dumps(payload),
        ))

    # ── Signal execution ──────────────────────────────────────────────────────

    def _execute_signal(self, sig: PendingSignal) -> None:
        self._store.update_signal_status(sig.id, SignalStatus.SUBMITTING)
        payload = json.loads(sig.payload_json)

        try:
            if sig.signal_type in (SignalType.ENTRY, SignalType.MANUAL):
                self._execute_entry(sig, payload)
            elif sig.signal_type == SignalType.CLOSE:
                self._execute_close(sig, payload)
            elif sig.signal_type == SignalType.ROLL:
                self._execute_roll(sig, payload)
            elif sig.signal_type == SignalType.LEG_ROLL:
                self._execute_leg_roll(sig, payload)
            elif sig.signal_type == SignalType.OPEN_RECOVERY:
                self._execute_entry(sig, payload)
        except FillTimeout as exc:
            self._store.update_signal_status(sig.id, SignalStatus.CANCELLED, error_msg=str(exc))
            self._notifier.notify("warning", "Order timed out", str(exc))
        except Exception as exc:
            raise

    def _fill_entry_defaults(self, payload: dict) -> dict:
        """Compute default strikes and mids for a /fire signal that omitted them."""
        today = today_naive_ny()
        exp_ts = pd.Timestamp(payload["expiration"])
        entry_dte = (exp_ts - today).days
        T = max(entry_dte / 365.0, 1e-7)
        market_row = self._snapshot_market(today)
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        ctx = PricingContext(eval_date=today, expiration=exp_ts)
        kw = build_entry(self._engine, S, T, r, vix, entry_dte, ctx, self._params)
        if kw is None:
            raise ValueError("build_entry returned None — no valid strangle for this expiration")
        exp_str = exp_ts.strftime("%Y%m%d")
        put_q = self._get_quote(kw["put_strike"], exp_str, "P", S, T, r, vix)
        call_q = self._get_quote(kw["call_strike"], exp_str, "C", S, T, r, vix)
        return {
            **payload,
            "entry_date": str(today.date()),
            "put_strike": payload.get("put_strike") or kw["put_strike"],
            "call_strike": payload.get("call_strike") or kw["call_strike"],
            "put_mid_ps": kw["put_mid_ps"],
            "call_mid_ps": kw["call_mid_ps"],
            "net_credit": kw["net_credit"],
            "entry_dte": entry_dte,
            "entry_vix": vix,
            "limit_price": put_q["limit_price"] + call_q["limit_price"],
            "put_ibkr_mid": put_q["ibkr_mid"],
            "call_ibkr_mid": call_q["ibkr_mid"],
            "put_bs_mid": put_q["bs_mid"],
            "call_bs_mid": call_q["bs_mid"],
            "quote_source": put_q["source"],
        }

    def _execute_entry(self, sig: PendingSignal, payload: dict) -> None:
        # For /fire signals the UI may omit strikes — compute defaults now.
        if not payload.get("put_strike") or not payload.get("call_strike"):
            payload = self._fill_entry_defaults(payload)

        # Validate strikes against IBKR's actual listed contracts (snap to nearest).
        if self._ibkr.is_connected:
            payload["put_strike"] = self._ibkr.validate_strike(payload["put_strike"])
            payload["call_strike"] = self._ibkr.validate_strike(payload["call_strike"])

        fill = self._ibkr.place_strangle(
            put_strike=payload["put_strike"],
            call_strike=payload["call_strike"],
            expiration=str(payload["expiration"]).replace("-", ""),
            qty=payload.get("qty", 1),
            limit_price=payload["limit_price"] or (payload["put_bs_mid"] or 0) + (payload["call_bs_mid"] or 0),
        )

        meta = {
            "put_mid_ps": payload["put_mid_ps"],
            "call_mid_ps": payload["call_mid_ps"],
            "entry_vix": payload["entry_vix"],
            "entry_dte": payload["entry_dte"],
            "max_vix": payload["entry_vix"],
        }

        pt = PaperTrade(
            entry_date=pd.Timestamp(payload["entry_date"]),
            expiration=pd.Timestamp(payload["expiration"]),
            put_strike=payload["put_strike"],
            call_strike=payload["call_strike"],
            net_credit=payload["net_credit"] or fill.avg_price * 100,
            daily_marks_json=json.dumps([[payload["entry_date"], 0.0]]),
            manual=payload.get("manual", False),
            ibkr_perm_id=str(fill.perm_id),
            metadata_json=json.dumps(meta),
        )
        self._store.save_trade(pt)
        self._store.update_signal_status(
            sig.id, SignalStatus.FILLED, fill_json=json.dumps(_fill_to_dict(fill))
        )
        self._notifier.notify(
            "success",
            "Entry filled",
            f"Strangle {payload['put_strike']}P/{payload['call_strike']}C "
            f"exp {payload['expiration']} @ ${fill.avg_price:.2f}",
        )

    def _execute_close(self, sig: PendingSignal, payload: dict) -> None:
        pt = self._store.load_trade(sig.trade_num)
        if pt is None:
            raise ValueError(f"Trade {sig.trade_num} not found")

        fill = self._ibkr.close_strangle(pt, payload["limit_price"])

        pnl = pt.net_credit - fill.avg_price * 100 - 2 * self._params["commission_per_leg"]
        meta = json.loads(pt.metadata_json)
        meta["stop_regime"] = payload.get("stop_regime")
        meta["overshoot_used"] = payload.get("overshoot_used")
        meta["pnl_pct"] = pnl / pt.net_credit if pt.net_credit else 0.0

        today = today_naive_ny()
        pt.status = "closed"
        pt.exit_date = today
        pt.exit_type = payload.get("exit_type", "CLOSE")
        pt.pnl = round(pnl, 2)
        pt.metadata_json = json.dumps(meta)
        self._store.save_trade(pt)

        self._store.update_signal_status(
            sig.id, SignalStatus.FILLED, fill_json=json.dumps(_fill_to_dict(fill))
        )
        self._notifier.notify(
            "success", "Close filled",
            f"Trade {pt.trade_num} closed, P&L ${pnl:+.2f}",
        )

    def _execute_roll(self, sig: PendingSignal, payload: dict) -> None:
        pt = self._store.load_trade(sig.trade_num)
        if pt is None:
            raise ValueError(f"Trade {sig.trade_num} not found")

        today = today_naive_ny()

        # Step 1: close the existing strangle
        close_fill = self._ibkr.close_strangle(pt, payload["limit_price"])
        close_pnl = pt.net_credit - close_fill.avg_price * 100

        pt.status = "closed"
        pt.exit_date = today
        pt.exit_type = "ROLLED"
        pt.pnl = round(close_pnl, 2)
        pt.roll_count = pt.roll_count
        meta = json.loads(pt.metadata_json)
        meta["roll_credit"] = payload.get("roll_credit")
        pt.metadata_json = json.dumps(meta)
        self._store.save_trade(pt)

        # Step 2: open the new strangle
        nt = payload["new_trade"]
        try:
            open_fill = self._ibkr.place_strangle(
                put_strike=nt["put_strike"],
                call_strike=nt["call_strike"],
                expiration=payload["open_expiration"],
                qty=1,
                limit_price=nt["put_mid_ps"] + nt["call_mid_ps"],
            )
        except Exception as exc:
            # Close filled but open failed → emit OPEN_RECOVERY
            self._store.update_signal_status(
                sig.id, SignalStatus.FAILED, error_msg=f"open failed after close: {exc}"
            )
            recovery_payload = {**nt, "parent_signal_id": sig.id, "expiration": payload["open_expiration"]}
            self._store.enqueue_signal(PendingSignal(
                signal_type=SignalType.OPEN_RECOVERY,
                trade_num=pt.trade_num,
                payload_json=json.dumps(recovery_payload),
                parent_signal_id=sig.id,
            ))
            self._notifier.notify(
                "error", "Roll partial: open failed",
                f"Trade {pt.trade_num} closed but new strangle not placed — OPEN_RECOVERY enqueued",
            )
            return

        new_meta = {
            "put_mid_ps": nt["put_mid_ps"],
            "call_mid_ps": nt["call_mid_ps"],
            "entry_vix": nt.get("entry_vix", 0.0),
            "entry_dte": nt.get("entry_dte", 0),
            "max_vix": nt.get("entry_vix", 0.0),
        }
        new_pt = PaperTrade(
            entry_date=today,
            expiration=pd.Timestamp(payload["open_expiration"]),
            put_strike=nt["put_strike"],
            call_strike=nt["call_strike"],
            net_credit=nt["net_credit"] or open_fill.avg_price * 100,
            parent_trade_num=pt.trade_num,
            roll_count=pt.roll_count + 1,
            daily_marks_json=json.dumps([[str(today.date()), 0.0]]),
            ibkr_perm_id=str(open_fill.perm_id),
            metadata_json=json.dumps(new_meta),
        )
        self._store.save_trade(new_pt)
        self._store.update_signal_status(
            sig.id, SignalStatus.FILLED, fill_json=json.dumps(_fill_to_dict(open_fill))
        )
        self._notifier.notify("success", "Roll filled", f"Trade {pt.trade_num} rolled into new strangle")

    def _execute_leg_roll(self, sig: PendingSignal, payload: dict) -> None:
        pt = self._store.load_trade(sig.trade_num)
        if pt is None:
            raise ValueError(f"Trade {sig.trade_num} not found")

        side = payload["side"]
        old_k = payload["old_strike"]
        new_k = payload["new_strike"]
        exp = payload["expiration"]
        right = "P" if side == "put" else "C"

        # Buy back old leg, sell new leg
        close_fill = self._ibkr.place_leg(old_k, exp, right, 1, payload["limit_price"], "BUY")
        open_fill = self._ibkr.place_leg(new_k, exp, right, 1, 0.0, "SELL")

        debit_paid = close_fill.avg_price * 100 - open_fill.avg_price * 100
        net_credit_delta = -debit_paid

        meta = json.loads(pt.metadata_json)
        if side == "put":
            meta["current_put_strike"] = new_k
        else:
            meta["current_call_strike"] = new_k
        meta["current_baseline_mid"] = payload.get("current_baseline_mid")
        pt.net_credit += net_credit_delta
        pt.metadata_json = json.dumps(meta)
        self._store.save_trade(pt)

        self._store.save_leg_roll(
            trade_num=pt.trade_num,
            event_date=pd.Timestamp.now().normalize(),
            side=side,
            old_strike=old_k,
            new_strike=new_k,
            debit_paid=debit_paid,
            data_json=json.dumps(payload),
        )

        self._store.update_signal_status(
            sig.id, SignalStatus.FILLED,
            fill_json=json.dumps({"close": _fill_to_dict(close_fill), "open": _fill_to_dict(open_fill)}),
        )
        self._notifier.notify(
            "success", "Leg roll filled",
            f"Trade {pt.trade_num} {side} rolled {old_k} → {new_k}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _persist_daily_mark(self, pt: PaperTrade, mark: tuple) -> None:
        marks = json.loads(pt.daily_marks_json)
        marks.append([str(mark[0].date()), float(mark[1])])
        pt.daily_marks_json = json.dumps(marks)
        self._store.save_trade(pt)

    def _persist_max_vix(self, pt: PaperTrade, max_vix: Optional[float]) -> None:
        if max_vix is None:
            return
        meta = json.loads(pt.metadata_json)
        old = meta.get("max_vix", 0.0) or 0.0
        if max_vix > old:
            meta["max_vix"] = max_vix
            pt.metadata_json = json.dumps(meta)
            self._store.save_trade(pt)

    def _calc_nlv(self, market_row: dict) -> float:
        total_mtm = 0.0
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        for pt in self._store.load_open_trades():
            marks = json.loads(pt.daily_marks_json)
            if marks:
                total_mtm += float(marks[-1][1])
        return total_mtm

    def _intraday_stop_triggered(self, pt: PaperTrade, market_row: dict) -> bool:
        S = market_row["spy_close"]
        vix = market_row["vix_close"]
        r = market_row["risk_free_rate"]
        T = max((pt.expiration - pd.Timestamp.now().normalize()).days / 365.0, 1e-7)
        ctx = PricingContext(expiration=pt.expiration)
        put_mid = self._engine.get_leg_mark(pt.put_strike, S, int(T * 365), vix, r, "put", ctx=ctx)
        call_mid = self._engine.get_leg_mark(pt.call_strike, S, int(T * 365), vix, r, "call", ctx=ctx)
        current_cost = (put_mid + call_mid) * 100
        pnl = pt.net_credit - current_cost
        stop = self._params["stop_loss_pct"]
        return pnl < -stop * pt.net_credit


# ── Conversion helpers (PaperTrade ↔ Trade) ──────────────────────────────────


def _paper_trade_to_trade(pt: PaperTrade, leg_rolls_raw: list) -> Trade:
    """Reconstruct a strategy.Trade from a PaperTrade DB record."""
    meta = json.loads(pt.metadata_json) if pt.metadata_json else {}

    daily_marks = [
        (pd.Timestamp(d), float(v))
        for d, v in json.loads(pt.daily_marks_json)
    ]

    leg_rolls = [
        LegRollEvent(
            event_date=pd.Timestamp(r["event_date"]),
            side=r["side"],
            old_strike=float(r["old_strike"]),
            new_strike=float(r["new_strike"]),
            close_cost_ps=float(json.loads(r.get("data_json") or "{}").get("close_cost_ps", 0.0)),
            new_credit_ps=float(json.loads(r.get("data_json") or "{}").get("new_credit_ps", 0.0)),
            net_credit_dollar=float(json.loads(r.get("data_json") or "{}").get("net_credit_delta", 0.0)),
            trigger_delta=float(json.loads(r.get("data_json") or "{}").get("trigger_delta", 0.0)),
        )
        for r in leg_rolls_raw
    ]

    entry_dte = int(meta.get("entry_dte", (pt.expiration - pt.entry_date).days))
    put_mid_ps = float(meta.get("put_mid_ps", pt.net_credit / 200.0))
    call_mid_ps = float(meta.get("call_mid_ps", pt.net_credit / 200.0))

    return Trade(
        trade_num=pt.trade_num,
        entry_date=pt.entry_date,
        expiration=pt.expiration,
        entry_dte=entry_dte,
        put_strike=pt.put_strike,
        call_strike=pt.call_strike,
        put_mid_ps=put_mid_ps,
        call_mid_ps=call_mid_ps,
        net_credit=pt.net_credit,
        entry_vix=float(meta.get("entry_vix", 0.0)),
        exit_date=pt.exit_date,
        exit_type=pt.exit_type,
        pnl=pt.pnl,
        pnl_pct=float(meta.get("pnl_pct", 0.0)) if meta.get("pnl_pct") is not None else None,
        stop_regime=meta.get("stop_regime"),
        overshoot_used=float(meta["overshoot_used"]) if meta.get("overshoot_used") is not None else None,
        max_vix=float(meta.get("max_vix", 0.0)) if meta.get("max_vix") is not None else None,
        used_market_data=bool(meta.get("used_market_data", False)),
        parent_trade_num=pt.parent_trade_num,
        roll_count=pt.roll_count,
        daily_marks=daily_marks,
        leg_rolls=leg_rolls,
        current_put_strike=float(meta["current_put_strike"]) if meta.get("current_put_strike") is not None else None,
        current_call_strike=float(meta["current_call_strike"]) if meta.get("current_call_strike") is not None else None,
        current_baseline_mid=float(meta["current_baseline_mid"]) if meta.get("current_baseline_mid") is not None else None,
    )


def _fill_to_dict(fill: Fill) -> dict:
    return {
        "order_id": fill.order_id,
        "perm_id": fill.perm_id,
        "avg_price": fill.avg_price,
        "qty": fill.qty,
        "commission": fill.commission,
        "filled_at": fill.filled_at.isoformat(),
    }
