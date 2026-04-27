"""FastAPI server for the paper trading web UI.

Usage:
    python scripts/run_paper_api.py [--host HOST] [--port PORT] [--config PATH] [--db PATH]

Defaults: host=0.0.0.0, port=8001.
The daemon (run_paper_daemon.py) and this server share the same SQLite database
via WAL mode — they can run simultaneously without conflict.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn

from straddle.paper_trading.api import create_app
from straddle.paper_trading.config import load as load_config
from straddle.paper_trading.state import StateStore


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Paper trading API server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--config", default=str(root / "data" / "paper_config.json"))
    parser.add_argument("--db", default=str(root / "data" / "paper_trades.db"))
    args = parser.parse_args()

    config = load_config(args.config)
    store = StateStore(args.db)
    app = create_app(store=store, config=config, config_path=args.config)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
