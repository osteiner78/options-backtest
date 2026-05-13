# Pre-Grid-Search Validation Plan

**Date:** 2026-05-12  
**Status:** Ready for implementation  
**Blocks:** Definitive grid search, any further strategy conclusions

---

## Context

This plan addresses three critical gaps identified in the project review before the definitive grid search can be run:

1. **Synthetic fallback dominance** — ~50% of BOVA11 entries and ~45% of PETR4 entries fall back to `SyntheticEngine` because the DB lacks valid bid/ask for the target delta. Every prior grid search conclusion may be an artifact of BSM + parametric skew rather than real B3 prices.

2. **Sharpe verification gap** — The daily MTM Sharpe fix exists in code (commit `22600b8`), but it was never verified to produce sane values against the v2 grid search configurations that showed PETR4 Sharpe of −20. If those same configs now produce |Sharpe| < 3, the fix is confirmed. If not, there's still a bug.

3. **CDI IVs not wired** — `implied_volatility_cdi` and `delta_cdi` columns exist in the DB but the engine still reads the flat-12% columns. Before adopting CDI, we need to verify strike selection stability.

After these three diagnostics, plus calibrating quality tests for B3 and deciding on a synthetic fallback policy, the data layer will be ready for the definitive grid search.

---

## Step 1 — Add entry/exit/MTM source logging to strategy.py

**Goal:** For each trade, record whether entry, exit, and daily marks used real DB data or synthetic fallback. Report the breakdown in metrics output.

**Why:** Without this, we cannot tell whether the "BOVA11 positive ridge" is a property of real B3 markets or an artifact of `SyntheticEngine` pricing at the ~50% of entries that lack DB data.

### 1.1 — Modify Trade dataclass in `src/straddle/strategy.py`

Add fields after `used_market_data` (line 303):

```python
# Source tracking: whether entry/exit/MTM used real DB data
entry_source: str = "unknown"     # "db" | "synthetic"
exit_source: str = "unknown"      # "db" | "synthetic"
mtm_source_days: int = 0         # count of days MTM used real DB data
mtm_total_days: int = 0          # total days trade was held
```

### 1.2 — Track entry source in `build_entry()`

In `src/straddle/strategy.py`, the `build_entry()` function (line 200) already receives `used_db` from `engine.get_entry_marks()`. After line 233 (`kw["used_market_data"] = used_db`), add:

```python
kw["entry_source"] = "db" if used_db else "synthetic"
```

### 1.3 — Track exit source in `evaluate_trade_step()`

In `evaluate_trade_step()` (line 536), the function computes daily marks using `engine.get_leg_mark()`. For `MarketEngine`, `get_leg_mark()` returns DB ask when available and falls back to synthetic.

Add a helper function in `MarketEngine` (`src/straddle/engines.py`) to check data availability:

```python
def _source_for_strike(self, date_str: str, exp_str: Optional[str], opt: str, strike: float) -> str:
    """Return 'db' if a valid row exists in the DB for this strike, else 'synthetic'."""
    if date_str is None or exp_str is None:
        return "synthetic"
    und_clause, und_val = self._und_filter()
    params = [date_str, exp_str, opt, strike]
    if und_val is not None:
        params.append(und_val)
    cur = self._con.execute(
        f"""SELECT 1 FROM options_data
           WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
             {und_clause}
             AND mark > 0 AND ask >= bid
           LIMIT 1""",
        params,
    )
    return "db" if cur.fetchone() else "synthetic"
```

Then in `evaluate_trade_step()`, after computing `put_mid_d` and `call_mid_d` (around lines 581-598), add source tracking:

```python
# Source tracking for daily MTM
if hasattr(engine, '_source_for_strike') and ctx is not None:
    date_str = eval_date.strftime("%Y-%m-%d")
    exp_str = trade.expiration.strftime("%Y-%m-%d") if trade.expiration else None
    put_src = engine._source_for_strike(date_str, exp_str, "put", trade.active_put_strike)
    call_src = engine._source_for_strike(date_str, exp_str, "call", trade.active_call_strike)
    if put_src == "db" and call_src == "db":
        trade.mtm_source_days += 1
    trade.mtm_total_days += 1
```

### 1.4 — Track exit source

When a trade exits (line 777 onwards, `if exit_type:`), set:

```python
trade.exit_source = "db" if trade.mtm_source_days > 0 else "synthetic"
```

More precisely, on exit day, check if the exit marks came from DB or synthetic. The `used_market_data` field on the Trade already tracks entry source. For the exit, look at whether the last day's marks were from DB. We'll approximate this by checking the last recorded evaluation:

If `exit_type is not None` and we computed marks via `engine.get_leg_mark()`, we need to track whether those calls returned DB data or synthetic. The simplest approach: check whether `_strike_ask()` returned non-None for at least one leg on the exit date. Add a flag in `TradeStepResult`:

```python
@dataclass
class TradeStepResult:
    exited: bool
    exit_type: Optional[str] = None
    new_trade: Optional[Trade] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    close_cost: float = 0.0
    mid_d: float = 0.0
    put_mid_d: float = 0.0
    call_mid_d: float = 0.0
    exit_db_source: str = "unknown"  # "db" | "synthetic"
```

In `evaluate_trade_step()`, after computing `put_mid_d` and `call_mid_d`, set:

