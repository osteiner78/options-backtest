# V4 Execution Sensitivity Analysis — Implementation Plan

**Target:** A coding agent
**Goal:** Determine whether BOVA11 short strangle profitability depends on execution price assumptions, and validate the rb3 bid/ask data quality.
**Why:** V3 results showed deeply negative Sharpe across all 7,560 configurations using "sell at bid / buy at ask" (worst-case fills). This contradicts established B3 VRP literature. Before concluding the strategy is unviable, we must understand whether the result is driven by execution assumptions rather than strategy design.

---

## Overview

The plan has 4 phases:

1. **P0A — Execution price sensitivity scan** (highest priority, immediately actionable)
2. **P0B — rb3 bid/ask data validation** (critical, requires manual data check)
3. **P1 — American vs European option pricing verification** (quick code check)
4. **P2 — Individual trade forensics** (understand where losses come from)

Phase 1 is the main deliverable. Phases 2-4 can run in parallel or after.

---

## Phase P0A: Execution Price Sensitivity Scan

### Motivation

The V3 grid uses "sell at bid, buy at ask" — the worst possible execution. This is one extreme. The other extreme (mid-price with -5%/+5% fill adjustment) gives synthetic-mode Sharpe of +1.08 vs market-mode -0.12. The truth is somewhere in between.

We need to re-run the grid (or a representative subset) at multiple execution price assumptions to find the break-even point.

### Execution Price Modes

Introduce a new parameter `execution_mode` with 5 levels:

| Mode | Entry price | Close price | MTM price | Description |
|------|------------|-------------|-----------|-------------|
| `bid_ask` | bid | ask | ask | Current behavior (worst case) |
| `mid_minus_1tick` | mid - 1 tick | mid + 1 tick | mid + 1 tick | Conservative limit order |
| `mid` | mid | mid | mid | Fair fill |
| `mid_plus_1tick` | mid + 1 tick (credit) | mid - 1 tick (debit) | mid | Favorable limit order |
| `synthetic` | mid × (1+open_fill_adj) | mid × (1+close_fill_adj) | mid × (1+close_fill_adj) | Current synthetic mode |

**B3 tick size:** For BOVA11 options, the minimum tick is R$0.01 for premiums < R$1.00 and R$0.05 for premiums >= R$1.00. We'll use a single `tick_size` parameter (default R$0.05) that the coding agent can override in `MARKET_PRESETS`.

### Code Changes

#### 1. Add `execution_mode` to `PricingParams` TypedDict and `PARAMS`

**File:** `src/straddle/params.py`

Add to `PricingParams`:
```python
execution_mode: str  # "bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick" | "synthetic"
```

Add to `PRICING` dict:
```python
"execution_mode": "bid_ask",  # default: worst-case fills
```

Add `tick_size` to the `PricingParams` TypedDict and to `PRICING`:
```python
tick_size: float  # minimum price increment for execution_mode calculations
```
```python
"tick_size": 0.05,  # R$0.05 default (B3 equity options, premiums >= R$1.00)
```

Add `tick_size` to each `MARKET_PRESETS` entry:
```python
# spy:
"tick_size": 0.01,
# bova11:
"tick_size": 0.05,
# petr4:
"tick_size": 0.05,
```

#### 2. Modify `MarketEngine` to use `execution_mode`

**File:** `src/straddle/engines.py`

The key changes are in 3 methods that currently hard-code "sell at bid, buy at ask":

**2a. `get_entry_marks()` (line ~557-563)**

Current code returns bid for both legs:
```python
return (
    float(put_row["strike"]),
    float(call_row["strike"]),
    float(put_row["bid"]),  # sell at bid
    float(call_row["bid"]),  # sell at bid
    True,
)
```

