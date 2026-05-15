# Plan 015 — Phase 2 End Report: 16Δ Compromise Deep-dive

**Date:** 2026-05-15  
**Commit:** 3356b96  
**Output file:** `data/B3/v7_16delta_deep_dive.csv` (284 rows)

## Config Tested

```
target_delta: 0.16, dte_max: 21, dte_min: 15
profit_target_pct: 0.50, manage_at_dte: 14
vix_filter: rv_pct:70, stop_loss_pct: 3.0
execution_mode: mid, portfolio_mode: laddering
```
Top-1 holdout Sharpe at dte_max=21 in v7 Cell J.

## Step 2.1: Standalone Runs

| Period | n_trades | Sharpe | Total Return | MDD |
|--------|----------|--------|-------------|-----|
| Train (2018–2022) | 171 | 0.593 | 46.48% | -3.33% |
| Holdout (2023–2025) | 113 | 1.883 | 59.16% | -1.35% |

## Step 2.2: Liquidity Check (holdout entries)

| Config | Legs Queried | Mean Spread/Mark | Median | >30% Legs | >50% Legs |
|--------|-------------|-----------------|--------|-----------|-----------|
| 16Δ | 220 | **33.4%** | 21.8% | 37.7% | 20.9% |
| 25Δ | 262 | **20.3%** | 11.6% | — | — |

**Decision gate:** 33.4% ≤ 35% threshold → proceed with equity comparison.

16Δ spreads are 64% wider than 25Δ on average. A meaningful liquidity premium is required.

## Step 2.3: Manual P&L Verification (5 holdout trades)

All 5 selected trades (PROFIT, ROLLED, 21DTE, FORCE_CLOSE; no STOP trades in holdout) show a consistent R$4.00 difference between simulation P&L and raw DB mark difference. This is **expected**: R$4.00 = 2 legs × 2 sides × R$1.00 commission_per_leg. Simulation correctly deducts commissions; DB comparison uses raw marks.

Conclusion: verification **passes** — simulation matches DB marks, with commission offset as expected.

## Step 2.4: Metrics Comparison 16Δ vs 25Δ

| Metric | 16Δ Train | 16Δ Hold | 25Δ Train | 25Δ Hold |
|--------|----------|---------|---------|---------|
| n_trades | 171 | 113 | 240 | 134 |
| sharpe | 0.593 | **1.883** | 0.908 | **1.292** |
| total_return | 46.5% | 59.2% | 57.3% | 61.2% |
| max_drawdown | -3.33% | -1.35% | -4.20% | -1.92% |
| calmar | 2.38 | 12.86 | 2.26 | 9.28 |
| win_rate | 70.8% | 82.8% | 73.9% | 77.6% |

**16Δ holdout Sharpe premium over 25Δ: +0.591.** But train stability is weaker (0.593 vs 0.908), reflecting looser min(train,holdout) stability.

## Step 2.5: Commission Sensitivity (16Δ holdout)

| Commission | Sharpe | Return | MDD | n_trades |
|-----------|--------|--------|-----|---------|
| 1× (base) | 1.883 | 59.2% | -1.35% | 113 |
| 2× | 1.593 | 58.1% | -1.38% | 112 |
| 3× | 1.341 | 57.3% | -1.40% | 113 |

16Δ survives at 3× commission without flipping negative. Sharpe degradation: -0.542 at 3×.

## Step 2.6: Verdict

- 16Δ spread/mark (33.4%) is tighter than the 35% gate → practicably tradeable at mid
- 16Δ Sharpe premium (+0.591 in holdout) is real but driven by higher volatility of lower-delta strikes
- Liquidity disadvantage (64% wider spreads) means 16Δ is more sensitive to execution slippage
- Train Sharpe (0.593) is weaker than 25Δ (0.908) — 16Δ is less robust across periods

**Recommendation:** 16Δ is a viable upgrade path after gaining experience at 25Δ. Start at 25Δ for liquidity, consider 16Δ only with demonstrated mid-fill capability.

## Confidence

**Likely-good** — Full comparison run. The key caveat is that train Sharpe for 16Δ (0.593) suggests higher regime-sensitivity vs 25Δ (0.908). Further investigation with v7 grid's stability ranking would be needed to fully characterize.