```python
if hasattr(engine, '_source_for_strike') and ctx is not None:
    date_str = eval_date.strftime("%Y-%m-%d")
    exp_str = trade.expiration.strftime("%Y-%m-%d") if trade.expiration else None
    put_src = engine._source_for_strike(date_str, exp_str, "put", trade.active_put_strike)
    call_src = engine._source_for_strike(date_str, exp_str, "call", trade.active_call_strike)
    result_mtm_db = (put_src == "db" and call_src == "db")
```

Then at exit (all `return TradeStepResult(exited=True, ..., exit_db_source="db" if result_mtm_db else "synthetic")`).

On the caller side (`evaluate_trade()`), after the trade closes, set:

```python
if closed.exit_type is not None:
    closed.exit_source = res.exit_db_source if hasattr(res, 'exit_db_source') else "unknown"
```

### 1.5 — Report source breakdown in metrics

In `src/straddle/metrics.py`, modify `compute_metrics()` to add source statistics:

```python
# Source tracking
entry_db_count = sum(1 for t in trades if getattr(t, 'entry_source', 'unknown') == 'db')
exit_db_count = sum(1 for t in trades if t.exit_type is not None and getattr(t, 'exit_source', 'unknown') == 'db')
mtm_db_pct_list = []
for t in trades:
    total = getattr(t, 'mtm_total_days', 0)
    source_days = getattr(t, 'mtm_source_days', 0)
    if total > 0:
        mtm_db_pct_list.append(source_days / total)

results["entry_db_count"] = entry_db_count
results["entry_db_total"] = len(trades)
results["entry_db_pct"] = entry_db_count / len(trades) if trades else 0
results["exit_db_count"] = exit_db_count
results["mtm_avg_db_pct"] = float(np.mean(mtm_db_pct_list)) if mtm_db_pct_list else 0
```

### 1.6 — Add source columns to `trades_to_df()` in `scripts/phase1_regression.py`

In the `trades_to_df()` function, add:

```python
"entry_source": t.entry_source,
"exit_source": t.exit_source,
"mtm_source_days": t.mtm_source_days,
"mtm_total_days": t.mtm_total_days,
"mtm_db_pct": t.mtm_source_days / t.mtm_total_days if t.mtm_total_days > 0 else 0,
```

### 1.7 — Validation

Run the Phase 1 regression script with source tracking:

```bash
python scripts/phase1_regression.py
```

Verify the output includes source tracking for each trade. Check that:
- `entry_source` is either "db" or "synthetic"
- `mtm_db_pct` is between 0 and 1
- BOVA11 shows ~50% entry_db_pct (matching the Phase 1 finding)
- PETR4 shows ~55% entry_db_pct

**Expected output:** A table showing for each underlying/db combination:
- % of entries using real DB pricing
- % of exits using real DB pricing  
- Average % of MTM days using real DB pricing
- P&L broken down by entry_source (db vs synthetic)

**Time estimate:** 2-3 hours

---

## Step 2 — Quantify synthetic fallback dominance

**Goal:** Run one BOVA11 backtest with the v2 top config and report P&L by entry source. This tells us whether the grid search "positive ridge" results are driven by real B3 data or by the synthetic engine.

### 2.1 — Create diagnostic script

Create `scripts/quantify_synthetic_dominance.py`:

```python
"""Step 2: Quantify synthetic fallback dominance.

Runs a single BOVA11 backtest with the v2 top config and reports P&L broken
down by entry_source (db vs synthetic).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import numpy as np
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset

ROOT = Path(__file__).resolve().parent.parent

# v2 top BOVA11 config: d=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF
CONFIG = {
    "target_delta": 0.30,
    "dte_min": 30,
    "dte_max": 45,
    "manage_at_dte": 14,
    "profit_target_pct": 0.75,
    "vol_filter_mode": "off",
    "defensive_leg_roll_enabled": False,
    "single_position": True,
    "mode": "market",
}

def main():
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    params.update(CONFIG)
    params["start_date"] = "2020-04-01"
    params["end_date"] = "2025-12-31"

    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market="bova11",
    )

    engine = make_engine(params)
    try:
        trades, equity, skipped, vix_blocked = run_backtest(data, params, engine)
    finally:
        engine.close()

    # Build dataframe with source info
    rows = []
    for t in trades:
        rows.append({
            "trade_num": t.trade_num,
            "entry_date": t.entry_date,
            "entry_source": getattr(t, "entry_source", "unknown"),
            "exit_source": getattr(t, "exit_source", "unknown"),
            "mtm_db_pct": getattr(t, "mtm_source_days", 0) / max(getattr(t, "mtm_total_days", 1), 1),
            "pnl": t.pnl,
            "exit_type": t.exit_type,
            "roll_count": t.roll_count,
        })
    df = pd.DataFrame(rows)

    print("\n" + "=" * 60)
    print("  BOVA11 Synthethic vs Real DB Breakdown")
    print("  Config: d=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF")
    print("=" * 60)

    # Entry source breakdown
    db_trades = df[df["entry_source"] == "db"]
    synth_trades = df[df["entry_source"] == "synthetic"]
    total = len(df)

    print(f"\n  Total trades: {total}")
    print(f"  DB entries: {len(db_trades)} ({len(db_trades)/total*100:.1f}%)")
    print(f"  Synthetic entries: {len(synth_trades)} ({len(synth_trades)/total*100:.1f}%)")

    # P&L by source
    if len(db_trades) > 0:
        pnl_db = db_trades["pnl"].dropna()
        print(f"\n  DB-entry P&L:")
        print(f"    Total:   R${pnl_db.sum():+,.2f}")
        print(f"    Mean:    R${pnl_db.mean():+,.2f}")
        print(f"    Win rate: {(pnl_db > 0).mean()*100:.1f}%")
        print(f"    N:        {len(pnl_db)}")

    if len(synth_trades) > 0:
        pnl_synth = synth_trades["pnl"].dropna()
        print(f"\n  Synthetic-entry P&L:")
        print(f"    Total:   R${pnl_synth.sum():+,.2f}")
        print(f"    Mean:    R${pnl_synth.mean():+,.2f}")
        print(f"    Win rate: {(pnl_synth > 0).mean()*100:.1f}%")
        print(f"    N:        {len(pnl_synth)}")

    # Chains: how many root chains start with synthetic entry?
    roots = df[df["roll_count"] == 0]
    db_roots = roots[roots["entry_source"] == "db"]
    synth_roots = roots[roots["entry_source"] == "synthetic"]
    print(f"\n  Root chains:")
    print(f"    DB entry:         {len(db_roots)} ({len(db_roots)/len(roots)*100:.1f}%)")
    print(f"    Synthetic entry:  {len(synth_roots)} ({len(synth_roots)/len(roots)*100:.1f}%)")

    # MTM source breakdown
    avg_db_pct = df["mtm_db_pct"].mean()
    median_db_pct = df["mtm_db_pct"].median()
    print(f"\n  MTM source (average % of days using DB data):")
    print(f"    Mean:   {avg_db_pct*100:.1f}%")
    print(f"    Median: {median_db_pct*100:.1f}%")

    # Mixed chains: entry=DB but MTM mostly synthetic
    mixed = df[(df["entry_source"] == "db") & (df["mtm_db_pct"] < 0.5)]
    print(f"\n  Mixed chains (DB entry, <50% DB MTM): {len(mixed)}")

    # Save detailed output
    out_dir = ROOT / "output" / "synthetic_diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "bova11_source_breakdown.parquet")
    print(f"\n  Saved → {out_dir / 'bova11_source_breakdown.parquet'}")

if __name__ == "__main__":
    main()
```

### 2.2 — Run diagnostic

```bash
python scripts/quantify_synthetic_dominance.py
```

### 2.3 — Decision gate

Report the following numbers:

| Metric | Value |
|--------|-------|
| % of entries using real DB | ? |
| % of exits using real DB | ? |
| Avg % of MTM days using real DB | ? |
| DB-entry P&L total | ? |
| Synthetic-entry P&L total | ? |
| DB-entry mean P&L/trade | ? |
| Synthetic-entry mean P&L/trade | ? |

**If >70% of entries use real DB data:** The grid search conclusions are trustworthy. Proceed to Step 3.

**If <50% of entries use real DB data (expected for BOVA11):** The grid search results are dominated by synthetic pricing. You have two options:
- Option A: Fix the synthetic engine's B3 calibration (put_slope, call_slope) to better match DB prices, then re-run. This is calibration work, not data work.
- Option B: Accept the 50% synthetic rate and report all results with the source breakdown as a mandatory caveat. Every grid search cell must include `entry_db_pct`.

**If 50-70% of entries use real DB:** Partially trustworthy. Report source breakdowns; conclusions that hold in both DB and synthetic subsets are robust.

**Time estimate:** 1-2 hours (including script creation and run time)

---

## Step 3 — Verify Sharpe fix produces sane values

**Goal:** Confirm that the daily MTM Sharpe implementation (commit `22600b8`) produces reasonable Sharpe values for the worst v2 grid search configurations.

### 3.1 — Create verification script

Create `scripts/verify_sharpe_fix.py`:

```python
"""Step 3: Verify the daily MTM Sharpe fix produces sane values.

Re-runs the worst PETR4 configuration from the v2 grid search
(target_delta=0.30, dte=45, profit=0.75, manage=14, vol_filter=OFF)
and reports both old-style (P&L-smearing proxy) and new-style Sharpe.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset
from straddle.metrics import compute_metrics

ROOT = Path(__file__).resolve().parent.parent

def run_and_report(market: str, config: dict, label: str):
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params.update(config)
    params["start_date"] = "2020-04-01"
    params["end_date"] = "2025-12-31"

    data = load_market_data(
        start_date=params["start_date"],
        end_date=params["end_date"],
        market=market,
    )

    engine = make_engine(params)
    try:
        trades, equity, skipped, vix_blocked = run_backtest(data, params, engine)
    finally:
        engine.close()

    metrics = compute_metrics(trades, equity, params, data)

    print(f"\n  {label}:")
    print(f"    Trades:       {metrics.get('n', 0)}")
    print(f"    Total P&L:    R${sum(t.pnl for t in trades if t.pnl):+,.2f}")
    print(f"    Win rate:      {metrics.get('wr', 0)*100:.1f}%")
    print(f"    Sharpe:        {metrics.get('sharpe', 'N/A')}")
    print(f"    MDD:           {metrics.get('mdd', 0)*100:.1f}%")
    print(f"    Calmar:        {metrics.get('calmar', 'N/A')}")

    # Verify daily_marks exist and sum correctly
    for t in trades[:3]:  # spot-check first 3 trades
        marks = t.daily_marks
        if marks and len(marks) >= 2:
            daily_deltas = [marks[i][1] - marks[i-1][1] for i in range(1, len(marks))]
            mark_sum = sum(daily_deltas)
            pnl_direct = t.pnl or 0.0
            diff = abs(mark_sum - pnl_direct)
            if diff > 1.0:
                print(f"    WARNING: Trade {t.trade_num} daily_marks sum={mark_sum:.2f}, pnl={pnl_direct:.2f}, diff={diff:.2f}")

    return metrics

def main():
    print("=" * 60)
    print("  Sharpe Verification")
    print("  Testing whether daily MTM Sharpe produces sane values")
    print("=" * 60)

    # v2 configs that showed extreme Sharpe
    configs = {
        "PETR4 worst (d=0.30)": {
            "target_delta": 0.30,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 14,
            "profit_target_pct": 0.75,
            "vol_filter_mode": "off",
            "defensive_leg_roll_enabled": False,
            "mode": "market",
        },
        "BOVA11 best (d=0.30)": {
            "target_delta": 0.30,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 14,
            "profit_target_pct": 0.75,
            "vol_filter_mode": "off",
            "defensive_leg_roll_enabled": False,
            "mode": "market",
        },
        "PETR4 baseline (d=0.16)": {
            "target_delta": 0.16,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 21,
            "profit_target_pct": 0.50,
            "vol_filter_mode": "vix",
            "vix_entry_max": 80.0,
            "mode": "market",
        },
        "BOVA11 baseline (d=0.16)": {
            "target_delta": 0.16,
            "dte_min": 30,
            "dte_max": 45,
            "manage_at_dte": 21,
            "profit_target_pct": 0.50,
            "vol_filter_mode": "vix",
            "vix_entry_max": 50.0,
            "mode": "market",
        },
    }

    results = {}
    for label, config in configs.items():
        market = "petr4" if "PETR4" in label else "bova11"
        results[label] = run_and_report(market, config, label)

    print("\n" + "=" * 60)
    print("  VERIFICATION SUMMARY")
    print("=" * 60)
    print("  Expected: Sharpe values in [-2, +2] range")
    print("  If Sharpe still > |5|, the fix is incomplete.")
    print()
    for label, m in results.items():
        sharpe = m.get("sharpe", "N/A")
        if isinstance(sharpe, float):
            sane = "✓ SANE" if abs(sharpe) < 5 else "✗ EXTREME"
        else:
            sane = "? UNKNOWN"
        print(f"  {label}: Sharpe={sharpe:.2f} {sane}" if isinstance(sharpe, float) else f"  {label}: Sharpe={sharpe} {sane}")

if __name__ == "__main__":
    main()
```

### 3.2 — Run verification

```bash
python scripts/verify_sharpe_fix.py
```

### 3.3 — Hand-verification of daily MTM

Pick one trade from the output (ideally a trade with high P&L that ran for >20 days). Manually verify:

1. The trade has `daily_marks` with entries for each day it was held
2. The sum of daily P&L deltas equals the realized P&L within R$1.00
3. The daily P&L series is not all zeros interspersed with a single large value (which would indicate the old smearing bug)

To do this, add a temporary debug block after the backtest in the script:

```python
# Pick the longest-holding trade for manual verification
if trades:
    longest = max(trades, key=lambda t: len(t.daily_marks) if t.daily_marks else 0)
    print(f"\n  Manual verification — Trade {longest.trade_num}:")
    print(f"    Entry: {longest.entry_date.date()}, Exit: {longest.exit_date.date()}")
    print(f"    P&L (realized): R${longest.pnl:+.2f}")
    if longest.daily_marks and len(longest.daily_marks) > 1:
        deltas = [longest.daily_marks[i][1] - longest.daily_marks[i-1][1]
                   for i in range(1, len(longest.daily_marks))]
        print(f"    P&L (sum of daily deltas): R${sum(deltas):+.2f}")
        print(f"    # of daily marks: {len(longest.daily_marks)}")
        # Check for all-zeros pattern (smearing bug indicator)
        non_zero_days = sum(1 for d in deltas if abs(d) > 0.01)
        print(f"    Non-zero daily deltas: {non_zero_days}/{len(deltas)}")
```

### 3.4 — Decision gate

**If all Sharpe values are in the range [-5, +5]** (ideally [-3, +3]): The fix is verified. Proceed to Step 4.

**If any Sharpe is > |10|**: There's still a bug. Investigate:
- Check `strategy.py` line 997-1013 (the equity curve construction from `daily_marks`)
- Check `metrics.py` line 142-148 (the Sharpe computation from equity curve)
- Verify that `equity_curve` uses `daily_pnl.cumsum()` and not realized P&L spreading

**Time estimate:** 1-2 hours

---

## Step 4 — Wire CDI IVs into the engine

**Goal:** Add a `use_cdi_ivs` flag that makes the engine use `implied_volatility_cdi` and `delta_cdi` columns instead of the flat-12% columns.

