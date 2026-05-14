# V4 Execution Sensitivity Analysis — REVISED Plan

**Target:** A coding agent (with human-driven Phase P0B)
**Goal:** Determine whether BOVA11 short strangle profitability depends on execution price assumptions, and validate rb3 bid/ask data quality against external sources.
**Why:** V3 results showed deeply negative Sharpe across all 7,560 configurations using "sell at bid / buy at ask" (worst-case fills). This contradicts established B3 VRP literature. The v2 data showed synthetic-mode Sharpe of +1.08 vs market-mode -0.12 — a 1.2 Sharpe gap that lives entirely on the execution assumption. Before concluding the strategy is unviable, we must (a) verify rb3 bid/ask are real published quotes, and (b) measure how the result changes across the realistic execution spectrum.

**Changes from original plan (006):**
1. P0B (bid/ask validation) now has a **specific pass/fail criterion** and a **manual TradingView protocol** for the human user
2. P0A (execution sensitivity scan) adds a fifth execution mode (`volume_filtered`) that skips low-volume days where EOD quotes are structurally unreliable
3. Decision tree at the end is more explicit about which conclusions are licensed by which P0A/P0B outcomes

---

## Overview and Sequencing

The plan has 4 phases with strict dependencies:

```
P0B (human) — bid/ask validation
    ├─ PASS  → P0A interpretable across all 5 execution modes
    └─ FAIL  → P0A interpretable for "mid" and "synthetic" modes only;
                "bid_ask" and "tick" modes are noise

P0A (agent) — execution sensitivity scan
    ├─ Run regardless of P0B outcome
    └─ Interpretation depends on P0B

P1 (agent) — American/European verification (quick check, parallel)

P2 (agent) — Trade forensics (only if P0A shows a viable mode)
```

**Important:** P0B should run first or in parallel. P0A is the main deliverable but its conclusions depend on knowing whether the bid/ask data is real.

---

## Phase P0B: rb3 Bid/Ask Data Validation (HUMAN-DRIVEN)

### Why this must be done

We have no evidence that rb3's `bid` and `ask` columns contain real published quotes from B3. They might be:

- **Real EOD quotes** from B3's official market-data feed — what we assumed
- **Computed estimates** like `close ± fixed_spread_pct` — would invalidate the entire bid/ask analysis
- **Last-traded prices** within a session — different from "best bid/ask at close"
- **Settlement prices** with implied spread — common for less liquid contracts

Until we know which, every conclusion that depends on `bid` or `ask` is suspect.

### The human-driven part

The coding agent can't open a browser and look at TradingView. This phase is yours to run. I'll write the protocol so it takes ~90 minutes total.

#### Step 1 — Pick the validation dates

Choose **10 dates** across the 2017–2025 window covering different market regimes:

| Date | Why |
|------|-----|
| 2017-05-19 | Post-Joesley Day (idiosyncratic vol spike — should see wide spreads) |
| 2018-10-31 | Bolsonaro election week (vol regime change) |
| 2019-10-15 | Normal mid-cycle trading day |
| 2020-03-12 | COVID crash worst day (spreads should be enormous) |
| 2020-09-15 | Mid-COVID recovery (high vol but stable) |
| 2021-05-12 | Normal post-vaccine trading |
| 2022-10-31 | Lula election day |
| 2023-08-15 | Normal trading, post-FX volatility |
| 2024-03-15 | Recent control date |
| 2024-12-19 | Year-end thin trading (spreads should be wide) |

#### Step 2 — Identify the BOVA11 options to spot-check

For each date, your coding agent needs to provide you with **two specific contracts**: the BOVA11 option closest to 16-delta put and the BOVA11 option closest to 16-delta call, both at the next monthly expiration. Have the agent run a small script that queries rb3 and outputs a CSV like:

```
date, type, strike, expiration, rb3_bid, rb3_ask, rb3_mark, rb3_delta, rb3_volume
2017-05-19, put,  56.0, 2017-06-19, 0.35, 0.45, 0.40, -0.16, 1240
2017-05-19, call, 64.0, 2017-06-19, 0.30, 0.40, 0.35, +0.16, 980
... (20 rows total: 10 dates × 2 options)
```

