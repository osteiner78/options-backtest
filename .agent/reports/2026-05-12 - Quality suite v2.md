# Phase 4 — Quality Test Suite v2

**Date:** 2026-05-12  
**Status:** Complete — 4 new tests added, B3-appropriate thresholds noted for 3 of them

---

## New tests added to `scripts/check_rb3_quality.py`

| Test | Description | BOVA11 | PETR4 |
|------|-------------|--------|-------|
| I: Put-call parity | C − P ≈ S − K·e^(−rT) within 5% of S | 0.58% | 5.83% |
| J: Term structure | IV jumps between adjacent expirations > 10 vol pts | 2.35% | 9.37% |
| L: Strike grid | Expiry-dates with <5 strikes | 43.89% | 43.17% |
| M: Corruption regression | Close > R$1000 (old DB had R$500k rows) | 0 (PASS) | 0 (PASS) |

## Analysis of "failures"

### Test I — Put-call parity (BOVA11 0.58%, PETR4 5.83%)

The median parity violation is tiny: 0.24% of underlying for BOVA11, 0.43% for PETR4. The 5% threshold catches tail cases dominated by:

- **PETR4 American options:** Put-call parity is a European relationship. PETR4 single-stock options have early-exercise premium (especially puts at Brazil's 12-15% interest rates). A 5% threshold is too tight for American options.
- **Deep ITM/OTM options:** Where bid-ask spreads are wide relative to close price
- **Low-liquidity strikes:** Where close price may be stale

The 5% threshold should be raised to 10% for PETR4 or the test should be skipped for American options.

### Test J — Term structure (BOVA11 2.35%, PETR4 9.37%)

IV jumps >10 vol pts between adjacent expirations are expected for:
- Single-stock options around earnings/events (PETR4 has volatile earnings)
- Crisis periods (COVID 2020, election 2022)
- Low-liquidity expirations

The 10 vol pt threshold is calibrated for SPY/liquid ETFs. For B3 single stocks, this is too strict. This test is useful as an informational indicator but should not be a hard gate.

### Test L — Strike grid (43% with <5 strikes)

B3 options are shallow. Many expirations have only 1-3 strikes. This is a market structure fact, not a data quality issue. The `min_strikes=5` threshold should be lowered to 3 for B3.

### Test M — Corruption regression (PASS)

Clean pass. The old corruption pattern (R$500k prices on R$3 options) is confirmed absent from rb3 data. This is the most important test — it validates the core reason for the migration.

## CI Integration

`--strict` flag added to `check_rb3_quality.py`:

```bash
python scripts/check_rb3_quality.py --strict  # exits 1 if any test fails
```

No Makefile was created (project uses setup.py/pyproject.toml, not make). The check can be invoked directly or added to a CI script.

## Files modified

| File | Change |
|------|--------|
| `scripts/check_rb3_quality.py` | Added tests I, J, L, M + `--strict` flag (7 → 11 tests) |
