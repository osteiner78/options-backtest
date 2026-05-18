# Phase 2 End Report — Plan 020: Improve Code Quality

## What was built

- **2a — metrics.py `_compute_source_tracking_stats`**: Extracted the 16-line source tracking block (DB counts, MTM DB pct) duplicated verbatim in `compute_metrics` and `compute_portfolio_metrics`. Both call sites now use `results.update(_compute_source_tracking_stats(trades))`.
- **2b — portfolio.py `_compute_close_mid_and_commissions`**: Extracted the duplicated mid-close/n_comm logic that handled the iron-condor vs strangle split. Takes optional `long_put_mid_ps`/`long_call_mid_ps` and returns `(mid_close_ps, n_comm)`. Replaced at both call sites in the portfolio evaluation loop.
- **2c — engines.py `_synthetic_fallback_entry`**: Extracted the 3 identical 4-line fallback blocks in `MarketEngine.get_entry_marks` (no context, no DB row, no bid) into a single private method. Each call site now: `pk, ck, pm, cm = self._synthetic_fallback_entry(S, T, r, vix, ctx)`.

## Test results

```
============================= 129 passed in 1.93s ==============================
```

## Deviations from plan

- **2c**: The plan specified a `delta: float` parameter in the function signature, but `SyntheticEngine.get_entry_marks` does not accept a separate `delta` argument (it reads `delta` from `ctx.target_delta` internally). Omitted the `delta` parameter; all 3 call sites already pass only `ctx`, matching the actual API.

## Follow-ups

None.

## Confidence rating

**certain** — 129/129 tests pass, no behavioral changes.