This file (`validation_targets.csv`) is what you'll manually look up.

#### Step 3 — Manual lookup in TradingView

TradingView has an "Options" feature for B3-listed names. Here's the protocol:

1. Open TradingView, navigate to BOVA11 (the cash ETF, not options)
2. Open the **Options chain** view (sidebar → Options, or right-panel toggle)
3. **Set the date** to the validation date using the historical chart cursor:
   - Open the chart, set timeframe to daily
   - Drag cursor to the date in question (e.g., 2017-05-19)
   - The option chain should display EOD values for that date
4. **Filter to the target expiration** (next month after the validation date)
5. **Locate the target strikes** from `validation_targets.csv`
6. **Record what TradingView shows**:
   - bid
   - ask
   - close (or last)
   - volume
   - delta if available
7. Save to a comparison CSV (`validation_comparison.csv`) with columns:

```
date, type, strike, rb3_bid, tv_bid, rb3_ask, tv_ask, rb3_close, tv_close, rb3_volume, tv_volume, notes
```

**Caveats about TradingView for B3 options:**

- TradingView's B3 option coverage is patchy historically. Pre-2019, expect some dates to have no data at all.
- The option chain in TradingView may show different fields than the cash chart. If you can't find a historical options chain view, try the desktop app's "DOM" panel set to the option symbol.
- Some option symbols in TradingView differ from rb3's encoding. BOVA11 calls/puts use the standard letter-strike codes (e.g., `BOVAH50` for August calls at strike 50). You may need to manually translate from rb3's strike+expiration to TradingView's contract symbol.
- For dates where TradingView doesn't have data, mark `tv_bid=NA, tv_ask=NA, notes="not available in TV"`. Don't drop the row; the absence is itself a signal.

**If TradingView coverage is too poor (>50% of rows are NA):**

- Brapi.dev's historical option chain endpoint (R$99.99/month) is the fallback. Single-month subscription is acceptable for this one-time validation.
- Alternative: search for a Brazilian quant finance forum/blog where someone has posted screenshots of historical BOVA11 option chains from a broker terminal (XP, Clear, BTG). This is haphazard but free.
- Last resort: contact a friend with a Bloomberg terminal and ask for 10 historical option snapshots. 30 minutes of someone else's time.

#### Step 4 — Pass/fail evaluation

After completing the lookup, compute three numbers from the comparison data:

**Metric 1: Bid match rate**
```
bid_match = 1 if abs(rb3_bid - tv_bid) / tv_bid < 0.10 else 0
% bid match = mean(bid_match) across non-NA rows
```
A 10% tolerance accounts for TradingView's possibly different quote source.

**Metric 2: Ask match rate** (same formula)

**Metric 3: Spread consistency**
```
rb3_spread = (rb3_ask - rb3_bid) / rb3_mark
tv_spread  = (tv_ask  - tv_bid)  / tv_close
% spread within 50%  = mean(abs(rb3_spread - tv_spread) / tv_spread < 0.50)
```

**Decision gate:**

| Outcome | Bid match % | Ask match % | Interpretation |
|---------|-------------|-------------|----------------|
| **PASS** | ≥80% | ≥80% | rb3 bid/ask are real quotes; trust execution modes |
| **PARTIAL** | 50-80% | 50-80% | rb3 quotes are real but possibly from a different feed or time-of-day; use with caution |
| **FAIL** | <50% | <50% | rb3 bid/ask are computed or unreliable; mid-price modes only |

If PARTIAL or FAIL, still run P0A but anchor conclusions on the `mid` and `synthetic` execution modes.

#### Step 5 — Document the result

Write findings to `research/2026-05-14 - rb3 bid-ask external validation.md`:

