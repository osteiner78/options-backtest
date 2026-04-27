"""IBKR client wrapper for paper trading.

ib_insync is imported lazily inside methods — this module loads without it
installed. Tests should use MockIBKRClient instead of IBKRClient directly.

Contract convention: Option('SPY', YYYYMMDD, strike, right, 'SMART', tradingClass='SPY')
Market data type 3 = frozen/delayed (15-min delay, free).
"""

import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from straddle.paper_trading.config import PaperConfig
from straddle.paper_trading.notifications import Notifier
from straddle.paper_trading.state import PaperTrade


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class Fill:
    order_id: int
    perm_id: int
    avg_price: float
    qty: int
    commission: float
    filled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FillTimeout(Exception):
    """Raised when an IBKR order does not fill within fill_timeout_sec."""


# ── Quote sanity gate (standalone for easy testing) ──────────────────────────


def is_quote_sane(bid: float, ask: float, age_sec: float, config: PaperConfig) -> bool:
    """Return True if the quote passes all sanity checks from PaperConfig."""
    if bid <= config.quote_min_bid:
        return False
    if ask < bid:
        return False
    if bid > 0 and (ask - bid) / bid > config.quote_max_spread_pct:
        return False
    if age_sec > config.quote_max_age_sec:
        return False
    return True


# ── Real IBKR client ─────────────────────────────────────────────────────────


