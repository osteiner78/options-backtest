"""Grid search for short strangle strategy parameters on B3 market.

Runs backtests with cash_investment_mode="risk_free" + cash_yield_annual=0.0
so that portfolio metrics (sharpe, total_return, max_drawdown) reflect the
pure strangle P&L — no underlying B&H contamination.

Usage: python scripts/grid_search.py  (self-equivalence verification)
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

GRID_DIMS = ["target_delta", "dte_max", "profit_target_pct",
             "manage_at_dte", "vix_filter", "defensive_leg_roll"]

DTE_MIN_BY_DTE_MAX = {21: 15, 30: 20, 45: 30}

METRICS_KEYS = [
    ("n_trades", "n", 0),
    ("total_return", "tot", 0.0),
    ("annualized_return", "ann", 0.0),
    ("sharpe", "sharpe", 0.0),
    ("max_drawdown", "mdd", 0.0),
    ("calmar", "calmar", 0.0),
    ("win_rate", "wr_chain", 0.0),
    ("underlying_return", "underlying_total_return", 0.0),
    ("underlying_sharpe", "underlying_sharpe", 0.0),
]

_ALPHA_DEFAULTS: dict[str, float] = {
    "alpha_vs_bh": 0.0,
    "alpha_sharpe": 0.0,
}

_CHAIN_DEFAULTS: dict[str, object] = {
    "n_chains": 0,
    "n_rolls_total": 0,
    "avg_rolls_per_chain": 0.0,
    "max_rolls_per_chain": 0,
    "chain_length_dist": {},
}

_SQRT252 = 15.874507866387544


def _apply_grid_overrides(combo: dict) -> dict:
    overrides: dict[str, object] = {}
    for key in GRID_DIMS:
        val = combo[key]
        if key == "vix_filter":
            overrides = _apply_vol_filter(val, overrides)
        elif key == "defensive_leg_roll":
            overrides["defensive_leg_roll_enabled"] = bool(val)
        else:
            overrides[key] = val
    overrides["dte_min"] = DTE_MIN_BY_DTE_MAX[combo["dte_max"]]
    return overrides


def _apply_vol_filter(val: object, overrides: dict) -> dict:
    s = str(val)
    if s.upper() == "OFF":
        overrides["vol_filter_mode"] = "off"
        overrides["vol_filter_threshold"] = 0.0
        overrides["vix_entry_filter_enabled"] = False
        overrides["vix_entry_max"] = 999.0
    elif s.startswith("rv_pct:"):
        overrides["vol_filter_mode"] = "rv_pct"
        overrides["vol_filter_threshold"] = float(s.split(":")[1])
    elif s.startswith("ivr:"):
        overrides["vol_filter_mode"] = "ivr"
        overrides["vol_filter_threshold"] = float(s.split(":")[1])
    else:
        overrides["vol_filter_mode"] = "vix"
        overrides["vol_filter_threshold"] = float(s)
        overrides["vix_entry_filter_enabled"] = True
        overrides["vix_entry_max"] = float(s)
    return overrides


def _is_valid(combo: dict) -> bool:
    dte_min = DTE_MIN_BY_DTE_MAX[combo["dte_max"]]
    return combo["manage_at_dte"] < dte_min


def _compute_alpha(equity_df: pd.DataFrame, data: pd.DataFrame,
                   metrics: dict, params: dict, trades: list) -> dict[str, float]:
    import numpy as np

    start = pd.Timestamp(params["start_date"])
    end = pd.Timestamp(params["end_date"])

    # Build daily MTM P&L from trade daily_marks, consistent with
    # _compute_mtm_equity used by compute_portfolio_metrics for Sharpe.
    records: list[dict] = []
    for t in trades:
        marks = getattr(t, "daily_marks", []) or []
        for date, mark in marks:
            records.append({"date": date, "trade": t.trade_num, "mark": mark})
    if records:
        df_marks = pd.DataFrame(records).sort_values(["trade", "date"])
        df_marks["prev"] = df_marks.groupby("trade")["mark"].shift(1).fillna(0.0)
        df_marks["delta"] = df_marks["mark"] - df_marks["prev"]
        daily_pnl = df_marks.groupby("date")["delta"].sum().sort_index()
        init = float(params.get("initial_balance", 50_000))
        mtm_equity = (init + daily_pnl.cumsum()).loc[start:end]
        strangle_daily = mtm_equity.pct_change().fillna(0.0).replace(
            [np.inf, -np.inf], 0.0)
    else:
        eq = equity_df["total_equity"].loc[start:end]
        strangle_daily = eq.pct_change().fillna(0.0).replace(
            [np.inf, -np.inf], 0.0)

    ul = data["underlying_close"].loc[start:end]
    underlying_daily = ul.pct_change().fillna(0.0)

    common = strangle_daily.index.intersection(underlying_daily.index)
    residual = strangle_daily.loc[common] - underlying_daily.loc[common]

    rs = float(residual.std(ddof=0))
    alpha_sr = float(residual.mean()) / rs * _SQRT252 if rs > 0 else 0.0

    alpha_vs_bh = (
        float(metrics.get("tot", 0.0))
        - float(metrics.get("underlying_total_return", 0.0))
    )
    return {"alpha_vs_bh": alpha_vs_bh, "alpha_sharpe": alpha_sr}


def _compute_chain_diagnostics(trades: list) -> dict[str, object]:
    roots = [t for t in trades if getattr(t, "parent_trade_num", None) is None]
    n_chains = len(roots)
    n_rolls = len(trades) - n_chains
    chain_lengths: dict[int, int] = {}
    for t in roots:
        depth = 0
        child = t
        while getattr(child, "child_trade_num", None) is not None:
            child_num = child.child_trade_num
            matches = [tr for tr in trades if tr.trade_num == child_num]
            if matches:
                child = matches[0]
                depth += 1
            else:
                break
        chain_lengths[depth] = chain_lengths.get(depth, 0) + 1
    max_chain = max(chain_lengths) if chain_lengths else 0
    avg_rolls = n_rolls / n_chains if n_chains > 0 else 0.0
    return {
        "n_chains": n_chains,
        "n_rolls_total": n_rolls,
        "avg_rolls_per_chain": avg_rolls,
        "max_rolls_per_chain": max_chain,
        "chain_length_dist": str(chain_lengths),
    }


def _run_one(market: str, period_label: str, start_date: str, end_date: str,
             combo: dict) -> dict:
    from straddle.params import PARAMS, apply_market_preset
    from straddle.data import load_market_data
    from straddle.engines import make_engine
    from straddle import run_portfolio_backtest
    from straddle.metrics import compute_portfolio_metrics

    try:
        params = dict(PARAMS)
        params = apply_market_preset(params, market)
        params["start_date"] = start_date
        params["end_date"] = end_date
        params["mode"] = "market"
        params["portfolio_mode"] = "laddering"
        params["cash_investment_mode"] = "risk_free"
        params["cash_yield_annual"] = 0.0
        params.update(_apply_grid_overrides(combo))
        data = load_market_data(start_date, end_date, market=market)
        engine = make_engine(params)
        try:
            trades, equity_df, _, _ = run_portfolio_backtest(
                data, params, engine)
            metrics = compute_portfolio_metrics(
                trades, equity_df, params, data)
        finally:
            if hasattr(engine, "close"):
                engine.close()
        row: dict[str, object] = dict(combo)
        row["market"] = market
        row["period_label"] = period_label
        row["start_date"] = start_date
        row["end_date"] = end_date
        for out_key, src_key, default in METRICS_KEYS:
            row[out_key] = metrics.get(src_key, default)
        row.update(_compute_alpha(equity_df, data, metrics, params, trades))
        row.update(_compute_chain_diagnostics(trades))
        row["error"] = None
        return row
    except Exception as e:
        row = dict(combo)
        row["market"] = market
        row["period_label"] = period_label
        row["start_date"] = start_date
        row["end_date"] = end_date
        for out_key, src_key, default in METRICS_KEYS:
            row[out_key] = 0 if default == 0 else 0.0
        row.update(_ALPHA_DEFAULTS)
        row.update(_CHAIN_DEFAULTS)
        row["error"] = str(e)
        return row


def enumerate_grid(grid_def: dict) -> list[dict]:
    keys = [k for k in GRID_DIMS if k in grid_def]
    values = [grid_def[k] for k in keys]
    raw_combos = list(itertools.product(*values))
    all_combos = [dict(zip(keys, c)) for c in raw_combos]
    valid = [c for c in all_combos if _is_valid(c)]
    print(f"Grid: {len(all_combos)} raw combos, {len(valid)} after validity "
          f"filter ({len(all_combos) - len(valid)} dropped)")
    return valid


def _prepare_df(results: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(results)
    if "vix_filter" in df.columns:
        df["vix_filter"] = df["vix_filter"].astype(str)
    if "defensive_leg_roll" in df.columns:
        df["defensive_leg_roll"] = df["defensive_leg_roll"].astype(bool)
    if "error" in df.columns:
        df["error"] = df["error"].astype(object)
    return df


def run_grid(grid_def: dict, runs: list[tuple], n_workers: int = -1,
             output_path: Path = Path("data/B3/grid_search_results.parquet"),
             ) -> pd.DataFrame:
    from joblib import Parallel, delayed
    from tqdm import tqdm

    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_results: list[dict] = []
    combos = enumerate_grid(grid_def)
    for run in runs:
        period_label, market, start_date, end_date = run
        tasks = [delayed(_run_one)(market, period_label, start_date, end_date, c)
                 for c in combos]
        print(f"Dispatching {len(tasks)} tasks for {market} ({period_label})...")
        gen = Parallel(n_jobs=n_workers, backend="loky", verbose=0,
                       return_as="generator")(tasks)
        segment = list(tqdm(gen, total=len(tasks),
                            desc=f"{market}-{period_label}"))
        all_results.extend(segment)
        _prepare_df(all_results).to_parquet(output_path, index=False)
        print(f"Checkpoint saved: {len(all_results)} rows → {output_path}")
    df = _prepare_df(all_results)
    n_err = int(df["error"].notna().sum())
    n_few = int((df["n_trades"] < 50).sum())
    n_invalid = int(((df["manage_at_dte"]
                      >= df["dte_max"].map(DTE_MIN_BY_DTE_MAX))
                     & df["error"].isna()).sum())
    print(f"Summary: {len(df)} runs total — {n_err} errors, "
          f"{n_few} with n_trades < 50, {n_invalid} invalid "
          f"(manage_at_dte >= dte_min)")
    if n_err > 0:
        print("Failed runs:")
        failures = df[df["error"].notna()]
        for _, r in failures.iterrows():
            print(f"  [{r['market']}/{r['period_label']}] "
                  f"vix={r['vix_filter']} delta={r['target_delta']} "
                  f"dte={r['dte_max']}: {str(r['error'])[:200]}")
    return df


if __name__ == "__main__":
    from straddle.params import PARAMS, apply_market_preset
    from straddle.data import load_market_data
    from straddle.engines import make_engine
    from straddle import run_portfolio_backtest
    from straddle.metrics import compute_portfolio_metrics

    COMBO = {"target_delta": 0.20, "dte_max": 45, "profit_target_pct": 0.50,
             "manage_at_dte": 21, "vix_filter": "OFF",
             "defensive_leg_roll": False}
    START, END, MARKET = "2017-01-01", "2019-12-31", "bova11"

    worker = _run_one(MARKET, "smoke", START, END, COMBO)

    params = dict(PARAMS)
    params = apply_market_preset(params, MARKET)
    params["start_date"] = START
    params["end_date"] = END
    params["mode"] = "market"
    params["portfolio_mode"] = "laddering"
    params["cash_investment_mode"] = "risk_free"
    params["cash_yield_annual"] = 0.0
    params.update(_apply_grid_overrides(COMBO))
    data = load_market_data(START, END, market=MARKET)
    engine = make_engine(params)
    try:
        trades, equity_df, _, _ = run_portfolio_backtest(data, params, engine)
        direct = compute_portfolio_metrics(trades, equity_df, params, data)
    finally:
        if hasattr(engine, "close"):
            engine.close()

    direct_alpha = _compute_alpha(equity_df, data, direct, params, trades)

    assert worker["error"] is None, f"worker errored: {worker['error']}"
    assert worker["n_trades"] == direct["n"], \
        (worker["n_trades"], direct["n"])
    assert abs(worker["sharpe"] - direct["sharpe"]) < 1e-9
    assert abs(worker["total_return"] - direct["tot"]) < 1e-9
    assert abs(worker["calmar"] - direct["calmar"]) < 1e-9
    assert abs(worker["alpha_vs_bh"] - direct_alpha["alpha_vs_bh"]) < 1e-9
    assert abs(worker["alpha_sharpe"] - direct_alpha["alpha_sharpe"]) < 1e-9
    print(f"OK  worker == direct: n_trades={worker['n_trades']}  "
          f"sharpe={worker['sharpe']:.4f}  "
          f"total_return={worker['total_return']:.4f}  "
          f"alpha_vs_bh={worker['alpha_vs_bh']:.4f}  "
          f"alpha_sharpe={worker['alpha_sharpe']:.4f}")