```markdown
# rb3 Bid/Ask External Validation

**Method:** Manual TradingView spot-check
**Sample:** 10 dates × 2 options = 20 contracts
**Coverage:** X of 20 contracts had TradingView data (Y% coverage)

## Results

- Bid match (±10%): X/20 (Z%)
- Ask match (±10%): X/20 (Z%)
- Spread consistency (±50%): X/20 (Z%)

## Decision

[PASS / PARTIAL / FAIL]

## Notes
- [Any contracts where rb3 and TV disagreed by more than 50%]
- [Dates where TV had no data]
- [Patterns observed]
```

---

## Phase P0A: Execution Price Sensitivity Scan

### Motivation

The V3 grid uses "sell at bid, buy at ask" — the worst possible execution. The other extreme (mid-price with -5%/+5% fill adjustment) gives synthetic-mode Sharpe of +1.08 vs market-mode -0.12. We need to find the realistic break-even.

### Execution Modes — REVISED with volume filter

Introduce a new parameter `execution_mode` with **5 levels** (originally 4, adding `volume_filtered`):

| Mode | Entry price | Close price | MTM price | Description |
|------|------------|-------------|-----------|-------------|
| `bid_ask` | bid | ask | ask | Current behavior (worst case) |
| `mid_minus_1tick` | mid - 1 tick | mid + 1 tick | mid + 1 tick | Conservative limit order |
| `mid` | mid | mid | mid | Fair fill |
| `mid_plus_1tick` | mid + 1 tick (credit) | mid - 1 tick (debit) | mid | Favorable limit order |
| `volume_filtered` | mid if volume ≥ daily median; skip otherwise | (same) | (same) | Realistic patient retail trader |
| `synthetic` | mid × (1+open_fill_adj) | mid × (1+close_fill_adj) | mid × (1+close_fill_adj) | Pure BSM (no DB) |

The `volume_filtered` mode is new and addresses a confound: B3 EOD quotes can be stale on low-volume days. A patient retail trader wouldn't blindly accept whatever bid/ask shows at 16:55; they'd skip the day or use a different entry timing. This mode encodes that behavior.

**B3 tick size:** R$0.05 for BOVA11 options with premiums ≥ R$1.00; R$0.01 below. Use a single `tick_size=0.05` default and let market presets override.

### Code Changes

#### 1. Add `execution_mode` and `tick_size` to `PricingParams` and presets

**File:** `src/straddle/params.py`

```python
# In PricingParams TypedDict:
execution_mode: str  # "bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick" | "volume_filtered" | "synthetic"
tick_size: float
volume_filter_min_pct: float  # for volume_filtered mode; option must have volume >= this percentile of daily distribution
```

```python
# In PRICING dict:
"execution_mode": "bid_ask",
"tick_size": 0.05,
"volume_filter_min_pct": 0.50,  # 50th percentile (median) — skip below-median volume days
```

```python
# In MARKET_PRESETS:
# spy:
"tick_size": 0.01,
# bova11:
"tick_size": 0.05,
# petr4:
"tick_size": 0.05,
```

#### 2. Modify `MarketEngine.get_entry_marks()` to handle all 5 modes

**File:** `src/straddle/engines.py`

```python
exec_mode = self._exec_mode
tick = self._tick_size

if exec_mode == "bid_ask":
    put_price = float(put_row["bid"])
    call_price = float(call_row["bid"])
    valid = put_price > 0 and call_price > 0
elif exec_mode == "volume_filtered":
    # Skip the entry entirely if either leg's volume is below the threshold
    put_vol_ok = float(put_row.get("volume", 0)) >= self._daily_vol_threshold
    call_vol_ok = float(call_row.get("volume", 0)) >= self._daily_vol_threshold
    if not (put_vol_ok and call_vol_ok):
        return None  # signal entry skip
    put_price = float(put_row["mark"])
    call_price = float(call_row["mark"])
    valid = True
elif exec_mode == "synthetic":
    put_price = self.apply_fill_adj(float(put_row["mark"]), "open")
    call_price = self.apply_fill_adj(float(call_row["mark"]), "open")
    valid = True
else:  # mid, mid_minus_1tick, mid_plus_1tick
    put_mid = float(put_row["mark"])
    call_mid = float(call_row["mark"])
    if exec_mode == "mid_minus_1tick":
        put_price = max(put_mid - tick, 0.01)  # sell slightly below mid (worse fill)
        call_price = max(call_mid - tick, 0.01)
    elif exec_mode == "mid_plus_1tick":
        put_price = put_mid + tick  # sell slightly above mid (favorable fill)
        call_price = call_mid + tick
    else:  # "mid"
        put_price = put_mid
        call_price = call_mid
    valid = True

return (float(put_row["strike"]), float(call_row["strike"]),
        put_price, call_price, valid)
```

