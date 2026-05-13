# B3 Migration Follow-up — Implementation Plan

**Date created:** 2026-05-12
**Status:** Proposed
**Depends on:** `2026-05-12 - B3 data migration to rb3.md` (completed)

---

## Overview

The rb3 migration is complete and the new database passes basic quality tests. However, the
6-trade sanity backtest is too small to confirm data parity, and several pre-existing engine
bugs (Sharpe smearing, flat rate, missing defensive roll) block trustworthy backtest results.

This plan executes the remaining validation, fixes the engine bugs, and hardens the quality
test suite — in a strict order so we never debug strategy logic against unvalidated data.

### Sequencing principle

```
Phase 1 (validate rb3 fully) ──┐
                               ├── all phases below assume rb3 is trustworthy
Phase 2 (fix Sharpe bug)    ───┤
                               ├── all risk-adjusted analysis assumes this is fixed
Phase 3 (real yield curve)  ───┤
                               ├── precision improvement; not a blocker but cheap to do early
Phase 4 (harden tests)      ───┤
                               ├── insurance against future regressions
Phase 5+ (strategy work)    ───┘
```

**Gating rules:**

- If Phase 1 shows systematic bias in rb3 → STOP. Investigate before proceeding.
- If Phase 2 isn't done → never quote Sharpe ratios, win-rate confidence intervals, or any
  risk-adjusted metric in a writeup.
- Phases 3 and 4 can run in parallel after Phase 1 passes.

---

## Phase 1 — Full-Period Regression (BLOCKER)

**Goal:** Confirm that the 2024 H1 P&L difference (BOVA11 +R$97 rb3 vs +R$227 old, PETR4
+R$46 vs +R$47) is sampling noise, not systematic bias.

**Time estimate:** 1 day (mostly backtest run time + analysis)

### Task 1.1: Full-period parity backtest

Run both BOVA11 and PETR4 from `2017-01-01` to `2025-12-31` on both databases with identical
parameters:

```python
config = {
    "delta_target": 0.16,
    "dte_target_min": 30,
    "dte_target_max": 45,
    "manage_at_dte": 21,
    "profit_target": 0.50,
    "single_position": True,
    "roll_for_credit": True,
    "use_price_stop": False,
    "defensive_leg_roll_enabled": False,  # Keep matching the validated baseline
    "vix_entry_filter_enabled": True,
    "vix_entry_max": 35,
}
```

Save results to:

- `output/phase1_regression/bova11_old_db.parquet`
- `output/phase1_regression/bova11_rb3_db.parquet`
- `output/phase1_regression/petr4_old_db.parquet`
- `output/phase1_regression/petr4_rb3_db.parquet`

Each file should contain one row per trade with: entry_date, exit_date, exit_reason,
put_strike, call_strike, credit, exit_credit, pnl, dte_at_entry, vix_at_entry.

### Task 1.2: Comparison analysis

Compute and report:

**Aggregate metrics (table per underlying):**
| Metric | rb3 | old DB | Δ | Δ % |
|---|---|---|---|---|
| Trade count | | | | |
| Total P&L | | | | |
| Mean P&L per trade | | | | |
| Median P&L per trade | | | | |
| Win rate | | | | |
| Average credit | | | | |
| Average DTE at entry | | | | |
| Exit reason breakdown (PROFIT/21DTE/ROLLED) | | | | |

**Strike difference distribution:**
For each matching trade pair (same entry date), compute:

- `delta_put = rb3.put_strike - old.put_strike`
- `delta_call = rb3.call_strike - old.call_strike`
- `delta_credit = rb3.credit - old.credit`

Plot histograms. **Critical question: is the distribution centered on 0 (no bias) or skewed?**

**Trades that diverge materially:**
For trades where `|rb3.pnl - old.pnl| > R$50`, build a side-by-side table. Look for patterns:

- Are divergences clustered in time?
- Are they correlated with VIX regime?
- Are they correlated with rb3's flat-r vs old's actual-r?

### Task 1.3: Decision gate

**Pass criteria:**

