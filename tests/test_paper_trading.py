"""Tests for paper trading milestones 2 and 3: config, auth, notifications, IBKR client."""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from straddle.paper_trading.auth import (
    create_session,
    destroy_session,
    hash_password,
    require_token,
    verify_password,
)
from straddle.paper_trading.config import (
    PaperConfig,
    load,
    save,
    to_public_dict,
    update_from_public,
)
from straddle.paper_trading.notifications import Notifier
from straddle.paper_trading.state import Notification, StateStore


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_store(tmp_path):
    return StateStore(str(tmp_path / "test.db"))


@pytest.fixture
def temp_config_path(tmp_path):
    return str(tmp_path / "paper_config.json")


# ── Config tests ─────────────────────────────────────────────────────────────


def test_config_defaults_created_when_missing(temp_config_path):
    cfg = load(temp_config_path)
    assert isinstance(cfg, PaperConfig)
    assert cfg.ibkr_port == 7497
    assert Path(temp_config_path).exists()


def test_config_roundtrip(temp_config_path):
    cfg = PaperConfig(ibkr_port=4002, ntfy_topic="my-topic")
    save(cfg, temp_config_path)
    loaded = load(temp_config_path)
    assert loaded.ibkr_port == 4002
    assert loaded.ntfy_topic == "my-topic"


def test_config_ignores_unknown_keys(tmp_path):
    path = str(tmp_path / "cfg.json")
    data = {"ibkr_port": 4002, "unknown_future_key": "ignored"}
    Path(path).write_text(json.dumps(data))
    cfg = load(path)
    assert cfg.ibkr_port == 4002


def test_config_get_omits_sensitive_fields():
    cfg = PaperConfig(password_hash="$2b$12$abc")
    public = to_public_dict(cfg)
    assert "password_hash" not in public
    assert "ibkr_port" in public


def test_config_put_rejects_sensitive_fields():
    cfg = PaperConfig()
    with pytest.raises(ValueError, match="sensitive"):
        update_from_public(cfg, {"password_hash": "hacked"})


def test_config_update_from_public_applies_changes():
    cfg = PaperConfig(ibkr_port=7497)
    updated = update_from_public(cfg, {"ibkr_port": 4002, "ntfy_topic": "alerts"})
    assert updated.ibkr_port == 4002
    assert updated.ntfy_topic == "alerts"
    assert cfg.ibkr_port == 7497  # original unchanged (dataclass is value-typed)


def test_config_update_ignores_unknown_keys():
    cfg = PaperConfig()
    updated = update_from_public(cfg, {"nonexistent": "value", "ibkr_port": 4002})
    assert updated.ibkr_port == 4002


# ── Auth tests ────────────────────────────────────────────────────────────────


def test_password_hash_and_verify():
    hashed = hash_password("correct-horse")
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong-password", hashed)


def test_auth_login_issues_session_token(temp_store):
    token = create_session(temp_store)
    assert len(token) > 20
    assert temp_store.validate_session(token)


def test_auth_destroy_session(temp_store):
    token = create_session(temp_store)
    destroy_session(temp_store, token)
    assert not temp_store.validate_session(token)


def test_auth_rejects_missing_token(temp_store):
    app = FastAPI()

    @app.get("/protected")
    async def protected(t=pytest.importorskip("fastapi").Depends(require_token(temp_store))):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/protected")
    assert response.status_code in (401, 403)


def test_auth_accepts_valid_token(temp_store):
    token = create_session(temp_store)

    app = FastAPI()

    @app.get("/protected")
    async def protected(t=pytest.importorskip("fastapi").Depends(require_token(temp_store))):
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_auth_rejects_invalid_token(temp_store):
    app = FastAPI()

    @app.get("/protected")
    async def protected(t=pytest.importorskip("fastapi").Depends(require_token(temp_store))):
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/protected", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401


# ── Notification tests ────────────────────────────────────────────────────────


