"""FastAPI backend for the SPY short strangle backtest.
Exposes a REST API for running backtests and retrieving results.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from straddle import (PARAMS, compute_metrics, compute_portfolio_metrics, load_market_data, make_engine, run_backtest, run_portfolio_backtest)
from straddle.data import _DB_FIRST, _db_coverage_end
from straddle.runs_store import init_db, upsert_run, list_runs, get_run, delete_run, patch_label

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SPY Short Strangle Backtest API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# In-memory store for *active* runs only (pending/running).
# Completed results live in SQLite; this dict keeps only status + progress
# so memory usage stays flat regardless of run count.
_results: Dict[str, dict] = {}

init_db()

# ── Declarative API→internal parameter remapping ─────────────────────────────
# Keys here are the API field names (from BacktestRequest); values are the
# engine-internal param names (from params.py / PARAMS).
_PARAM_REMAP = {
    "pricing_mode":      "mode",
    "pricing_risk_free": "risk_free_rate",
    "risk_free_rate":    "cash_yield_annual",
    "defensive_enabled": "defensive_leg_roll_enabled",
}


class BacktestRequest(BaseModel):
    """Per-field validators return 422 with structured field errors on bad input."""
    start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    initial_balance: Optional[float] = Field(default=None, gt=0)
    strategy_mode: Optional[str] = Field(default=None, pattern=r"^(short_strangle|iron_condor)$")
    wing_delta: Optional[float] = Field(default=None, ge=0.01, le=0.30)
    target_delta: Optional[float] = Field(default=None, ge=0.05, le=0.45)
    dte_min: Optional[int] = Field(default=None, ge=0, le=365)
    dte_max: Optional[int] = Field(default=None, ge=0, le=365)
    profit_target_pct: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    stop_loss_pct: Optional[float] = Field(default=None, ge=0.1, le=10.0)
    single_position: Optional[bool] = None
    portfolio_mode: Optional[str] = Field(default=None, pattern=r"^(laddering|single)$")
    max_bpr_allocation: Optional[float] = Field(default=None, gt=0, le=1.0)
    entry_cooldown_days: Optional[int] = Field(default=None, ge=0, le=30)
    cash_investment_mode: Optional[str] = Field(default=None, pattern=r"^(risk_free|spy|blend)$")
    risk_free_rate: Optional[float] = Field(default=None, ge=0, le=0.2)
    manage_at_dte: Optional[int] = Field(default=None, ge=0, le=60)
    roll_for_credit: Optional[bool] = None
    max_rolls: Optional[int] = Field(default=None, ge=0, le=10)
    vix_entry_filter_enabled: Optional[bool] = None
    vix_entry_max: Optional[float] = Field(default=None, ge=5, le=100)
    defensive_enabled: Optional[bool] = None
    defensive_trigger_delta: Optional[float] = Field(default=None, ge=0.1, le=0.5)
    defensive_target_delta: Optional[float] = Field(default=None, ge=0.05, le=0.3)
    pricing_mode: Optional[str] = Field(default=None, pattern=r"^(synthetic|market)$")
    pricing_risk_free: Optional[float] = Field(default=None, ge=0, le=0.2)
    put_slope: Optional[float] = Field(default=None, ge=0, le=2.0)
    call_slope: Optional[float] = Field(default=None, ge=0, le=2.0)

class TradeSummary(BaseModel):
    trade_num: int
    entry_date: str
    exit_date: Optional[str]
    expiration: str
    put_strike: float
    call_strike: float
    long_put_strike: Optional[float] = None
    long_call_strike: Optional[float] = None
    net_credit: float
    pnl: Optional[float]
    pnl_pct: Optional[float]
    exit_type: Optional[str]
    entry_vix: float
    roll_count: int = 0
    parent_trade_num: Optional[int] = None
    n_leg_rolls: int = 0
    used_market_data: bool = False


class ExitStatRow(BaseModel):
    type: str
    count: int
    pct: float
    win_pct: Optional[float] = None
    avg_pnl: Optional[float] = None
    total_pnl: float


class VixRegimeStatRow(BaseModel):
    regime: str
    range: str
    count: int
    win_pct: Optional[float] = None
    avg_pnl: Optional[float] = None
    total_pnl: float

class MetricsResponse(BaseModel):
    n_trades: int; initial_balance: float; final_balance: float
    total_return: float; annualized_return: float; sharpe: float; max_drawdown: float
    calmar: float; win_rate: float; avg_pnl: float; spy_total_return: float
    spy_annualized_return: float; spy_sharpe: float; spy_max_drawdown: float; spy_calmar: float
    exit_breakdown: Dict[str, int]; ret_options: float; ret_cash_spy: float
    ret_cash_rf: float; cagr_options: float; cagr_cash_spy: float; cagr_cash_rf: float
    peak_positions: Optional[int] = None; avg_positions: Optional[float] = None
    avg_bpr_util_pct: Optional[float] = None; peak_bpr_util_pct: Optional[float] = None
    max_streak: Optional[int] = None
    exit_stats: List[ExitStatRow] = Field(default_factory=list)
    vix_regime_stats: List[VixRegimeStatRow] = Field(default_factory=list)

class BacktestResponse(BaseModel):
    run_id: str; status: str; params: Dict[str, Any]; metrics: Optional[MetricsResponse] = None
    trades: Optional[List[TradeSummary]] = None; equity_curve: Optional[Dict[str, float]] = None
    spy_curve: Optional[Dict[str, float]] = None; bpr_curve: Optional[Dict[str, float]] = None
    pos_count_curve: Optional[Dict[str, int]] = None; vix_curve: Optional[Dict[str, float]] = None
    vix_blocked_dates: Optional[List[str]] = None; error: Optional[str] = None

def _build_metrics_response(metrics: dict, params: dict, trades: list, data: pd.DataFrame) -> MetricsResponse:
    init = float(params.get("initial_balance", 50_000))
    years = (pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])).days / 365.25
    if years <= 0: years = 0.01
    def _ann(tot): return (1 + tot) ** (1 / years) - 1 if tot > -1 else -1.0
    def _clean(v): return float(v) if v is not None and not np.isnan(v) and not np.isinf(v) else 0.0
    short_pnl = sum(t.pnl for t in trades if t.pnl is not None)
    cash_yield_total = metrics.get("cash_yield_earned", 0.0)
    cash_mode = params["cash_investment_mode"]
    spy_alloc = params["spy_allocation_pct"]
    if cash_mode == "spy": ret_cash_spy, ret_cash_rf = cash_yield_total / init, 0.0
    elif cash_mode == "risk_free": ret_cash_spy, ret_cash_rf = 0.0, cash_yield_total / init
    else: ret_cash_spy, ret_cash_rf = (cash_yield_total * spy_alloc) / init, (cash_yield_total * (1 - spy_alloc)) / init
    spy_window = data.loc[pd.Timestamp(params["start_date"]) : pd.Timestamp(params["end_date"]), "spy_close"]
    spy_ann, spy_mdd, spy_calmar = 0.0, 0.0, 0.0
    if not spy_window.empty:
        s_vals = spy_window.values; spy_tot = (s_vals[-1] - s_vals[0]) / s_vals[0]
        spy_ann = _ann(spy_tot); pk = np.maximum.accumulate(s_vals)
        spy_mdd = float(((s_vals - pk) / pk).min()); spy_calmar = spy_ann / abs(spy_mdd) if spy_mdd != 0 else 0.0
    return MetricsResponse(
        n_trades=metrics.get("n", 0), initial_balance=init, final_balance=metrics.get("final", init),
        total_return=_clean(metrics.get("tot", 0)), annualized_return=_clean(metrics.get("ann", 0)),
        sharpe=_clean(metrics.get("sharpe", 0)), max_drawdown=_clean(metrics.get("mdd", 0)), calmar=_clean(metrics.get("calmar", 0)),
        win_rate=_clean(metrics.get("wr", 0)), avg_pnl=_clean(metrics.get("avg_pnl", 0)),
        spy_total_return=_clean(metrics.get("spy_total_return", 0)), spy_annualized_return=_clean(spy_ann),
        spy_sharpe=_clean(metrics.get("spy_sharpe", 0)), spy_max_drawdown=_clean(spy_mdd), spy_calmar=_clean(spy_calmar),
        exit_breakdown={"PROFIT": metrics.get("n_p", 0), "STOP": metrics.get("n_s", 0), "21DTE": metrics.get("n_d", 0), "EXPIRY": metrics.get("n_e", 0), "ROLLED": metrics.get("n_r", 0), "FORCE_CLOSE": metrics.get("n_f", 0)},
        ret_options=_clean(short_pnl/init), ret_cash_spy=_clean(ret_cash_spy), ret_cash_rf=_clean(ret_cash_rf),
        cagr_options=_clean(_ann(short_pnl/init)), cagr_cash_spy=_clean(_ann(ret_cash_spy)), cagr_cash_rf=_clean(_ann(ret_cash_rf)),
        peak_positions=metrics.get("peak_positions"), avg_positions=metrics.get("avg_positions"),
        avg_bpr_util_pct=_clean(metrics.get("avg_bpr_util", 0) / 100.0) if "avg_bpr_util" in metrics else None,
        peak_bpr_util_pct=_clean(metrics.get("peak_bpr_util", 0) / 100.0) if "peak_bpr_util" in metrics else None,
        max_streak=metrics.get("max_streak"),
        exit_stats=metrics.get("exit_stats", []),
        vix_regime_stats=metrics.get("vix_regime_stats", []),
    )

def _run_backtest_task(run_id: str, params: dict):
    _results[run_id]["status"] = "running"
    _results[run_id]["progress"] = {"pct": 0.0, "trades_so_far": 0, "current_date": None}
    upsert_run(run_id, "running", params)
    is_portfolio = params.get("portfolio_mode", "laddering") == "laddering"

    def _cb(info: dict):
        _results[run_id]["progress"] = info

    try:
        data = load_market_data(start_date=params["start_date"], end_date=params["end_date"])
        engine = make_engine(params)
        try:
            if is_portfolio:
                trades, equity_df, portfolio, _ = run_portfolio_backtest(data, params, engine, progress_callback=_cb)
                metrics = compute_portfolio_metrics(trades, equity_df, params, data)
                eq_curve = {str(k.date()): v for k, v in equity_df["total_equity"].items()}
                bpr_curve = {str(k.date()): v for k, v in equity_df["utilized_bpr"].items()}
                pos_curve = {str(k.date()): int(v) for k, v in equity_df["open_positions"].items()}
                vix_blocked_dates = [str(d.date()) for d, _ in portfolio.vix_blocked_dates]
            else:
                trades, equity_curve, _, vix_blocked_dates = run_backtest(data, params, engine, progress_callback=_cb)
                metrics = compute_metrics(trades, equity_curve, params, data)
                eq_curve = {str(k.date()): v for k, v in equity_curve.items()}
                bpr_curve, pos_curve = {}, {}

            # Restrict VIX curve to the backtest window (data may have a 90-day pre-buffer)
            start_ts = pd.Timestamp(params["start_date"])
            end_ts   = pd.Timestamp(params["end_date"])
            vix_window = data.loc[start_ts:end_ts, "vix_close"]
            spy_series = data.loc[start_ts:end_ts, "spy_close"]
            spy_curve = (
                {str(k.date()): float(v / float(spy_series.iloc[0]) * params["initial_balance"])
                 for k, v in spy_series.items()}
                if not spy_series.empty else {}
            )
            vix_curve = {str(k.date()): float(v) for k, v in vix_window.items()}

            trade_rows = [{
                "trade_num": t.trade_num,
                "entry_date": t.entry_date.strftime("%Y-%m-%d"),
                "exit_date": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else None,
                "expiration": t.expiration.strftime("%Y-%m-%d"),
                "put_strike": t.put_strike,
                "call_strike": t.call_strike,
                "long_put_strike": t.long_put_strike,
                "long_call_strike": t.long_call_strike,
                "net_credit": t.net_credit,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "exit_type": t.exit_type,
                "entry_vix": t.entry_vix,
                "roll_count": t.roll_count,
                "parent_trade_num": t.parent_trade_num,
                "n_leg_rolls": len(t.leg_rolls),
                "used_market_data": t.used_market_data,
            } for t in trades]
            metrics_resp = _build_metrics_response(metrics, params, trades, data)

            result_payload = {
                "metrics": metrics_resp.model_dump(),
                "trades": trade_rows,
                "equity_curve": eq_curve,
                "spy_curve": spy_curve,
                "bpr_curve": bpr_curve,
                "pos_count_curve": pos_curve,
                "vix_curve": vix_curve,
                "vix_blocked_dates": vix_blocked_dates,
            }
            # Persist full result to SQLite; keep only status in memory
            upsert_run(run_id, "completed", params, result=result_payload)
            _results[run_id] = {
                "run_id": run_id,
                "status": "completed",
                "params": params,
                "progress": {"pct": 1.0, "trades_so_far": len(trades), "current_date": None},
            }
        finally:
            if hasattr(engine, "close"): engine.close()
    except Exception as e:
        logger.error(f"Backtest {run_id} failed: {e}")
        _results[run_id].update({"status": "failed", "error": str(e)})
        upsert_run(run_id, "failed", params)

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/config")
def get_config():
    """Return defaults, per-field ranges/enums, and capabilities."""
    db_path = PARAMS.get("db_path", "data/Spy Options Database.db")
    try:
        db_last = _db_coverage_end(db_path)
        market_max = db_last.date().isoformat()
    except Exception:
        market_max = None

    ranges = {
        "target_delta":            {"min": 0.05, "max": 0.45, "step": 0.01},
        "wing_delta":              {"min": 0.01, "max": 0.30, "step": 0.01},
        "dte_min":                 {"min": 0,    "max": 365,  "step": 1},
        "dte_max":                 {"min": 0,    "max": 365,  "step": 1},
        "profit_target_pct":       {"min": 0.01, "max": 1.0,  "step": 0.01},
        "stop_loss_pct":           {"min": 0.1,  "max": 10.0, "step": 0.1},
        "max_bpr_allocation":      {"min": 0.01, "max": 1.0,  "step": 0.01},
        "entry_cooldown_days":     {"min": 0,    "max": 30,   "step": 1},
        "manage_at_dte":           {"min": 0,    "max": 60,   "step": 1},
        "max_rolls":               {"min": 0,    "max": 10,   "step": 1},
        "vix_entry_max":           {"min": 5,    "max": 100,  "step": 1},
        "defensive_trigger_delta": {"min": 0.1,  "max": 0.5,  "step": 0.01},
        "risk_free_rate":          {"min": 0,    "max": 0.2,  "step": 0.001},
        "put_slope":               {"min": 0,    "max": 2.0,  "step": 0.05},
        "call_slope":              {"min": 0,    "max": 2.0,  "step": 0.05},
    }
    enums = {
        "strategy_mode":        ["short_strangle", "iron_condor"],
        "pricing_mode":         ["synthetic", "market"],
        "portfolio_mode":       ["laddering", "single"],
        "cash_investment_mode": ["risk_free", "spy", "blend"],
    }
    capabilities = {
        "supports_iron_condor":  True,
        "market_data_min_date":  _DB_FIRST.date().isoformat(),
        "market_data_max_date":  market_max,
    }
    return {
        "defaults":     dict(PARAMS),
        "ranges":       ranges,
        "enums":        enums,
        "capabilities": capabilities,
    }


@app.post("/backtest", response_model=BacktestResponse)
async def run_backtest_api(background_tasks: BackgroundTasks, req: BacktestRequest = BacktestRequest()):
    run_id = str(uuid4())
    params = dict(PARAMS)
    overrides = req.model_dump(exclude_none=True)
    # Apply declarative key remapping before merging
    for api_key, internal_key in _PARAM_REMAP.items():
        if api_key in overrides:
            overrides[internal_key] = overrides.pop(api_key)
    params.update(overrides)
    _results[run_id] = {"run_id": run_id, "status": "pending", "params": params}
    background_tasks.add_task(_run_backtest_task, run_id, params)
    return BacktestResponse(run_id=run_id, status="pending", params=params)

@app.get("/backtest/{run_id}", response_model=BacktestResponse)
def get_backtest_result(run_id: str):
    entry = _results.get(run_id)
    # Active run (pending/running): return lightweight status without full data
    if entry and entry["status"] in ("pending", "running"):
        return BacktestResponse(run_id=run_id, status=entry["status"], params=entry.get("params", {}))
    # Completed/failed: read from SQLite (authoritative source for full payloads)
    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(status_code=404)
    result = stored.get("result") or {}
    return BacktestResponse(
        run_id=run_id, status=stored["status"], params=stored["params"],
        error=result.get("error"),
        **{k: result.get(k) for k in (
            "metrics", "trades", "equity_curve", "spy_curve",
            "bpr_curve", "pos_count_curve", "vix_curve", "vix_blocked_dates",
        ) if result.get(k) is not None},
    )


async def _sse_generator(run_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE events for a running backtest until it completes."""
    while True:
        entry = _results.get(run_id)
        if entry is None:
            # Not in memory — check SQLite (run from a previous server session)
            stored = get_run(run_id)
            if stored:
                yield f"data: {json.dumps({'status': stored['status'], 'pct': 1.0, 'trades_so_far': 0, 'current_date': None})}\n\n"
            else:
                yield f"event: error\ndata: {json.dumps({'error': 'run not found'})}\n\n"
            return
        progress = entry.get("progress", {})
        status = entry.get("status", "pending")
        payload = json.dumps({
            "status": status,
            "pct": progress.get("pct", 0.0),
            "trades_so_far": progress.get("trades_so_far", 0),
            "current_date": progress.get("current_date"),
        })
        yield f"data: {payload}\n\n"
        if status in ("completed", "failed"):
            return
        await asyncio.sleep(0.25)


