# Plan 016 — All Phases End Report

**Date:** 2026-05-15  
**Branch:** b3-backtest

---

## What Was Built

**Phase 1 — Measurement:**  
`scripts/measure_sharpe_impact.py` runs 6 key configs (4 BOVA11 + 2 PETR4) with the
fixed code and reports old vs new Sharpe. Results:

| Config | Period | Old Sharpe | New Sharpe | Δ |
|--------|--------|-----------|-----------|---|
| 25Δ BOVA11 | train | 0.908 | 0.904 | −0.004 |
| 25Δ BOVA11 | holdout | 1.292 | 1.328 | +0.036 |
| 16Δ BOVA11 | holdout | 1.883 | 1.925 | +0.042 |
| 12Δ BOVA11 | holdout | 11.557 | 11.485 | −0.073 |
| 25Δ PETR4 | train | 0.613 | 0.621 | +0.008 |
| 25Δ PETR4 | holdout | 1.211 | 1.213 | +0.001 |

Max |ΔSharpe| = **0.073**.

**Phase 2 — Decision:**  
0.073 < 0.15 threshold → **do NOT re-run full grid**. Fix is immaterial for conclusions.

**Phase 3 — Skipped** (not triggered by Phase 2 decision gate).

**Phase 4 — Report updates:**  
- `016 - v7 final confirmation results.md`: §1 Key numbers (1.29→1.33), §5 Cell A note
  with full ΔSharpe table, §6 commission table baseline corrected, §9 Sharpe updated,
  §10 new section documenting I-2/I-6/I-10 bug fixes.
- `017 - post-v7 follow-up results.md`: §2.1 holdout Sharpe (1.883→1.925), §2.4 comparison
  table updated, §2.5 baseline corrected, §4.2 PETR4 recommended Sharpe updated, summary
  table row added for I-10 fix.

**Phase 5 — Verification:**  
- 3-config spot-check via `scripts/spot_check_sharpe.py`: max |Δ|=0.026, all PASS.
- `pytest tests/ -v`: **129/129 passed** (1.86s).
- Parquet files are git-tracked with pre-fix values — documented in reports; acceptable
  since Phase 2 decision was not to re-run.

---

## Test Results

```
============================= 129 passed in 1.86s ==============================
```

Spot-check output:
```
25Δ/dte21/pt50%/rv90/stop3/mid holdout      0.775   0.802  +0.026
16Δ/dte60/pt50%/OFF/stop2/mid holdout       0.279   0.301  +0.022
20Δ/dte30/pt50%/rv80/stop3/mid holdout     -0.496  -0.501  -0.005
PASS — all spot-checks within 0.15 Δ threshold.
```

---

## Deviations from Plan

- Phase 3, 4.3, 4.4 skipped (Phase 2 gate not triggered) — expected.
- 16Δ BOVA11 *train* Sharpe not re-measured (plan only specified holdout for Step 1.2).
  Parquet value (0.593) left in §2.1 of 017 report for the train row.
- Commission sensitivity 2×/3× rows in §6 not re-run; only the baseline was updated.
  Both are documented with footnotes.

---

## Confidence Rating: **certain**

- I-10 fix confirmed applied in code (diff verified against commit 1db7e66)
- All 9 measured configs show |ΔSharpe| well under the 0.15 threshold
- 129 tests pass
- Directional VRP conclusion unchanged
