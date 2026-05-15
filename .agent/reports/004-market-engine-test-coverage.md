# 004 — No Test Coverage for MarketEngine / B3 Paths

**Status:** resolved

## Symptom

The test suite (85 tests) only tested `SyntheticEngine` with SPY parameters. There was
zero coverage for:
- `MarketEngine` entry/exit marks (with DB queries)
- B3 market presets (`bova11`, `petr4`)
- Synthetic fallback with fill adjustment
- Per-leg source tracking via `get_leg_mark_with_source`

## Fix Applied

Added `TestMarketEngineFillAdj` class to `tests/test_engines.py` with 5 new tests:

| Test | What it verifies |
|------|-----------------|
| `test_db_marks_unchanged_by_adj` | DB marks returned directly, no fill adj applied |
| `test_synthetic_fallback_close_adj` | Synthetic fallback (buy) gets `apply_fill_adj(..., "close")` |
| `test_synthetic_fallback_open_adj` | Synthetic fallback (sell) gets `apply_fill_adj(..., "open")` |
| `test_entry_synthetic_fallback_adj` | Entry synthetic fallback gets adjusted combined credit |
| `test_apply_fill_adj_noop` | `MarketEngine.apply_fill_adj` is a no-op (design intent) |

Tests connect to the real rb3 DB. If the DB is unavailable, tests are skipped with
`pytest.skip`. Synthetic fallback is forced by using pre-2008 dates.

## Verification

All 5 tests pass. Total test count: 85 → 90.
