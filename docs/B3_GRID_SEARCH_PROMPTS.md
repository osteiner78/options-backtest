# B3 Grid Search — Implementation Prompts

Three sequential prompts. Run them in order. Each is self-contained and assumes a fresh assistant session with access to the repo at `/Users/oliversteiner/Documents/code/options-backtest`.

The full plan is `docs/B3_GRID_SEARCH_PLAN.md`. Reference it for context if needed, but the prompts below are sufficient to execute.

---

## Prompt 1 — Create `scripts/grid_search.py`

```
Create the file scripts/grid_search.py. ~150 lines max.

REQUIREMENTS:

1. Top-level imports only: pathlib, itertools, sys, time; pandas as pd; from joblib import Parallel, delayed; from tqdm import tqdm. Add the project src/ to sys.path so `straddle.*` resolves when called from a notebook:
       sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

2. Constants at module level:
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

3. Function `_apply_grid_overrides(combo: dict) -> dict`:
   - Returns a dict suitable for params.update().
   - Maps `vix_filter` → if value == "OFF": {"vix_entry_filter_enabled": False, "vix_entry_max": 999.0} else {"vix_entry_filter_enabled": True, "vix_entry_max": float(value)}.
   - Maps `defensive_leg_roll` → {"defensive_leg_roll_enabled": bool(value)}.
   - Sets `dte_min` from DTE_MIN_BY_DTE_MAX[combo["dte_max"]].
   - All other keys pass through unchanged.

4. Function `_is_valid(combo: dict) -> bool`:
   - dte_min = DTE_MIN_BY_DTE_MAX[combo["dte_max"]]
   - Returns combo["manage_at_dte"] < dte_min.

5. Function `_run_one(market: str, period_label: str, start_date: str, end_date: str, combo: dict) -> dict`:
   - Imports inside the function (so worker subprocesses pickle cleanly):
       from straddle.params import PARAMS, apply_market_preset
       from straddle.data import load_market_data
       from straddle.engines import make_engine
       from straddle import run_portfolio_backtest
       from straddle.metrics import compute_portfolio_metrics
   - Body, in this exact order:
       params = dict(PARAMS)
       params = apply_market_preset(params, market)
       params["start_date"] = start_date
       params["end_date"]   = end_date
       params["mode"]       = "market"
       params["portfolio_mode"] = "laddering"
       params.update(_apply_grid_overrides(combo))
       data   = load_market_data(start_date, end_date, market=market)
       engine = make_engine(params)
       try:
           trades, equity_df, _, _ = run_portfolio_backtest(data, params, engine)
           metrics = compute_portfolio_metrics(trades, equity_df, params, data)
       finally:
           if hasattr(engine, "close"):
               engine.close()
   - Builds and returns a row dict containing: every key in `combo`, plus market, period_label, start_date, end_date, plus each (out_key, src_key, default) in METRICS_KEYS as out_key=metrics.get(src_key, default).
   - Wrap the entire body in try/except Exception; on failure return the same row with metric values = 0.0 / 0 and an additional key "error" set to str(e). On success "error" key is None. (The notebook will surface failures via this column.)

6. Function `enumerate_grid(grid_def: dict) -> list[dict]`:
   - Returns the cartesian product of grid_def values as a list of dicts, filtered by _is_valid.
   - Order of keys in each dict matches GRID_DIMS.
   - Print "Grid: {raw_count} raw combos, {valid_count} after validity filter ({invalid_count} dropped)" before returning.

7. Function `run_grid(grid_def: dict, runs: list[tuple], n_workers: int = -1, output_path: Path = Path("data/B3/grid_search_results.parquet")) -> pd.DataFrame`:
   - `runs` is a list of (period_label, market, start_date, end_date) tuples.
   - output_path.parent.mkdir(parents=True, exist_ok=True)
   - Initialize an empty list `all_results = []`.
   - Iterate over each `run` in `runs`:
       - Build the task list for this specific run × each valid combo.
       - Print "Dispatching {N} tasks for {market} ({period_label})..."
       - Dispatch with `Parallel(n_jobs=n_workers, backend="loky", verbose=0)` wrapping `delayed(_run_one)` calls. Wrap the iteration with tqdm(total=N, desc=f"{market}-{period_label}").
       - Extend `all_results` with the results from this segment.
       - Convert the current `all_results` to a DataFrame and save to parquet via df.to_parquet(output_path, index=False) to checkpoint progress.
   - Convert `all_results` to the final DataFrame.
   - Print summary: total runs, runs with error, runs with n_trades < 50.
   - Return the DataFrame.

8. Add `if __name__ == "__main__":` at the bottom that runs a smoke test with a 2-element grid (target_delta=[0.20], dte_max=[30], profit_target_pct=[0.50], manage_at_dte=[14], vix_filter=["OFF"], defensive_leg_roll=[False]) on BOVA11 train (2017-01-01 to 2019-12-31) and prints the resulting single-row DataFrame.

CONSTRAINTS:
- No imports of straddle.* at module level. Only inside _run_one. This is a hard requirement for joblib worker pickling on macOS.
- No global state. No mutable module-level dicts beyond the constants above.
- Do NOT use multiprocessing.Pool, concurrent.futures, or asyncio. Only joblib.Parallel.
- Do NOT modify any file under src/straddle/.
- Do NOT edit src/straddle/params.py. Grid combos override via params.update() at runtime.
- File ends with a single trailing newline. No trailing whitespace.

WHEN DONE:
Run `python scripts/grid_search.py` and confirm it prints a single-row DataFrame with non-zero n_trades, finite sharpe, and error=None.
```

