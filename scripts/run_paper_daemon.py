"""Paper trading daemon for SPY short strangle.

Usage:
    python scripts/run_paper_daemon.py setup-auth [--config PATH]
    python scripts/run_paper_daemon.py run [--once] [--dry-run] [--config PATH] [--db PATH]

Subcommands:
    setup-auth  Interactive bcrypt password setup. Writes hash to paper_config.json.
    run         Start the daemon (default). Connects IBKR, schedules periodic jobs.

Flags (run):
    --once      Run one daily cycle immediately, then exit (useful for smoke tests).
    --dry-run   Enqueue signals and log, but never call IBKR order submission methods.
                Surfaced in /health so the UI shows a banner.
    --config    Path to paper_config.json (default: data/paper_config.json).
    --db        Path to paper_trades.db  (default: data/paper_trades.db).

Verification (no TWS required):
    python scripts/run_paper_daemon.py run --once --dry-run
    → signal enqueued with BS-only quotes (or IBKR + BS if TWS is up), no orders placed.
"""

import argparse
import getpass
import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from straddle.engines import make_engine
from straddle.paper_trading.auth import hash_password
from straddle.paper_trading.config import PaperConfig
from straddle.paper_trading.config import load as load_config
from straddle.paper_trading.config import save as save_config
from straddle.paper_trading.ibkr_client import IBKRClient
from straddle.paper_trading.notifications import Notifier
from straddle.paper_trading.runner import PaperTradingEngine, today_naive_ny
from straddle.paper_trading.state import StateStore
from straddle.params import PARAMS

logger = logging.getLogger("paper_daemon")

# ── Entry points ──────────────────────────────────────────────────────────────


def cmd_setup_auth(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)

    print("Setting up paper trading authentication.")
    password = getpass.getpass("Enter new password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    cfg.password_hash = hash_password(password)
    save_config(cfg, args.config)
    print(f"Password set. Config written to {args.config}")
    print(f"Tip: chmod 600 {args.config}  # protects the bcrypt hash")


def cmd_run(args: argparse.Namespace) -> None:
    _configure_logging()

    cfg = load_config(args.config)
    store = StateStore(args.db)
    notifier = Notifier(
        store,
        log_path=cfg.log_path,
        ntfy_topic=cfg.ntfy_topic,
        ntfy_server=cfg.ntfy_server,
    )

    if PARAMS.get("strategy_mode", "short_strangle") != "short_strangle":
        logger.error("Paper trading v1 only supports strategy_mode='short_strangle'")
        sys.exit(1)

    if args.dry_run:
        logger.info("DRY-RUN mode — no IBKR order submission")

    ibkr = IBKRClient(cfg, notifier=notifier)
    connected = _try_connect(ibkr, cfg)

    engine = make_engine({**PARAMS, "mode": "synthetic"})
    runner = PaperTradingEngine(
        params=PARAMS,
        config=cfg,
        ibkr=ibkr,
        store=store,
        notifier=notifier,
        pricing_engine=engine,
        dry_run=args.dry_run,
    )

    if args.once:
        _run_once(runner, ibkr, connected, args.config, cfg, store, force=getattr(args, "force", False))
        return

    _run_scheduler(runner, ibkr, cfg, store, connected, args.config)


# ── Single-cycle mode ─────────────────────────────────────────────────────────


def _run_once(
    runner: PaperTradingEngine,
    ibkr: IBKRClient,
    connected: bool,
    config_path: str,
    cfg: PaperConfig,
    store: StateStore,
    force: bool = False,
) -> None:
    today = today_naive_ny()
    logger.info("--once: running daily cycle for %s", today.date())

    if not force and not _is_scheduled_trading_day(today):
        logger.info("Not a scheduled trading day — skipping cycle (use --force to override)")
    else:
        runner.run_daily_cycle(today)

    signals = store.list_signals()
    logger.info("Signals in DB after cycle: %d total", len(signals))
    for sig in signals:
        import json
        payload = json.loads(sig.payload_json)
        source = payload.get("quote_source", "?")
        logger.info(
            "  [%s] type=%-12s status=%-10s quote_source=%s",
            sig.id, sig.signal_type.value, sig.status.value, source,
        )

    if connected:
        ibkr.disconnect()
    logger.info("--once complete")


# ── Scheduler (full daemon) mode ──────────────────────────────────────────────


def _run_scheduler(
    runner: PaperTradingEngine,
    ibkr: IBKRClient,
    cfg: PaperConfig,
    store: StateStore,
    connected: bool,
    config_path: str,
) -> None:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
    except ImportError:
        logger.error("apscheduler / pytz not installed: pip install apscheduler pytz")
        sys.exit(1)

    ny_tz = pytz.timezone("America/New_York")
    scheduler = BackgroundScheduler(timezone=ny_tz)
    config_mtime = [_mtime(config_path)]

    def _daily_job():
        nonlocal cfg
        # Live-reload config if file changed
        new_mtime = _mtime(config_path)
        if new_mtime != config_mtime[0]:
            cfg = load_config(config_path)
            config_mtime[0] = new_mtime
            logger.info("Config reloaded from %s", config_path)

        today = today_naive_ny()
        if not _is_scheduled_trading_day(today):
            logger.info("Not a trading day (%s), skipping daily cycle", today.date())
            return
        runner.run_daily_cycle(today)

    # Daily evaluation job (weekdays at eval_time_et)
    h, m = [int(x) for x in cfg.eval_time_et.split(":")]
    scheduler.add_job(
        _daily_job,
        "cron",
        day_of_week="mon-fri",
        hour=h,
        minute=m,
        id="daily_cycle",
        misfire_grace_time=300,
    )

    # Process approved signals every 5 s
    scheduler.add_job(
        runner.process_approved_signals,
        "interval",
        seconds=5,
        id="process_signals",
    )

    # Heartbeat tick
    scheduler.add_job(
        lambda: store.tick_heartbeat(ibkr_connected=ibkr.is_connected, dry_run=runner._dry_run),
        "interval",
        seconds=cfg.heartbeat_interval_sec,
        id="heartbeat",
    )

    # Account cache refresh every 30 s (only if IBKR connected)
    scheduler.add_job(
        lambda: _refresh_account(ibkr, store),
        "interval",
        seconds=30,
        id="account_cache",
    )

    # Optional intraday stop-loss polling
    if cfg.intraday_enabled:
        scheduler.add_job(
            runner.run_intraday_check,
            "interval",
            minutes=cfg.intraday_poll_minutes,
            id="intraday_check",
        )

    scheduler.start()
    logger.info(
        "Daemon started. Daily cycle at %s ET (weekdays). Ctrl-C to stop.",
        cfg.eval_time_et,
    )

    stop_event = [False]

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received")
        stop_event[0] = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop_event[0]:
        time.sleep(1)

    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=True)
    if ibkr.is_connected:
        ibkr.disconnect()
    logger.info("Daemon stopped")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _try_connect(ibkr: IBKRClient, cfg: PaperConfig) -> bool:
    """Attempt IBKR connection; return True on success, False on failure."""
    try:
        connected = ibkr.connect()
    except ModuleNotFoundError:
        logger.warning(
            "ib_insync not installed (pip install ib_insync) — running in BS-only mode"
        )
        return False
    except Exception as exc:
        logger.warning("IBKR connection failed: %s — using Yahoo/BS fallback", exc)
        return False

    if connected:
        logger.info("Connected to IBKR at %s:%d", cfg.ibkr_host, cfg.ibkr_port)
    else:
        logger.warning(
            "Could not connect to IBKR at %s:%d — using Yahoo/BS fallback",
            cfg.ibkr_host, cfg.ibkr_port,
        )
    return connected