def test_notifier_writes_to_db(temp_store, tmp_path):
    notifier = Notifier(temp_store, log_path=str(tmp_path / "test.log"))
    notifier.notify("info", "Test title", "Test body")

    notifs = temp_store.list_notifications()
    assert len(notifs) == 1
    assert notifs[0].title == "Test title"
    assert notifs[0].level == "info"
    assert notifs[0].read_at is None


def test_notifier_writes_to_log_file(temp_store, tmp_path):
    log_path = str(tmp_path / "test.log")
    notifier = Notifier(temp_store, log_path=log_path)
    notifier.notify("warning", "Log test", "Should appear in file")

    content = Path(log_path).read_text()
    assert "Log test" in content
    assert "Should appear in file" in content


def test_notifier_multiple_levels(temp_store, tmp_path):
    notifier = Notifier(temp_store, log_path=str(tmp_path / "test.log"))
    for level in ("info", "warning", "error", "success"):
        notifier.notify(level, f"{level} title", f"{level} body")

    notifs = temp_store.list_notifications()
    assert len(notifs) == 4
    levels = {n.level for n in notifs}
    assert levels == {"info", "warning", "error", "success"}


def test_notifier_ntfy_failure_is_swallowed(temp_store, tmp_path):
    # Invalid server URL — should not raise
    notifier = Notifier(
        temp_store,
        log_path=str(tmp_path / "test.log"),
        ntfy_topic="test-topic",
        ntfy_server="http://localhost:19999",  # nothing listening here
    )
    notifier.notify("info", "title", "body")  # must not raise
    notifs = temp_store.list_notifications()
    assert len(notifs) == 1  # DB write still succeeded


# ── IBKR client tests (milestone 3) ──────────────────────────────────────────


from straddle.paper_trading.ibkr_client import (
    Fill,
    FillTimeout,
    MockIBKRClient,
    is_quote_sane,
)


@pytest.fixture
def default_config():
    return PaperConfig()


# Quote sanity gate


def test_quote_sane_valid(default_config):
    assert is_quote_sane(bid=1.00, ask=1.10, age_sec=30, config=default_config)


def test_quote_insane_bid_too_low(default_config):
    # bid=0.04 < quote_min_bid=0.05
    assert not is_quote_sane(bid=0.04, ask=0.10, age_sec=30, config=default_config)


def test_quote_insane_ask_below_bid(default_config):
    assert not is_quote_sane(bid=1.10, ask=1.00, age_sec=30, config=default_config)


def test_quote_insane_spread_too_wide(default_config):
    # spread = (2.00 - 1.00) / 1.00 = 100% >> 25%
    assert not is_quote_sane(bid=1.00, ask=2.00, age_sec=30, config=default_config)


def test_quote_insane_stale(default_config):
    # age_sec=120 > quote_max_age_sec=90
    assert not is_quote_sane(bid=1.00, ask=1.10, age_sec=120, config=default_config)


def test_quote_sane_at_spread_boundary(default_config):
    # spread exactly 25% — still sane (boundary is inclusive)
    ask = 1.00 * (1 + default_config.quote_max_spread_pct)
    assert is_quote_sane(bid=1.00, ask=ask, age_sec=30, config=default_config)


def test_quote_insane_just_over_spread_boundary(default_config):
    ask = 1.00 * (1 + default_config.quote_max_spread_pct) + 0.01
    assert not is_quote_sane(bid=1.00, ask=ask, age_sec=30, config=default_config)


# MockIBKRClient


def test_mock_ibkr_returns_spy_close():
    mock = MockIBKRClient(spy_close=505.25)
    assert mock.get_spy_close() == 505.25


def test_mock_ibkr_returns_vix_close():
    mock = MockIBKRClient(vix_close=22.5)
    assert mock.get_vix_close() == 22.5


def test_mock_ibkr_returns_configured_quote():
    quote = {"bid": 1.50, "ask": 1.60, "mid": 1.55, "last": 1.52, "age_sec": 10, "sane": True}
    mock = MockIBKRClient(quotes={(480.0, "20250221", "P"): quote})
    result = mock.get_option_quote(480.0, "20250221", "P")
    assert result == quote


