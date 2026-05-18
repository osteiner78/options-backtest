"""Sanity check: single_position vs laddering results for a fixed config.

Validates that both position modes produce internally consistent results
and that laddering improves capital utilization (more trades, higher returns)
while single_position isolates one position at a time.

Usage: python scripts/verify_position_mode.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "grid_search", PROJECT_ROOT / "scripts" / "grid_search.py"
)
_grid_search = importlib.util.module_from_spec(_spec)
sys.modules["grid_search"] = _grid_search
_spec.loader.exec_module(_grid_search)

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle import run_backtest, run_portfolio_backtest
from straddle.metrics import compute_metrics, compute_portfolio_metrics

BASE_CONFIG = {
    "target_delta": 0.16,
    "dte_max": 30,
    "profit_target_pct": 0.50,
    "manage_at_dte": 14,
    "vix_filter": "rv_pct:80",
    "defensive_leg_roll": False,
    "stop_loss_pct": 3.0,
}

SYMBOL = "bova11"
START, END = "2023-01-02", "2025-11-30"

_apply_grid_overrides = _grid_search._apply_grid_overrides

for exec_mode in ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"]:
    print(f"\n{'='*60}")
    print(f"Execution mode: {exec_mode}")
    print(f"{'='*60}")

    combo = dict(BASE_CONFIG, execution_mode=exec_mode)

    for mode_label, portfolio_mode in [
        ("single_position", "single_position"),
        ("laddering", "laddering"),
    ]:
        combo_pm = dict(combo, portfolio_mode=portfolio_mode)
        params = dict(PARAMS)
        params = apply_market_preset(params, SYMBOL)
        params["start_date"] = START
        params["end_date"] = END
        params["mode"] = "market"
        params["cash_investment_mode"] = "risk_free"
        params["cash_yield_annual"] = 0.0
        params.update(_apply_grid_overrides(combo_pm))

        data = load_market_data(START, END, market=SYMBOL)
        engine = make_engine(params)
        try:
            if portfolio_mode == "laddering":
                trades, equity_df, _, _ = run_portfolio_backtest(
                    data, params, engine, progress=False
                )
                metrics = compute_portfolio_metrics(trades, equity_df, params, data)
                peak_pos = metrics.get("peak_positions", 0)
                avg_pos = metrics.get("avg_positions", 0.0)
            else:
                trades, equity_curve, _, _ = run_backtest(
                    data, params, engine
                )
                metrics = compute_metrics(trades, equity_curve, params, data)
                peak_pos = 1
                avg_pos = 1.0
        finally:
            if hasattr(engine, "close"):
                engine.close()

        print(
            f"  {mode_label:>16s}: sharpe={metrics['sharpe']:>7.2f}  "
            f"n={metrics['n']:>3}  tot={metrics['tot']:>7.1%}  "
            f"mdd={metrics['mdd']:>6.1%}  peak_pos={peak_pos:>2}  "
            f"avg_pos={avg_pos:.1f}"
        )