def _is_scheduled_trading_day(date: pd.Timestamp) -> bool:
    """Return True if date is a NYSE trading day (not a holiday or weekend)."""
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(str(date.date()), str(date.date()))
        return not schedule.empty
    except Exception:
        # Fallback: just check it's a weekday
        return date.weekday() < 5


def _get_early_close_time(date: pd.Timestamp) -> "pd.Timestamp | None":
    """Return close time if today is an early-close session, else None."""
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(str(date.date()), str(date.date()))
        if schedule.empty:
            return None
        close_utc = schedule.iloc[0]["market_close"]
        close_ny = close_utc.tz_convert("America/New_York")
        if close_ny.hour < 16:  # early close (e.g. 13:00 on day before holiday)
            return close_ny
    except Exception:
        pass
    return None


def _refresh_account(ibkr: IBKRClient, store: StateStore) -> None:
    if not ibkr.is_connected:
        return
    try:
        store.cache_account(ibkr.get_account_summary())
    except Exception as exc:
        logger.debug("Account cache refresh failed: %s", exc)


def _mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Silence noisy third-party loggers
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    default_config = str(Path(__file__).resolve().parent.parent / "data" / "paper_config.json")
    default_db = str(Path(__file__).resolve().parent.parent / "data" / "paper_trades.db")

    parser = argparse.ArgumentParser(
        description="Paper trading daemon for SPY short strangle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # setup-auth
    auth_p = sub.add_parser("setup-auth", help="Set bcrypt password for web UI")
    auth_p.add_argument("--config", default=default_config, metavar="PATH")

    # run
    run_p = sub.add_parser("run", help="Start the paper trading daemon")
    run_p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    run_p.add_argument("--dry-run", action="store_true", help="No IBKR order submission")
    run_p.add_argument("--force", action="store_true", help="Skip market-day check (useful for weekend tests)")
    run_p.add_argument("--config", default=default_config, metavar="PATH")
    run_p.add_argument("--db", default=default_db, metavar="PATH")

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "setup-auth":
        cmd_setup_auth(args)
    elif args.command == "run" or args.command is None:
        if args.command is None:
            # Default to run with no args parsed — re-parse with run defaults
            args = parser.parse_args(["run"] + sys.argv[1:])
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)