- |Δ Total P&L| / |Total P&L| < 15% per underlying
- Strike difference distribution centered within ±1 strike, no fat tails
- Mean P&L per trade within 1 standard error
- No clustering of divergences in specific market regimes

**If pass:** Proceed to Phase 2.

**If fail:** Investigate before doing anything else. Likely culprits:

1. Flat r=12% vs actual r causing systematic delta miscalibration → Phase 3 becomes urgent
2. Different IV filtering thresholds between sources
3. Different bid/ask field meanings
4. Different handling of expiry/exercise

**Document findings either way** in `docs/2026-05-XX - Phase 1 full-period regression.md`.

### Deliverables

- [ ] `scripts/phase1_regression.py` — driver script
- [ ] `notebooks/phase1_analysis.ipynb` — analysis notebook
- [ ] `output/phase1_regression/*.parquet` — backtest outputs
- [ ] `docs/2026-05-XX - Phase 1 full-period regression.md` — findings + decision

---

## Phase 2 — Fix Sharpe Inflation Bug

**Goal:** Replace P&L-spreading with true daily mark-to-market in Sharpe computation.

**Time estimate:** 1-2 days

### Background

From your memory: the current Sharpe is inflated because realized P&L is "smeared" over the
holding period instead of being computed from daily MTM. This makes the strategy look smoother
than it is.

### Task 2.1: Locate and document the current implementation

Find where Sharpe is computed in `engines.py` / wherever the backtest aggregates results. Add
a docstring or comment block explaining what's wrong with it.

### Task 2.2: Implement true daily MTM

For each held position, on each trading day:

1. Query the option chain for that day at the position's strikes
2. Compute the mark price (bid+ask)/2 or use `close` if no bid/ask
3. If chain row missing → use synthetic fallback (BSM with current vix_close and underlying)
4. Daily P&L = (today's mark - yesterday's mark) × contracts × multiplier

Build a daily P&L time series. Sharpe = (mean daily return × 252) / (std daily return × √252).

### Task 2.3: Validation

Run a known-good backtest both ways:

- Old (smeared) Sharpe
- New (true MTM) Sharpe

The new Sharpe should be **lower** (typically by 20-40%). If it's higher or unchanged, the
implementation is wrong.

Verify on a single trade with known daily P&L:

- Compute expected daily MTM by hand for one 30-day trade
- Confirm engine produces the same numbers

### Task 2.4: Re-run Phase 1 regression with new Sharpe

After fix, re-add Sharpe and Sortino to the Phase 1 comparison table. These should now be
trustworthy.

### Deliverables

- [ ] Modified `engines.py` (or wherever P&L aggregation lives)
- [ ] Unit test: `tests/test_daily_mtm.py` with hand-computed expected values
- [ ] Updated Phase 1 regression report with corrected Sharpe numbers
- [ ] Brief writeup: `docs/2026-05-XX - Sharpe fix.md`

---

## Phase 3 — Replace Flat r=12% with Daily CDI

**Goal:** Use actual daily CDI rates (already in your backtest parquets) instead of flat 12%
for IV/delta computation. Improves precision by ~0.5 vol points.

**Time estimate:** 1 day

### Background

`bova11_backtest.parquet` and `petr4_backtest.parquet` already contain a `risk_free_rate`
column with daily CDI values (per your build log: "4100 days | 1.90% → 14.90%"). The rb3 IVs
were computed at a constant r=12%. We can recompute IVs in Python using the daily rate.

### Task 3.1: Recompute IVs/deltas with daily CDI

Add a column to `b3_options_rb3.db` (or a new derived DB) with IVs computed at the actual
daily rate:

```python
import sqlite3
import pandas as pd
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

# Load options data
conn = sqlite3.connect("data/B3/b3_options_rb3.db")
opts = pd.read_sql("SELECT * FROM options_data", conn)

# Load daily CDI rates
bova_meta = pd.read_parquet("data/B3/bova11_backtest.parquet")
petr_meta = pd.read_parquet("data/B3/petr4_backtest.parquet")

# Build rate lookup: date -> r
rate_lookup = {}
for df, und in [(bova_meta, 'bova11'), (petr_meta, 'petr4')]:
    for date, r in df['risk_free_rate'].items():
        rate_lookup[(und, str(date.date()))] = r

# Recompute IV per row using actual r
def bsm_price(S, K, T, r, sigma, opt_type):
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    if opt_type == 'call':
        return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    else:
        return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

def implied_vol(price, S, K, T, r, opt_type):
    try:
        return brentq(lambda s: bsm_price(S, K, T, r, s, opt_type) - price,
                      0.001, 5.0, maxiter=100)
    except (ValueError, RuntimeError):
        return np.nan

# Apply per row (use joblib for parallelism — 1.4M rows is slow)
```

Add two new columns: `implied_volatility_cdi`, `delta_cdi`.

### Task 3.2: Compare old vs new IVs

For ATM options at 30-45 DTE (the strikes you actually trade), plot:

- `implied_volatility` (flat r=12%) vs `implied_volatility_cdi` (daily r)
- Expected: median difference ~0.5 vol points, with sign depending on whether actual r was
  above or below 12%

If differences exceed 2 vol points consistently, something is wrong with the computation.

### Task 3.3: Re-run Phase 1 regression

Run BOVA11 and PETR4 again using daily-CDI IVs/deltas. Compare to flat-r results from
Phase 1. The strike selection should now be slightly more accurate, but P&L magnitude
should be similar.

### Task 3.4: Decide which column to use as default

Two options:

- **Replace** `implied_volatility` with the CDI version (simpler, cleaner)
- **Keep both** and let the engine choose via a config flag (safer, allows comparison)

Recommendation: keep both initially, switch the default after Phase 1 re-run confirms no
surprises. Drop the flat-r columns later when you're confident.

### Deliverables

- [ ] `scripts/recompute_iv_with_cdi.py` — recomputation script
- [ ] Updated `b3_options_rb3.db` with new columns
- [ ] Comparison notebook: `notebooks/iv_flat_vs_cdi.ipynb`
- [ ] Engine config update to use CDI-based IVs
- [ ] Brief writeup: `docs/2026-05-XX - Daily CDI rate adoption.md`

---

## Phase 4 — Harden Quality Test Suite

**Goal:** Add missing quality tests so future data refreshes can't silently regress.

**Time estimate:** 2-3 days (mostly the Bloomberg comparison)

### Task 4.1: Add missing automated tests to `check_rb3_quality.py`

#### Test I: Put-call parity violations

```python
def test_put_call_parity(df, max_violation_pct=0.05):
    """
    For matched call/put on same (date, expiration, strike):
    C - P should be approximately S - K*exp(-r*T) within bid-ask.
    """
    calls = df[df['type'] == 'call'].set_index(['date', 'expiration', 'strike'])
    puts = df[df['type'] == 'put'].set_index(['date', 'expiration', 'strike'])
    matched = calls.join(puts, lsuffix='_c', rsuffix='_p', how='inner')

    matched['T'] = (pd.to_datetime(matched.index.get_level_values('expiration'))
                    - pd.to_datetime(matched.index.get_level_values('date'))).dt.days / 252
    matched['expected'] = matched['close_underlying_c'] - matched['strike'] * np.exp(-0.12*matched['T'])
    matched['actual'] = matched['mark_c'] - matched['mark_p']
    matched['violation'] = (matched['actual'] - matched['expected']).abs() / matched['close_underlying_c']

    return matched[matched['violation'] > max_violation_pct]
```

#### Test J: Term structure monotonicity

For each (date, underlying), find ATM call IVs at the 3 nearest expirations. If the IV at
expiration N is more than 10 vol points different from expiration N+1 AND that gap doesn't
appear on neighboring days, flag it as a probable data error.

#### Test L: Strike grid completeness

```python
def test_strike_grid(df, min_strikes=5):
    """Each (date, underlying, expiration) should have at least N strikes."""
    grid = df.groupby(['date', 'underlying', 'expiration']).size()
    return grid[grid < min_strikes]
```

#### Test M: Regression test for the old corruption pattern

```python
def test_no_extreme_corruption(df):
    """The old DB had ~5 rows with mark > R$500k. Verify rb3 has zero."""
    huge = df[df['mark'] > 1000]
    assert len(huge) == 0, f"Found {len(huge)} rows with mark > R$1000"
```