class IBKRClient:
    """Thin ib_insync wrapper providing the quote + order interface needed by
    PaperTradingEngine. All ib_insync symbols are imported inside methods so
    the class is importable without ib_insync installed."""

    def __init__(self, config: PaperConfig, notifier: Optional[Notifier] = None) -> None:
        self._config = config
        self._notifier = notifier
        self._ib = None  # ib_insync.IB, created in connect()

    @property
    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def connect(self) -> bool:
        """Connect with exponential backoff (3 attempts). Returns True on success."""
        import ib_insync

        ib_insync.util.patchAsyncio()
        self._ib = ib_insync.IB()
        client_id = self._config.ibkr_client_id + os.getpid() % 100

        for attempt in range(3):
            try:
                self._ib.connect(
                    self._config.ibkr_host,
                    self._config.ibkr_port,
                    clientId=client_id,
                    timeout=10,
                    readonly=False,
                )
                return True
            except Exception as exc:
                wait = 2 ** attempt
                if self._notifier:
                    self._notifier.notify(
                        "warning",
                        "IBKR connect failed",
                        f"attempt {attempt + 1}/3: {exc}; retry in {wait}s",
                    )
                time.sleep(wait)

        if self._notifier:
            self._notifier.notify("error", "IBKR disconnected", "All connection attempts failed")
        return False

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    # ── Market data ───────────────────────────────────────────────────────────

    def get_spy_close(self) -> float:
        """Return SPY last regular-session close.

        Tries reqHistoricalData first (works on paper accounts without market
        data subscriptions, and on weekends). Falls back to reqMktData type-4
        (delayed-frozen) for live-account users with a data subscription.
        """
        import ib_insync

        contract = ib_insync.Stock("SPY", "SMART", "USD")
        self._ib.qualifyContracts(contract)

        price = self._last_close_from_history(contract, "TRADES")
        if price is not None:
            return price

        # Fallback: delayed-frozen streaming tick
        self._ib.reqMarketDataType(4)
        ticker = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)
        p = ticker.close
        if p is not None and not math.isnan(p):
            return float(p)
        raise ValueError("SPY close unavailable (no market data subscription and history failed)")

    def get_vix_close(self) -> float:
        """Return VIX last close (historical + delayed-frozen fallback)."""
        import ib_insync

        contract = ib_insync.Index("VIX", "CBOE", "USD")
        self._ib.qualifyContracts(contract)

        price = self._last_close_from_history(contract, "TRADES")
        if price is not None:
            return price

        self._ib.reqMarketDataType(4)
        ticker = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)
        p = ticker.close
        if p is not None and not math.isnan(p):
            return float(p)
        raise ValueError("VIX close unavailable (no market data subscription and history failed)")

    def _run_in_loop(self, coro, timeout: float = 15):
        """Submit a coroutine to ib_insync's event loop from any thread.

        ib_insync's synchronous wrappers (reqHistoricalData, sleep, …) call
        loop.run_until_complete() internally.  That works from the main thread
        but deadlocks from a worker thread because the loop is already running.
        The fix: schedule the *async* coroutine on the running loop via
        run_coroutine_threadsafe, then block only this worker thread on the
        resulting Future — the event loop stays free to service IBKR traffic.
        """
        import asyncio
        loop = self._ib.client._loop
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _last_close_from_history(self, contract, what_to_show: str) -> Optional[float]:
        """Fetch the most recent daily close via reqHistoricalData (main-thread only)."""
        try:
            bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr="3 D",
                barSizeSetting="1 day",
                whatToShow=what_to_show,
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            )
            if bars:
                return float(bars[-1].close)
        except Exception:
            pass
        return None

    def _last_close_threadsafe(self, contract, what_to_show: str) -> Optional[float]:
        """Like _last_close_from_history but safe to call from background threads."""
        try:
            bars = self._run_in_loop(
                self._ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="3 D",
                    barSizeSetting="1 day",
                    whatToShow=what_to_show,
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                ),
                timeout=15,
            )
            if bars:
                return float(bars[-1].close)
        except Exception:
            pass
        return None

    def get_spy_close_threadsafe(self) -> Optional[float]:
        """Return SPY last close; safe to call from APScheduler worker threads."""
        import ib_insync
        contract = ib_insync.Stock("SPY", "SMART", "USD")
        try:
            self._run_in_loop(self._ib.qualifyContractsAsync(contract), timeout=10)
        except Exception:
            return None
        return self._last_close_threadsafe(contract, "TRADES")

    def get_vix_close_threadsafe(self) -> Optional[float]:
        """Return VIX last close; safe to call from APScheduler worker threads."""
        import ib_insync
        contract = ib_insync.Index("VIX", "CBOE", "USD")
        try:
            self._run_in_loop(self._ib.qualifyContractsAsync(contract), timeout=10)
        except Exception:
            return None
        return self._last_close_threadsafe(contract, "TRADES")

    def get_option_quote(
        self, strike: float, expiration: str, right: str
    ) -> Optional[dict]:
        """Return {bid, ask, mid, last, age_sec, sane} or None if data is
        unavailable. expiration is YYYYMMDD."""
        import ib_insync

        contract = ib_insync.Option(
            "SPY", expiration, strike, right, "SMART", tradingClass="SPY"
        )
        try:
            self._ib.qualifyContracts(contract)
        except Exception:
            return None

        self._ib.reqMarketDataType(4)
        ticker = self._ib.reqMktData(contract, "", False, False)
        self._ib.sleep(2)

        def _float(v) -> Optional[float]:
            return float(v) if v is not None and not math.isnan(float(v)) else None

        bid = _float(ticker.bid)
        ask = _float(ticker.ask)
        last = _float(ticker.last)

        if bid is None or ask is None:
            return None

        mid = (bid + ask) / 2

        if ticker.time is not None:
            ts = ticker.time
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
        else:
            age_sec = float("inf")

        sane = is_quote_sane(bid, ask, age_sec, self._config)
        return {"bid": bid, "ask": ask, "mid": mid, "last": last, "age_sec": age_sec, "sane": sane}

    def get_option_quote_threadsafe(
        self, strike: float, expiration: str, right: str
    ) -> Optional[dict]:
        """Return option mid price safe to call from APScheduler worker threads.

        Uses reqHistoricalDataAsync(MIDPOINT) — the same mechanism used for
        SPY/VIX closes — which works on paper accounts, weekends, and without
        a market data subscription. reqTickersAsync snapshot mode does not
        reliably return data with delayed-frozen (type 4) settings.
        """
        import ib_insync

        contract = ib_insync.Option(
            "SPY", expiration, strike, right, "SMART", tradingClass="SPY"
        )
        try:
            self._run_in_loop(self._ib.qualifyContractsAsync(contract), timeout=10)
        except Exception:
            return None

        try:
            bars = self._run_in_loop(
                self._ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="2 D",
                    barSizeSetting="1 hour",
                    whatToShow="MIDPOINT",
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                ),
                timeout=20,
            )
        except Exception:
            return None

        if not bars:
            return None

        mid = float(bars[-1].close)
        if mid <= 0 or math.isnan(mid):
            return None

        # Historical MIDPOINT gives actual mid; treat as a sane quote.
        return {"bid": mid, "ask": mid, "mid": mid, "last": mid, "age_sec": 0, "sane": True}

    def is_contract_valid(
        self, symbol: str, expiration: str, strike: float, right: str
    ) -> bool:
        """Return True if the option contract still exists in IBKR."""
        import ib_insync

        contract = ib_insync.Option(
            symbol, expiration, strike, right, "SMART", tradingClass=symbol
        )
        try:
            return len(self._ib.reqContractDetails(contract)) > 0
        except Exception:
            return False

    def validate_strike(self, strike: float) -> float:
        """Snap strike to the nearest valid SPY option strike via reqSecDefOptParams."""
        import ib_insync

        spy = ib_insync.Stock("SPY", "SMART", "USD")
        qualified = self._ib.qualifyContracts(spy)
        if not qualified:
            return round(strike)
        params = self._ib.reqSecDefOptParams("SPY", "", "STK", qualified[0].conId)
        for p in params:
            if p.exchange == "SMART" and p.strikes:
                return min(sorted(p.strikes), key=lambda s: abs(s - strike))
        return round(strike)

    # ── Order execution ───────────────────────────────────────────────────────

    def place_strangle(
        self,
        put_strike: float,
        call_strike: float,
        expiration: str,
        qty: int,
        limit_price: float,
    ) -> Fill:
        """Sell a put+call strangle as a single BAG combo order."""
        import ib_insync

        put_c = ib_insync.Option("SPY", expiration, put_strike, "P", "SMART", tradingClass="SPY")
        call_c = ib_insync.Option("SPY", expiration, call_strike, "C", "SMART", tradingClass="SPY")
        self._ib.qualifyContracts(put_c, call_c)

        combo = _make_bag("SPY")
        combo.comboLegs = [
            _combo_leg(put_c.conId, qty, "SELL"),
            _combo_leg(call_c.conId, qty, "SELL"),
        ]
        order = ib_insync.LimitOrder("BUY", qty, limit_price)
        return self._submit_and_wait(combo, order)

    def place_leg(
        self,
        strike: float,
        expiration: str,
        right: str,
        qty: int,
        limit_price: float,
        action: str,
    ) -> Fill:
        """Place a single-leg option order."""
        import ib_insync

        contract = ib_insync.Option("SPY", expiration, strike, right, "SMART", tradingClass="SPY")
        self._ib.qualifyContracts(contract)
        order = ib_insync.LimitOrder(action, qty, limit_price)
        return self._submit_and_wait(contract, order)

    def close_strangle(self, trade: PaperTrade, limit_price: float) -> Fill:
        """Buy back both legs of an open strangle at limit_price (net debit)."""
        import ib_insync

        exp = trade.expiration.strftime("%Y%m%d")
        put_c = ib_insync.Option("SPY", exp, trade.put_strike, "P", "SMART", tradingClass="SPY")
        call_c = ib_insync.Option("SPY", exp, trade.call_strike, "C", "SMART", tradingClass="SPY")
        self._ib.qualifyContracts(put_c, call_c)

        combo = _make_bag("SPY")
        combo.comboLegs = [
            _combo_leg(put_c.conId, 1, "BUY"),
            _combo_leg(call_c.conId, 1, "BUY"),
        ]
        order = ib_insync.LimitOrder("SELL", 1, limit_price)
        return self._submit_and_wait(combo, order)

    def place_roll_combo(
        self,
        close_put_strike: float,
        close_call_strike: float,
        close_expiration: str,
        open_put_strike: float,
        open_call_strike: float,
        open_expiration: str,
        limit_price: float,
    ) -> Fill:
        """Place a 4-leg roll combo (buy 2 close legs, sell 2 open legs)."""
        import ib_insync

        c_put = ib_insync.Option("SPY", close_expiration, close_put_strike, "P", "SMART", tradingClass="SPY")
        c_call = ib_insync.Option("SPY", close_expiration, close_call_strike, "C", "SMART", tradingClass="SPY")
        o_put = ib_insync.Option("SPY", open_expiration, open_put_strike, "P", "SMART", tradingClass="SPY")
        o_call = ib_insync.Option("SPY", open_expiration, open_call_strike, "C", "SMART", tradingClass="SPY")
        self._ib.qualifyContracts(c_put, c_call, o_put, o_call)

        combo = _make_bag("SPY")
        combo.comboLegs = [
            _combo_leg(c_put.conId, 1, "BUY"),
            _combo_leg(c_call.conId, 1, "BUY"),
            _combo_leg(o_put.conId, 1, "SELL"),
            _combo_leg(o_call.conId, 1, "SELL"),
        ]
        order = ib_insync.LimitOrder("BUY", 1, limit_price)
        return self._submit_and_wait(combo, order)

    def get_account_summary(self) -> dict:
        return {item.tag: item.value for item in self._ib.accountSummary()}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _submit_and_wait(self, contract, order) -> Fill:
        import ib_insync

        trade = self._ib.placeOrder(contract, order)
        deadline = time.time() + self._config.fill_timeout_sec

        while time.time() < deadline:
            self._ib.sleep(1)
            if trade.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled"):
                break

        if trade.orderStatus.status != "Filled":
            self._ib.cancelOrder(order)
            raise FillTimeout(
                f"Order not filled within {self._config.fill_timeout_sec}s "
                f"(status={trade.orderStatus.status})"
            )

        commission = sum(
            f.commissionReport.commission
            for f in trade.fills
            if f.commissionReport and not math.isnan(f.commissionReport.commission)
        )
        return Fill(
            order_id=order.orderId,
            perm_id=trade.orderStatus.permId,
            avg_price=trade.orderStatus.avgFillPrice,
            qty=int(trade.orderStatus.filled),
            commission=commission,
        )