---

## Prompt 2 — Create `research/B3 - parameter grid search.ipynb`

```
Create research/B3 - parameter grid search.ipynb as a Jupyter notebook with the following 13 cells in this exact order. Use nbformat.v4 to construct the file. The kernel is python3.

CELL 1 (markdown):
# B3 Parameter Grid Search
6-dimension grid across BOVA11 and PETR4 with train/holdout split. Train ends pre-COVID (Mar 2020 crash excluded). Holdout = 2020-04 to 2025-12.

CELL 2 (code) — imports + path setup:
%matplotlib inline
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path.cwd().parent if (Path.cwd().name == "research") else Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from grid_search import run_grid, enumerate_grid, GRID_DIMS

OUT_DIR = ROOT / "data" / "B3"
RESULTS_PATH = OUT_DIR / "grid_search_results.parquet"

CELL 3 (code) — grid definition:
GRID = {
    "target_delta":       [0.20, 0.25, 0.30],
    "dte_max":            [21, 30, 45],
    "profit_target_pct":  [0.25, 0.50, 0.75],
    "manage_at_dte":      [10, 14, 21],
    "vix_filter":         [25, 30, 35, "OFF"],
    "defensive_leg_roll": [True, False],
}
combos = enumerate_grid(GRID)
print(f"Valid combos per (market, period): {len(combos)}")

CELL 4 (code) — period definition:
RUNS = [
    ("train",   "bova11", "2017-01-01", "2019-12-31"),
    ("holdout", "bova11", "2020-04-01", "2025-12-01"),
    ("train",   "petr4",  "2011-01-01", "2019-12-31"),
    ("holdout", "petr4",  "2020-04-01", "2025-12-01"),
]
for r in RUNS:
    print(r)

CELL 5 (code) — run grid (this is the long-running cell, ~10-15 min):
df = run_grid(GRID, RUNS, n_workers=-1, output_path=RESULTS_PATH)
print(f"Saved {len(df)} rows to {RESULTS_PATH}")

CELL 6 (code) — load results:
df = pd.read_parquet(RESULTS_PATH)
print(df.shape)
df.head()

CELL 7 (code) — sanity checks:
print("Total rows:", len(df))
print("By market × period:")
print(df.groupby(["market", "period_label"]).size())
print("\nFailures:", (df["error"].notna()).sum())
print("Underpowered (n_trades < 50):", (df["n_trades"] < 50).sum())
print("\nSharpe summary by market × period:")
print(df.groupby(["market", "period_label"])["sharpe"].describe()[["mean","std","min","max"]])

CELL 8 (markdown):
## Heatmap (a) — Sharpe by target_delta × dte_max

CELL 9 (code) — heatmap target_delta × dte_max, two subplots (BOVA11, PETR4):
def heatmap(ax, sub, x, y, title):
    pivot = sub.pivot_table(values="sharpe", index=y, columns=x, aggfunc="mean")
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)));   ax.set_yticklabels(pivot.index)
    ax.set_xlabel(x); ax.set_ylabel(y); ax.set_title(title)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            ax.text(j, i, f"{v:.2f}" if pd.notna(v) else "n/a",
                    ha="center", va="center", color="black", fontsize=9)
    return im

fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax, mkt in zip(axes, ["bova11", "petr4"]):
    sub = df.query("period_label == 'train' and market == @mkt and error.isna()", engine="python")
    im  = heatmap(ax, sub, "dte_max", "target_delta", f"{mkt.upper()} — train")
fig.colorbar(im, ax=axes, label="Mean Sharpe", shrink=0.8)
plt.savefig(OUT_DIR / "grid_heatmap_delta_dte.png", dpi=120, bbox_inches="tight")
plt.show()

CELL 10 (code) — heatmap profit_target × manage_at_dte (re-uses heatmap helper):
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax, mkt in zip(axes, ["bova11", "petr4"]):
    sub = df.query("period_label == 'train' and market == @mkt and error.isna()", engine="python")
    im  = heatmap(ax, sub, "manage_at_dte", "profit_target_pct", f"{mkt.upper()} — train")
fig.colorbar(im, ax=axes, label="Mean Sharpe", shrink=0.8)
plt.savefig(OUT_DIR / "grid_heatmap_profit_manage.png", dpi=120, bbox_inches="tight")
plt.show()

CELL 11 (code) — scatter n_trades vs Sharpe colored by total_return:
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax, mkt in zip(axes, ["bova11", "petr4"]):
    sub = df.query("period_label == 'train' and market == @mkt and error.isna()", engine="python")
    sc = ax.scatter(sub["n_trades"], sub["sharpe"], c=sub["total_return"],
                    cmap="RdYlGn", vmin=-0.5, vmax=0.5, s=18, alpha=0.7)
    ax.axvline(50, ls="--", c="grey", lw=0.8, label="n=50 cutoff")
    ax.axhline(0,  ls=":",  c="black", lw=0.5)
    ax.set_xlabel("n_trades"); ax.set_ylabel("Sharpe")
    ax.set_title(f"{mkt.upper()} — train")
    ax.legend(loc="lower right")
fig.colorbar(sc, ax=axes, label="Total return", shrink=0.8)
plt.savefig(OUT_DIR / "grid_scatter_ntrades_sharpe.png", dpi=120, bbox_inches="tight")
plt.show()

CELL 12 (code) — top-10 configs per market and holdout validation scatter:
COLS = ["sharpe","calmar","total_return","n_trades"] + GRID_DIMS

for mkt in ["bova11", "petr4"]:
    print(f"\n=== {mkt.upper()} top-10 by train Sharpe (n_trades>=50) ===")
    top = (df.query("period_label=='train' and market==@mkt and error.isna() and n_trades>=50",
                    engine="python")
             .nlargest(10, "sharpe")[COLS])
    print(top.to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
for ax, mkt in zip(axes, ["bova11", "petr4"]):
    train = df.query("period_label=='train' and market==@mkt and error.isna() and n_trades>=50",
                     engine="python")
    hold  = df.query("period_label=='holdout' and market==@mkt and error.isna() and n_trades>=50",
                     engine="python")
    j = train.merge(hold, on=GRID_DIMS, suffixes=("_t","_h"))
    ax.scatter(j["sharpe_t"], j["sharpe_h"], alpha=0.5, s=15)
    lim = max(abs(j[["sharpe_t","sharpe_h"]].values).max() if len(j) else 1.0, 1.0)
    ax.plot([-lim, lim], [-lim, lim], ls="--", c="grey", label="y = x")
    ax.axhline(0, ls=":", c="black", lw=0.5); ax.axvline(0, ls=":", c="black", lw=0.5)
    top = j.nlargest(10, "sharpe_t")
    for _, r in top.iterrows():
        ax.annotate(f"d={r.target_delta} dte={r.dte_max}",
                    (r.sharpe_t, r.sharpe_h), fontsize=7)
    ax.set_xlabel("Sharpe (train)"); ax.set_ylabel("Sharpe (holdout)")
    ax.set_title(f"{mkt.upper()}: train vs holdout")
    ax.legend(loc="upper left")
plt.savefig(OUT_DIR / "grid_train_vs_holdout.png", dpi=120, bbox_inches="tight")
plt.show()

CELL 13 (markdown):
## Conclusions
Fill in based on the charts above:
- Top-cluster signal: are top-10 train configs concentrated in a region of the grid, or scattered?
- Holdout robustness: do top configs cluster on/above the y=x diagonal, or below?
- Sharpe magnitude: is any positive Sharpe achievable, or is the entire surface negative?
- n<50 coverage: any market×period where most configs are underpowered?

CONSTRAINTS:
- Do NOT execute the notebook from this prompt. The user runs cell 5 manually (it's the 10-15 min one).
- Outputs in the saved .ipynb must be empty (cell["outputs"] = [], cell["execution_count"] = None).
- Use nbformat to write the .ipynb file. Validate with nbformat.validate(nb).
- File path is exactly: research/B3 - parameter grid search.ipynb (with spaces, lowercase 'parameter').

WHEN DONE:
Print the absolute path of the saved notebook and confirm it passes nbformat validation.
```