### Task 4.2: Test K — Bloomberg/external cross-source spot-check

Pick 10 high-stakes dates spanning the data range:

- 2017-05-18 — Joesley Day (PETR4 -16%)
- 2018-10-08 — Bolsonaro election week
- 2020-03-12 — COVID crash worst day
- 2020-03-23 — COVID bottom
- 2021-03-30 — Petrobras CEO firing
- 2022-10-31 — Lula election
- 2023-01-09 — Brasília attack
- 2024-03-15 — Random control date
- 2024-12-20 — Year-end thin trading
- 2025-04-02 — Random control date

For each date, document the ATM put and ATM call (30-45 DTE) in:

- rb3 database (mark, IV, delta)
- External source (Bloomberg/TradingView/Oplab — whichever you have access to)

Build a comparison table in `docs/2026-05-XX - External validation.md`. **Acceptance:**
prices within R$0.05 or bid-ask spread, IVs within 2 vol points.

This is the only test that catches "rb3 looks internally consistent but is systematically
off." It's tedious but it's the gold standard.

### Task 4.3: CI integration

Add a pre-commit or pre-push hook (or just a Make target) that runs `check_rb3_quality.py`
and blocks if any test exceeds 0.1% violations:

```makefile
check-data:
	python scripts/check_rb3_quality.py --strict
	@echo "✓ Data quality checks passed"
```

Don't gate every commit on this (it's slow), but require it before merging to main or
running production paper trades.

### Deliverables

- [ ] Updated `scripts/check_rb3_quality.py` with tests I, J, L, M
- [ ] `docs/2026-05-XX - External validation.md` with Test K results
- [ ] `Makefile` (or equivalent) with `check-data` target
- [ ] Brief writeup: `docs/2026-05-XX - Quality suite v2.md`

---

## Phase 5 — Strategy Improvements (UNBLOCKED after Phases 1–4)

Pre-existing TODOs from migration_context.md, in priority order.

### Task 5.1: Implement defensive leg roll (HIGH)

From your memory: when the tested side delta breaches 0.30, roll the untested side to capture
more premium. This is the largest missing piece of the tastytrade strategy.

**Specification:**

- Trigger: any leg's |delta| > 0.30 OR underlying moved past short strike
- Action: close the untested leg, open new untested leg at current 16-delta
- Booking: realize partial credit from closed leg, add new credit
- Constraint: only roll within current expiration cycle (no roll-out)

Implementation in `engines.py` near `_best_row`. Add a new method `_check_defensive_roll`.

### Task 5.2: Enforce single-position-at-a-time (HIGH)

Current bug: rolled trades can extend past the next monthly entry date, causing two
overlapping positions. Fix:

```python
if has_open_position(entry_date):
    skip_entry(reason="position_overlap")
```

The engine already has `single_position=True` flag — verify it's actually enforced and add a
test that exercises a rolling scenario followed by a monthly entry.

### Task 5.3: Update sensitivity analysis (MEDIUM)

Sensitivity scripts currently hardcode SyntheticEngine. Migrate them to use MarketEngine with
the new DB. This is mechanical — same pattern as the migration itself.

### Task 5.4: Run the canonical strategy validation matrix (MEDIUM)

Once 5.1 and 5.2 are done, run the full parameter sweep:

- VIX entry filter: on/off
- VIX entry max: 25, 30, 35, 40
- Defensive roll: on/off
- DTE target: 30-45, 35-50, 40-55
- Delta target: 0.10, 0.16, 0.20, 0.25

Compare to your existing sweep results in the parameter_grid_search HTML files. The new
results should be the **definitive** version since they use validated data + fixed engine.

### Task 5.5: Intraday data evaluation (LOW)

CBOE DataShop for SPY at 5-minute intervals — already on your roadmap. Defer until live
trading is closer.

For B3 intraday: research whether Oplab, B3 Trader, or similar provide historical intraday
options data. This is harder than for SPY.

### Deliverables