# ── BAG helpers (ib_insync boilerplate) ──────────────────────────────────────


def _make_bag(symbol: str):
    import ib_insync

    combo = ib_insync.Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = "SMART"
    return combo


def _combo_leg(con_id: int, ratio: int, action: str):
    import ib_insync

    leg = ib_insync.ComboLeg()
    leg.conId = con_id
    leg.ratio = ratio
    leg.action = action
    leg.exchange = "SMART"
    return leg


# ── Mock for tests ────────────────────────────────────────────────────────────


class MockIBKRClient:
    """Test double for IBKRClient.

    By default place_* methods raise AssertionError so tests can verify that
    no orders are submitted during run_daily_cycle. Pass fills={...} to
    configure specific methods to return a Fill instead.

    Usage:
        mock = MockIBKRClient(spy_close=500.0, vix_close=18.0)
        mock = MockIBKRClient(fills={"place_strangle": Fill(...)})
        mock = MockIBKRClient(quotes={(480.0, "20250221", "P"): {...}})
    """

    def __init__(
        self,
        spy_close: float = 500.0,
        vix_close: float = 20.0,
        quotes: Optional[dict] = None,
        account_summary: Optional[dict] = None,
        fills: Optional[dict] = None,
        exceptions: Optional[dict] = None,
        connected: bool = True,
    ) -> None:
        self.spy_close = spy_close
        self.vix_close = vix_close
        self._quotes: dict = quotes or {}
        self._account_summary: dict = account_summary or {
            "NetLiquidation": "50000",
            "BuyingPower": "40000",
            "TotalCashValue": "50000",
            "MaintMarginReq": "0",
        }
        self._fills: dict = fills or {}
        self._exceptions: dict = exceptions or {}
        self._connected = connected

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_spy_close(self) -> float:
        return self.spy_close

    def get_vix_close(self) -> float:
        return self.vix_close

    def get_option_quote(self, strike: float, expiration: str, right: str) -> Optional[dict]:
        return self._quotes.get((strike, expiration, right))

    def is_contract_valid(self, symbol: str, expiration: str, strike: float, right: str) -> bool:
        return True

    def validate_strike(self, strike: float) -> float:
        return round(strike)

    def place_strangle(self, *args, **kwargs) -> Fill:
        return self._fill_or_raise("place_strangle")

    def place_leg(self, *args, **kwargs) -> Fill:
        return self._fill_or_raise("place_leg")

    def close_strangle(self, *args, **kwargs) -> Fill:
        return self._fill_or_raise("close_strangle")

    def place_roll_combo(self, *args, **kwargs) -> Fill:
        return self._fill_or_raise("place_roll_combo")

    def get_account_summary(self) -> dict:
        return self._account_summary

    def _fill_or_raise(self, method: str) -> Fill:
        if method in self._exceptions:
            raise self._exceptions[method]
        if method in self._fills:
            return self._fills[method]
        raise AssertionError(
            f"MockIBKRClient.{method} called but no fill configured — "
            "this means an order was placed when it should not have been"
        )
