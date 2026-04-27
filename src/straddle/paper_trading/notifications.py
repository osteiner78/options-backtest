"""Notification delivery for the paper trading daemon.

Every notify() call:
  1. Writes to a rotating log file (data/paper_trading.log).
  2. Inserts a row into the notifications table (in-app feed).
  3. If ntfy_topic is set, POSTs to {ntfy_server}/{ntfy_topic} (errors swallowed).
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from straddle.paper_trading.state import Notification, StateStore

_NTFY_PRIORITY = {"info": "default", "warning": "high", "error": "urgent", "success": "default"}


class Notifier:
    def __init__(
        self,
        store: StateStore,
        log_path: str = "data/paper_trading.log",
        ntfy_topic: Optional[str] = None,
        ntfy_server: str = "https://ntfy.sh",
    ) -> None:
        self._store = store
        self._ntfy_topic = ntfy_topic
        self._ntfy_server = ntfy_server.rstrip("/")
        self._logger = _build_logger(log_path)

    def notify(self, level: str, title: str, body: str) -> None:
        self._logger.log(_log_level(level), "[%s] %s — %s", level.upper(), title, body)
        self._store.add_notification(Notification(level=level, title=title, body=body))
        if self._ntfy_topic:
            self._post_ntfy(level, title, body)

    def _post_ntfy(self, level: str, title: str, body: str) -> None:
        try:
            import httpx

            url = f"{self._ntfy_server}/{self._ntfy_topic}"
            headers = {
                "Title": title,
                "Priority": _NTFY_PRIORITY.get(level, "default"),
                "Tags": level,
            }
            httpx.post(url, content=body.encode(), headers=headers, timeout=5)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("ntfy delivery failed: %s", exc)


def _build_logger(log_path: str) -> logging.Logger:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"paper_trading.{log_path}")
    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def _log_level(level: str) -> int:
    return {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR,
            "success": logging.INFO}.get(level, logging.INFO)
