# Phase 1 Start — Entry Cooldown Sensitivity Script

**Date:** 2026-05-18 | **Plan:** 022 — entry_cooldown_sensitivity

## Scope

Create `scripts/run_cooldown_sensitivity.py` — a standalone grid runner for
5 cooldown values × 3 DTE windows × 2 periods = 30 backtests against BOVA11
market data. Fixed base: 25Δ/pt50%/manage14/OFF/stop2.0/mid/laddering.

## Pre-work observations

- `compute_portfolio_metrics` already returns `avg_bpr_util` and `peak_bpr_util`
  as percentages (0-100) at `src/straddle/metrics.py:442-449`. No conversion needed.
- `apply_market_preset` returns a new dict (doesn't mutate). The plan pseudocode
  doesn't capture the return value — will fix during implementation.
- `engine` variable in the plan's finally block needs `None` initialization
  to avoid `NameError` on failure. Will add this.
- All imports in the plan pseudocode resolve correctly from `straddle/__init__.py`.
- No engine changes required — purely additive script + data.

## Confidence: certain
