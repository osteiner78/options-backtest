"""Tests for paper trading API (milestone 6)."""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from straddle.paper_trading.api import create_app
from straddle.paper_trading.auth import hash_password
from straddle.paper_trading.config import PaperConfig
from straddle.paper_trading.state import (
    Notification,
    PaperTrade,
    PendingSignal,
    SignalStatus,
    SignalType,
    StateStore,
)


PASSWORD = "testpassword123"


@pytest.fixture
def store(tmp_path):
    return StateStore(str(tmp_path / "test.db"))


@pytest.fixture
def config(tmp_path):
    return PaperConfig(password_hash=hash_password(PASSWORD))


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "paper_config.json")


@pytest.fixture
def client(store, config, config_path):
    app = create_app(store=store, config=config, config_path=config_path)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_client(client):
    """TestClient with a valid Bearer token already set."""
    resp = client.post("/login", json={"password": PASSWORD})
    assert resp.status_code == 200
    token = resp.json()["token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, token


# ── Auth ──────────────────────────────────────────────────────────────────────


def test_login_returns_token(client):
    resp = client.post("/login", json={"password": PASSWORD})
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_login_wrong_password(client):
    resp = client.post("/login", json={"password": "wrongpass"})
    assert resp.status_code == 401


def test_login_no_password_hash_configured(store, config_path):
    cfg = PaperConfig(password_hash="")
    app = create_app(store=store, config=cfg, config_path=config_path)
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.post("/login", json={"password": "anything"})
    assert resp.status_code == 503


def test_logout(auth_client):
    c, token = auth_client
    resp = c.post("/logout")
    assert resp.status_code == 200
    # Token should no longer be valid
    resp2 = c.get("/signals")
    assert resp2.status_code == 401


def test_protected_endpoint_without_token(client):
    resp = client.get("/signals")
    assert resp.status_code in (401, 403)


# ── Health (public) ───────────────────────────────────────────────────────────


def test_health_public_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "heartbeat_age_sec" in data
    assert "ibkr_connected" in data
    assert "dry_run" in data
    assert "open_trade_count" in data


def test_health_reflects_heartbeat(store, client):
    store.tick_heartbeat(ibkr_connected=True, open_trade_count=2, dry_run=True)
    resp = client.get("/health")
    data = resp.json()
    assert data["ibkr_connected"] is True
    assert data["open_trade_count"] == 2
    assert data["dry_run"] is True
    assert data["heartbeat_age_sec"] is not None
    assert data["heartbeat_age_sec"] < 5


# ── Signals ───────────────────────────────────────────────────────────────────


def test_get_signals_empty(auth_client):
    c, _ = auth_client
    resp = c.get("/signals")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_signals_with_status_filter(auth_client, store):
    c, _ = auth_client
    sig_id = store.enqueue_signal(PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json=json.dumps({"put_strike": 480.0}),
    ))
    store.update_signal_status(sig_id, SignalStatus.APPROVED)
    store.enqueue_signal(PendingSignal(
        signal_type=SignalType.CLOSE,
        payload_json=json.dumps({"put_strike": 480.0}),
    ))

    pending = c.get("/signals?status=pending").json()
    approved = c.get("/signals?status=approved").json()
    all_sigs = c.get("/signals").json()

    assert len(pending) == 1
    assert pending[0]["signal_type"] == "CLOSE"
    assert len(approved) == 1
    assert approved[0]["signal_type"] == "ENTRY"
    assert len(all_sigs) == 2


def test_approve_signal(auth_client, store):
    c, _ = auth_client
    sig_id = store.enqueue_signal(PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json="{}",
    ))
    resp = c.post(f"/signals/{sig_id}/approve")
    assert resp.status_code == 200
    sigs = store.list_signals(status=SignalStatus.APPROVED)
    assert len(sigs) == 1


def test_reject_signal_with_reason(auth_client, store):
    c, _ = auth_client
    sig_id = store.enqueue_signal(PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json="{}",
    ))
    resp = c.post(f"/signals/{sig_id}/reject", json={"reason": "VIX too high"})
    assert resp.status_code == 200
    sigs = store.list_signals(status=SignalStatus.REJECTED)
    assert len(sigs) == 1
    assert sigs[0].error_msg == "VIX too high"


def test_approve_nonexistent_signal(auth_client):
    c, _ = auth_client
    resp = c.post("/signals/9999/approve")
    assert resp.status_code == 404


def test_signal_payload_included_in_response(auth_client, store):
    c, _ = auth_client
    payload = {"put_strike": 480.0, "call_strike": 520.0, "ibkr_mid": 6.55, "bs_mid": 6.45}
    store.enqueue_signal(PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json=json.dumps(payload),
    ))
    sigs = c.get("/signals").json()
    assert sigs[0]["payload"]["put_strike"] == 480.0
    assert sigs[0]["payload"]["ibkr_mid"] == 6.55


# ── Trades ────────────────────────────────────────────────────────────────────


def test_get_trades_empty(auth_client):
    c, _ = auth_client
    assert c.get("/trades").json() == []


def test_get_trades_by_status(auth_client, store):
    c, _ = auth_client
    open_pt = PaperTrade(
        entry_date=pd.Timestamp("2025-01-15"), expiration=pd.Timestamp("2025-02-21"),
        put_strike=480.0, call_strike=520.0, net_credit=650.0, status="open",
    )
    closed_pt = PaperTrade(
        entry_date=pd.Timestamp("2025-01-05"), expiration=pd.Timestamp("2025-01-17"),
        put_strike=475.0, call_strike=515.0, net_credit=600.0, status="closed",
        exit_date=pd.Timestamp("2025-01-10"), exit_type="PROFIT", pnl=300.0,
    )
    store.save_trade(open_pt)
    store.save_trade(closed_pt)

    assert len(c.get("/trades?status=open").json()) == 1
    assert len(c.get("/trades?status=closed").json()) == 1
    assert len(c.get("/trades").json()) == 2