New code:
```python
exec_mode = self._exec_mode
tick = self._tick_size

if exec_mode == "bid_ask":
    put_price = float(put_row["bid"])
    call_price = float(call_row["bid"])
elif exec_mode == "synthetic":
    put_price = self.apply_fill_adj(float(put_row["mark"]), "open")
    call_price = self.apply_fill_adj(float(call_row["mark"]), "open")
else:
    # mid, mid_minus_1tick, mid_plus_1tick
    put_mid = float(put_row["mark"])
    call_mid = float(call_row["mark"])
    if exec_mode == "mid_minus_1tick":
        put_price = put_mid - tick  # sell slightly below mid
        call_price = call_mid - tick
    elif exec_mode == "mid_plus_1tick":
        put_price = put_mid + tick  # sell slightly above mid (favorable)
        call_price = call_mid + tick
    else:  # "mid"
        put_price = put_mid
        call_price = call_mid

return (
    float(put_row["strike"]),
    float(call_row["strike"]),
    put_price,
    call_price,
    True,
)
```

**IMPORTANT:** When `execution_mode` is not `"bid_ask"`, the `apply_fill_adj` call in `build_entry()` (`strategy.py` line 226) should become a no-op, because the execution mode already controls the fill price. This is tricky — see section 2d below.

**2b. `_strike_ask()` (line ~847-872)**

This method returns the ask price for closing a short position (buying back). Currently:
```python
return float(row["ask"]) if row else None
```

New behavior for `execution_mode`:
- `bid_ask`: return `float(row["ask"])` (current)
- `mid_minus_1tick`: return `float(row["mark"]) + tick_size` (pay slightly above mid)
- `mid`: return `float(row["mark"])`
- `mid_plus_1tick`: return `float(row["mark"]) - tick_size` (favorable: pay below mid)
- `synthetic`: should not reach this path (would use synthetic fallback)

Rename to `_strike_close_price()` and add `execution_mode` logic:

```python
def _strike_close_price(self, date_str, exp_str, opt, strike):
    """Return the close-side price for one leg based on execution_mode."""
    # ... existing query to get row ...
    if row is None:
        return None
    
    exec_mode = self._exec_mode
    tick = self._tick_size
    
    if exec_mode == "bid_ask":
        return float(row["ask"])
    
    mark = float(row["mark"])
    if exec_mode == "mid_minus_1tick":
        return mark + tick  # pay more than mid (conservative)
    elif exec_mode == "mid_plus_1tick":
        return mark - tick  # pay less than mid (favorable)
    else:  # "mid"
        return mark
```

**Note:** The old method name `_strike_ask` is used in `get_daily_mark()`. Update all call sites.

**2c. `get_leg_mark_with_source()` (line ~701-730)**

Currently, this method delegates to `_strike_close_price()` (renamed from `_strike_ask()`) with direction logic:
```python
col = "bid" if buy_or_sell == "sell" else "ask"
```

