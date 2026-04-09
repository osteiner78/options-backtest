"""FastAPI backend for the SPY short strangle backtest.

Exposes a REST API for running backtests and retrieving results.

Usage:
    pip install -e ".[api]"
    uvicorn straddle.api:app --reload
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from straddle import (
    PARAMS,
    compute_metrics,
    load_market_data,
    make_engine,
    run_backtest,
)

app = FastAPI(
    title="SPY Short Strangle Backtest API",
    description="REST API for running SPY short strangle backtests",
    version="0.1.0",
)

# In-memory result store
_results: Dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=2)


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
    initial_balance: Optional[float] = Field(default=None, description="Starting account balance")
    single_position: Optional[bool] = Field(default=None, description="Skip new entries while position is open")
    vix_entry_filter_enabled: Optional[bool] = Field(default=None, description="Enable VIX entry filter")
    vix_entry_max: Optional[float] = Field(default=None, description="Max VIX for entry")
    defensive_leg_roll_enabled: Optional[bool] = Field(default=None, description="Enable defensive leg roll")
    roll_for_credit: Optional[bool] = Field(default=None, description="Roll at 21 DTE for credit")
    manage_at_dte: Optional[int] = Field(default=None, description="DTE threshold for management")
    max_rolls: Optional[int] = Field(default=None, description="Max consecutive rolls")


class TradeSummary(BaseModel):
    """Simplified trade representation for API responses."""
    trade_num: int
    entry_date: str
    exit_date: Optional[str]
    expiration: str
    put_strike: float
    call_strike: float
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


class BacktestResponse(BaseModel):
    """Full backtest response with metrics and trade summary."""
    run_id: str
    status: str
    params: Dict[str, Any]
    metrics: Optional[MetricsResponse] = None
    trades: Optional[List[TradeSummary]] = None
    equity_curve: Optional[Dict[str, float]] = None
    error: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_params(req: BacktestRequest) -> dict:
    """Merge request overrides with default PARAMS."""
    params = dict(PARAMS)
    overrides = req.model_dump(exclude_none=True)
    params.update(overrides)
    return params


def _run_backtest_sync(params: dict) -> dict:
    """Run a full backtest and return results dict."""
    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
    )
    engine = make_engine(params)
    try:
        trades, equity_curve, skipped_entries, skipped_vix = run_backtest(
            data, params, engine
        )
    finally:
        if hasattr(engine, "close"):
            engine.close()

    metrics = compute_metrics(trades, equity_curve, params, data)

    # Serialize trades
    trade_summaries = [
        TradeSummary(
            trade_num=t.trade_num,
            entry_date=str(t.entry_date.date()),
            exit_date=str(t.exit_date.date()) if t.exit_date else None,
            expiration=str(t.expiration.date()),
            put_strike=t.put_strike,
            call_strike=t.call_strike,
            net_credit=t.net_credit,
            pnl=t.pnl,
            pnl_pct=t.pnl_pct,
            exit_type=t.exit_type,
            entry_vix=t.entry_vix,
        )
        for t in trades
    ]

    # Serialize equity curve
    eq_curve = {str(k.date()): v for k, v in equity_curve.items()}

    # Exit breakdown
    exit_breakdown = {}
    for t in trades:
        et = t.exit_type or "UNKNOWN"
        exit_breakdown[et] = exit_breakdown.get(et, 0) + 1

    final_balance = params["initial_balance"] + sum(t.pnl for t in trades)

    return {
        "params": params,
        "metrics": MetricsResponse(
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
            exit_breakdown=exit_breakdown,
        ),
        "trades": trade_summaries,
        "equity_curve": eq_curve,
        "skipped_entries": skipped_entries,
        "skipped_vix": skipped_vix,
    }


# ── Routes ───────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/backtest", response_model=BacktestResponse)
def run_backtest_api(req: BacktestRequest = BacktestRequest()):
    """Run a backtest with optional parameter overrides.

    Returns the full results inline. For long-running backtests,
    consider using the async endpoint (future).
    """
    run_id = str(uuid4())[:8]
    params = _build_params(req)

    try:
        result = _run_backtest_sync(params)
        return BacktestResponse(
            run_id=run_id,
            status="completed",
            params=params,
            metrics=result["metrics"],
            trades=result["trades"],
            equity_curve=result["equity_curve"],
        )
    except Exception as e:
        return BacktestResponse(
            run_id=run_id,
            status="failed",
            params=params,
            error=str(e),
        )


@app.get("/backtest/{run_id}", response_model=BacktestResponse)
def get_backtest_result(run_id: str):
    """Retrieve a previously run backtest result by ID."""
    if run_id not in _results:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    result = _results[run_id]
    return BacktestResponse(
        run_id=run_id,
        status=result.get("status", "unknown"),
        params=result.get("params", {}),
        metrics=result.get("metrics"),
        trades=result.get("trades"),
        equity_curve=result.get("equity_curve"),
        error=result.get("error"),
    )
