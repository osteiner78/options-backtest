# Phase 3 End — v7 Refined Grid Complete

**Date:** 2026-05-15
**Commit:** 06c71d2 `[phase-3] v7 refined grid — 5376 backtests, 0 errors`

---

## What Was Built

- **`scripts/run_v7_grid.py`** — standalone runner for the v7 grid definition
- **`scripts/grid_search.py`** — updated to call `clear_vol_cache()` at start of `run_grid()`
- **`research/2026-05-15 - B3 - v7 refined grid.ipynb`** — analysis notebook with cells A–K
- **`data/B3/v7_grid_search_results.parquet`** — 5376 rows, 0 errors

## Grid Summary

| Dimension | v6 values | v7 values | Reason for change |
|-----------|-----------|-----------|-------------------|
| target_delta | 0.12–0.50 (6) | 0.12–0.25 (4) | Dropped 30Δ, 50Δ (poor) |
| dte_max | 21/30/45/60 (4) | 21/30/45/60 (4) | No change |
| profit_target_pct | 0.25/0.50/0.75 (3) | 0.25/0.50 (2) | Dropped 0.75 (low diff) |
| manage_at_dte | 5/7/14/21 (4) | 5/7/14/21 (4) | No change |
| vix_filter | OFF/rv70/80/90 (4) | OFF/rv70/80/90 (4) | No change |
| defensive_leg_roll | True/False (2) | False only (1) | ΔSharpe ±0.03 |
| stop_loss_pct | 2.0/3.0 (2) | 2.0/3.0 (2) | No change |
| execution_mode | bid_ask/mid/mid+1t (3) | same (3) | No change |
| portfolio_mode | laddering (1) | laddering (1) | No change |

**2688 valid combos × 2 periods = 5376 total runs. 0 errors, 0 invalid.**

---

## Key Results

### Cell A — Sharpe by Execution Mode

| Period | bid_ask | mid | mid_plus_1tick |
|--------|---------|-----|----------------|
| Train | 0.0% positive | 66.5% positive | 85.7% positive |
| Holdout | 3.6% positive | **86.3% positive** | **98.8% positive** |

Train medians: bid_ask=-1.24, mid=0.13, mid+1tick=0.48
Holdout medians: bid_ask=-0.99, mid=0.44, mid+1tick=1.45

**bid_ask is unviable.** Bid/ask spreads for BOVA11 options (avg 25–40% of mark depending on delta) consume the premium.

### Cell B — Break-even Execution Level (holdout)

| Level | Count | % |
|-------|-------|---|
| mid (viable there) | 741 | 82.7% |
| bid_ask (viable) | 32 | 3.6% |
| mid_plus_1tick only | 112 | 12.5% |
| none viable | 11 | 1.2% |

**86.3% of configs viable at mid or better.** 12.5% require mid+1tick fills (execution-sensitive, mainly 12δ configs).

### Cell C — Delta × Mode (holdout median Sharpe)

| delta | bid_ask | mid | mid_plus_1tick |
|-------|---------|-----|----------------|
| 12δ | -1.61 | 0.37 | **2.24** |
| 16δ | -1.06 | 0.36 | **1.44** |
| 20δ | -0.77 | **0.49** | 1.48 |
| 25δ | -0.67 | **0.50** | 1.12 |

12δ dominates at mid+1tick but is execution-sensitive (see Phase 2). 25δ is best at mid with tightest spreads.

### Cell D — DTE × Delta (holdout, all modes median)

DTE=30 is best for 12δ/16δ. DTE=45/60 better for 20δ/25δ. Short DTE (21) competitive for larger deltas.

### Cell E — Profit Target

0.25 profit target: better for mid+1tick (1.85 vs 1.14)
0.50 profit target: better for mid (0.53 vs 0.28)

### Cell F — Vol Filter (holdout, mid+1tick)

All filters cluster tightly (medians 1.38–1.48 Sharpe). rv_pct:90 marginally best. OFF slightly worse. Filter adds limited value but doesn't hurt.

### Cell G — Stop Loss

2.0× slightly better than 3.0× at mid (0.47 vs 0.42).

### Cell H — Train/Holdout Correlation

| Mode | Corr | Both positive |
|------|------|--------------|
| bid_ask | 0.629 | 0.0% |
| mid | -0.275 | **54.1%** |
| mid_plus_1tick | 0.318 | **84.5%** |

mid has surprisingly low train/holdout correlation but a reasonable 54% of configs positive in both. mid+1tick is more stable at 84.5%.

### Cell I — DB Coverage

| Period | bid_ask entry_db% | mid entry_db% |
|--------|------------------|---------------|
| train | 48.6% | 81.4% |
| holdout | 96.5% | 99.2% |

Holdout is almost entirely DB-priced. Train has ~50% synthetic for bid_ask (only enters when bid>0). **These values now correctly display as percentages (0–100) after Phase 1 fix.**

### Cell K — Top 15 Stability (mid, practical)

Top 3 by `min(train, holdout)` at mid:
1. **12δ, dte30, pt25%, manage=7, rv_pct:70, sl=2.0** → min=1.10, avg=1.16
2. **12δ, dte30, pt25%, manage=5, rv_pct:70, sl=2.0** → min=1.08, avg=1.15
3. **12δ, dte30, pt50%, manage=7, rv_pct:70, sl=2.0** → min=0.97, avg=1.02

Top liquid configs (25δ/20δ, viable at bid_ask too):
4. **25δ, dte21, pt50%, manage=14, OFF, sl=2.0** → min=0.91
5. **25δ, dte21, pt50%, manage=7, rv_pct:80, sl=2.0** → min=0.88
6. **20δ, dte21, pt50%, manage=7, OFF, sl=2.0** → min=0.88

---

## Deviations from Plan

None. Grid dimensions match plan exactly. Combo count (2688 valid) was slightly higher than planned estimate (~2300) because the validity filter dropped fewer combos than anticipated.

---

## Follow-ups for Phase 4+

- Phase 4 (commission sensitivity): use top 5 by `min_sharpe` at mid as the base configs
- Phase 5 (10-trade verification): select from best mid config (25δ/dte21/pt50%)
- Phase 6 (period robustness): use top 15 by min_sharpe at mid for the 225 backtests
- The 12δ configs lead the stability table but are execution-sensitive — Phase 6 should include them to check if the Sharpe holds across 5 rolling 3-year windows

---

## Confidence Rating: **certain**

5376/5376 runs completed, 0 errors. Results are deterministic (no randomness in the engine). The main caveat is that ~50% of train entries are synthetic for bid_ask mode — flagged in Cell I.
