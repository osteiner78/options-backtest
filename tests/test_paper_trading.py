"""Tests for paper trading milestone 2: config, auth, notifications."""

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
