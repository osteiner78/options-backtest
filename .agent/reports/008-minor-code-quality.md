# 008 — Minor Code Quality: Single-Position Gate, Comments

**Status:** resolved

## Issues Addressed

### 8.1 — Single-position gate allows same-day entry after exit
**Symptom:** `strategy.py:960` used `entry_date < latest_open_exit` (strict less-than).
If a trade chain exited on date D and the next monthly entry date was also D, the gate
would allow a new position on the same day — technically opening at the same EOD
prices used to close the prior position.

**Fix:** Changed to `entry_date <= latest_open_exit`. In practice, monthly 3rd-Friday
entries rarely coincide with exit dates, but the `<=` guard is semantically correct.

### 8.2 — Gap open mark vix round-trip
**Finding:** No actual bug. The `get_gap_open_mark` uses `vix_prev_raw` (decimal) directly
to compute sigma without a `/100 * 100` round-trip. The sigma computation is:
```
vix_open_sigma = vix_prev_raw * (1 + gap_mult * gap_pct) * vix_iv_mult
```
This is equivalent to the normal path but computed inline. No redundant operations.

### 8.3 — Expiry fallback uses closing price
**Finding:** Acceptable. The `evaluate_trade` fallback expiry path uses the last trading
day's close for intrinsic value. Since BVMF calendar adjustment ensures expiration falls
on a trading day, the close IS the settlement price. If expiration were ever on a
non-trading day, the last close is a reasonable proxy.

## Files Changed
- `strategy.py:960`: `entry_date < latest_open_exit` → `entry_date <= latest_open_exit`

## Verification
- All 90 tests pass