def test_mock_ibkr_returns_none_for_unknown_quote():
    mock = MockIBKRClient()
    assert mock.get_option_quote(999.0, "20250221", "P") is None


def test_mock_ibkr_raises_on_place_strangle_by_default():
    mock = MockIBKRClient()
    with pytest.raises(AssertionError, match="place_strangle"):
        mock.place_strangle(480.0, 520.0, "20250221", 1, 6.50)


def test_mock_ibkr_raises_on_close_strangle_by_default(tmp_path):
    from straddle.paper_trading.state import PaperTrade
    import pandas as pd

    mock = MockIBKRClient()
    trade = PaperTrade(
        entry_date=pd.Timestamp("2025-01-15"),
        expiration=pd.Timestamp("2025-02-21"),
        put_strike=480.0,
        call_strike=520.0,
        net_credit=650.0,
    )
    with pytest.raises(AssertionError, match="close_strangle"):
        mock.close_strangle(trade, 3.00)


def test_mock_ibkr_returns_fill_when_configured():
    expected_fill = Fill(order_id=1, perm_id=12345, avg_price=6.48, qty=1, commission=2.05)
    mock = MockIBKRClient(fills={"place_strangle": expected_fill})
    result = mock.place_strangle(480.0, 520.0, "20250221", 1, 6.50)
    assert result is expected_fill
    assert result.avg_price == 6.48


def test_mock_ibkr_connect_disconnect():
    mock = MockIBKRClient(connected=False)
    assert not mock.is_connected
    mock.connect()
    assert mock.is_connected
    mock.disconnect()
    assert not mock.is_connected


def test_mock_ibkr_validate_strike_snaps_to_nearest_dollar():
    mock = MockIBKRClient()
    assert mock.validate_strike(480.3) == 480.0
    assert mock.validate_strike(480.7) == 481.0


def test_fill_timeout_is_exception():
    exc = FillTimeout("did not fill in 60s")
    assert isinstance(exc, Exception)
    assert "60s" in str(exc)


def test_mock_ibkr_account_summary_defaults():
    mock = MockIBKRClient()
    summary = mock.get_account_summary()
    assert "NetLiquidation" in summary
    assert "BuyingPower" in summary


def test_mock_ibkr_custom_account_summary():
    mock = MockIBKRClient(account_summary={"NetLiquidation": "75000", "BuyingPower": "60000"})
    summary = mock.get_account_summary()
    assert summary["NetLiquidation"] == "75000"


# ── Runner tests (milestone 4) ────────────────────────────────────────────────


import pandas as pd

from straddle.engines import make_engine
from straddle.paper_trading.runner import PaperTradingEngine, _paper_trade_to_trade
from straddle.paper_trading.state import PaperTrade, SignalStatus, SignalType
from straddle.params import PARAMS


# ── Shared runner fixture ─────────────────────────────────────────────────────

SPY_PRICE = 500.0
VIX_LEVEL = 18.0
# Entry dates must be ~30-45 DTE from a 3rd Friday. Use a fixed "today" that
# puts us in the right window and near expiry for exit tests.
# 2025-01-15 is ~37 days before 2025-02-21 (3rd Friday of Feb) → valid entry.
# For exit tests, use 2025-01-31 which is 21 days before 2025-02-21.
ENTRY_DATE = pd.Timestamp("2025-01-15")
EXIT_DATE = pd.Timestamp("2025-01-31")   # 21 calendar days before 2025-02-21
EXPIRATION = pd.Timestamp("2025-02-21")


def _make_data_loader(spy: float = SPY_PRICE, vix: float = VIX_LEVEL):
    """Synthetic data loader — returns a flat DataFrame, no network."""
    def _loader(start_date: str, end_date: str) -> pd.DataFrame:
        dates = pd.bdate_range(start=start_date, end=end_date)
        if len(dates) == 0:
            return pd.DataFrame(
                columns=["spy_open", "spy_high", "spy_low", "spy_close", "vix_close", "risk_free_rate"]
            )
        return pd.DataFrame({
            "spy_open": spy, "spy_high": spy + 2, "spy_low": spy - 2,
            "spy_close": spy, "vix_close": vix, "risk_free_rate": 0.05,
        }, index=dates)
    return _loader