**Handle the `volume_filtered` "skip" signal:** When `get_entry_marks` returns `None`, the strategy entry should be skipped without retrying. Add this handling in `build_entry()` so it returns `None` and the entry date is recorded as `vol_filtered_skip`. Add a new exit reason to track these.

#### 3. Initialize new attributes in `MarketEngine.__init__()`

```python
self._exec_mode = params.get("execution_mode", "bid_ask")
self._tick_size = params.get("tick_size", 0.05)
self._volume_filter_min_pct = params.get("volume_filter_min_pct", 0.50)

# Pre-compute daily volume threshold for volume_filtered mode
if self._exec_mode == "volume_filtered":
    self._daily_vol_threshold = self._compute_volume_threshold()
else:
    self._daily_vol_threshold = 0
```

```python
def _compute_volume_threshold(self) -> float:
    """Compute the median daily traded contracts for this underlying."""
    cur = self._conn.cursor()
    cur.execute("""
        SELECT volume FROM options_data
        WHERE underlying = ? AND volume > 0
    """, (self._underlying,))
    vols = [r[0] for r in cur.fetchall() if r[0] is not None]
    if not vols:
        return 0
    vols.sort()
    n = len(vols)
    idx = int(n * self._volume_filter_min_pct)
    return vols[min(idx, n - 1)]
```

#### 4. Modify `_strike_close_price()` and `get_leg_mark_with_source()` for consistency

These methods handle daily MTM and exit pricing. They must use the same `execution_mode`:

```python
# Pseudo-code for the close/exit price selection
if exec_mode == "bid_ask":
    close_price = float(row["ask"])  # buy back at ask
elif exec_mode == "volume_filtered":
    # On exit, always use mid (we already committed to the trade)
    close_price = float(row["mark"])
elif exec_mode == "mid_minus_1tick":
    close_price = float(row["mark"]) + tick  # buy slightly above mid (worse)
elif exec_mode == "mid_plus_1tick":
    close_price = max(float(row["mark"]) - tick, 0.01)  # buy slightly below mid (favorable)
else:  # mid, synthetic
    close_price = float(row["mark"])  # synthetic handled separately
```

Important: for `volume_filtered`, the volume check only applies to **entry**. Once in the trade, exits use mid-price unconditionally. Otherwise we'd skip exits on low-volume days, which is unrealistic.

#### 5. Update `apply_fill_adj` semantics

`MarketEngine.apply_fill_adj()` stays a no-op for all DB-sourced modes. The tick offset IS the fill model. Only when synthetic fallback fires does the call to `self._synth.apply_fill_adj()` matter, and that path is unchanged.

#### 6. Update `uses_real_fills` flag

```python
self.uses_real_fills = self._exec_mode in ("bid_ask", "volume_filtered")
```

#### 7. Add `execution_mode` to grid search

**File:** `scripts/grid_search.py`

```python
"execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick", "volume_filtered"]
```

Skip `"synthetic"` in the grid — it's identical to running `mode="synthetic"`.

In `_apply_grid_overrides()`:

```python
elif key == "execution_mode":
    overrides["execution_mode"] = val
```

### V4 Grid Specification

A reduced grid focused on execution sensitivity, not strategy re-exploration:

```python
GRID = {
    "target_delta": [0.16, 0.20, 0.25],
    "dte_max": [30, 45],
    "profit_target_pct": [0.50],
    "manage_at_dte": [7, 14],
    "vix_filter": ["OFF", "rv_pct:80"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [3.0],
    "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick", "volume_filtered"],
}
```