### 4.1 — Add config flag to `src/straddle/params.py`

In the `PRICING` dict (line 136), add:

```python
"use_cdi_ivs": False,  # True → use implied_volatility_cdi / delta_cdi columns from rb3 DB
```

### 4.2 — Modify `MarketEngine.__init__()` in `src/straddle/engines.py`

After line 501 (`self._market = market`), add:

```python
self._use_cdi = params.get("use_cdi_ivs", False)
```

And after the `_has_underlying_col` detection (line 508), add CDI column detection:

```python
self._has_cdi_cols = False
if self._use_cdi:
    cdi_cols = {row[1] for row in self._con.execute("PRAGMA table_info(options_data)").fetchall()}
    if "implied_volatility_cdi" in cdi_cols and "delta_cdi" in cdi_cols:
        self._has_cdi_cols = True
        print(f"  MarketEngine: using CDI-based IVs/deltas (daily r)")
    else:
        print(f"  MarketEngine: WARNING — use_cdi_ivs=True but CDI columns not found in DB, falling back to flat-12%")
        self._use_cdi = False
```

### 4.3 — Modify `_best_row()` in `src/straddle/engines.py`

In `_best_row()` (line 737), modify the SQL query to select the appropriate IV/delta column:

Replace the current query (lines 749-763):
```python
cur = self._con.execute(
    f"""
    SELECT strike, mark, bid, ask, delta, implied_volatility, volume
    FROM options_data
    WHERE date = ? AND expiration = ? AND type = ?
      {und_clause}
      AND mark > 0 AND ask >= bid AND volume > 0
      AND delta IS NOT NULL
      {iv_clause}
    ORDER BY ABS(delta - ?) ASC
    LIMIT 1
    """,
    params,
)
```

With:
```python
delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
iv_where = "AND implied_volatility_cdi < 2.0" if (self._use_cdi and self._has_cdi_cols) else iv_clause

cur = self._con.execute(
    f"""
    SELECT strike, mark, bid, ask, {delta_col} AS delta, 
           CASE WHEN {self._use_cdi and self._has_cdi_cols} THEN implied_volatility_cdi ELSE implied_volatility END AS implied_volatility, 
           volume
    FROM options_data
    WHERE date = ? AND expiration = ? AND type = ?
      {und_clause}
      AND mark > 0 AND ask >= bid AND volume > 0
      AND {delta_col} IS NOT NULL
      {iv_where}
    ORDER BY ABS({delta_col} - ?) ASC
    LIMIT 1
    """,
    params,
)
```

**Important:** The `ORDER BY ABS(delta - ?)` must use the same `delta_col` so that strike selection uses CDI-based deltas when the flag is on.

### 4.4 — Modify `get_daily_delta()` in `src/straddle/engines.py`

In `get_daily_delta()` (line 603), modify the SQL query to use the CDI delta column when available:

```python
delta_col_name = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
und_clause, und_val = self._und_filter()
params = [date_str, exp_str, opt, strike]
if und_val is not None:
    params.append(und_val)
cur = self._con.execute(
    f"""SELECT {delta_col_name} AS delta FROM options_data
       WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
       {und_clause} AND mark > 0 LIMIT 1""",
    params,
)
row = cur.fetchone()
if row and row["delta"] is not None:
    return float(row["delta"])
return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
```

### 4.5 — Modify `find_strike_at_delta()` in `src/straddle/engines.py`

In `find_strike_at_delta()` (line 672), modify to use CDI columns:

```python
delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
iv_where = "AND implied_volatility_cdi < 2.0" if (self._use_cdi and self._has_cdi_cols) else iv_clause

params = [date_str, exp_str, opt]
if und_val is not None:
    params.append(und_val)
params.append(signed_target)
cur = self._con.execute(
    f"""SELECT strike, bid FROM options_data
       WHERE date = ? AND expiration = ? AND type = ?
       {und_clause}
       AND mark > 0 AND ask >= bid AND volume > 0
       AND {delta_col} IS NOT NULL {iv_where}
       ORDER BY ABS({delta_col} - ?) ASC LIMIT 1""",
    params,
)
```

### 4.6 — Validate CDI IVs with Phase 1 regression

Create `scripts/validate_cdi_ivs.py`:

```python
"""Step 4.6: Validate CDI IVs produce stable strike selection.

Re-runs the Phase 1 regression with use_cdi_ivs=True and compares
strike selection trade-by-trade against the flat-12% results.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from straddle import PARAMS, load_market_data, make_engine, run_backtest
from straddle.params import apply_market_preset

ROOT = Path(__file__).resolve().parent.parent
START = "2017-01-02"
END = "2025-12-31"

def run_one(market: str, use_cdi: bool, label: str) -> pd.DataFrame:
    params = dict(PARAMS)
    params = apply_market_preset(params, market)
    params["start_date"] = START
    params["end_date"] = END
    params["mode"] = "market"
    params["vix_entry_max"] = 35.0 if market == "bova11" else 80.0
    params["use_cdi_ivs"] = use_cdi

    data = load_market_data(start_date=START, end_date=END, market=market)
    engine = make_engine(params)
    try:
        trades, _, _, _ = run_backtest(data, params, engine)
    finally:
        engine.close()

    rows = []
    for t in trades:
        rows.append({
            "entry_date": t.entry_date,
            "put_strike": t.put_strike,
            "call_strike": t.call_strike,
            "net_credit": t.net_credit,
            "pnl": t.pnl,
            "entry_source": getattr(t, "entry_source", "unknown"),
        })
    df = pd.DataFrame(rows)
    print(f"  [{label}] {len(df)} trades, P&L={df['pnl'].sum():+,.2f}")
    return df


def compare(market: str, df_flat: pd.DataFrame, df_cdi: pd.DataFrame):
    merged = pd.merge(
        df_flat[["entry_date", "put_strike", "call_strike", "net_credit", "pnl"]].rename(
            columns={"put_strike": "put_flat", "call_strike": "call_flat",
                     "net_credit": "credit_flat", "pnl": "pnl_flat"}),
        df_cdi[["entry_date", "put_strike", "call_strike", "net_credit", "pnl"]].rename(
            columns={"put_strike": "put_cdi", "call_strike": "call_cdi",
                     "net_credit": "credit_cdi", "pnl": "pnl_cdi"}),
        on="entry_date", how="inner",
    )

    n = len(merged)
    put_same = (merged["put_flat"] == merged["put_cdi"]).sum()
    call_same = (merged["call_flat"] == merged["call_cdi"]).sum()

    print(f"\n  {market.upper()} — flat-12% vs CDI strike selection:")
    print(f"    Matched trades:             {n}")
    print(f"    Same put strike:            {put_same}/{n} ({put_same/n*100:.1f}%)")
    print(f"    Same call strike:           {call_same}/{n} ({call_same/n*100:.1f}%)")
    print(f"    Both strikes same:          {(merged['put_flat'] == merged['put_cdi']).sum()}/{n}")
    print(f"    Mean put strike diff:        {(merged['put_cdi'] - merged['put_flat']).mean():+.2f}")
    print(f"    Mean call strike diff:       {(merged['call_cdi'] - merged['call_flat']).mean():+.2f}")
    print(f"    P&L delta:                  R${merged['pnl_cdi'].sum() - merged['pnl_flat'].sum():+,.2f}")

    stable_pct = (put_same == n and call_same == n)
    if put_same / n >= 0.95 and call_same / n >= 0.95:
        print(f"    DECISION: ✓ Stable (>95% same strikes) — adopt CDI as default")
    else:
        print(f"    DECISION: ✗ Unstable (<95% same strikes) — investigate before adopting")
    return merged


def main():
    for market in ("bova11", "petr4"):
        print(f"\n{'─'*60}")
        print(f"  {market.upper()}")
        print(f"{'─'*60}")
        df_flat = run_one(market, use_cdi=False, label=f"{market}_flat")
        df_cdi = run_one(market, use_cdi=True, label=f"{market}_cdi")
        compare(market, df_flat, df_cdi)

if __name__ == "__main__":
    main()
```

### 4.7 — Decision gate

**If >95% of trades pick the same strike with CDI vs flat-12%:** Adopt CDI as default. Set `use_cdi_ivs: True` in both B3 presets in `params.py`.

**If <95% of trades pick the same strike:** The CDI rate is changing strike selection meaningfully. Investigate whether the CDI-based strikes are closer to real market delta (they should be). Report the distribution of strike differences. If CDI picks strikes that are closer to real B3 traded strikes (verify manually on a few dates), adopt CDI anyway despite the change.

**Time estimate:** 3-4 hours (including wiring, testing, and regression run)

---

## Step 5 — Calibrate quality tests for B3

**Goal:** Adjust `check_rb3_quality.py` test thresholds for B3 market structure, or mark informational-only tests clearly.

### 5.1 — Update Test I thresholds

In `scripts/check_rb3_quality.py`, modify `test_i_parity()` (line 172):

Change the threshold to be per-underlying:
```python
def test_i_parity(df: pd.DataFrame, label: str) -> dict:
    # BOVA11 is European → 5% threshold is appropriate
    # PETR4 is American → 10% threshold to account for early-exercise premium
    max_violation_pct = 0.05 if label == "bova11" else 0.10
    ...
```

### 5.2 — Update Test J to informational

In `test_j_term_structure()`, add a note and change the status logic:

```python
def test_j_term_structure(df: pd.DataFrame, label: str, max_jump: float = 0.10) -> dict:
    """INFORMATIONAL — B3 single-stock options have legitimate IV jumps at earnings.
    Do not use as a hard gate. Report but do not fail."""
    ...
    return {
        ...
        "informational": True,  # Mark as informational in output
    }
```

In `run_all()`, modify the status logic:
```python
if r.get("informational"):
    status = "INFO"  # Always INFO, never FAIL
else:
    status = "PASS" if pct_v <= TARGET_PCT else "FAIL"
```

### 5.3 — Update Test L threshold

In `test_l_strike_grid()`, lower the minimum for B3:

```python
def test_l_strike_grid(df: pd.DataFrame, label: str, min_strikes: int = 5) -> dict:
    # B3 options are shallow — 3 strikes per expiry is a more realistic floor
    effective_min = 3 if label in ("bova11", "petr4") else min_strikes
    ...
```

### 5.4 — Run updated tests

