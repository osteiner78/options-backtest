# Phase 2 Complete — DTE30 Deep-Dive Analysis Notebook

**Date:** 2026-05-18 | **Plan:** 023 — dte30_cooldown_deep_dive

## What was built

`research/2026-05-18 - B3 - dte30 deep dive.ipynb` — executed notebook (495KB) with:
- **Cell A:** IR heatmap — manage_at_dte × cooldown (two heatmaps per pt)
- **Cell B:** IR vs cooldown by mgr (holdout solid + train dashed); mgr=5 excluded
- **Cell C:** Profit target comparison (boxplots)
- **Cell D:** Train vs holdout stability scatter
- **Cell E:** IR–BPR frontier with dte21 Plan 022 overlay
- **Cell F:** BPR utilization × manage_at_dte
- **Summary:** Top 10 stability-ranked configs + pivot table

## Test results

```
129 passed in 1.79s
```
Notebook: 8 code cells executed, 0 errors.

## Key findings

| Question | Answer |
|----------|--------|
| Q1: Optimal mgr for dte30/25Δ? | **14** — consistently beats mgr=7 |
| Q2: pt=25% vs 50%? | **50%** dominates |
| Q3: dte30/cd=7 robust? | **No** — IR_train=0.44 vs IR_holdout=1.45 |
| Q4: Any dte30 beats dte21 frontier? | **No** — higher BPR, lower IR |
| Q5: Calendar saturation? | **No** — dte30 continues scaling to cd=1 |

## Deviations from plan

- mgr=5 dropped from Cell B and summary (deviation allowance: consistently IR < 0.8)
- Phase 3 not triggered (no config meets min_IR > 1.20 AND n_trades >= 80)

## Confidence: certain