def _make_runner(
    store,
    tmp_path,
    ibkr=None,
    dry_run=False,
    params=None,
) -> PaperTradingEngine:
    params = params or {**PARAMS, "roll_for_credit": False, "vix_entry_filter_enabled": False}
    config = PaperConfig()
    notifier = Notifier(store, log_path=str(tmp_path / "runner.log"))
    if ibkr is None:
        ibkr = MockIBKRClient(spy_close=SPY_PRICE, vix_close=VIX_LEVEL, connected=True)
    engine = make_engine({**PARAMS, "mode": "synthetic"})
    return PaperTradingEngine(
        params=params,
        config=config,
        ibkr=ibkr,
        store=store,
        notifier=notifier,
        pricing_engine=engine,
        dry_run=dry_run,
        data_loader=_make_data_loader(),
    )


def _insert_open_trade(store, entry_date=ENTRY_DATE, expiration=EXPIRATION) -> PaperTrade:
    """Insert a minimal open trade with enough metadata for the evaluator."""
    pt = PaperTrade(
        entry_date=entry_date,
        expiration=expiration,
        put_strike=480.0,
        call_strike=520.0,
        net_credit=650.0,
        daily_marks_json="[]",
        metadata_json=json.dumps({
            "put_mid_ps": 2.50,
            "call_mid_ps": 4.00,
            "entry_vix": VIX_LEVEL,
            "entry_dte": (expiration - entry_date).days,
            "max_vix": VIX_LEVEL,
        }),
    )
    trade_num = store.save_trade(pt)
    pt.trade_num = trade_num
    return pt


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_runner_emits_pending_not_orders(temp_store, tmp_path):
    """run_daily_cycle enqueues a signal but never calls place_strangle."""
    mock = MockIBKRClient(spy_close=SPY_PRICE, vix_close=VIX_LEVEL, connected=True)
    runner = _make_runner(temp_store, tmp_path, ibkr=mock)

    _insert_open_trade(temp_store)

    # EXIT_DATE is exactly manage_at_dte (21) days before EXPIRATION → 21DTE exit
    runner.run_daily_cycle(EXIT_DATE)

    signals = temp_store.list_signals(status=SignalStatus.PENDING)
    assert len(signals) == 1, "Expected exactly one pending signal"
    assert signals[0].signal_type == SignalType.CLOSE
    # MockIBKRClient raises AssertionError if place_strangle is called —
    # the test would have already failed above if any order was attempted.


def test_evaluator_mutation_isolated(temp_store, tmp_path):
    """Rejecting a close signal must leave the DB trade unchanged (deep-copy discipline)."""
    runner = _make_runner(temp_store, tmp_path)
    pt = _insert_open_trade(temp_store)

    runner.run_daily_cycle(EXIT_DATE)

    # Reject the signal
    sigs = temp_store.list_signals()
    assert len(sigs) == 1
    temp_store.update_signal_status(sigs[0].id, SignalStatus.REJECTED)

    # Canonical trade must still be open
    reloaded = temp_store.load_trade(pt.trade_num)
    assert reloaded.status == "open"
    assert reloaded.pnl is None
    assert reloaded.exit_type is None


def test_hybrid_quote_prefers_ibkr_when_sane(temp_store, tmp_path):
    sane_quote = {"bid": 1.50, "ask": 1.60, "mid": 1.55, "last": 1.52, "age_sec": 10, "sane": True}
    mock = MockIBKRClient(
        spy_close=SPY_PRICE, vix_close=VIX_LEVEL,
        quotes={(480.0, "20250221", "P"): sane_quote},
        connected=True,
    )
    runner = _make_runner(temp_store, tmp_path, ibkr=mock)

    q = runner._get_quote(480.0, "20250221", "P", SPY_PRICE, 37 / 365.0, 0.05, VIX_LEVEL)
    assert q["source"] == "ibkr"
    assert q["ibkr_mid"] == 1.55
    assert q["bs_mid"] is not None
    assert q["limit_price"] == 1.55