```bash
python scripts/check_rb3_quality.py
```

Verify that BOVA11 now passes tests I and L, and that PETR4 passes I with the 10% threshold.

**Time estimate:** 30 minutes

---

## Step 6 — Decide on synthetic fallback policy

**Goal:** Based on the findings from Step 2, choose a policy for handling the ~50% synthetic fallback rate and implement it.

### 6.1 — Option analysis

Based on the Phase 1 finding (Phase 1 doc): "Root cause: B3 liquidity. Only ~50% of option-day rows have `bid > 0 AND ask >= bid`." The engine's `_best_row()` method requires `mark > 0 AND ask >= bid AND volume > 0 AND delta IS NOT NULL`, and `get_entry_marks()` requires both put and call rows to match. If either leg has no match, the entire entry falls back to `SyntheticEngine`.

**Option A: Relax `volume > 0` for MTM (not entry) lookups**

Change `_strike_ask()` to not require `volume > 0` when doing daily MTM. This means we accept stale prices for close-cost marking, but we still require volume at entry. Change in `engines.py` line 780:

```python
# Current: AND ask >= bid
# Proposed: AND ask >= bid AND volume > 0  (for entry via _best_row and find_strike_at_delta)
#            AND ask >= bid                (for MTM via _strike_ask — already doesn't require volume)
```

Actually, `_strike_ask()` already doesn't require `volume > 0`. The issue is `_best_row()` and `find_strike_at_delta()` which are used for entry. For MTM, the engine already falls back per-leg to synthetic. So this won't help entry rate.

**Option B: Use `mark` (close price) as mid-price within `_best_row()`**

When `bid > 0` but `ask = 0`, or when `bid = 0` but `ask > 0`, use `mark` as the fill price instead of requiring both sides. This expands the set of valid option rows.

Modify `_best_row()` to accept rows where `mark > 0 AND ((bid > 0 AND ask > 0 AND ask >= bid) OR (mark > 0))` and use `mark` as the fill price when bid/ask are missing.

This is the most impactful change. Implementation:

In `_best_row()`, change the query to:
```sql
SELECT strike, mark, 
       CASE WHEN bid > 0 AND ask > 0 AND ask >= bid THEN bid ELSE mark END AS bid,
       CASE WHEN bid > 0 AND ask > 0 AND ask >= bid THEN ask ELSE mark END AS ask,
       delta, implied_volatility, volume
FROM options_data
WHERE date = ? AND expiration = ? AND type = ?
  {und_clause}
  AND mark > 0 
  AND delta IS NOT NULL
  {iv_clause}
ORDER BY ABS(delta - ?) ASC
LIMIT 1
```

And remove the `volume > 0` requirement for entries. This will significantly increase the DB hit rate but introduces a risk: using close prices instead of bid/ask means the strategy's entry price is less conservative (we'd sell at `mark` rather than `bid`).

**Option C: Accept the ~50% rate and report it as a known limitation**

Don't change the engine. Instead, ensure that every grid search output includes `entry_db_pct` and `mtm_avg_db_pct`. This is the safest approach and requires only the logging from Step 1.

**Recommendation:** Implement Option C (accept and report) as the immediate fix, plus Option B as a future improvement for Phase 5. The risk of using close prices at entry is that the strategy appears more profitable than it really is (close ≈ mid, but actual fills are at bid which is lower).

### 6.2 — Implement Option C (mandatory)

This is already covered by Step 1. Just ensure the grid search output format includes:
```
market: bova11, config: ..., Sharpe: X, P&L: Y, entry_db_pct: 49%, mtm_db_pct: 52%
```

### 6.3 — Document the limitation

Add to `params.py` or a project-level doc:

```python
# NOTE: B3 options have ~50% bid/ask coverage at target delta. When DB data
# is unavailable, the engine falls back to SyntheticEngine (BSM + parametric
# skew). This means approximately half of trade entries are priced by the
# synthetic model. Grid search results should always be reported with
# entry_db_pct to indicate how much real market data was used.
```

**Time estimate:** 1 hour (mainly documentation)

---

## Step 7 — Run the definitive grid search prerequisites checklist

After completing Steps 1-6, verify all prerequisites are met before running the definitive grid search:

### 7.1 — Checklist

| # | Prerequisite | Verified by | Status |
|---|-------------|-------------|--------|
| 1 | Sharpe values in [-5, +5] for all test configs | Step 3 verification script | ☐ |
| 2 | CDI IVs produce >95% same strikes as flat-12% | Step 4 validation script | ☐ |
| 3 | Source tracking (entry_source, mtm_db_pct) in all trade outputs | Step 1 code changes | ☐ |
| 4 | entry_db_pct reported for BOVA11 and PETR4 | Step 2 diagnostic | ☐ |
| 5 | Quality tests calibrated for B3 | Step 5 threshold updates | ☐ |
| 6 | Daily CDI rate wired in (if Step 4.7 passes) | params.py use_cdi_ivs | ☐ |
| 7 | rb3 data has no R$500k corruption | Test M (already passing) | ☐ |
| 8 | B3-native vol filter implemented | Already in params.py (rv_pct, ivr modes) | ☐ |

### 7.2 — Grid search configuration

The definitive grid search should use:

```python
PARAMS_GRID = {
    "target_delta": [0.16, 0.20, 0.25, 0.30],
    "dte_min": [30],
    "dte_max": [45, 60],
    "profit_target_pct": [0.50, 0.75],
    "manage_at_dte": [14, 21],
    "vol_filter_mode": ["off", "ivr"],  # B3-native
    "vol_filter_threshold": [0.25, 0.50],  # for ivr mode
    "defensive_leg_roll_enabled": [False],  # confirmed to hurt on B3
    "use_cdi_ivs": [True],  # if Step 4.7 passes
    "single_position": [True],
}
```

Train/holdout split:
- Train: 2020-04-01 to 2023-12-31 (post-COVID, avoids crisis skew)
- Holdout: 2024-01-01 to 2025-12-31

Markets: BOVA11 only (PETR4 is conclusively negative across all configurations).

Minimum trade filter: `n_chains >= 50` (not `n_trades >= 100`, since chains count multi-roll positions, not individual rolls).

Each grid point must output: Sharpe, total P&L, win rate, max drawdown, Calmar, **entry_db_pct**, **mtm_avg_db_pct**.

**Time estimate:** Running the grid is separate from this plan (1-2 days of compute), but configuration takes 1-2 hours.

---

## Timeline

| Step | Task | Est. time | Depends on |
|------|------|-----------|------------|
| 1 | Add source tracking to strategy.py + metrics.py | 2-3h | None |
| 2 | Quantify synthetic dominance (run diagnostic) | 1-2h | Step 1 |
| 3 | Verify Sharpe fix produces sane values | 1-2h | None |
| 4 | Wire CDI IVs into engine + validate | 3-4h | None |
| 5 | Calibrate quality tests for B3 | 30min | None |
| 6 | Document synthetic fallback policy | 1h | Step 2 |
| 7 | Prerequisites checklist + grid config | 1-2h | Steps 1-6 |

**Total estimated time:** 10-14 hours

Steps 1, 3, 4, and 5 can be done in parallel by the coding agent. Step 2 depends on Step 1. Step 6 depends on Step 2. Step 7 depends on all previous steps.

---

## Files to create/modify

### New files
| File | Purpose |
|------|---------|
| `scripts/quantify_synthetic_dominance.py` | Step 2: BOVA11 source breakdown diagnostic |
| `scripts/verify_sharpe_fix.py` | Step 3: Sharpe sanity verification |
| `scripts/validate_cdi_ivs.py` | Step 4.6: CDI vs flat-12% strike comparison |

### Modified files
| File | Changes |
|------|---------|
| `src/straddle/strategy.py` | Add `entry_source`, `exit_source`, `mtm_source_days`, `mtm_total_days` to Trade dataclass; track sources in `evaluate_trade_step()` and `build_entry()` |
| `src/straddle/engines.py` | Add `use_cdi_ivs` flag; modify `_best_row()`, `get_daily_delta()`, `find_strike_at_delta()` to use `delta_cdi`/`implied_volatility_cdi` when flag is set; add `_source_for_strike()` helper |
| `src/straddle/params.py` | Add `use_cdi_ivs: False` to PRICING dict |
| `src/straddle/metrics.py` | Add source tracking stats to `compute_metrics()` |
| `scripts/check_rb3_quality.py` | Adjust Test I threshold (PETR4 → 10%), mark Test J as informational, lower Test L min_strikes to 3 for B3 |
| `scripts/phase1_regression.py` | Add source columns to `trades_to_df()` |

### Documentation
| File | Content |
|------|---------|
| `docs/2026-05-12 2145 - Pre-grid-search validation plan.md` | This plan |
| `docs/2026-05-XX - Synthetic dominance analysis.md` | Step 2 output |
| `docs/2026-05-XX - Sharpe verification.md` | Step 3 output |
| `docs/2026-05-XX - CDI IV validation.md` | Step 4 output |

---

## Key risks and mitigations

1. **CDI columns not populated for all rows**: ~10% of DB rows have `NULL` for `implied_volatility_cdi` / `delta_cdi` (deep OTM/ITM where BSM didn't converge). The engine must fall back to the flat-12% columns for these rows. In `_best_row()`, add: `AND (delta_cdi IS NOT NULL OR NOT ?)` where the param is `self._use_cdi`.

2. **Source tracking overhead**: Adding `_source_for_strike()` calls in the daily loop may slow backtests. If performance is an issue, pre-compute a set of (date, expiration, strike, type) tuples that have valid DB data at initialization time, then check membership in O(1) during the loop.

3. **Sharpe still extreme after fix**: If Step 3 shows extreme Sharpe values, investigate `strategy.py` lines 997-1013. The `daily_pnl` computation sums deltas across all trades for each day. If multiple overlapping trades produce P&L on the same day, the daily P&L may be dominated by a few large events. This is expected for a short strangle strategy (most days near zero, rare large losses). In this case, the Sharpe may legitimately be negative — the question is whether it's -5 (realistic) or -20 (bug).

4. **Grid search runtime**: BOVA11-only grid with ~4 × 2 × 2 × 2 × 2 × 2 × 1 = 64 configurations × 2 (train + holdout) = 128 backtests. Market mode backtests take ~5-10 minutes each (DB queries). Total: ~10-20 hours. Consider parallelizing across 4 cores.