---

## Prompt 3 — Smoke test before the long run

```
Before the user kicks off the full grid (cell 5 of research/B3 - parameter grid search.ipynb takes ~10-15 min), verify three things end-to-end. Run these commands from the repo root /Users/oliversteiner/Documents/code/options-backtest.

CHECK 1 — module-level smoke test:
   python scripts/grid_search.py
EXPECT: prints a single-row DataFrame with n_trades > 0, finite sharpe, error=None. If joblib is not installed, install it (pip install joblib tqdm) then retry.

CHECK 2 — numerical equivalence to a direct laddering call (NOT to the CLI):

Background: scripts/run_backtest.py is hardcoded to single-position mode (run_backtest), but the grid worker uses laddering (run_portfolio_backtest). They are different strategies; numerical equivalence is impossible. The right check is "the worker reproduces a direct call to the same laddering pipeline used by the API", i.e., self-equivalence, not CLI-equivalence.

Run this Python snippet from the repo root and assert numerical equality:

   import sys
   from pathlib import Path
   sys.path.insert(0, "scripts")
   sys.path.insert(0, "src")

   from grid_search import _run_one
   from straddle.params import PARAMS, apply_market_preset
   from straddle.data import load_market_data
   from straddle.engines import make_engine
   from straddle import run_portfolio_backtest
   from straddle.metrics import compute_portfolio_metrics

   # Pick one valid combo from the grid:
   COMBO = {"target_delta": 0.20, "dte_max": 45, "profit_target_pct": 0.50,
            "manage_at_dte": 21, "vix_filter": "OFF", "defensive_leg_roll": False}
   START, END, MARKET = "2017-01-01", "2019-12-31", "bova11"

   # Path 1: through the grid worker
   worker = _run_one(MARKET, "smoke", START, END, COMBO)

   # Path 2: direct call (mirrors api.py::_run_backtest_task lines 185-201 exactly)
   from grid_search import _apply_grid_overrides
   params = dict(PARAMS)
   params = apply_market_preset(params, MARKET)
   params["start_date"] = START
   params["end_date"]   = END
   params["mode"]       = "market"
   params["portfolio_mode"] = "laddering"
   params.update(_apply_grid_overrides(COMBO))
   data   = load_market_data(START, END, market=MARKET)
   engine = make_engine(params)
   try:
       trades, equity_df, _, _ = run_portfolio_backtest(data, params, engine)
       direct = compute_portfolio_metrics(trades, equity_df, params, data)
   finally:
       if hasattr(engine, "close"):
           engine.close()

   # Assert exact equality (same code path, same inputs → identical floats)
   assert worker["error"] is None, f"worker errored: {worker['error']}"
   assert worker["n_trades"]     == direct["n"], (worker["n_trades"], direct["n"])
   assert abs(worker["sharpe"]   - direct["sharpe"]) < 1e-9
   assert abs(worker["total_return"] - direct["tot"]) < 1e-9
   assert abs(worker["calmar"]   - direct["calmar"]) < 1e-9
   print(f"OK  worker n_trades={worker['n_trades']}  sharpe={worker['sharpe']:.4f}  total_return={worker['total_return']:.4f}")

EXPECT: prints "OK ..." with non-zero n_trades. If any assertion fires, do NOT proceed. Diagnose: (a) _apply_grid_overrides not applied identically; (b) sys.path mismatch loading a wrong straddle; (c) hidden state in MarketEngine. The two paths only differ in worker error-handling and dict packing — any numerical drift is a bug.

CHECK 3 — validity filter assertion:
   python -c "from scripts.grid_search import enumerate_grid; combos = enumerate_grid({'target_delta':[0.20,0.25,0.30],'dte_max':[21,30,45],'profit_target_pct':[0.25,0.5,0.75],'manage_at_dte':[10,14,21],'vix_filter':[25,30,35,'OFF'],'defensive_leg_roll':[True,False]}); print(len(combos))"
EXPECT: 504 (3*7*3*4*2 where 7 = valid (dte_max, manage_at_dte) pairs out of 9).

If all three checks pass, the user can open research/B3 - parameter grid search.ipynb and run cell 5 (the long one). Tell them: "Smoke tests pass. The grid runner is verified to reproduce the canonical laddering pipeline byte-for-byte. Ready to run cell 5 (~10-15 min)."

CONSTRAINTS:
- Do NOT run the full grid yourself. The user owns the long-running cell.
- Do NOT modify any file under src/straddle/.
- If a check fails, stop and report the failure with diagnosis. Do not attempt fixes without user approval.
```

---

## Notes for the user

After Prompt 3 passes:
1. Open `research/B3 - parameter grid search.ipynb` in JupyterLab / VS Code
2. Run cells 1-4 to set up the grid
3. Run cell 5 — wait ~10-15 minutes (`tqdm` shows progress)
4. Run cells 6-13 to view the analysis

The 5 PNG charts also save to `data/B3/grid_*.png` so you can drag them into a write-up later.

If you want to re-analyse without re-running the grid: skip cell 5 and start from cell 6 (which loads the saved parquet).
