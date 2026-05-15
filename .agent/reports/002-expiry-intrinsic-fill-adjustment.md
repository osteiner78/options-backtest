# 002 — Fill Adjustment Incorrectly Applied to Intrinsic Value at Expiry

**Status:** resolved

## Symptom

In synthetic mode (and synthetic-fallback in market mode), the close-cost at expiry
includes a 5% fill adjustment on intrinsic value. At expiry, options are fungible
with the underlying — the bid-ask spread collapses and intrinsic value IS the fair
price. Applying `apply_fill_adj(intr, "close")` adds 5% to intrinsic, effectively
adding $0.20/share (= $20/contract) of phantom transaction cost.

## Root Cause

Two code paths apply `apply_fill_adj()` without checking whether the trade is at expiration:

1. **`evaluate_trade_step` (strategy.py:641-648):** `close_cost = engine.apply_fill_adj(mid_d, "close") * mult + comm`.
   When `eval_date >= expiration` and `dte_rem == 0`, `mid_d` is close to intrinsic.

2. **`evaluate_trade` fallback expiry (strategy.py:908):** `cc = engine.apply_fill_adj(intr, "close") * mult + comm`.
   This explicitly prices at intrinsic, then adds fill adj.

## Fix Applied (strategy.py)

1. **`evaluate_trade_step`:** Added `if dte_rem > 0:` guard around both the iron condor
   and strangle close-cost formulas. At expiry, close cost uses raw mid (no adj).

2. **`evaluate_trade` fallback:** Removed `apply_fill_adj` from intrinsic close cost.
   `cc = intr * mult + n_comm * comm`.

## Verification

- All 90 tests pass
- Manual check: intrinsic=4.0 → old close_cost=422.00, new=402.00 (diff=$20 removed)
- In practice, this only affects trades that expire ITM (rare with manage_at_dte=21)
