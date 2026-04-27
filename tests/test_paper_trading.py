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