@app.get("/backtest/{run_id}/stream")
async def stream_backtest(run_id: str):
    """SSE endpoint — streams progress events until the run completes."""
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Run history endpoints ─────────────────────────────────────────────────────

class RunListItem(BaseModel):
    run_id: str
    created_at: str
    status: str
    label: Optional[str] = None
    params: Dict[str, Any]


class LabelRequest(BaseModel):
    label: str


@app.get("/runs", response_model=List[RunListItem])
def list_runs_endpoint(limit: int = 50):
    return list_runs(limit=limit)


@app.get("/runs/{run_id}")
def get_run_endpoint(run_id: str):
    row = get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


@app.patch("/runs/{run_id}/label")
def label_run(run_id: str, req: LabelRequest):
    if not patch_label(run_id, req.label):
        raise HTTPException(status_code=404)
    return {"ok": True}


@app.delete("/runs/{run_id}")
def delete_run_endpoint(run_id: str):
    if not delete_run(run_id):
        raise HTTPException(status_code=404)
    _results.pop(run_id, None)
    return {"ok": True}


# ── Compare endpoint ──────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    run_ids: List[str]


@app.post("/compare")
def compare_runs(req: CompareRequest):
    """Return a dict of run_id → metrics for side-by-side comparison."""
    out = {}
    for rid in req.run_ids:
        # SQLite is the authoritative source for completed runs
        row = get_run(rid)
        if row and row.get("result") and row["result"].get("metrics"):
            out[rid] = row["result"]["metrics"]
    return out
