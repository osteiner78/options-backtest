"""Runtime configuration for paper trading daemon.

Loaded from data/paper_config.json (created on first run).
Sensitive fields (password_hash) are never returned by GET /config.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_SENSITIVE_FIELDS = frozenset({"password_hash"})


@dataclass
class PaperConfig:
    # IBKR connection
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497            # 7497=paper TWS, 4002=paper Gateway
    ibkr_client_id: int = 17

    # Scheduling
    eval_time_et: str = "16:30"
    intraday_enabled: bool = False
    intraday_poll_minutes: int = 15

    # Order execution
    order_limit_slippage: float = 0.05
    fill_timeout_sec: int = 60
    signal_ttl_entry_minutes: int = 240        # 4h — ENTRY signals
    signal_ttl_management_minutes: int = 1080  # 18h — CLOSE/ROLL/LEG_ROLL/OPEN_RECOVERY
    revalidation_max_drift_pct: float = 0.01   # auto-reject if quote drifted >1%

    # Quote sanity
    quote_max_spread_pct: float = 0.25
    quote_min_bid: float = 0.05
    quote_max_age_sec: int = 90

    # Notifications
    ntfy_topic: Optional[str] = None
    ntfy_server: str = "https://ntfy.sh"
    log_path: str = "data/paper_trading.log"

    # Heartbeat
    heartbeat_interval_sec: int = 60
    heartbeat_alert_after_sec: int = 300

    # Auth (sensitive — never returned by GET /config)
    password_hash: str = ""
    session_ttl_days: int = 7


def load(path: str) -> PaperConfig:
    """Load config from JSON file, creating it with defaults if absent."""
    p = Path(path)
    if not p.exists():
        cfg = PaperConfig()
        save(cfg, path)
        return cfg
    data = json.loads(p.read_text())
    known = {k: v for k, v in data.items() if k in PaperConfig.__dataclass_fields__}
    return PaperConfig(**known)


def save(cfg: PaperConfig, path: str) -> None:
    """Persist config to JSON. File should be chmod 600 (holds bcrypt hash)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2))


def to_public_dict(cfg: PaperConfig) -> dict:
    """Return all fields except sensitive ones — safe for GET /config response."""
    return {k: v for k, v in asdict(cfg).items() if k not in _SENSITIVE_FIELDS}


def update_from_public(cfg: PaperConfig, payload: dict) -> PaperConfig:
    """Return new PaperConfig with public fields updated from payload.

    Raises ValueError if payload attempts to set a sensitive field.
    Ignores unknown keys silently.
    """
    for key in payload:
        if key in _SENSITIVE_FIELDS:
            raise ValueError(f"Cannot update sensitive field via public API: {key!r}")
    current = asdict(cfg)
    for k, v in payload.items():
        if k in current:
            current[k] = v
    return PaperConfig(**current)