- [ ] Implemented defensive leg roll in engine
- [ ] Single-position enforcement with test coverage
- [ ] Updated sensitivity analysis using MarketEngine
- [ ] New parameter grid search results
- [ ] Intraday data feasibility study (write-up only)

---

## Timeline Summary

Conservative single-person estimate, assuming ~4 focused hours per workday:

| Phase                               | Days | Cumulative |
| ----------------------------------- | ---- | ---------- |
| Phase 1 — Full regression           | 1    | 1          |
| Phase 2 — Sharpe fix                | 2    | 3          |
| Phase 3 — Daily CDI                 | 1    | 4          |
| Phase 4 — Quality suite + Bloomberg | 3    | 7          |
| Phase 5.1 — Defensive roll          | 3    | 10         |
| Phase 5.2 — Single position         | 1    | 11         |
| Phase 5.3 — Sensitivity update      | 1    | 12         |
| Phase 5.4 — Grid search             | 1    | 13         |

**~2.5 weeks of focused work** to reach a defensible "production-ready backtest" state.

Phases 3 and 4 can be parallelized after Phase 1 passes — they don't touch the same code.

---

## Decision Points (gates that require human judgment)

1. **End of Phase 1:** Does rb3 show systematic bias vs old DB?
   - Yes → debug before continuing
   - No → proceed to Phase 2

2. **End of Phase 2:** Is corrected Sharpe materially lower (20-40% reduction)?
   - Much lower (>50%) → suspect implementation error
   - Within expected range → trust new numbers, proceed

3. **End of Phase 3:** Do daily-CDI IVs change strike selection materially?
   - Yes → re-run Phase 1 with new IVs and reconfirm
   - No → adopt as default, move on

4. **End of Phase 4 Test K:** Does rb3 match Bloomberg within tolerance?
   - Yes → declare data layer production-ready
   - No → investigate which source is correct; may need to switch data vendors

5. **End of Phase 5.4:** Are new grid search results consistent with prior parameter
   selections (no leg roll, VIX max=35)?
   - Yes → those parameters are now empirically validated against clean data
   - No → re-evaluate strategy assumptions before going live

---

## What I'd skip / defer

- **Adding more underlyings (VALE3, ITUB4, BBDC4)** — wait until BOVA11/PETR4 are
  production-validated. Adding more underlyings amplifies any data quality issues.
- **Intraday data for B3** — research only, no implementation until live SPY trading is
  comfortable. The complexity isn't worth it pre-revenue.
- **Cross-asset hedging analysis (PETR4 position vs strategy)** — separate workstream,
  doesn't belong in the backtest validation track.

---

## Risks

1. **Phase 1 reveals systematic bias.** Most likely cause: flat r=12% in rb3 vs actual r in
   old DB. Mitigation: Phase 3 happens earlier than scheduled.
2. **Bloomberg access issues for Test K.** If no Bloomberg, use Oplab (Brazilian retail
   options platform with historical data) or TradingView. Test K is mandatory; the source
   is negotiable.
3. **Sharpe fix breaks existing reports.** All prior performance numbers in your docs will
   become outdated. Plan to mark them as "computed with smeared P&L" in retrospect.
4. **Defensive roll implementation surfaces new bugs.** Likely — this is the most complex
   strategy change. Budget extra time and write unit tests first.

---

## Files this plan will produce

```
scripts/
  phase1_regression.py
  recompute_iv_with_cdi.py
  (modified) check_rb3_quality.py

src/straddle/
  (modified) engines.py — Sharpe fix, defensive roll, single-position enforcement

tests/
  test_daily_mtm.py
  test_defensive_roll.py
  test_single_position.py

notebooks/
  phase1_analysis.ipynb
  iv_flat_vs_cdi.ipynb

docs/
  2026-05-XX - Phase 1 full-period regression.md
  2026-05-XX - Sharpe fix.md
  2026-05-XX - Daily CDI rate adoption.md
  2026-05-XX - External validation.md
  2026-05-XX - Quality suite v2.md
  2026-05-XX - Defensive leg roll implementation.md

output/
  phase1_regression/*.parquet
  grid_search_v4/  (post-fixes definitive version)
```
