# Post-v7 Follow-up Investigations — Results

**Date:** 2026-05-15  
**Branch:** b3-backtest  
**Commit:** 3356b96  
**Plan:** `.agent/plans/015-post-v7-follow-up-investigations.md`

---

## Phase 1: Force-close P&L Fix — Impact Assessment ✅ COMPLETE

**Config tested:** 25Δ/dte21/pt50%/mid/laddering, holdout 2023-01-02 to 2025-11-30

**Result:**
- Total trades: 134
- Force-closed: **1 (0.7%)** — threshold: 5%
- Force-close P&L: **R$29.00 (0.8% of total)** — threshold: 2%

**Decision: No re-run needed.** The Phase 5 force-close P&L fix is immaterial to v7 grid results.

---

## Phase 2: 16Δ Compromise Deep-dive ✅ COMPLETE

**Config:** 16Δ / dte21 / pt50% / rv_pct:70 / stop_loss=3.0 / mid

### 2.1 Standalone Results
| Period | n | Sharpe | Return | MDD |
|--------|---|--------|--------|-----|
| Train (2018–2022) | 171 | 0.593 | 46.5% | -3.33% |
| Holdout (2023–2025) | 113 | **1.883** | 59.2% | -1.35% |

### 2.2 Liquidity
| Config | Mean Spread/Mark | Legs >30% |
|--------|----------------|----------|
| 16Δ (holdout) | **33.4%** | 37.7% |
| 25Δ (holdout) | **20.3%** | — |

**Gate:** 33.4% ≤ 35% → tradeable at mid. (64% wider than 25Δ — meaningful liquidity cost.)

### 2.3 Manual P&L Verification
4 of 4 trade types verified. Consistent R$4.00 offset = 4 × commission_per_leg (expected).

### 2.4 Metrics Comparison (holdout)
| Metric | 16Δ | 25Δ | Δ |
|--------|-----|-----|---|
| Sharpe | **1.883** | 1.292 | +0.591 |
| Win rate | 82.8% | 77.6% | +5.2pp |
| MDD | -1.35% | -1.92% | better |
| Train Sharpe | 0.593 | 0.908 | **-0.315** |

### 2.5 Commission Sensitivity (16Δ holdout)
| Commission | Sharpe |
|-----------|--------|
| 1× | 1.883 |
| 2× | 1.593 |
| 3× | **1.341** (still positive) |

### 2.6 Verdict
16Δ is **practicably tradeable at mid** but is notably less liquid than 25Δ (spread/mark 33% vs 20%). The holdout Sharpe premium (+0.591) is real, but the weaker train stability (0.593 vs 0.908) means more regime sensitivity. Recommended path: start at 25Δ, upgrade to 16Δ after demonstrating consistent mid-fill execution.

**Expected Sharpe degradation if 30% of fills happen at bid:**
- 16Δ: losing ~30% of net_credit × 30% = roughly -0.3 to -0.5 Sharpe units
- Compared to 25Δ which has tighter spreads and less sensitivity to execution shortfall

---

## Phase 3: Grid Degeneracy Documentation ✅ COMPLETE

### 3.1 Quantification
- 50 of 768 grid groups (6.5%) have degenerate results
- All 50 degenerate groups are in `mid_plus_1tick` at `profit_target_pct=0.25`
- Degeneracy: all trades exit via PROFIT before any `manage_at_dte` or `stop_loss_pct` activates

**Canonical example:** 12δ/dte30/pt25%/rv_pct:80/mid_plus_1tick → 6 identical rows with Sharpe=11.557057 (confirmed)

### 3.2 Cell L Added
Two cells added to `research/2026-05-15 - B3 - v7 refined grid.ipynb`:
- Markdown cell: explanation + mechanism description
- Code cell: full quantification with degeneracy table

---

## Phase 4: PETR4 Analysis — PILOT COMPLETE, FULL GRID IN PROGRESS ⏳

### 4.1 Pilot Results (18 backtests)
| Mode | Train median | Holdout median |
|------|-------------|---------------|
| bid_ask | -0.878 | -0.835 |
| **mid** | +0.024 | **+0.877** |
| mid_plus_1tick | +1.861 | +2.401 |

**Individual config results (holdout):**

| Config | bid_ask | mid | mid+1tick |
|--------|---------|-----|----------|
| 25Δ/dte21/pt50%/OFF | -1.166 | **1.211** | 2.377 |
| 20Δ/dte21/pt50%/rv:80 | -0.766 | **0.729** | 2.401 |
| 16Δ/dte21/pt50%/rv:70 | -0.835 | **0.877** | 3.908 |

**Decision gate: PROCEED.** Mid holdout median 0.877 > 0 → run full grid.

### 4.2 PETR4-specific Considerations
- PETR4 is a single stock → higher idiosyncratic vol, different VRP characteristics
- American exercise (BAW pricing) enabled — ΔSharpe vs European was 0.0 for BOVA11 but PETR4 puts may have early exercise value in extreme downmoves
- `dividend_yield=0.0` (B3 preset default) — PETR4 pays dividends; if material, may slightly undervalue the put vs fair value. Flag for follow-up.
- bid_ask mode consistently negative (spread consumes all premium) — same pattern as BOVA11

### 4.3 Full Grid Status
Running in background: `conda run -n backtest python3.11 scripts/phase4_petr4_full_grid.py`
Output: `data/B3/v7_petr4_grid_search_results.parquet`
Report pending — see `015-phase-4-end.md` when complete.

---

## Phase 5: Max-Drawdown Stress Scenarios ✅ COMPLETE

**Full period: 2018-01-02 to 2025-11-30**

### 5.1 Worst 6-Month Windows

| Config | Window | 6M Return | Intra-MDD |
|--------|--------|----------|----------|
| 25δ/mid | 2022-01-24 to 2022-08-16 | **-3.70%** | -4.20% |
| 16δ/mid | 2018-04-19 to 2018-12-26 | **-3.13%** | -3.33% |
| 12δ/mid+1tick | 2018-03-22 to 2019-03-27 | **+0.02%** | -0.84% |

25δ/mid worst cluster: Jan–Aug 2022 (BOVA11 rate-hike drawdown). All three worst windows for 25δ are in the same period.

### 5.2 Gap Events
**None detected** (no daily MTM drop >5% in any config over the full period).

### 5.3 Interpretation
Maximum realistic drawdown for the recommended 25δ/mid config: **~4.2% of capital** over 6 months. This is well within margin safety buffers. The strategy's small per-trade premium and 50% profit target naturally limit concentrated tail exposure.

---

## Summary of Findings

| Investigation | Result | Action |
|--------------|--------|--------|
| Force-close P&L fix | Immaterial (0.7% trades, 0.8% P&L) | No re-run |
| 16Δ practicability | Tradeable (spread 33.4% < 35% gate) | Viable upgrade |
| Grid degeneracy | 6.5% of groups | Documented in notebook |
| PETR4 VRP | Positive! Mid median 0.877 | Full grid running |
| Stress scenarios | Max -4.2% over 6M, no gap events | No tail risk flagged |

---

*Full grid and Phase 4 report pending.*
