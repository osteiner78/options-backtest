# Phase 2 Complete — Cooldown Sensitivity Analysis Notebook

**Date:** 2026-05-18 | **Plan:** 022 — entry_cooldown_sensitivity

## What was built

`research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb` — self-contained analysis notebook with:
- **Cell A:** IR vs entry_cooldown chart + stability table (15 rows: dte_max × cooldown pairs with train/holdout IR)
- **Cell B:** n_trades vs cooldown (trade frequency scaling)
- **Cell C:** avg_bpr_util vs cooldown (capital efficiency chart)
- **Cell D:** IR–BPR Frontier scatter + Pareto frontier line (key decision chart)
- **Cell E:** max_drawdown vs cooldown (tail risk)
- **Cell F:** avg/peak positions vs cooldown (concurrency)
- **Cell G:** Train vs holdout stability scatter + overfitting gap analysis
- **Summary table:** 15 configs sorted by IR descending + cross-tab pivots

## Test results

```
129 passed in 1.80s
```

Notebook executed via `jupyter nbconvert --execute` — all 9 code cells rendered without errors (735KB output).

## Key findings

| Finding | Details |
|---------|---------|
| **H1 (IR peaks at cd=3 for dte21)** | Mixed — IR peaks at cd=5/7 (1.78) but those have only 71 trades vs 135 at cd=3 (IR=1.43) |
| **H2 (Lower cd benefits dte30/45)** | Partially confirmed — dte30/cd=7 hits IR=1.45 with 24.4% BPR |
| **H3 (BPR cap binds)** | Confirmed — dte45/cd=1 avg BPR=77.7%, well above 30% cap |
| **H4 (MDD insensitive to cooldown)** | Partially — dte45 shows sensitivity (−8.3% to −2.4%) |
| **Train/holdout gap** | Higher cooldowns show *more* overfitting (cd=7: −0.67 gap vs cd=1: −0.33) |

## Deviations from plan

None beyond what was already noted in Phase 1. All cells A-G implemented as specified.

## Follow-ups

- Recommend targeted deep-dive: dte30 × cooldown ∈ {1, 3, 7} × manage_at_dte ∈ {7, 14} (6 backtests)

## Confidence: certain
