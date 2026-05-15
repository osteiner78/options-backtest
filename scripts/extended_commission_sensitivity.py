"""
Extended commission sensitivity analysis for the top 5 v7 BOVA11 configs.
Tests commission multipliers 1x, 2x, 3x, 5x, 7x, 10x of R$1.00 baseline.
Covers both BOVA11 and PETR4 recommended configs.

Output:
  output/commission_extended/bova11_commission_extended.csv
  output/commission_extended/petr4_commission_extended.csv
  docs/YYYY-MM-DD - extended commission sensitivity.md
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics
from grid_search import _apply_vol_filter

OUTPUT_DIR = Path("output/commission_extended")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASELINE_COMMISSION = 1.00

MULTIPLIERS = [1, 2, 3, 5, 7, 10]

BOVA11_CONFIGS = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 3.0},
    {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:70", "stop_loss_pct": 3.0},
]

PETR4_CONFIGS = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
]

MODES = ["bid_ask", "mid", "mid_plus_1tick"]

RUNS = [
    ("train",   "2018-01-02", "2022-12-30"),
    ("holdout", "2023-01-02", "2025-11-30"),
]


def run_one(market: str, config: dict, mode: str, period: str,
            start: str, end: str, commission: float) -> dict:
    params = apply_market_preset(dict(PARAMS), market)
    overrides = _apply_vol_filter(config["vix_filter"], {})
    overrides.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "portfolio_mode": "laddering",
        "cash_investment_mode": "risk_free",
        "cash_yield_annual": 0.0,
        "execution_mode": mode,
        "commission_per_leg": commission,
        "single_position": False,
        "target_delta": config["target_delta"],
        "dte_max": config["dte_max"],
        "dte_min": 15,
        "profit_target_pct": config["profit_target_pct"],
        "manage_at_dte": config["manage_at_dte"],
        "stop_loss_pct": config["stop_loss_pct"],
        "use_price_stop": True,
    })
    params.update(overrides)
    data = load_market_data(start, end, market=market)
    engine = make_engine(params)
    trades, eq, *_ = run_portfolio_backtest(data, params, engine, progress=False)
    m = compute_portfolio_metrics(trades, eq, params, data)
    return {
        "market": market,
        "period": period,
        "execution_mode": mode,
        "commission": commission,
        "commission_multiplier": commission / BASELINE_COMMISSION,
        "config_label": (
            f"{int(config['target_delta']*100)}d"
            f"/dte{config['dte_max']}"
            f"/pt{int(config['profit_target_pct']*100)}%"
            f"/{config.get('vix_filter','OFF')}"
        ),
        **{k: v for k, v in config.items()},
        "sharpe":       m.get("sharpe", None),
        "total_return": m.get("tot", None),
        "n_trades":     m.get("n", None),
        "max_drawdown": m.get("mdd", None),
    }


def main():
    all_rows = []

    for market, configs in [("bova11", BOVA11_CONFIGS), ("petr4", PETR4_CONFIGS)]:
        print(f"\n{'='*50}")
        print(f"Market: {market.upper()}")
        n = len(configs) * len(MODES) * len(MULTIPLIERS) * len(RUNS)
        print(f"Running {n} backtests...")

        for cfg in configs:
            for mode in MODES:
                for mult in MULTIPLIERS:
                    commission = BASELINE_COMMISSION * mult
                    for period, start, end in RUNS:
                        label = f"{cfg['target_delta']}d/{mode}/commission={mult}x/{period}"
                        print(f"  {label}", end="... ", flush=True)
                        try:
                            row = run_one(market, cfg, mode, period, start, end, commission)
                            all_rows.append(row)
                            print(f"Sharpe={row['sharpe']:.2f}" if row['sharpe'] is not None else "n/a")
                        except Exception as e:
                            print(f"ERROR: {e}")
                            all_rows.append({
                                "market": market, "period": period,
                                "execution_mode": mode,
                                "commission": commission,
                                "commission_multiplier": mult,
                                "config_label": str(cfg),
                                "sharpe": None, "error": str(e),
                            })

    df = pd.DataFrame(all_rows)

    for market in ["bova11", "petr4"]:
        sub = df[df["market"] == market]
        sub.to_csv(OUTPUT_DIR / f"{market}_commission_extended.csv", index=False)

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/{today} - extended commission sensitivity.md"
    with open(report_path, "w") as f:
        f.write("# Extended Commission Sensitivity - BOVA11 & PETR4\n\n")
        f.write(f"**Date:** {today}  \n")
        f.write(f"**Baseline commission:** R${BASELINE_COMMISSION:.2f}/leg  \n")
        f.write(f"**Multipliers tested:** {MULTIPLIERS}  \n")
        f.write(f"  (5x = R${BASELINE_COMMISSION*5:.2f}/leg, ~mid-range retail)  \n")
        f.write(f"  (10x = R${BASELINE_COMMISSION*10:.2f}/leg, ~expensive retail)\n\n")

        f.write("---\n\n")

        for market in ["bova11", "petr4"]:
            sub = df[df["market"] == market]
            f.write(f"## {market.upper()}\n\n")

            hold_mid = sub[
                (sub["period"] == "holdout") &
                (sub["execution_mode"] == "mid")
            ]
            if not hold_mid.empty:
                pivot = hold_mid.pivot_table(
                    index="config_label",
                    columns="commission_multiplier",
                    values="sharpe",
                    aggfunc="first",
                )
                f.write("### Holdout Sharpe at `mid` execution\n\n")
                f.write(pivot.round(2).to_markdown())
                f.write("\n\n")

                f.write("### Break-even commission multiplier (holdout, mid)\n\n")
                f.write("| Config | Last positive | Sharpe at 10x |\n|--------|-------------|---------------|\n")
                for cfg_label, row in pivot.iterrows():
                    positive_mults = [m for m in MULTIPLIERS if row.get(m, -999) > 0]
                    last_pos = max(positive_mults) if positive_mults else "none"
                    sharpe_10x = row.get(10, None)
                    sharpe_str = f"{sharpe_10x:.2f}" if sharpe_10x is not None else "n/a"
                    f.write(f"| {cfg_label} | {last_pos}x | {sharpe_str} |\n")
                f.write("\n")

            hold_10x = sub[
                (sub["period"] == "holdout") &
                (sub["commission_multiplier"] == 10)
            ]
            if not hold_10x.empty:
                f.write("### Holdout Sharpe at 10x commission by execution mode\n\n")
                pivot_mode = hold_10x.pivot_table(
                    index="config_label",
                    columns="execution_mode",
                    values="sharpe",
                    aggfunc="first",
                )
                f.write(pivot_mode.round(2).to_markdown())
                f.write("\n\n")

    print(f"\nReport: {report_path}")
    return df


if __name__ == "__main__":
    df = main()
    print("Done.")
