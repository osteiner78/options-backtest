# Plan 015 — Phase 1 End Report: Force-close P&L Materiality

**Date:** 2026-05-15  
**Commit:** 3356b96

## What Was Built

Ran the recommended 25Δ/dte21/pt50%/mid/laddering BOVA11 config for the full holdout period (2023-01-02 to 2025-11-30) to count force-closed trades and assess whether the Phase 5 P&L fix materially affected v7 grid results.

## Test Results

```
Total trades:          134
Force-closed trades:   1 (0.7%)   [threshold: 5%]
Total P&L:             R$3732.27
Force-close P&L:       R$29.00 (0.8% of total |P&L|)   [threshold: 2%]
```

**Force-close detail:**
- 1 trade: entry=2025-11-07, exit=2025-11-28, pnl=R$29.00, net_credit=R$204.00

**Exit type distribution:**
- ROLLED: 67 (50.0%)
- PROFIT: 48 (35.8%)
- 21DTE: 18 (13.4%)
- FORCE_CLOSE: 1 (0.7%)

## Decision Gate

PASS — Both thresholds satisfied:
- Force-closed trades: 0.7% < 5% threshold
- P&L contribution: 0.8% < 2% threshold

**No re-run of v7 grid needed.** The force-close P&L fix committed in Phase 5 (7aa889e) has negligible impact on the v7 grid results since force-closed trades represent <1% of trades and <1% of P&L in the recommended config.

## Notes

- Bug: plan pseudocode omitted `dte_min`. Fixed by setting `dte_min=15` per `DTE_MIN_BY_DTE_MAX[21]` in grid_search.py.
- Running env: requires conda `backtest` env with `python3.11` (not system python3 which lacks pandas).

## Confidence

**Certain** — Single-run assessment, decision gate is unambiguous.
