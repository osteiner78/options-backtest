# Paper Trading Engine for SPY Short Strangle (IBKR)

## Context

The repo currently runs historical backtests (Yahoo Finance + SQLite options DB). The goal is to take the same strategy live in **paper-trade mode against an IBKR paper account** so the strategy can be observed running forward in real market conditions before risking real capital.

Design constraints from review:

1. **No auto-firing.** The daemon emits *pending signals* (entries, profit closes, 21-DTE rolls, defensive leg rolls). The user reviews each in a web UI and explicitly approves/rejects before any IBKR order is sent.
2. **Standalone web app.** `apps/paper-ui/` (FastAPI + HTMX/Alpine, no build step beyond Tailwind CLI). Lives next to the existing `apps/streamlit-ui/`; shares no code.
3. **Notifications.** ntfy push + in-app feed + rotating log file. Triggered on: new pending signal, fill, daemon heartbeat miss, IBKR disconnect, intraday stop trigger.
4. **Daemon health monitoring.** Heartbeat row written every cycle; an external watchdog (or the API's `/health` polled by an ntfy schedule) raises an alert when the heartbeat ages past threshold.
5. **Hybrid pricing.** Prefer IBKR delayed quotes when sane (bid > 0, ask ≥ bid, spread within cap, age within window). Fall back to BS+skew. Both prices stored on every signal so the UI shows the spread.
6. **4:30 PM ET evaluation.**
7. **Intraday monitoring** off by default; when enabled, polls every N minutes for stop-loss conditions.
8. **On-demand manual entry** via `/fire` endpoint + UI button; signal tagged `manual=True` and goes through the same approval queue.
9. **Auth.** bcrypt password (set at `setup-auth`), `/login` issues session token, `Authorization: Bearer` on every other endpoint.
10. **Runtime config separate from `params.py`.** `data/paper_config.json` holds paper-only knobs (UI-editable). `params.py` keeps backtest defaults pristine.

The existing strategy code (`strategy.py`, `engines.py`) is reused without modification. The new layer is glue: **market snapshot → existing evaluator → pending signals → user approval → IBKR orders → state persisted → notifications**.

**Scope locks for v1.** Strategy locked to `short_strangle` (no iron condor — 4-leg combos and disabled defensive rolls add complexity not yet warranted). Position model locked to single-position (one open chain at a time). Daemon raises on startup if config disagrees.

**Conventions.** Trading dates are naive `pd.Timestamp` to match the existing repo. The single helper `today_naive_ny() = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)` produces "today in NY" everywhere. All schedules use the `America/New_York` tz on `AsyncIOScheduler`.

---

## Architecture

```
                   ┌────────────────────────────────────────────┐
                   │  scripts/run_paper_daemon.py               │
                   │  (long-running: daily eval + intraday      │
                   │   poll + heartbeat + IBKR connection)      │
                   └──────────────┬─────────────────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  paper_trading.runner             │
                │    PaperTradingEngine             │
                │    - run_daily_cycle (16:30 ET)   │
                │    - run_intraday_check (opt-in)  │
                │    - process_approved_signals     │
                │    - heartbeat tick               │
                └─┬───────────────┬─────────────────┘
                  │               │
   ┌──────────────▼──┐    ┌───────▼────────────────┐
   │ strategy.py     │    │ paper_trading.ibkr     │
   │  build_entry    │    │   IBKRClient           │
   │  evaluate_step  │    │   (ib_insync wrapper,  │
   │  Trade          │    │    quote sanity gate)  │
   └─────────────────┘    └────────────────────────┘
                  │
   ┌──────────────▼──┐    ┌────────────────────────┐
   │ engines.py      │    │ paper_trading.state    │
   │  SyntheticEng.  │    │   StateStore (SQLite,  │
   │  (BS+skew, used │    │   data/paper_trades.db │
   │   for fallback  │    │   WAL mode, single     │
   │   + display)    │    │   IBKR writer process) │
   └─────────────────┘    └────────────────────────┘
                                  │
   ┌──────────────────────────────▼────────────────┐
   │  scripts/run_paper_api.py  (FastAPI server)   │
   │   /signals, /signals/{id}/approve|reject,     │
   │   /trades, /account (DB-cached), /equity,     │
   │   /config, /fire, /health, /notifications     │
   │   - bcrypt + session token auth               │
   │   - approve = write status='approved' in DB;  │
   │     daemon picks it up                        │
   └──────────────────────────────┬────────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │  apps/paper-ui  (HTMX + Alpine)   │
                │   Login → Signals → Trades        │
                │   → Account → Config → Fire       │
                └───────────────────────────────────┘
```

**Concurrency model.** Two processes share `data/paper_trades.db` (WAL mode):
- **Daemon** holds the only `ib_insync` connection, runs on `AsyncIOScheduler`. Writes: signals, trades, equity, heartbeat, account-cache row, notifications.
- **API** is read-mostly. Its only write is updating `pending_signals.status` to `approved`/`rejected` (or inserting a new manual signal). It never touches IBKR.
- **Hand-off**: every 5 s the daemon sweeps `pending_signals WHERE status='approved'`, sends to IBKR, transitions `submitting → filled|cancelled|failed`, persists `Trade` updates, and emits notifications.

---

## Pending-signal lifecycle

```
generated  ──►  pending  ──►  approved  ──►  submitting  ──►  filled
                   │              │                              │
                   ▼              ▼                              ▼
               rejected      cancelled                       failed
                              (timeout                     (IBKR rejected
                               before fill)                 or exception)
```

- `pending` — daemon emitted; user has not acted.
- `approved` — user clicked Approve; awaiting daemon pickup.
- `rejected` — user clicked Reject; terminal.
- `submitting` — daemon sent to IBKR; awaiting fill or timeout.
- `filled` — IBKR confirmed; runner has updated the related `Trade`.
- `cancelled` — fill timeout (`fill_timeout_sec`) reached; order cancelled.
- `failed` — IBKR rejected or unhandled exception; reason in `error_msg`.

**TTL by signal type** (all configurable):
- `ENTRY` — 4h (overnight gap invalidates strikes; next morning's open re-evaluates).
- `CLOSE` / `ROLL` / `LEG_ROLL` / `OPEN_RECOVERY` — 18h (survives overnight so EOD signals are actionable next morning).

Expired pending signals auto-flip to `rejected/expired`.

**Mutation discipline.** `evaluate_trade_step()` mutates the in-memory `Trade` (appends `daily_marks`, applies `LegRollEvent`, updates `max_vix` / `stop_regime` / `overshoot_used`). To keep approval reversible without touching `strategy.py`:

1. Evaluator runs on a **`copy.deepcopy(trade)`** snapshot.
2. Pure bookkeeping always persists to the canonical `Trade`: today's `daily_mark` (mid-to-market), and `max_vix = max(canonical.max_vix or 0, vix_d)`.
3. Exit/roll/leg-roll outputs are **recommendations only** — the canonical `Trade` is otherwise unchanged until a fill confirms.
4. **One signal per trade per cycle.** If the snapshot's `len(leg_rolls) > canonical's`, emit only the `LEG_ROLL` signal and skip the exit branch this cycle (the rolled state will be re-evaluated next cycle, after the leg-roll fill is applied to the canonical Trade).
5. **On fill**, the canonical Trade absorbs the snapshot's relevant fields:
    - STOP fill → copy `stop_regime`, `overshoot_used` from snapshot.
    - LEG_ROLL fill → append the `LegRollEvent`, set `current_*_strike`, increment `net_credit`, set `current_baseline_mid` (all already computed on the snapshot).
    - ROLLED fill → mark the parent `Trade` exited (`exit_date`, `exit_dte`, `exit_type='ROLLED'`, `pnl`, `pnl_pct`, `roll_credit`) and insert the `new_trade` (its kwargs were committed at signal time).

**Signal payload contents.** Every signal stores both quotes (IBKR mid + BS mid + which was used), the limit price, the strike(s), and the full kwargs needed to reconstruct the order without re-running the evaluator. Strikes are immutable from generation to fill; the daemon may re-quote the limit at submission time but never re-strike.

**Submission-time revalidation.** Before sending to IBKR, `process_approved_signals` always:
- Re-quotes the limit using the same hybrid logic (IBKR mid when sane, BS otherwise) and re-anchors the limit. If the new mid drifts more than `revalidation_max_drift_pct` from the signal-time mid, auto-reject + re-emit a fresh signal so the user re-reviews.
- Verifies contract validity via `reqContractDetails` (the option may have expired, e.g., user approved after vacation).
- For `ENTRY`: re-checks the VIX entry filter, single-position lock, and that the market session is open.
- On any failure: status → `failed/<reason>`, notify, do not place the order.

**21-DTE roll atomicity.** A `ROLLED` signal carries both legs of the close + both legs of the new entry. The runner prefers a single 4-leg combo BAG limit; if IBKR can't price the cross-expiration combo, it splits into close-then-open with linked-signal state. If the open fails after the close fills, the runner emits a high-priority `OPEN_RECOVERY` signal so the user can re-attempt or stay flat.

---

## File-by-file plan

### New: `src/straddle/paper_trading/__init__.py`
Public surface: `PaperTradingEngine`, `IBKRClient`, `StateStore`, `PaperConfig`, `Notifier`. Re-exported from `straddle/__init__.py`.

### New: `src/straddle/paper_trading/config.py`
`PaperConfig` dataclass loaded from `data/paper_config.json` (created on first run). UI-editable.

```python
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
    signal_ttl_entry_minutes: int = 4 * 60          # ENTRY signals
    signal_ttl_management_minutes: int = 18 * 60    # CLOSE/ROLL/LEG_ROLL/OPEN_RECOVERY
    revalidation_max_drift_pct: float = 0.01        # auto-reject if quote drifted >1%

    # Quote sanity
    quote_max_spread_pct: float = 0.25
    quote_min_bid: float = 0.05
    quote_max_age_sec: int = 90

    # Notifications
    ntfy_topic: str | None = None
    ntfy_server: str = "https://ntfy.sh"
    log_path: str = "data/paper_trading.log"

    # Heartbeat
    heartbeat_interval_sec: int = 60
    heartbeat_alert_after_sec: int = 300

    # Auth (sensitive — never returned by GET /config)
    password_hash: str = ""             # bcrypt; set via setup-auth
    session_ttl_days: int = 7           # auth_sessions inactivity expiry
```

`load()` / `save()` round-trip JSON. `to_public_dict()` strips sensitive fields for `GET /config`. `update_from_public(payload)` is the only path PUT can use; it rejects writes to sensitive fields.

**Live reload.** The daemon `stat()`s the config file at the start of every cycle and reloads on mtime change. Sensitive fields can also be rotated via SIGHUP. The config file should be `chmod 600` since it holds the bcrypt password hash.

### New: `src/straddle/paper_trading/ibkr_client.py`
`ib_insync` wrapper.
- `connect()` / `disconnect()` with exponential backoff on reconnect; emits `Notifier` event on disconnect. `clientId` defaults to `ibkr_client_id + os.getpid() % 100` to avoid collision when the daemon restarts before TWS has released the slot.
- `get_spy_close() -> float` (delayed market data type 3 — uses the last 4:00 PM regular-session close, which the delayed feed populates within a few minutes).
- `get_vix_close() -> float`.
- `get_option_quote(strike, expiration, right) -> dict | None` — returns `{bid, ask, mid, last, age_sec, sane}`. Sanity gate uses `PaperConfig` thresholds (bid > `quote_min_bid`, ask ≥ bid, spread ≤ `quote_max_spread_pct`, age ≤ `quote_max_age_sec`).
- `is_contract_valid(symbol, expiration, strike, right) -> bool` — uses `reqContractDetails` to confirm the option still exists and isn't expired. Called during submission-time revalidation.
- `place_strangle(...) -> Fill`, `place_leg(...) -> Fill`, `place_roll_combo(...) -> Fill`, `close_strangle(trade) -> Fill`. All raise `FillTimeout` on timeout.
- `get_account_summary() -> dict` — `{NetLiquidation, BuyingPower, TotalCashValue, MaintMarginReq, ...}`. Daemon caches into `account_cache` table every 30 s.
- Contract: `Option('SPY', expiration_yyyymmdd, strike, right, 'SMART', tradingClass='SPY')`.
- `validate_strike(strike) -> float` — snaps an arbitrary user-supplied strike to the nearest valid SPY contract strike (queries `reqContractDetails` and rounds).

### New: `src/straddle/paper_trading/state.py`
SQLite at `data/paper_trades.db`, **WAL mode**, mirrors `runs_store.py` style.

Tables:
- `paper_trades` — `trade_num PK, entry_date, expiration, put_strike, call_strike, net_credit, parent_trade_num, roll_count, status, exit_date, exit_type, pnl, daily_marks_json, manual BOOL, ibkr_perm_id`.
- `leg_rolls` — `id PK, trade_num FK, event_date, side, old_strike, new_strike, debit_paid`.
- `equity_curve` — `date PK, nlv, cash, open_trade_count, source (MTM|IBKR_NLV)`.
- `pending_signals` — `id PK, created_at, signal_type (ENTRY|CLOSE|ROLL|LEG_ROLL|MANUAL|OPEN_RECOVERY), trade_num NULL, payload_json, status, approved_at, submitted_at, executed_at, fill_json, error_msg, ibkr_perm_id, parent_signal_id NULL`.
- `heartbeat` — single row `id=1`: `last_tick_at, last_eval_at, ibkr_connected, open_trade_count, version`.
- `account_cache` — single row `id=1`: `updated_at, summary_json`.
- `notifications` — `id PK, created_at, level, title, body, read_at`.
- `auth_sessions` — `token PK, created_at, last_used_at`.

Methods: `save_trade`, `load_open_trades`, `record_equity`, `enqueue_signal`, `list_signals(status=...)`, `update_signal_status`, `tick_heartbeat`, `read_heartbeat`, `cache_account`, `read_account_cache`, `add_notification`, `list_notifications`, session CRUD.

### New: `src/straddle/paper_trading/notifications.py`
`Notifier.notify(level, title, body)`:
- Always writes to rotating `data/paper_trading.log`.
- Always inserts into `notifications` table.
- If `ntfy_topic` set, POSTs to `{ntfy_server}/{ntfy_topic}` (httpx, short timeout, errors swallowed + logged).

### New: `src/straddle/paper_trading/auth.py`
- `hash_password` / `verify_password` via `passlib[bcrypt]`.
- `require_token(request, store)` FastAPI dependency — checks Bearer against `auth_sessions`.
- `create_session(store) -> token` (256-bit urlsafe, stored as `last_used_at = now`).
- `destroy_session(store, token)`.
- CLI: `python scripts/run_paper_daemon.py setup-auth` — interactive password set, writes bcrypt hash to `PaperConfig`.

### New: `src/straddle/paper_trading/runner.py`
`PaperTradingEngine` orchestrator.

```python
class PaperTradingEngine:
    def __init__(self, params, config, ibkr, store, notifier, pricing_engine):
        ...

    @property
    def open_trades(self):
        # Always reload from DB so API-side changes are visible
        return self.store.load_open_trades()

    def run_daily_cycle(self, today):
        market_row = self._snapshot_market()         # IBKR SPY/VIX + Yahoo r
        data_df    = self._build_lookback_df(today, market_row)

        for trade in self.open_trades:
            snapshot = copy.deepcopy(trade)
            n_rolls_before = len(snapshot.leg_rolls)
            res = evaluate_trade_step(snapshot, today, data_df, self.engine, self.params)

            # Always-persist bookkeeping (deep-copy loses these otherwise)
            self._persist_daily_mark(trade, snapshot.daily_marks[-1])
            self._persist_max_vix(trade, snapshot.max_vix)

            # One signal per trade per cycle: leg-roll wins, exit re-evaluated next cycle
            if len(snapshot.leg_rolls) > n_rolls_before:
                self._enqueue_signal_leg_roll(trade, snapshot, market_row)
            elif res.exited:
                self._enqueue_signal_close_or_roll(trade, snapshot, res, market_row)

        if self._should_enter_today(today):
            self._enqueue_entry_signal(today, market_row)

        self._record_equity(today, market_row)
        self.store.tick_heartbeat(last_eval_at=today)

    def run_intraday_check(self):
        if not self.config.intraday_enabled: return
        market_row = self._snapshot_market()
        for trade in self.open_trades:
            if self._stop_triggered(trade, market_row):
                self._enqueue_signal_intraday_stop(trade, market_row)

    def process_approved_signals(self):
        for sig in self.store.list_signals(status="approved"):
            self._execute_signal(sig)   # revalidate → IBKR → fill → mutate canonical Trade
```

**`_snapshot_market()`** returns a single dict `{spy_close, spy_open, spy_high, spy_low, vix_close, risk_free_rate}` for `today`. SPY/VIX from IBKR delayed type-3 ticks; risk-free from `data.fetch_risk_free_rate()`. If `^IRX` returns NaN, fall back to `params["risk_free_rate"]` — never propagate NaN into the engine.

**`_build_lookback_df(today, market_row)`** seeds at least 10 trading days of history from Yahoo (SPY OHLC + VIX + risk-free), appends today's snapshot row indexed at `today`, and returns a DataFrame indexed by date with columns `spy_close, spy_open, spy_high, spy_low, vix_close, risk_free_rate`. Required because `evaluate_trade_step` reads `data.iloc[prev_idx - 1]` for the price-stop overshoot path; a single-row frame would degrade gap detection.

**Pricing-source separation.**
- *Strike selection* (`get_entry_marks`, `find_strike_at_delta` inside `build_entry`/`attempt_defensive_leg_roll`): always BS+skew. Delta targeting requires a model; OTM IBKR quotes are too noisy.
- *Limit price for the order*: `_get_quote(strike, exp, right)` — hybrid: prefer IBKR mid when sane, else BS+skew. Both numbers are persisted in every signal `payload_json` so the UI can show the spread.

**`_should_enter_today(today)`** returns `True` only if (a) `today` is a configured entry date, (b) the VIX entry filter passes, and (c) **no** non-terminal `Trade` exists in `paper_trades` (single-position lock for v1). Re-checked again at submission time.

Reused unmodified:
- `evaluate_trade_step()` — `strategy.py:418`
- `build_entry()` — `strategy.py:83`
- `attempt_defensive_leg_roll()` — `strategy.py:249`
- `Trade`, `LegRollEvent` — `strategy.py:165`, `:152`
- `get_monthly_expiration()`, `get_entry_dates()` — `strategy.py:24`, `:42`
- `make_engine({**params, "mode": "synthetic"})` — `engines.py:604`
- `fetch_risk_free_rate()` — `data.py`

### New: `src/straddle/paper_trading/api.py`
FastAPI app, mounted by `scripts/run_paper_api.py`.

Endpoints (all behind `require_token` except `/login` and `/health`):
- `POST /login` body `{password}` → token.
- `POST /logout`
- `GET /signals?status=pending` — payload includes IBKR vs BS prices, age, signal type, related trade.
- `POST /signals/{id}/approve`
- `POST /signals/{id}/reject` body `{reason}`
- `GET /trades?status=open|closed`, `GET /trades/{trade_num}`
- `GET /account` — reads `account_cache`; returns `{summary, updated_at, stale}` where `stale=True` if `updated_at` older than 5 min. UI greys the value when stale.
- `GET /equity?from=...&to=...`
- `GET /config` — `to_public_dict()` (no sensitive fields).
- `PUT /config` — `update_from_public(payload)`. Daemon picks up changes via mtime poll.
- `POST /fire` body `{expiration, put_strike?, call_strike?, qty}` → composes a manual entry signal (16Δ defaults if strikes omitted), `manual=True`. API enqueues; daemon validates strike (`IBKRClient.validate_strike`) and rejects with reason if invalid.
- `GET /health` — `{heartbeat_age_sec, ibkr_connected, dry_run, open_trade_count, version}`. Public; suitable for the watchdog. UI uses `dry_run` to render a persistent banner so approvals can't silently no-op.
- `GET /notifications?unread=true`, `POST /notifications/{id}/ack`

**Auth.** Sessions live in `auth_sessions`; idle sessions older than `session_ttl_days` (default 7) are rejected and cleaned up. `/logout` deletes the row immediately.

### New: `apps/paper-ui/`
HTMX + Alpine + Tailwind, served by FastAPI via `StaticFiles` + Jinja2 templates.
```
apps/paper-ui/
  templates/
    base.html
    login.html
    signals.html        # polls /signals every 5s via hx-trigger
    trades.html
    account.html
    config.html
    fire.html
  static/
    app.js              # token storage, htmx Bearer header
    app.css             # compiled Tailwind
    tailwind.config.js
    input.css
```
One-shot Tailwind compile: `npx tailwindcss -i input.css -o app.css --minify`. Documented in README.

### New: `scripts/run_paper_daemon.py`
At startup: call `ib_insync.util.patchAsyncio()` once so `AsyncIOScheduler`, `httpx.AsyncClient`, and the IBKR connection share a single asyncio loop.

Subcommands:
- `setup-auth` — interactive bcrypt setup; prints success.
- `run` (default) — connect IBKR, build `AsyncIOScheduler` (tz `America/New_York`):
  - `run_daily_cycle` daily on weekdays. Default fire time is `eval_time_et` (16:30 ET). On half-day sessions (`pandas_market_calendars` `early_close`), the scheduler fires 30 min after the early close instead. US holidays are skipped entirely.
  - `process_approved_signals` every 5 s.
  - `run_intraday_check` every `intraday_poll_minutes` (only if enabled).
  - `tick_heartbeat` every `heartbeat_interval_sec`.
  - `cache_account` every 30 s.
- Flags: `--once`, `--dry-run` (enqueue + log; never call IBKR submit methods; surfaced in `/health` so the UI shows a banner).

### New: `scripts/run_paper_api.py`
Boots FastAPI via `uvicorn`. Flags: `--host`, `--port` (default 8001).

### New: `scripts/paper_watchdog.py` (small)
Standalone process / cronable script. Calls `GET /health`; if `heartbeat_age > heartbeat_alert_after_sec` or 5xx, posts ntfy alert. Tracks `last_alert_at` in a tiny local state file (default `data/watchdog_state.json`) and suppresses repeat alerts within a 30-min cooldown so a long outage doesn't spam ntfy. Documented as "run from a separate machine or cron for true dead-daemon detection."

### Modified: `src/straddle/params.py`
Add minimal sub-dict pointing to runtime files; do **not** add IBKR/UI/notification knobs here.

```python
class PaperTradingParams(TypedDict, total=False):
    paper_db_path: str
    paper_config_path: str

PAPER_TRADING: PaperTradingParams = {
    "paper_db_path": "data/paper_trades.db",
    "paper_config_path": "data/paper_config.json",
}
PARAMS = {**BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT, **PORTFOLIO, **PAPER_TRADING}
```

### Modified: `pyproject.toml`
```toml
paper = [
    "ib_insync>=0.9.86",
    "apscheduler>=3.10",
    "pandas_market_calendars>=4.3",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "httpx>=0.27",
    "passlib[bcrypt]>=1.7",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
]
# add to existing dev extra:
# "pytest-asyncio>=0.23",
```

### Modified: `src/straddle/__init__.py`
Re-export `PaperTradingEngine`, `PaperConfig`.

### New: `tests/test_paper_trading.py`
- `test_state_roundtrip`
- `test_signal_lifecycle` (pending → approved → submitting → filled)
- `test_signal_ttl_expires_pending`
- `test_runner_emits_pending_not_orders` — IBKR mock raises if `placeOrder` called inside `run_daily_cycle`.
- `test_evaluator_mutation_isolated` — rejecting a close signal leaves the on-disk `Trade` unchanged (verifies deep-copy discipline).
- `test_hybrid_quote_prefers_ibkr_when_sane` — sane → IBKR mid; insane → BS; both stored in payload.
- `test_dry_run_no_ibkr_submission`
- `test_open_trades_reflect_db_changes` — API rejection visible to daemon next cycle.
- `test_heartbeat_alert_threshold` — watchdog hits ntfy past threshold.
- `test_manual_fire_enqueues_signal_with_manual_flag`
- `test_manual_fire_invalid_strike_rejected` — daemon validation path.
- `test_auth_rejects_missing_token` — 401 without Bearer.
- `test_auth_login_issues_session_token`
- `test_config_get_omits_sensitive_fields` and `test_config_put_rejects_sensitive_fields`
- `test_roll_atomicity_recovery` — close fills, open fails → `OPEN_RECOVERY` signal emitted.

Existing `test_strategy.py` and `test_engines.py` cover the strategy/pricing surface unchanged.

---

## Critical files referenced

- `src/straddle/params.py` — minimal additions only.
- `src/straddle/strategy.py:83` (`build_entry`), `:249` (`attempt_defensive_leg_roll`), `:418` (`evaluate_trade_step`), `:165` (`Trade`), `:152` (`LegRollEvent`), `:24-78` (calendar helpers) — **reused unmodified**.
- `src/straddle/engines.py:107` (`SyntheticEngine`), `:604` (`make_engine`).
- `src/straddle/data.py` — `fetch_risk_free_rate()`.
- `src/straddle/runs_store.py` — pattern reference.
- `apps/streamlit-ui/` — sibling-app reference; new `apps/paper-ui/` does not share code.
- `pyproject.toml` — add `paper` extra and `pytest-asyncio` to dev.

---

## Open issues / explicit non-goals (v1)

- **Strategy locked to `short_strangle`.** Iron-condor mode (4-leg combos, defensive rolls disabled) is out of scope for v1. Daemon raises on startup if `params["strategy_mode"] != "short_strangle"`.
- **Single-position lock.** One open chain at a time. Multi-position laddering / portfolio mode is out of scope.
- **No fill retry / re-quote loop.** A combo limit that doesn't fill within `fill_timeout_sec` is cancelled and surfaced as a notification. User decides whether to re-fire manually.
- **Risk-free rate** comes from Yahoo `^IRX` (daily, NaN-fallback to `params["risk_free_rate"]`); not refreshed intraday.
- **Single user / single account.** Auth model assumes one operator; no multi-tenant or multi-IBKR-account support.
- **No live-data subscription.** All option quotes are 15-min delayed; SPY/VIX spot are delayed. By design — BS fallback covers the worst of it.
- **Daylight-savings**: `AsyncIOScheduler` uses tz `America/New_York`.
- **Database**: WAL mode enabled at startup; both processes open with `journal_mode=WAL`. No backup automation. **Schema migrations** are manual: v1 ships frozen DDL; later schema changes require documented `ALTER TABLE` snippets.

---

## Implementation order (suggested milestones)

Each milestone is independently verifiable.

1. **State layer + tests** — `state.py` + DDL + `tests/test_paper_trading.py::test_state_roundtrip,test_signal_lifecycle`. No IBKR. No FastAPI.
2. **Config + auth + notifications** — `config.py`, `auth.py`, `notifications.py` + tests. Still no IBKR.
3. **IBKR client** — `ibkr_client.py` with a fake/mock for tests; smoke against paper TWS once the user starts it.
4. **Runner (offline)** — `runner.py` driven by a stub IBKR; verify mutation discipline + signal emission + dry-run path.
5. **Runner (online)** — wire real IBKR; verify `--once` smoke against paper TWS.
6. **API** — `api.py` + `scripts/run_paper_api.py`; cURL the endpoints.
7. **UI** — `apps/paper-ui/` with login → signals → approve flow; manual `/fire` form last.
8. **Watchdog + ntfy live test** — kill daemon, confirm alert.
9. **Week-long endurance run** — both processes up; weekday 4:30 PM cycles; compare MTM with offline backtest.

---

## Verification plan

1. `pytest tests/test_paper_trading.py -v` — all new tests pass.
2. `pytest tests/ -v` — existing suite untouched.
3. `python scripts/run_paper_daemon.py setup-auth` — sets password, writes config.
4. `python scripts/run_paper_daemon.py run --once --dry-run` (no TWS required) — signal enqueued; both IBKR + BS quotes (or BS-only if disconnected) in payload; no order placed.
5. `python scripts/run_paper_api.py --port 8001`, then `curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/signals` → returns enqueued signal.
6. UI smoke at `http://localhost:8001/` — log in, see signal with IBKR vs BS prices, click Approve, watch `approved → submitting → filled` (in `--dry-run` it stops at `approved`, no-op).
7. Live IBKR (paper TWS on `127.0.0.1:7497`): `python scripts/run_paper_daemon.py run --once` → user approves in UI → verify in TWS that strangle (16Δ put + 16Δ call, 30–45 DTE 3rd-Friday SPY monthly) appears at expected strikes.
8. Manual fire: pick any 3rd-Friday expiration, optionally override strikes, submit → signal appears tagged `manual`, approve → fill confirmed in TWS.
9. Endurance: both processes up for one trading week. Each weekday at 16:30 ET → `equity_curve` row, signals for any management actions, ntfy fires within seconds. Heartbeat row updates every 60 s; killing the daemon triggers a watchdog ntfy within `heartbeat_alert_after_sec`. Compare daily MTM against an offline backtest over the same window — leg-by-leg drift should be cents.