def test_hybrid_quote_falls_back_to_bs_when_insane(temp_store, tmp_path):
    insane_quote = {"bid": 0.01, "ask": 9.99, "mid": 5.0, "last": None, "age_sec": 200, "sane": False}
    mock = MockIBKRClient(
        spy_close=SPY_PRICE, vix_close=VIX_LEVEL,
        quotes={(480.0, "20250221", "P"): insane_quote},
        connected=True,
    )
    runner = _make_runner(temp_store, tmp_path, ibkr=mock)

    q = runner._get_quote(480.0, "20250221", "P", SPY_PRICE, 37 / 365.0, 0.05, VIX_LEVEL)
    assert q["source"] == "bs"
    assert q["ibkr_mid"] is None
    assert q["limit_price"] == q["bs_mid"]


def test_dry_run_no_ibkr_submission(temp_store, tmp_path):
    """In dry_run mode process_approved_signals must be a no-op."""
    mock = MockIBKRClient(spy_close=SPY_PRICE, vix_close=VIX_LEVEL, connected=True)
    runner = _make_runner(temp_store, tmp_path, ibkr=mock, dry_run=True)
    _insert_open_trade(temp_store)

    runner.run_daily_cycle(EXIT_DATE)

    sigs = temp_store.list_signals()
    assert len(sigs) == 1

    # Approve the signal
    temp_store.update_signal_status(sigs[0].id, SignalStatus.APPROVED)

    # process_approved_signals is a no-op in dry_run
    runner.process_approved_signals()

    sigs_after = temp_store.list_signals()
    assert sigs_after[0].status == SignalStatus.APPROVED  # unchanged


def test_open_trades_reflect_db_changes(temp_store, tmp_path):
    """Trades closed via DB (e.g. by the API) must not appear as open next cycle."""
    runner = _make_runner(temp_store, tmp_path)
    pt = _insert_open_trade(temp_store)

    # Simulate the API closing the trade directly
    pt.status = "closed"
    pt.exit_date = EXIT_DATE
    pt.exit_type = "PROFIT"
    pt.pnl = 325.0
    temp_store.save_trade(pt)

    runner.run_daily_cycle(EXIT_DATE)

    # No signals should be emitted for the already-closed trade
    # (and no entry signal because we're past the entry window for Feb)
    for sig in temp_store.list_signals():
        loaded_pt = temp_store.load_trade(sig.trade_num) if sig.trade_num else None
        if loaded_pt:
            assert loaded_pt.trade_num != pt.trade_num, "Signal for closed trade should not exist"


def test_manual_fire_enqueues_signal_with_manual_flag(temp_store, tmp_path):
    runner = _make_runner(temp_store, tmp_path)

    sig_id = runner.fire_manual_entry(
        expiration="2025-02-21",
        put_strike=480.0,
        call_strike=520.0,
    )

    sigs = temp_store.list_signals()
    assert len(sigs) == 1
    assert sigs[0].signal_type == SignalType.MANUAL
    payload = json.loads(sigs[0].payload_json)
    assert payload["manual"] is True
    assert payload["put_strike"] == 480.0
    assert payload["call_strike"] == 520.0


def test_manual_fire_invalid_strike_rejected(temp_store, tmp_path):
    """A manual signal whose strike is far from current price should fail at execution."""
    bogus_fill = Fill(order_id=1, perm_id=99, avg_price=0.01, qty=1, commission=0.0)
    mock = MockIBKRClient(
        spy_close=SPY_PRICE, vix_close=VIX_LEVEL, connected=True,
        exceptions={"place_strangle": FillTimeout("order not filled — strike too far OTM")},
    )
    runner = _make_runner(temp_store, tmp_path, ibkr=mock)

    # Enqueue a manual signal with unreasonable strikes (99% OTM)
    runner.fire_manual_entry(expiration="2025-02-21", put_strike=5.0, call_strike=9999.0)

    sigs = temp_store.list_signals()
    temp_store.update_signal_status(sigs[0].id, SignalStatus.APPROVED)

    # Execute — should catch FillTimeout and mark as cancelled
    runner.process_approved_signals()

    sigs_after = temp_store.list_signals()
    assert sigs_after[0].status == SignalStatus.CANCELLED
    assert "not filled" in sigs_after[0].error_msg


