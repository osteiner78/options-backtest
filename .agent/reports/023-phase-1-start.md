# Phase 1 Start — DTE30 Cooldown Deep-Dive

**Date:** 2026-05-18 | **Plan:** 023 — dte30_cooldown_deep_dive

## Scope

Create `scripts/run_dte30_deep_dive.py` — extends Plan 022's `run_cooldown_sensitivity.py`
with `manage_at_dte` and `profit_target_pct` dimensions. Fixed base: 25Δ/dte30/OFF/stop2.0/mid/laddering.
5 cooldowns × 3 manage_dte × 2 profit_targets × 2 periods = 60 backtests.

## Pre-work observations

- Same two code-quality fixes from Plan 022 apply: `apply_market_preset` return value
  capture and `engine = None` initialization before try block.
- `dte_max=30, dte_min=20` is hardcoded in BASE (dte30 is the only focus market).
- The script structure mirrors `run_cooldown_sensitivity.py` with 2 extra grid dimensions.
- BPR metrics already return as percentages (0-100) from `compute_portfolio_metrics`.
- Expected runtime: ~10-15 minutes for 60 backtests (dte30 positions run longer than dte21).
- Phase 3 has a conditional trigger: only run if any config achieves
  `min(IR_train, IR_holdout) > 1.20` AND `n_trades >= 80`. Will evaluate after Phase 2.

## Confidence: certain