def test_get_trade_by_num(auth_client, store):
    c, _ = auth_client
    pt = PaperTrade(
        entry_date=pd.Timestamp("2025-01-15"), expiration=pd.Timestamp("2025-02-21"),
        put_strike=480.0, call_strike=520.0, net_credit=650.0,
    )
    trade_num = store.save_trade(pt)
    resp = c.get(f"/trades/{trade_num}")
    assert resp.status_code == 200
    assert resp.json()["put_strike"] == 480.0
    assert resp.json()["call_strike"] == 520.0


def test_get_trade_not_found(auth_client):
    c, _ = auth_client
    assert c.get("/trades/9999").status_code == 404


# ── Account ───────────────────────────────────────────────────────────────────


def test_get_account_stale_when_no_cache(auth_client):
    c, _ = auth_client
    resp = c.get("/account")
    assert resp.status_code == 200
    assert resp.json()["stale"] is True
    assert resp.json()["summary"] == {}


def test_get_account_with_cache(auth_client, store):
    c, _ = auth_client
    store.cache_account({"NetLiquidation": "52000", "BuyingPower": "40000"})
    resp = c.get("/account")
    data = resp.json()
    assert data["stale"] is False
    assert data["summary"]["NetLiquidation"] == "52000"


# ── Equity ────────────────────────────────────────────────────────────────────


def test_get_equity_empty(auth_client):
    c, _ = auth_client
    assert c.get("/equity").json() == []


def test_get_equity_with_data(auth_client, store):
    c, _ = auth_client
    for i, date in enumerate(["2025-01-15", "2025-01-16", "2025-01-17"]):
        store.record_equity(pd.Timestamp(date), nlv=50000.0 + i * 1000, cash=20000.0)

    rows = c.get("/equity").json()
    assert len(rows) == 3
    assert rows[0]["nlv"] == 50000.0
    assert rows[2]["nlv"] == 52000.0


def test_get_equity_date_filter(auth_client, store):
    c, _ = auth_client
    for date in ["2025-01-14", "2025-01-15", "2025-01-16"]:
        store.record_equity(pd.Timestamp(date), nlv=50000.0, cash=20000.0)

    rows = c.get("/equity?from_date=2025-01-15").json()
    assert len(rows) == 2
    assert rows[0]["date"] == "2025-01-15"


# ── Config ────────────────────────────────────────────────────────────────────


def test_get_config_omits_sensitive(auth_client):
    c, _ = auth_client
    data = c.get("/config").json()
    assert "password_hash" not in data
    assert "ibkr_port" in data


def test_put_config_updates_field(auth_client, config_path):
    c, _ = auth_client
    resp = c.put("/config", json={"ibkr_port": 4002, "ntfy_topic": "my-alerts"})
    assert resp.status_code == 200
    assert resp.json()["ibkr_port"] == 4002
    assert resp.json()["ntfy_topic"] == "my-alerts"

    # Persisted to file
    from straddle.paper_trading.config import load
    saved = load(config_path)
    assert saved.ibkr_port == 4002


def test_put_config_rejects_sensitive(auth_client):
    c, _ = auth_client
    resp = c.put("/config", json={"password_hash": "hacked"})
    assert resp.status_code == 400


# ── Fire ──────────────────────────────────────────────────────────────────────


def test_fire_enqueues_manual_signal(auth_client, store):
    c, _ = auth_client
    resp = c.post("/fire", json={"expiration": "2025-02-21", "put_strike": 480.0, "call_strike": 520.0})
    assert resp.status_code == 200
    assert "signal_id" in resp.json()

    sigs = store.list_signals()
    assert len(sigs) == 1
    assert sigs[0].signal_type == SignalType.MANUAL
    payload = json.loads(sigs[0].payload_json)
    assert payload["manual"] is True
    assert payload["expiration"] == "2025-02-21"
    assert payload["put_strike"] == 480.0


def test_fire_without_strikes_enqueues_with_nulls(auth_client, store):
    c, _ = auth_client
    resp = c.post("/fire", json={"expiration": "2025-02-21"})
    assert resp.status_code == 200
    sigs = store.list_signals()
    payload = json.loads(sigs[0].payload_json)
    assert payload["put_strike"] is None
    assert payload["call_strike"] is None


# ── Notifications ─────────────────────────────────────────────────────────────


def test_get_notifications_empty(auth_client):
    c, _ = auth_client
    assert c.get("/notifications").json() == []


def test_get_notifications_unread_filter(auth_client, store):
    c, _ = auth_client
    n1_id = store.add_notification(Notification(level="info", title="A", body=""))
    store.add_notification(Notification(level="warning", title="B", body=""))
    store.mark_notification_read(n1_id)

    all_n = c.get("/notifications").json()
    unread = c.get("/notifications?unread=true").json()
    assert len(all_n) == 2
    assert len(unread) == 1
    assert unread[0]["title"] == "B"


def test_ack_notification(auth_client, store):
    c, _ = auth_client
    n_id = store.add_notification(Notification(level="info", title="T", body=""))
    resp = c.post(f"/notifications/{n_id}/ack")
    assert resp.status_code == 200

    unread = c.get("/notifications?unread=true").json()
    assert len(unread) == 0


def test_ack_nonexistent_notification(auth_client):
    c, _ = auth_client
    assert c.post("/notifications/9999/ack").status_code == 404
