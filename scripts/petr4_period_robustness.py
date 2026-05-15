"""
PETR4 period robustness analysis.
Mirrors the BOVA11 robustness from v7 Phase 6.

15 top PETR4 configs x 5 rolling 3-year windows x 3 execution modes = 225 backtests.

Windows:
  2015-01-02 to 2017-12-29  (low DB coverage expected)
  2016-01-04 to 2018-12-31  (moderate DB coverage)
  2018-01-02 to 2020-12-31  (good coverage)
  2020-01-02 to 2022-12-30  (good coverage)
  2022-01-03 to 2024-12-31  (full coverage)

Output:
  output/petr4_robustness/petr4_robustness_results.csv
  docs/YYYY-MM-DD - PETR4 period robustness.md
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
from grid_search import _apply_vol_filter, DTE_MIN_BY_DTE_MAX

OUTPUT_DIR = Path("output/petr4_robustness")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODES = ["bid_ask", "mid", "mid_plus_1tick"]

WINDOWS = [
    ("2015-2017", "2015-01-02", "2017-12-29"),
    ("2016-2018", "2016-01-04", "2018-12-31"),
    ("2018-2020", "2018-01-02", "2020-12-31"),
    ("2020-2022", "2020-01-02", "2022-12-30"),
    ("2022-2024", "2022-01-03", "2024-12-31"),
]


def get_top_petr4_configs(n: int = 15) -> list[dict]:
    """Load top N stable PETR4 configs from v7 parquet."""
    parquet_path = Path("data/B3/v7_petr4_grid_search_results.parquet")
    if not parquet_path.exists():
        raise FileNotFoundError(f"PETR4 v7 parquet not found: {parquet_path}")

    df = pd.read_parquet(parquet_path)
    valid = df[df["error"].isna() & (df["n_trades"] >= 30)].copy()

    mid = valid[valid["execution_mode"] == "mid"]
    train = mid[mid["period_label"] == "train"].set_index(
        ["target_delta", "dte_max", "profit_target_pct",
         "manage_at_dte", "vix_filter", "stop_loss_pct"]
    )["sharpe"].rename("train_sharpe")
    hold = mid[mid["period_label"] == "holdout"].set_index(
        ["target_delta", "dte_max", "profit_target_pct",
         "manage_at_dte", "vix_filter", "stop_loss_pct"]
    )["sharpe"].rename("holdout_sharpe")

    both = pd.concat([train, hold], axis=1).dropna()
    both["stability"] = both[["train_sharpe", "holdout_sharpe"]].min(axis=1)
    both = both.sort_values("stability", ascending=False)

    top = both.head(n).reset_index()
    configs = []
    for _, row in top.iterrows():
        configs.append({
            "target_delta":      row["target_delta"],
            "dte_max":           row["dte_max"],
            "profit_target_pct": row["profit_target_pct"],
            "manage_at_dte":     row["manage_at_dte"],
            "vix_filter":        row["vix_filter"],
            "stop_loss_pct":     row["stop_loss_pct"],
            "_stability":        row["stability"],
        })
    return configs


def run_one(config: dict, mode: str, window_name: str,
            start: str, end: str) -> dict:
    params = apply_market_preset(dict(PARAMS), "petr4")
    cfg = {k: v for k, v in config.items() if not k.startswith("_")}
    overrides = _apply_vol_filter(cfg["vix_filter"], {})
    overrides.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "portfolio_mode": "laddering",
        "cash_investment_mode": "risk_free",
        "cash_yield_annual": 0.0,
        "execution_mode": mode,
        "single_position": False,
        "target_delta": cfg["target_delta"],
        "dte_max": cfg["dte_max"],
        "dte_min": DTE_MIN_BY_DTE_MAX[cfg["dte_max"]],
        "profit_target_pct": cfg["profit_target_pct"],
        "manage_at_dte": cfg["manage_at_dte"],
        "stop_loss_pct": cfg["stop_loss_pct"],
        "use_price_stop": True,
    })
    params.update(overrides)
    data = load_market_data(start, end, market="petr4")
    engine = make_engine(params)
    trades, eq, *_ = run_portfolio_backtest(data, params, engine, progress=False)
    m = compute_portfolio_metrics(trades, eq, params, data)
    return {
        "window":           window_name,
        "execution_mode":   mode,
        "target_delta":     config["target_delta"],
        "dte_max":          config["dte_max"],
        "profit_target_pct":config["profit_target_pct"],
        "manage_at_dte":    config["manage_at_dte"],
        "vix_filter":       config["vix_filter"],
        "stop_loss_pct":    config["stop_loss_pct"],
        "stability_rank":   config.get("_stability", None),
        "sharpe":           m.get("sharpe", None),
        "total_return":     m.get("tot", None),
        "max_drawdown":     m.get("mdd", None),
        "n_trades":         m.get("n", None),
        "entry_db_pct":     m.get("entry_db_pct", None),
    }


def main():
    print("=" * 60)
    print("PETR4 Period Robustness (225 backtests)")
    print("=" * 60)

    print("\nLoading top 15 PETR4 configs from v7 parquet...")
    configs = get_top_petr4_configs(15)
    print(f"  {len(configs)} configs loaded")
    for i, c in enumerate(configs):
        print(f"  #{i+1}: {c['target_delta']}d dte{c['dte_max']} {c['vix_filter']} sl={c['stop_loss_pct']} (stability={c['_stability']:.3f})")

    n_total = len(configs) * len(WINDOWS) * len(MODES)
    print(f"\nRunning {n_total} backtests...")

    rows = []
    done = 0
    for cfg in configs:
        for window_name, start, end in WINDOWS:
            for mode in MODES:
                done += 1
                label = (f"{cfg['target_delta']}d/"
                         f"dte{cfg['dte_max']}/"
                         f"{mode}/"
                         f"{window_name}")
                print(f"  [{done}/{n_total}] {label}", end="... ", flush=True)
                try:
                    row = run_one(cfg, mode, window_name, start, end)
                    rows.append(row)
                    s = row["sharpe"]
                    db = row.get("entry_db_pct")
                    extra = f" (DB={db:.0f}%)" if db is not None else ""
                    print(f"Sharpe={s:.2f}{extra}" if s is not None else "n/a")
                except Exception as e:
                    print(f"ERROR: {e}")
                    rows.append({
                        "window": window_name, "execution_mode": mode,
                        "target_delta": cfg["target_delta"],
                        "sharpe": None, "error": str(e),
                    })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "petr4_robustness_results.csv", index=False)

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/{today} - PETR4 period robustness.md"
    with open(report_path, "w") as f:
        f.write("# PETR4 Period Robustness\n\n")
        f.write(f"**Date:** {today}  \n")
        f.write(f"**Configs:** 15 top stable from v7  \n")
        f.write(f"**Windows:** 5 rolling 3-year periods 2015-2024  \n")
        f.write(f"**Total backtests:** {len(df)}\n\n---\n\n")

        f.write("## Overall (all windows, all configs)\n\n")
        f.write("| Mode | % Positive | Median Sharpe | Plan target |\n")
        f.write("|------|-----------|--------------|------------|\n")
        targets_map = {"bid_ask": "<50%", "mid": ">50%", "mid_plus_1tick": ">70%"}
        for mode in MODES:
            sub = df[df["execution_mode"] == mode]["sharpe"].dropna()
            if len(sub) > 0:
                pct_pos = (sub > 0).mean() * 100
                med = sub.median()
                tgt = targets_map.get(mode, "")
                f.write(f"| {mode} | {pct_pos:.1f}% | {med:.3f} | {tgt} |\n")
            else:
                f.write(f"| {mode} | n/a | n/a | {targets_map.get(mode, '')} |\n")

        f.write("\n## By Window (mid execution)\n\n")
        f.write("| Window | % Positive | Median Sharpe | DB Coverage |\n")
        f.write("|--------|-----------|--------------|-------------|\n")
        for window_name, _, _ in WINDOWS:
            sub = df[(df["window"] == window_name) & (df["execution_mode"] == "mid")]
            sharpes = sub["sharpe"].dropna()
            if len(sharpes) > 0:
                pct_pos = (sharpes > 0).mean() * 100
                med = sharpes.median()
                db_pct = sub["entry_db_pct"].dropna().mean()
                db_str = f"{db_pct:.1f}%" if not pd.isna(db_pct) else "n/a"
                f.write(f"| {window_name} | {pct_pos:.1f}% | {med:.3f} | {db_str} |\n")
            else:
                f.write(f"| {window_name} | n/a | n/a | n/a |\n")

        f.write("\n## Recommended Config (25d/dte21/pt50%/OFF) by Window\n\n")
        f.write("| Window | bid_ask | mid | mid_plus_1tick | DB% |\n")
        f.write("|--------|---------|-----|----------------|-----|\n")
        rec = df[
            (df["target_delta"] == 0.25)
            & (df["dte_max"] == 21)
            & (df["profit_target_pct"] == 0.50)
            & (df["vix_filter"] == "OFF")
            & (df["stop_loss_pct"] == 2.0)
        ]
        for window_name, _, _ in WINDOWS:
            row_data = {}
            db_pct = None
            for mode in MODES:
                sub = rec[(rec["window"] == window_name) & (rec["execution_mode"] == mode)]
                if len(sub) > 0 and sub["sharpe"].notna().any():
                    row_data[mode] = sub["sharpe"].values[0]
                else:
                    row_data[mode] = None
                if mode == "mid" and len(sub) > 0 and "entry_db_pct" in sub.columns:
                    vals = sub["entry_db_pct"].dropna()
                    db_pct = vals.values[0] if len(vals) > 0 else None
            ba = f"{row_data['bid_ask']:.2f}" if row_data.get("bid_ask") is not None else "n/a"
            mi = f"{row_data['mid']:.2f}" if row_data.get("mid") is not None else "n/a"
            mt = f"{row_data['mid_plus_1tick']:.2f}" if row_data.get("mid_plus_1tick") is not None else "n/a"
            db_str = f"{db_pct:.0f}%" if db_pct is not None else "n/a"
            f.write(f"| {window_name} | {ba} | {mi} | {mt} | {db_str} |\n")

        mid_df = df[df["execution_mode"] == "mid"]["sharpe"].dropna()
        if len(mid_df) > 0:
            overall_pct = (mid_df > 0).mean() * 100
        else:
            overall_pct = 0

        data_rich_windows = ["2018-2020", "2020-2022", "2022-2024"]
        rich_sub = df[
            df["window"].isin(data_rich_windows)
            & (df["execution_mode"] == "mid")
        ]["sharpe"].dropna()
        if len(rich_sub) > 0:
            rich_pct = (rich_sub > 0).mean() * 100
        else:
            rich_pct = 0

        bova11_target = 78.7

        f.write(f"\n## Conclusion\n\n")
        f.write(f"- Overall (mid): {overall_pct:.1f}% configs positive across all windows\n")
        f.write(f"- Data-rich windows (2018-2024): {rich_pct:.1f}% configs positive at mid\n")

        if rich_pct >= 90:
            f.write(f"- **PETR4 is as robust as BOVA11** ({rich_pct:.1f}% vs BOVA11 {bova11_target}% in data-rich windows)\n")
        elif rich_pct >= 70:
            f.write(f"- **PETR4 is moderately robust** ({rich_pct:.1f}% vs BOVA11 {bova11_target}%)\n")
            f.write("  Consider starting BOVA11 first; add PETR4 after fill quality is confirmed.\n")
        else:
            f.write(f"- **PETR4 is less robust than BOVA11** ({rich_pct:.1f}% vs {bova11_target}%)\n")
            f.write("  Recommend NOT deploying PETR4 capital until further investigation.\n")

    print(f"\nReport: {report_path}")
    return df


if __name__ == "__main__":
    df = main()
    print("\nDone.")
