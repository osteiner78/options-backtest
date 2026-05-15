# 007 — Gap VIX Multiplier Not Calibrated for B3

**Status:** resolved (parameterized, awaiting calibration data)

## Symptom

The `gap_vix_multiplier` parameter (used in stop-loss GAP regime pricing) was set to
3.0 globally in `OVERSHOOT`, calibrated for S&P 500 / VIX relationship. B3 single-stocks
and ETFs may exhibit different gap/vol dynamics (political shocks, BRL/USD moves, oil
price events), but the parameter was not exposed in the per-market presets.

## Root Cause

The parameter was defined only in the global `OVERSHOOT` dict (`params.py:163`).
`MARKET_PRESETS["bova11"]` and `["petr4"]` did not override it.

## Fix Applied

Added `gap_vix_multiplier` to both B3 presets in `params.py` with SPY default (3.0)
and TODO calibration notes:

```python
# BOVA11:
"gap_vix_multiplier": 3.0,  # TODO: calibrate against B3 intraday gap data

# PETR4:
"gap_vix_multiplier": 3.0,  # TODO: calibrate against B3 intraday gap data
```

## Impact Assessment

- Only affects the GAP regime in stop-loss overshoot model
- Triggered only when `use_price_stop=True` and a gap day breaches the stop
- Default `use_price_stop=False` → this path is rarely hit
- The multiplier can now be overridden per market when calibration data is available

## Verification

- All 90 tests pass
- `apply_market_preset` correctly propagates the per-market value
