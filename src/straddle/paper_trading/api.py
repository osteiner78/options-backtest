"""FastAPI application for the paper trading web UI.

All endpoints except /login and /health require Bearer token authentication.

Usage:
    from straddle.paper_trading.api import create_app
    app = create_app(store=store, config=cfg, config_path="data/paper_config.json")
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from straddle.paper_trading.auth import create_session, destroy_session, verify_password
from straddle.paper_trading.config import PaperConfig, save, to_public_dict, update_from_public
from straddle.paper_trading.state import PendingSignal, SignalStatus, SignalType, StateStore


# ── Request / response models ─────────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str


class RejectRequest(BaseModel):
    reason: str = ""


class FireRequest(BaseModel):
    expiration: str
    put_strike: Optional[float] = None
    call_strike: Optional[float] = None
    qty: int = 1


# ── App factory ───────────────────────────────────────────────────────────────


def create_app(store: StateStore, config: PaperConfig, config_path: str) -> FastAPI:
    """Return a configured FastAPI app.

    Args:
        store:       StateStore instance (shared with the daemon via SQLite WAL).
        config:      Initial PaperConfig (PUT /config updates the in-memory copy
                     and writes to config_path so the daemon picks it up).
        config_path: Path to paper_config.json for persisting config changes.
    """
    app = FastAPI(title="Paper Trading API", version="0.1.0")
    _cfg: list[PaperConfig] = [config]   # mutable reference for PUT /config
    _security = HTTPBearer()

    def _require_token(
        credentials: HTTPAuthorizationCredentials = Depends(_security),
    ) -> str:
        if not store.validate_session(credentials.credentials):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return credentials.credentials

    # ── Auth ──────────────────────────────────────────────────────────────────

    @app.post("/login")
    def login(req: LoginRequest):
        if not _cfg[0].password_hash:
            raise HTTPException(
                status_code=503,
                detail="Authentication not configured — run: python scripts/run_paper_daemon.py setup-auth",
            )
        if not verify_password(req.password, _cfg[0].password_hash):
            raise HTTPException(status_code=401, detail="Incorrect password")
        return {"token": create_session(store)}

    @app.post("/logout")
    def logout(token: str = Depends(_require_token)):
        destroy_session(store, token)
        return {"ok": True}

    # ── Signals ───────────────────────────────────────────────────────────────

    @app.get("/signals")
    def list_signals(
        status: Optional[str] = None,
        token: str = Depends(_require_token),
    ):
        status_enum = SignalStatus(status) if status else None
        return [_signal_to_dict(s) for s in store.list_signals(status=status_enum)]

    @app.post("/signals/{signal_id}/approve")
    def approve_signal(signal_id: int, token: str = Depends(_require_token)):
        if not store.update_signal_status(signal_id, SignalStatus.APPROVED):
            raise HTTPException(status_code=404, detail="Signal not found")
        return {"ok": True}

    @app.post("/signals/{signal_id}/reject")
    def reject_signal(
        signal_id: int,
        req: RejectRequest,
        token: str = Depends(_require_token),
    ):
        if not store.update_signal_status(
            signal_id, SignalStatus.REJECTED, error_msg=req.reason or None
        ):
            raise HTTPException(status_code=404, detail="Signal not found")
        return {"ok": True}

    # ── Trades ────────────────────────────────────────────────────────────────

    @app.get("/trades")
    def list_trades(
        status: Optional[str] = None,
        token: str = Depends(_require_token),
    ):
        if status == "open":
            trades = store.load_open_trades()
        elif status == "closed":
            trades = store.load_closed_trades()
        else:
            trades = store.load_all_trades()
        return [_trade_to_dict(t) for t in trades]

    @app.get("/trades/{trade_num}")
    def get_trade(trade_num: int, token: str = Depends(_require_token)):
        trade = store.load_trade(trade_num)
        if trade is None:
            raise HTTPException(status_code=404, detail="Trade not found")
        return _trade_to_dict(trade)

    # ── Account ───────────────────────────────────────────────────────────────

    @app.get("/account")
    def get_account(token: str = Depends(_require_token)):
        summary, updated_at = store.read_account_cache()
        if summary is None:
            return {"summary": {}, "updated_at": None, "stale": True}
        age_sec = (datetime.now(timezone.utc) - updated_at).total_seconds()
        return {
            "summary": summary,
            "updated_at": updated_at.isoformat(),
            "stale": age_sec > 300,
        }

    # ── Equity ────────────────────────────────────────────────────────────────

    @app.get("/equity")
    def get_equity(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        token: str = Depends(_require_token),
    ):
        start = pd.Timestamp(from_date) if from_date else None
        end = pd.Timestamp(to_date) if to_date else None
        rows = store.get_equity_curve(start_date=start, end_date=end)
        return [
            {
                "date": str(r["date"].date()),
                "nlv": r["nlv"],
                "cash": r["cash"],
                "open_trade_count": r["open_trade_count"],
                "source": r["source"],
            }
            for r in rows
        ]

    # ── Config ────────────────────────────────────────────────────────────────

    @app.get("/config")
    def get_config_endpoint(token: str = Depends(_require_token)):
        return to_public_dict(_cfg[0])

    @app.put("/config")
    def update_config_endpoint(payload: Dict[str, Any], token: str = Depends(_require_token)):
        try:
            updated = update_from_public(_cfg[0], payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        _cfg[0] = updated
        save(updated, config_path)
        return to_public_dict(updated)

    # ── Fire (manual entry) ───────────────────────────────────────────────────

    @app.post("/fire")
    def fire_manual(req: FireRequest, token: str = Depends(_require_token)):
        """Enqueue a manual ENTRY signal. Daemon computes default strikes on execution."""
        payload = {
            "expiration": req.expiration,
            "put_strike": req.put_strike,
            "call_strike": req.call_strike,
            "qty": req.qty,
            "manual": True,
            # Fields below are null — daemon fills them in _fill_entry_defaults.
            "entry_date": None,
            "put_mid_ps": None,
            "call_mid_ps": None,
            "net_credit": None,
            "entry_dte": None,
            "entry_vix": None,
            "limit_price": None,
            "put_ibkr_mid": None,
            "call_ibkr_mid": None,
            "put_bs_mid": None,
            "call_bs_mid": None,
            "quote_source": "pending",
        }
        signal_id = store.enqueue_signal(
            PendingSignal(signal_type=SignalType.MANUAL, payload_json=json.dumps(payload))
        )
        return {"signal_id": signal_id}

    # ── Health (public — no auth) ─────────────────────────────────────────────

    @app.get("/health")
    def health():
        hb = store.read_heartbeat()
        age_sec = None
        if hb.get("last_tick_at"):
            last_tick = hb["last_tick_at"]
            if last_tick.tzinfo is None:
                last_tick = last_tick.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - last_tick).total_seconds()
        return {
            "heartbeat_age_sec": age_sec,
            "ibkr_connected": hb.get("ibkr_connected", False),
            "dry_run": hb.get("dry_run", False),
            "open_trade_count": hb.get("open_trade_count", 0),
            "version": hb.get("version", "0.1.0"),
        }

    # ── Notifications ─────────────────────────────────────────────────────────

    @app.get("/notifications")
    def list_notifications(
        unread: bool = False,
        token: str = Depends(_require_token),
    ):
        return [_notif_to_dict(n) for n in store.list_notifications(unread_only=unread)]

    @app.post("/notifications/{notification_id}/ack")
    def ack_notification(notification_id: int, token: str = Depends(_require_token)):
        if not store.mark_notification_read(notification_id):
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"ok": True}

    return app


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _signal_to_dict(sig) -> dict:
    return {
        "id": sig.id,
        "created_at": sig.created_at.isoformat(),
        "signal_type": sig.signal_type.value,
        "trade_num": sig.trade_num,
        "status": sig.status.value,
        "approved_at": sig.approved_at.isoformat() if sig.approved_at else None,
        "submitted_at": sig.submitted_at.isoformat() if sig.submitted_at else None,
        "executed_at": sig.executed_at.isoformat() if sig.executed_at else None,
        "payload": json.loads(sig.payload_json) if sig.payload_json else {},
        "fill": json.loads(sig.fill_json) if sig.fill_json else None,
        "error_msg": sig.error_msg,
        "parent_signal_id": sig.parent_signal_id,
    }


def _trade_to_dict(pt) -> dict:
    meta = json.loads(pt.metadata_json) if pt.metadata_json else {}
    return {
        "trade_num": pt.trade_num,
        "entry_date": str(pt.entry_date.date()),
        "expiration": str(pt.expiration.date()),
        "put_strike": pt.put_strike,
        "call_strike": pt.call_strike,
        "net_credit": pt.net_credit,
        "status": pt.status,
        "exit_date": str(pt.exit_date.date()) if pt.exit_date else None,
        "exit_type": pt.exit_type,
        "pnl": pt.pnl,
        "roll_count": pt.roll_count,
        "parent_trade_num": pt.parent_trade_num,
        "manual": pt.manual,
        "daily_marks": json.loads(pt.daily_marks_json),
        "max_vix": meta.get("max_vix"),
        "entry_vix": meta.get("entry_vix"),
    }


def _notif_to_dict(n) -> dict:
    return {
        "id": n.id,
        "created_at": n.created_at.isoformat(),
        "level": n.level,
        "title": n.title,
        "body": n.body,
        "read_at": n.read_at.isoformat() if n.read_at else None,
    }