Total: 3 × 2 × 1 × 2 × 2 × 1 × 1 × 5 = **120 combos × 2 periods = 240 backtests**.

Runtime: ~5-7 minutes on 8 cores.

### Analysis to Produce

In `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb`:

1. **Sharpe vs execution_mode boxplot** — for train and holdout, show how Sharpe changes across all 5 modes. This is the single most important chart.

2. **Break-even execution level** — the leftmost execution mode (most pessimistic) where holdout median Sharpe crosses zero. If `mid_minus_1tick`, the strategy is viable with patient limit orders. If `mid`, it needs aggressive limit orders. If `mid_plus_1tick`, it needs exceptional execution. If never, it's structurally unviable.

3. **Sharpe by execution_mode × target_delta** — does the break-even point differ by delta selection? 16-delta has the most spread sensitivity (small premium, wide relative spread); 30-delta less so.

4. **Volume filter impact** — does `volume_filtered` (which uses mid prices but skips low-volume days) produce different results than pure `mid`? If yes, the EOD quote staleness is a real factor. If similar, the spread cost is the binding issue regardless of liquidity.

5. **Spread analysis** — for entries with DB data, compute `(ask - bid) / mark` distribution by delta bucket and year. Compare to the synthetic fill adjustment of 5%. If 16-delta spreads are >>10%, this quantifies the "spread eats premium" effect.

6. **Per-trade P&L comparison under each mode** — for a single config (delta=0.20, dte=30, profit=0.50, manage=14, vix_filter=OFF), show trade-by-trade P&L for all 5 execution modes side-by-side. Is the gap uniform, or concentrated in specific market events?

7. **Volume filter skip rate** — what % of monthly entries does `volume_filtered` skip? If it's <5%, the volume issue is rare. If >30%, the strategy as designed is misaligned with B3 liquidity (and the v3 conclusion may be partly a liquidity artifact).

### Decision Tree (Combined P0A + P0B Outcomes)

| P0B result | P0A `bid_ask` Sharpe | P0A `mid` Sharpe | P0A `volume_filtered` Sharpe | Conclusion |
|-----------|---------------------|-------------------|-----------------------------|------------|
| PASS | <0 | ≥0 | ≥0 | **VRP exists; strategy needs limit-order execution to capture it.** |
| PASS | <0 | <0 | <0 | **Strategy is structurally unviable across all realistic execution modes.** v3 conclusion confirmed. |
| PASS | <0 | ≥0 | <0 | **VRP exists but only on liquid days that the strategy currently selects.** Investigate volume distribution and entry timing. |
| PASS | ≥0 | ≥0 | ≥0 | **Strategy is viable even at worst-case execution.** This would be surprising; double-check engine. |
| PARTIAL | — | ≥0 | ≥0 | **Mid-price viability suggests VRP exists; bid/ask result is unreliable.** Need better bid/ask source before live trading. |
| PARTIAL | — | <0 | <0 | **Even at mid (reliable input), strategy is unviable.** v3 conclusion essentially confirmed. |
| FAIL | — | ≥0 | ≥0 | **Mid-price suggests VRP exists; need new data source to model execution.** |
| FAIL | — | <0 | <0 | **Strategy unviable at mid-price regardless of bid/ask quality.** v3 conclusion confirmed. |

The key insight: **`mid` and `synthetic` modes give the answer that doesn't depend on bid/ask quality**. If those produce positive Sharpe, the strategy has merit and the only question is execution. If they don't, the strategy is unviable independent of any data validation question.

---

## Phase P1: American vs European Option Pricing Verification

(Unchanged from original plan — quick code check)

### Steps

1. Verify BOVA11 option style. BOVA11 is an ETF; B3 ETF options are European cash-settled. Confirm in B3 documentation. Confirm `"american_options": False` in BOVA11 preset.

2. Quick sensitivity test: Run a single backtest with `american_options=True` and `mode="synthetic"` for train period. Compare net_credit and Sharpe against `american_options=False`. The difference should be small (OTM puts have low early-exercise value).