When `execution_mode` is not `"bid_ask"`, the column selection changes:
- For DB-sourced marks: use `mark` column ± tick adjustments based on direction and mode
- For synthetic fallback: apply `self._synth.apply_fill_adj()` (already done in bug fix #1)

The `buy_or_sell` parameter maps to:
- `"sell"` → we receive credit (bid-side or mid-minus)
- `"buy"` → we pay cost (ask-side or mid-plus)

For `execution_mode != "bid_ask"`, both sides use `mark` with direction-dependent tick adjustments:

```python
if exec_mode == "bid_ask":
    col = "bid" if buy_or_sell == "sell" else "ask"
    # ... existing query with col ...
else:
    # Query mark column instead
    # For sell (credit): mark - tick (conservative) / mark (mid) / mark + tick (favorable)
    # For buy (cost): mark + tick (conservative) / mark (mid) / mark - tick (favorable)
    ...
```

**IMPORTANT design consideration:** The `_best_row()` method and `get_entry_marks()` handle entry pricing. `get_leg_mark_with_source()` and `_strike_close_price()` handle daily MTM and exit pricing. They need to be consistent with the same `execution_mode`.

**2d. Interaction with `apply_fill_adj`**

This is the most subtle part. Currently:

- `SyntheticEngine.apply_fill_adj()` applies ±5% fill adjustment to mid-prices
- `MarketEngine.apply_fill_adj()` is a no-op (bid/ask already include the spread)

When `execution_mode` changes:
- `"bid_ask"`: `MarketEngine.apply_fill_adj()` stays no-op (correct)
- `"mid"`, `"mid_minus_1tick"`, `"mid_plus_1tick"`: We're now using mark +/- ticks, which are effectively at mid ± small offset. Fill adjustment should NOT be applied on top of this, because the tick offset IS the fill model. So `apply_fill_adj()` should remain a no-op for all non-synthetic modes.
- `"synthetic"`: This mode effectively makes `MarketEngine` behave like `SyntheticEngine` — using mark prices with ±5% adjustments. For this mode, `apply_fill_adj()` should delegate to `self._synth.apply_fill_adj()`.

For the DB-sourced mid-price modes, the tick adjustment replaces the percentage fill adjustment. So `apply_fill_adj()` should remain a no-op for `bid_ask`, `mid`, `mid_minus_1tick`, and `mid_plus_1tick`. Only for `synthetic` mode should it delegate.

**Strategy.py changes:** The calls to `engine.apply_fill_adj()` in `build_entry()`, `evaluate_trade_step()`, and `evaluate_trade()` should work correctly if `apply_fill_adj()` returns the right thing per mode. No changes needed in strategy.py beyond what's already there.

#### 3. Initialize `execution_mode` and `tick_size` in `MarketEngine.__init__()`

**File:** `src/straddle/engines.py`, `MarketEngine.__init__()`

```python
self._exec_mode = params.get("execution_mode", "bid_ask")
self._tick_size = params.get("tick_size", 0.05)
```

Also, `self.uses_real_fills` should be updated:
```python
self.uses_real_fills = (self._exec_mode == "bid_ask")
```

#### 4. Update `_best_row()` to also return `mark` column

**File:** `src/straddle/engines.py`, `_best_row()` (line ~813-845)

Currently returns `strike, mark, bid, ask, delta, implied_volatility, volume`. This already includes everything needed. No change required.

#### 5. Add `execution_mode` to grid search

**File:** `scripts/grid_search.py`

Add `"execution_mode"` to `GRID_DIMS` list.

In the new v4 grid, `execution_mode` takes these values:
```python
"execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"]
```

**Do NOT include `"synthetic"` in the grid** — that mode is the same as running `mode="synthetic"` in the backtest and would produce identical results.

In `_apply_grid_overrides()`:
```python
elif key == "execution_mode":
    overrides["execution_mode"] = val
```

#### 6. Create v4 grid search notebook

**File:** `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb`

The v4 grid should be **smaller** than v3 to keep runtime manageable. We're not re-exploring all parameter combinations — we're testing execution sensitivity across a representative set:

```python
GRID = {
    "target_delta": [0.16, 0.20, 0.25],
    "dte_max": [30, 45],
    "profit_target_pct": [0.50],
    "manage_at_dte": [7, 14],
    "vix_filter": ["OFF", "rv_pct:80"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [3.0],
    "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"],
}
```

This gives: 3 × 2 × 1 × 2 × 2 × 1 × 1 × 4 = 96 combos × 2 periods = 192 backtests.

Total runtime: ~3-5 minutes on 8 cores.

### Analysis to Produce

The notebook should include:

1. **Sharpe vs execution_mode boxplot** — for each period, show how Sharpe changes across the 5 modes. This is the single most important chart.

2. **Break-even execution level** — find the execution_mode where holdout mean Sharpe crosses zero. If it's "mid_minus_1tick", the strategy becomes viable with slightly favorable limit orders.

3. **Sharpe by execution_mode × target_delta** — does the break-even point differ by delta selection?

4. **Per-trade P&L comparison** — for a single representative config (e.g., delta=0.20, dte=30, profit=0.50), show per-trade P&L under each mode. This reveals whether the spread cost is uniform or concentrated in gap events.

5. **Spread analysis** — for entries with DB data, compute `(mark - bid) / mark` and `(ask - mark) / mark` to quantify the actual spread. Compare to the synthetic fill adjustment of 5%.

6. **Update source tracking** — add `execution_mode` column to output. This lets us slice DB% vs synthetic% per execution mode.

### Expected Outcomes

| Scenario | Implication |
|---|---|
| `"mid"` produces positive holdout Sharpe | VRP exists but is consumed by bid-ask spread; strategy viable with limit orders |
| `"mid"` still negative | VRP is negative even at fair fill; strategy is structurally unviable |
| `"mid_minus_1tick"` crosses zero | ~1 tick of execution improvement needed; achievable with patient limit orders |
| All modes deeply negative | The v3 conclusion holds; strategy is unprofitable regardless of execution |

---

## Phase P0B: rb3 Bid/Ask Data Validation

### Motivation

If rb3 bid/ask are computed (e.g., mark ± fixed percentage) rather than quoted, then "sell at bid" is systematically worse than reality, and no grid search can produce correct results.

### Steps

#### 1. Spot-check rb3 against B3 official data

For 5-10 specific dates (spread across 2020-2025), compare the rb3 database's `bid`, `ask`, and `mark` columns against B3's official historical market data (available from B3's website or a broker terminal).

- Select dates: e.g., 2020-03-16 (COVID crash), 2021-06-15 (normal), 2022-10-24 (election), 2024-03-15 (normal), 2025-01-10 (recent)
- For each date, pick the BOVA11 option closest to 16-delta put and 16-delta call
- Compare bid, ask, mark, volume against B3's official EOD summary
- Check: Are bid/ask stale (same for many strikes)? Do they represent real executable quotes?

Run this as a Python script:

```python
# scripts/validate_rb3_bid_ask.py
"""Spot-check rb3 bid/ask quality against known patterns.

Checks:
1. Bid-ask spread distribution — are spreads realistic for BOVA11 options?
2. Bid/ask consistency — do mark prices fall between bid and ask?
3. Spread vs delta — do OTM options have proportionally wider spreads?
4. Stale data detection — are identical bid/ask values repeated across strikes?
"""
```

#### 2. Spread analysis within rb3 itself

Even without external data, we can check internal consistency:

```python
# For each option row with bid > 0 and ask > 0:
spread_pct = (ask - bid) / mark  # should be > 0 and < ~0.30
mark_inside = (bid <= mark <= ask)  # mark should be between bid and ask
```

Compute:
- Distribution of `spread_pct` by delta bucket and by year
- Percentage of rows where `mark` is NOT between bid and ask
- Average spread as fraction of premium for OTM puts (delta 0.10-0.25) vs ATM

**Expected:** BOVA11 ATM options should have spreads of 1-3% of premium. OTM (16-delta) options may have 5-15% spreads. If spreads are consistently >20% for 16-delta options, that explains why "sell at bid" destroys returns.

#### 3. Deliverable

A notebook `research/2026-05-14 - rb3 bid-ask validation.ipynb` with:
- Summary statistics on bid-ask spreads by delta bucket and year
- Flagged anomalies (mark outside bid-ask, zero spreads, identical values across strikes)
- comparison against B3 official data for spot-checked dates (if available)
- Recommendation: are the bid/ask data reliable enough for worst-case execution modeling?

---

## Phase P1: American vs European Option Pricing Verification

### Motivation

BOVA11 options are marked as European-style (`"american_options": False`) in the preset. If they are actually American (or if early exercise is relevant), the synthetic model underprices OTM puts, leading to inflated credit received on synthetic-fallback entries.

This affects ~28% of train entries and ~13% of holdout entries.

### Steps

#### 1. Verify BOVA11 option style

Search B3's official documentation or the rb3 database schema for option exercise style (European vs American). BOVA11 is an ETF, and B3 ETF options are indeed European-style (cash-settled), so the current setting is likely correct. But confirm this.

#### 2. Quick sensitivity test

If we set `"american_options": True` for BOVA11, the SyntheticEngine would use BAW put pricing (which prices OTM puts slightly higher). This would make synthetic entries show slightly *less* credit (more conservative). To quantify:

- Run a single backtest with `american_options=True` and `mode="synthetic"` for train period
- Compare net_credit and Sharpe against `american_options=False`
- The difference should be small (OTM puts have low early exercise value) but quantifying it removes ambiguity

#### 3. Deliverable

Add a cell to the v4 notebook comparing `american_options=True` vs `False` for a small set of configurations. If the difference is <1% of P&L, we can ignore it.

---

## Phase P2: Individual Trade Forensics

### Motivation

The aggregate statistics tell us the strategy is negative, but not *why*. Looking at individual trades reveals whether losses are:

A. Many small losses from spread costs (execution-based)  
B. Few large losses from directional moves (strategy-based)  
C. Concentrated in specific volatility regimes (entry timing-based)

### Steps

#### 1. Extract worst and best trades

For the holdout period, run a single representative config (e.g., delta=0.20, dte=30, profit=0.50, manage=7, vix_filter=OFF, leg_roll=False, stop_loss=3.0) under `execution_mode="bid_ask"` and `"mid"`.

For each, output:
- Top 10 worst individual trades (by P&L)
- Top 10 best individual trades
- Distribution of per-trade P&L (histogram)

#### 2. Examine the worst trade

For the worst trade:
- What was the entry credit? (bid vs mid comparison)
- What was the close cost? (ask vs mid comparison)
- How many days was it held?
- Did it hit a stop loss?
- Was it a directional move or vol expansion?

#### 3. Deliverable

Add a section to the v4 notebook or a standalone `research/2026-05-14 - trade forensics.ipynb` with:
- P&L histograms under bid_ask, mid, and mid_minus_1tick
- Worst-trade deep dive
- Entry credit comparison: bid vs mark for all DB-sourced entries (histogram of `(mark-bid)/mark`)

---

## Implementation Order

The coding agent should implement changes in this order:

### Step 1: Add `execution_mode` and `tick_size` parameters (params.py)
- Add to `PricingParams`, `PRICING`, and each `MARKET_PRESETS` entry
- No behavior change yet (default is `"bid_ask"`)

### Step 2: Update `MarketEngine.__init__()` (engines.py)
- Store `self._exec_mode` and `self._tick_size`
- Update `self.uses_real_fills`

### Step 3: Update `MarketEngine.get_entry_marks()` (engines.py)
- Implement execution_mode logic for DB-sourced marks
- The synthetic fallback path already returns mid prices with fill adjustment; when `execution_mode` is `"mid"` or `"mid_minus_1tick"` or `"mid_plus_1tick"`, the synthetic fallback should return mark-based prices with tick adjustments instead of bid/ask

### Step 4: Create `_strike_close_price()` replacing `_strike_ask()` (engines.py)
- Current `_strike_ask` returns the ask column. Rename and extend to support execution_mode
- The `col = "bid" if buy_or_sell == "sell" else "ask"` logic in `get_leg_mark_with_source()` needs updating for non-bid_ask modes

### Step 5: Update `get_leg_mark_with_source()` (engines.py)
- When `execution_mode != "bid_ask"`, query the `mark` column instead of choosing `bid`/`ask`
- Apply tick adjustment based on `buy_or_sell` direction and `execution_mode`

### Step 6: Verify `apply_fill_adj()` behavior (engines.py)
- For `bid_ask`, `mid`, `mid_minus_1tick`, `mid_plus_1tick`: `apply_fill_adj()` remains no-op
- For `synthetic`: `apply_fill_adj()` delegates to `self._synth.apply_fill_adj()` (already done via bug fix #1 for the fallback path)

### Step 7: Update grid search (scripts/grid_search.py)
- Add `execution_mode` to `GRID_DIMS`
- Add execution_mode handling in `_apply_grid_overrides()`
- Add `execution_mode` to output columns

### Step 8: Write tests (tests/test_engines.py)
- Test `MarketEngine` with `execution_mode="mid"` returns mark prices for DB entries
- Test `MarketEngine` with `execution_mode="mid_minus_1tick"` returns mark - tick for entry and mark + tick for close
- Test that `bid_ask` mode gives identical results to v3 (regression test)
- Test that synthetic fallback paths respect `execution_mode`

### Step 9: Create v4 notebook (research/2026-05-14 - B3 - v4 execution sensitivity.ipynb)
- Define the reduced grid as specified above
- Run grid search with 4 execution modes × 2 periods
- Generate the analysis charts specified in Phase P0A

### Step 10: rb3 validation notebook (research/2026-05-14 - rb3 bid-ask validation.ipynb)
- Load the rb3 database
- Compute spread distributions by delta bucket, year, and underlying
- Flag anomalies (mark outside bid-ask, zero spreads, stale values)
- Spot-check specific dates if B3 data is available

### Step 11: Run tests and verify
- `pytest tests/ -v` — all 90+ tests must pass
- Smoke test: run a single v3 config with `execution_mode="bid_ask"` and confirm results match v3 output exactly

---

## Key Design Decisions for the Coding Agent

1. **`execution_mode` only affects `MarketEngine`, not `SyntheticEngine`.** The synthetic engine always uses BS mid + fill adjustment. When `execution_mode="synthetic"`, the MarketEngine's DB paths are essentially bypassed (all marks come from synthetic fallback with fill adj). This is equivalent to running `mode="synthetic"` in the backtest.

2. **Tick adjustments are absolute, not percentage.** For BOVA11, a tick is R$0.05 per share (R$5 per contract). This means `mid_minus_1tick` subtracts R$0.05 per share from credit received (entry) and adds R$0.05 per share to buyback cost (close). For 16-delta options where premium might be R$1-3 per share, this represents a 2-5% penalty — comparable to the synthetic fill adjustment.

3. **The grid should NOT include `"synthetic"` execution_mode.** That would duplicate `mode="synthetic"` results. If you want to compare, just reference the v3 synthetic-mode runs.

4. **For the synthetic fallback paths within MarketEngine** (where DB data is missing), the `execution_mode` should NOT change behavior — synthetic fallback always uses BS mid + fill adjustment regardless of execution_mode. The fill adjustment already models spread cost at ±5%, which is in the same ballpark as 1-2 ticks for most BOVA11 options. Mixing tick-based DB pricing with percentage-based synthetic pricing is acceptable because the fallback paths are already a rough model.

5. **`_best_row()` must return bid, ask, and mark columns** — it already does (line 831: `SELECT strike, mark, bid, ask, ...`). The coding agent just needs to use the appropriate column based on `execution_mode`.

6. **`get_daily_mark()` needs updating too.** Currently calls `_strike_ask()` for both legs. It needs to call `_strike_close_price()` with the appropriate direction. For short positions, we're buying back (close cost = ask or mid+tick).

7. **Entry uses `find_strike_at_delta()` which returns `(strike, bid)`.** When `execution_mode != "bid_ask"`, this method needs to return `(strike, mark)` instead (or `(strike, mark +/- tick)` depending on mode). Check `find_strike_at_delta()` in MarketEngine — it currently queries the `bid` column. For `execution_mode="mid"`, it should query `mark`.

   Update `find_strike_at_delta()` (line ~756-787):
   ```python
   if self._exec_mode == "bid_ask":
       col = "bid"
   else:
       col = "mark"
   ```
   And adjust the return value to include the tick adjustment.

8. **Commission model:** The current commission is R$1.00/leg. This is already optimistic for retail (B3 + brokerage fees are typically R$2-5/round-trip). Do NOT change commission for this analysis — we want to isolate execution price effects.

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/straddle/params.py` | Add `execution_mode`, `tick_size` to `PricingParams`, `PRICING`, and each `MARKET_PRESETS` |
| `src/straddle/engines.py` | `MarketEngine.__init__`, `get_entry_marks`, `find_strike_at_delta`, `get_leg_mark_with_source`, `_strike_ask→_strike_close_price`, `get_daily_mark`, `apply_fill_adj` |
| `scripts/grid_search.py` | Add `execution_mode` to `GRID_DIMS`, `_apply_grid_overrides` |
| `tests/test_engines.py` | Add tests for each execution mode |
| `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb` | New notebook |
| `research/2026-05-14 - rb3 bid-ask validation.ipynb` | New notebook |

---

## Success Criteria

1. Bid-ask grid reproduces v3 results exactly (regression check)
2. Mid-price grid shows Sharpe improvement of expected magnitude (probably +0.5 to +1.5 over bid-ask)
3. The break-even execution level is identified
4. rb3 spread analysis shows realistic bid-ask distributions (or flags anomalies)
5. All tests pass

The most important output is **chart #1**: Sharpe vs execution_mode boxplot. This single chart will tell us whether the negative v3 conclusion is driven by execution assumptions or by strategy design.