def test_roll_atomicity_recovery(temp_store, tmp_path):
    """Close fills, open fails → OPEN_RECOVERY signal is emitted."""
    close_fill = Fill(order_id=1, perm_id=100, avg_price=3.25, qty=1, commission=2.0)
    mock = MockIBKRClient(
        spy_close=SPY_PRICE, vix_close=VIX_LEVEL, connected=True,
        fills={"close_strangle": close_fill},
        exceptions={"place_strangle": FillTimeout("open leg timed out")},
    )
    runner = _make_runner(
        temp_store, tmp_path, ibkr=mock,
        params={**PARAMS, "roll_for_credit": True, "vix_entry_filter_enabled": False},
    )

    pt = _insert_open_trade(temp_store)

    # Build a ROLL signal manually (simulating what run_daily_cycle would emit)
    roll_payload = {
        "trade_num": pt.trade_num,
        "close_put_strike": pt.put_strike,
        "close_call_strike": pt.call_strike,
        "close_expiration": pt.expiration.strftime("%Y%m%d"),
        "open_put_strike": 475.0,
        "open_call_strike": 525.0,
        "open_expiration": "20250321",
        "pnl": 325.0,
        "pnl_pct": 0.50,
        "roll_credit": 150.0,
        "limit_price": 3.25,
        "new_trade": {
            "put_strike": 475.0,
            "call_strike": 525.0,
            "put_mid_ps": 2.50,
            "call_mid_ps": 4.00,
            "net_credit": 680.0,
            "entry_dte": 35,
            "entry_vix": VIX_LEVEL,
        },
    }
    from straddle.paper_trading.state import PendingSignal, SignalType, SignalStatus
    sig_id = temp_store.enqueue_signal(PendingSignal(
        signal_type=SignalType.ROLL,
        trade_num=pt.trade_num,
        payload_json=json.dumps(roll_payload),
        status=SignalStatus.APPROVED,
    ))
    # Manually set to approved
    temp_store.update_signal_status(sig_id, SignalStatus.APPROVED)

    runner.process_approved_signals()

    # Parent trade should be marked closed
    reloaded = temp_store.load_trade(pt.trade_num)
    assert reloaded.status == "closed"
    assert reloaded.exit_type == "ROLLED"

    # An OPEN_RECOVERY signal should have been emitted
    all_sigs = temp_store.list_signals()
    recovery_sigs = [s for s in all_sigs if s.signal_type == SignalType.OPEN_RECOVERY]
    assert len(recovery_sigs) == 1


def test_paper_trade_to_trade_roundtrip(temp_store):
    """_paper_trade_to_trade reconstructs a Trade with correct key fields."""
    pt = _insert_open_trade(temp_store)
    trade = _paper_trade_to_trade(pt, [])

    assert trade.trade_num == pt.trade_num
    assert trade.put_strike == pt.put_strike
    assert trade.call_strike == pt.call_strike
    assert trade.net_credit == pt.net_credit
    assert trade.expiration == pt.expiration
    assert trade.put_mid_ps == 2.50
    assert trade.call_mid_ps == 4.00
    assert trade.entry_vix == VIX_LEVEL


def test_daily_marks_persisted_after_cycle(temp_store, tmp_path):
    """Each run_daily_cycle call appends exactly one daily mark per open trade."""
    runner = _make_runner(temp_store, tmp_path)
    _insert_open_trade(temp_store)

    # Use a date before the 21DTE threshold so the trade stays open
    runner.run_daily_cycle(pd.Timestamp("2025-01-20"))

    pt = temp_store.load_open_trades()[0]
    marks = json.loads(pt.daily_marks_json)
    assert len(marks) == 1
    assert marks[0][0] == "2025-01-20"
