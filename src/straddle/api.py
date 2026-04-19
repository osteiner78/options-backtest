"""FastAPI backend for the SPY short strangle backtest.

Exposes a REST API for running backtests and retrieving results.

Usage:
    pip install -e ".[api]"
    uvicorn straddle.api:app --reload
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from straddle import (
    PARAMS,
    compute_metrics,
    compute_portfolio_metrics,
    load_market_data,
    make_engine,
    run_backtest,
    run_portfolio_backtest,
)

# ── Logging Setup ────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SPY Short Strangle Backtest API",
    description="REST API for running SPY short strangle backtests",
    version="0.1.0",
)

# In-memory result store (In a production app, use Redis/Postgres)
_results: Dict[str, dict] = {}


# ── Pydantic Models ──────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    """Optional parameter overrides for a backtest run."""
    start_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")
    mode: Optional[str] = Field(default=None, description="Pricing mode: 'synthetic' or 'market'")
    target_delta: Optional[float] = Field(default=None, description="Strike selection delta (e.g. 0.16)")
    dte_min: Optional[int] = Field(default=None, description="Minimum DTE")
    dte_max: Optional[int] = Field(default=None, description="Maximum DTE")
    profit_target_pct: Optional[float] = Field(default=None, description="Profit target as fraction of premium")
    stop_loss_pct: Optional[float] = Field(default=None, description="Stop loss as fraction of premium")
    use_price_stop: Optional[bool] = Field(default=None, description="Enable price-based stop loss")
    initial_balance: Optional[float] = Field(default=None, description="Starting account balance")
    single_position: Optional[bool] = Field(default=None, description="Skip new entries while position is open")
    vix_entry_filter_enabled: Optional[bool] = Field(default=None, description="Enable VIX entry filter")
    vix_entry_max: Optional[float] = Field(default=None, description="Max VIX for entry")
    defensive_leg_roll_enabled: Optional[bool] = Field(default=None, description="Enable defensive leg roll")
    roll_for_credit: Optional[bool] = Field(default=None, description="Roll at 21 DTE for credit")
    manage_at_dte: Optional[int] = Field(default=None, description="DTE threshold for management")
    max_rolls: Optional[int] = Field(default=None, description="Max consecutive rolls")
    # Strategy variant
    strategy_mode: Optional[str] = Field(default=None, description="Strategy: 'short_strangle' or 'iron_condor'")
    wing_delta: Optional[float] = Field(default=None, description="Long-leg delta for iron-condor wings (e.g. 0.05)")
    # Portfolio mode
    portfolio_mode: Optional[bool] = Field(default=None, description="Enable multi-position portfolio mode")
    max_bpr_allocation: Optional[float] = Field(default=None, description="Max fraction of capital used as BPR (e.g. 0.30)")
    cash_yield_annual: Optional[float] = Field(default=None, description="Annual yield on uninvested cash (e.g. 0.04)")
    cash_investment_mode: Optional[str] = Field(default=None, description="Cash investment: 'risk_free', 'spy', or 'blend'")
    spy_allocation_pct: Optional[float] = Field(default=None, description="SPY fraction for 'blend' cash mode (0.0–1.0)")
    entry_cooldown_days: Optional[int] = Field(default=None, description="Minimum trading days between new entries")


class TradeSummary(BaseModel):
    """Simplified trade representation for API responses."""
    trade_num: int
    entry_date: str
    exit_date: Optional[str]
    expiration: str
    put_strike: float
    call_strike: float
    # Iron-condor wings — None for a short strangle
    long_put_strike: Optional[float] = None
    long_call_strike: Optional[float] = None
    net_credit: float
    pnl: Optional[float]
    pnl_pct: Optional[float]
    exit_type: Optional[str]
    entry_vix: float


class MetricsResponse(BaseModel):
    """Backtest metrics summary."""
    n_trades: int
    initial_balance: float
    final_balance: float
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    calmar: float
    win_rate: float
    win_rate_chain: float
    avg_pnl: float
    max_consecutive_losses: int
    spy_total_return: float
    spy_sharpe: float
    exit_breakdown: Dict[str, int]
    # Portfolio-mode only (omitted for single-position runs)
    peak_positions: Optional[int] = None
    avg_positions: Optional[float] = None
    avg_bpr_util_pct: Optional[float] = None
    peak_bpr_util_pct: Optional[float] = None


class BacktestResponse(BaseModel):
    """Full backtest response with metrics and trade summary."""
    run_id: str
    status: str
    params: Dict[str, Any]
    metrics: Optional[MetricsResponse] = None
    trades: Optional[List[TradeSummary]] = None
    equity_curve: Optional[Dict[str, float]] = None
    error: Optional[str] = None


# ── Internal Worker ──────────────────────────────────────────────────────

def _serialize_trades(trades) -> List[TradeSummary]:
    return [
        TradeSummary(
            trade_num=t.trade_num,
            entry_date=t.entry_date.strftime("%Y-%m-%d"),
            exit_date=t.exit_date.strftime("%Y-%m-%d") if t.exit_date else None,
            expiration=t.expiration.strftime("%Y-%m-%d"),
            put_strike=t.put_strike,
            call_strike=t.call_strike,
            long_put_strike=t.long_put_strike,
            long_call_strike=t.long_call_strike,
            net_credit=t.net_credit,
            pnl=t.pnl,
            pnl_pct=t.pnl_pct,
            exit_type=t.exit_type,
            entry_vix=t.entry_vix,
        )
        for t in trades
    ]


def _build_metrics_response(metrics: dict, portfolio_metrics: bool = False) -> MetricsResponse:
    resp = MetricsResponse(
        n_trades=metrics.get("n", 0),
        initial_balance=metrics.get("init", 0),
        final_balance=metrics.get("final", 0),
        total_return=metrics.get("tot", 0),
        annualized_return=metrics.get("ann", 0),
        sharpe=metrics.get("sharpe", 0),
        max_drawdown=metrics.get("mdd", 0),
        calmar=metrics.get("calmar", 0),
        win_rate=metrics.get("wr", 0),
        win_rate_chain=metrics.get("wr_chain", 0),
        avg_pnl=metrics.get("avg_pnl", 0),
        max_consecutive_losses=metrics.get("max_streak", 0),
        spy_total_return=metrics.get("spy_total_return", 0),
        spy_sharpe=metrics.get("spy_sharpe", 0),
        exit_breakdown={
            "PROFIT":      metrics.get("n_p", 0),
            "STOP":        metrics.get("n_s", 0),
            "21DTE":       metrics.get("n_d", 0),
            "EXPIRY":      metrics.get("n_e", 0),
            "ROLLED":      metrics.get("n_r", 0),
            "FORCE_CLOSE": metrics.get("n_f", 0),
        },
    )
    if portfolio_metrics:
        resp.peak_positions = metrics.get("peak_positions")
        resp.avg_positions = metrics.get("avg_positions")
        resp.avg_bpr_util_pct = metrics.get("avg_bpr_util")
        resp.peak_bpr_util_pct = metrics.get("peak_bpr_util")
    return resp


def _run_backtest_task(run_id: str, params: dict):
    """Worker function to run backtest in the background."""
    _results[run_id]["status"] = "running"
    is_portfolio = params.get("portfolio_mode", False)

    try:
        data = load_market_data(
            start_date=params["start_date"],
            end_date=params["end_date"],
        )
        engine = make_engine(params)

        try:
            if is_portfolio:
                trades, equity_df, _portfolio, _n_vix = run_portfolio_backtest(
                    data, params, engine
                )
                metrics = compute_portfolio_metrics(trades, equity_df, params, data)
                eq_curve = {str(k.date()): v for k, v in equity_df["total_equity"].items()}
            else:
                trades, equity_curve, _skipped, _skipped_vix = run_backtest(
                    data, params, engine
                )
                metrics = compute_metrics(trades, equity_curve, params, data)
                eq_curve = {str(k.date()): v for k, v in equity_curve.items()}
        finally:
            if hasattr(engine, "close"):
                engine.close()

        _results[run_id].update({
            "status": "completed",
            "metrics": _build_metrics_response(metrics, portfolio_metrics=is_portfolio),
            "trades": _serialize_trades(trades),
            "equity_curve": eq_curve,
        })
        logger.info(f"Backtest {run_id} completed successfully.")

    except Exception as e:
        logger.error(f"Backtest {run_id} failed: {e}")
        _results[run_id].update({
            "status": "failed",
            "error": str(e),
        })


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_params(req: BacktestRequest) -> dict:
    """Merge request overrides with default PARAMS."""
    params = dict(PARAMS)
    overrides = req.model_dump(exclude_none=True)
    params.update(overrides)
    return params


# ── Routes ───────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/backtest", response_model=BacktestResponse)
async def run_backtest_api(
    background_tasks: BackgroundTasks, 
    req: BacktestRequest = BacktestRequest()
):
    """Trigger a backtest in the background.

    Returns a run_id immediately. Poll /backtest/{run_id} for results.
    """
    run_id = str(uuid4())[:8]
    params = _build_params(req)
    
    # Initialize record
    _results[run_id] = {
        "run_id": run_id,
        "status": "pending",
        "params": params,
    }
    
    # Queue task
    background_tasks.add_task(_run_backtest_task, run_id, params)
    
    return BacktestResponse(
        run_id=run_id,
        status="pending",
        params=params,
    )


@app.get("/backtest/{run_id}", response_model=BacktestResponse)
def get_backtest_result(run_id: str):
    """Retrieve backtest status or results by ID."""
    if run_id not in _results:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    res = _results[run_id]
    return BacktestResponse(
        run_id=run_id,
        status=res.get("status", "unknown"),
        params=res.get("params", {}),
        metrics=res.get("metrics"),
        trades=res.get("trades"),
        equity_curve=res.get("equity_curve"),
        error=res.get("error"),
    )


@app.get("/backtests", response_model=List[BacktestResponse])
def list_backtests():
    """List all recent backtest runs."""
    return [
        BacktestResponse(
            run_id=rid,
            status=data["status"],
            params=data["params"],
        )
        for rid, data in _results.items()
    ]
