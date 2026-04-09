"""CLI entry point for the FastAPI backtest server.

Usage:
    python -m straddle.scripts.run_api
    python -m straddle.scripts.run_api --host 0.0.0.0 --port 8000
"""

import argparse
import sys
from pathlib import Path

# Ensure the package is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY Short Strangle Backtest API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install -e '.[api]'")
        sys.exit(1)

    print(f"Starting API server on http://{args.host}:{args.port}")
    print("Endpoints:")
    print("  GET  /health          — Health check")
    print("  POST /backtest        — Run a backtest")
    print("  GET  /backtest/{id}   — Get results by run ID")
    print()

    uvicorn.run(
        "straddle.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
