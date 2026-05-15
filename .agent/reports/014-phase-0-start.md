# Phase 0 Start — Bug Fixes

**Date:** 2026-05-15
**Plan:** 014 — v7 Final Validation & Refined Grid
**Scope:** Fix all 11 bugs + 6 suggestions from code-review report 015

## Understanding of Scope

Phase 0 addresses correctness bugs found in the full codebase review. The two highest-priority fixes (#1 and #2) directly affect grid search results: the `id(data)` cache key can silently return wrong vol-filter results across consecutive backtests, and the force-close double-call corrupts MTM equity calculations. All other fixes are correctness/safety improvements that don't change backtest results under normal single-run usage.

Baseline: 107 tests pass (confirmed via `pytest tests/ -v`).

## Pre-work Observations

- `apply_market_preset` (Bug #11): The plan says "use a separate `explicitly_set` set" but the function signature has no way to receive this information from callers. I will add an optional `explicitly_set: Optional[set] = None` parameter — backward-compatible, existing callers unaffected, callers that need the fix can opt in. This is a judgment call within the spirit of the plan.
- S6 (LRU eviction for `_results`): Low-priority, requires external library or more complex code. Will implement as a simple max-size trim instead.
- The `american_put_baw` already guards `T < 1e-7 or r < 1e-8` (line 201) but not `sigma < 1e-8`. Fix is additive.
- All 11 bugs are straightforward. No breaking changes expected.

## Fix Order

1. Bug #1 — `_VOL_CACHE` key (strategy.py) — highest impact on grid results
2. Bug #2 — force-close double-append (portfolio.py) — corrupts MTM equity
3. Bug #3 — bare `except:` (engines.py)
4. Bug #4 — `_PARAM_REMAP` naming (api.py)
5. Bug #5 — IVR filter inverted (strategy.py)
6. Bug #6 — `upsert_run` label erasure (runs_store.py)
7. Bug #7 — CWD-relative DB path (runs_store.py)
8. Bug #8 — dte_min/dte_max validation (api.py)
9. Bug #9 — globals never expire (strategy.py, data.py)
10. Bug #10 — sigma=0 crashes BAW (engines.py)
11. Bug #11 — `apply_market_preset` discards overrides (params.py)
12. S1–S6 suggestions
