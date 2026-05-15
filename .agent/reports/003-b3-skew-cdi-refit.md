# 003 — B3 Skew Parameters Re-fitted Against rb3 DB

**Status:** resolved

## Symptom

The B3 skew parameters (`put_slope` / `call_slope`) in `MARKET_PRESETS` were fitted on the
old `b3_options.db` which contained known corruption (R$500k marks). The Step 2 diagnostic
found that synthetic engine trades produce materially different P&L than DB-data trades,
suggesting the synthetic skew model was mis-calibrated.

## Root Cause

The skew parameters were fitted by `scripts/fit_b3_skew.py` against the old DB. The
script used the flat-12% IV and delta columns. After migrating to `b3_options_rb3.db` with
CDI-based IVs and deltas, the parameters were never re-fitted.

## Fix Applied

1. **`scripts/fit_b3_skew.py`:**
   - Changed `DB_PATH` to `data/B3/b3_options_rb3.db`
   - Changed SQL to use `delta_cdi` and `implied_volatility_cdi` (CDI-based)

2. **Re-ran `python scripts/fit_b3_skew.py --no-plot`:**

   | Market | Old put | Old call | New put | New call | Change |
   |--------|---------|----------|---------|----------|--------|
   | BOVA11 | 0.743   | 0.031    | 0.746   | 0.074    | call_slope 2.4× |
   | PETR4  | 0.523   | -0.057   | 0.522   | -0.046   | call_slope 0.8× |

   Key change: BOVA11 `call_slope` more than doubled (0.031 → 0.074).
   At 16Δ, call IV multiplier: 0.9895 → 0.9748 (calls priced ~1.5% lower).

3. **`src/straddle/params.py`:** Updated `MARKET_PRESETS["bova11"]` and `["petr4"]`
   with new values and updated documentation comments.

## Verification

- All 90 tests pass
- The new fit uses CDI-based deltas/IVs, matching the engine's `use_cdi_ivs` logic

## Follow-up

The `call_slope` for BOVA11 shows a structural shift: positive in 2019–2023,
near-zero or slightly negative in 2024–2025. Consider using a trailing-window fit
for production trading.