3. Add a cell to the v4 notebook comparing `american_options=True` vs `False`. If the difference is <1% of P&L, ignore it.

---

## Phase P2: Individual Trade Forensics

(Slightly modified — now run on the **best execution mode** identified by P0A, not blindly on bid_ask)

### Motivation

Aggregate statistics tell us if the strategy is positive or negative. Trade forensics tells us *why*. Three failure modes look the same in aggregate:

A. Many small losses from spread costs (execution-based)
B. Few large losses from gap events (tail risk)
C. Systematic theta loss (vega/IV regime)

The fix is different for each.

### Steps

1. Identify the **best holdout config from P0A** (highest Sharpe across the 5 execution modes).

2. Re-run that config and produce a per-trade output with:
    - entry_date, exit_date, exit_reason
    - net_credit at entry
    - max_loss_during_trade (worst MTM)
    - net_pnl at exit
    - entry_source (db vs synthetic)
    - execution_mode

3. Sort trades by P&L. Look at:
    - The 5 worst trades (largest losses): are they concentrated on specific dates (gap events) or spread across the period?
    - The 5 best trades: do they have any common pattern (vol regime, DTE at entry)?
    - The median trade: is the typical outcome small positive or small negative?

4. Compute the **spread cost contribution**: for each trade, compute the difference between bid_ask P&L and mid P&L. Average across all trades. This is the "tax" that execution imposes.

### Deliverable

A section in the v4 notebook with these per-trade tables and a one-paragraph summary.

---

## Definition of Done

This v4 work is complete when:

1. **P0B is complete:** A `research/2026-05-14 - rb3 bid-ask external validation.md` exists with PASS/PARTIAL/FAIL result and 10+ comparison data points.
2. **P0A is complete:** A grid search of 240 backtests has run across 5 execution modes; the boxplot of Sharpe vs execution_mode is rendered.
3. **The decision tree gives a clear conclusion** about strategy viability at each execution level.
4. **P1 confirms American/European pricing assumption.**
5. **P2 produces a per-trade forensic for the best config.**

If after all this the answer is "strategy is unviable at mid-price even on liquid days," then we have a defensible conclusion to stop. If the answer is "strategy is viable at mid but not at bid_ask," then the next research question is how to model and achieve mid-like execution in live paper trading.

---

## Files to Produce

```
src/straddle/
  params.py                                # +execution_mode, +tick_size, +volume_filter_min_pct
  engines.py                               # MarketEngine handles 5 execution modes
  strategy.py                              # handle volume_filtered skip signal

scripts/
  build_validation_targets.py              # NEW — outputs validation_targets.csv for human lookup
  grid_search.py                           # +execution_mode dimension

research/
  2026-05-14 - rb3 bid-ask external validation.md      # NEW — human-produced
  2026-05-14 - B3 - v4 execution sensitivity.ipynb     # NEW — main analysis

output/
  validation_targets.csv                   # NEW — input to human lookup
  validation_comparison.csv                # NEW — output of human lookup
  v4_grid_search_results.parquet           # NEW — 240-row grid output

tests/
  test_engines.py                          # +tests for each execution mode
```

---

## Risks and Mitigations

1. **TradingView coverage is too sparse for older dates.** Mitigation: use 2020-2025 dates only if pre-2020 coverage is missing. The conclusions matter for the post-COVID period anyway.

2. **Volume filter skips too many entries.** Mitigation: if `volume_filtered` skips >40% of monthly entries, lower `volume_filter_min_pct` to 0.25 (25th percentile) and re-run. Document the trade-off.

3. **P0A and P0B disagree** (e.g., P0B says PASS but P0A `mid` shows positive Sharpe while `bid_ask` shows deeply negative). Mitigation: this is informative, not contradictory — it tells us the bid/ask data is real but the spreads themselves are unusually wide on B3 single-name options. Document and proceed.

4. **The agent introduces a bug in the execution_mode dispatch.** Mitigation: write unit tests for each mode before running the grid. The test should verify that on a known trade with known prices, each mode produces the expected entry credit.
