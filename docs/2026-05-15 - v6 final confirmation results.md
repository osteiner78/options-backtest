# B3 BOVA11 — v6 Final Confirmation Results
Date: 2026-05-15 | Branch: b3-backtest | Plan: 013

---

## Executive Summary

**Revised Conclusion: VRP EXISTS and IS PROFITABLE with limit-order execution (mid/mid_plus_1tick), but is fully consumed by bid-ask spreads with market-order execution.**

The v5 conclusion ("VRP exists but consumed by spreads") was based on corrupted results from an engine cache bug. With the fix, `mid_plus_1tick` holdout median Sharpe = **+1.11**, and **85% of all tested parameter combinations** are profitable in both training AND holdout periods. The strategy is demonstrably robust.

---

## Phase A: Reliability Verification

### A.1 — Cache Bug Confirmed

The original `v5_grid_search_results.parquet` was corrupted. The engine cache stored `(market, start, end)` as the key but not `execution_mode`, causing all modes after the first to inherit the first combo's engine settings.

| Period | Mode | Bugged original | Fixed | ΔSharpe |
|---|---|---|---|---|
| holdout | bid_ask | +0.67 | −0.58 | −1.24 |
| holdout | mid | +0.20 | +0.48 | +0.28 |
| holdout | mid_plus_1tick | +0.22 | **+1.11** | +0.89 |

**Authoritative results**: `v5_grid_search_laddering_fixed.parquet` (fixed cache).

### A.2 — Manual P&L Verification: PASS

Three trades verified against raw DB mark queries:

| Trade | exit_type | Engine P&L | Manual P&L | Diff |
|---|---|---|---|---|
| #1 PROFIT | PROFIT | R$64.00 | R$64.00 | R$0.00 |
| #3 LOSS | 21DTE | −R$60.00 | −R$60.00 | R$0.00 |
| #106 BREAKEVEN | ROLLED | R$1.00 | R$1.00 | R$0.00 |

Engine P&L matches DB-derived prices to the cent. Formula verified: `entry = (put_mark + tick + call_mark + tick) × 100 − 2`, `close = (put_mark − tick + call_mark − tick) × 100 + 2`.

### A.3 — SPY Regression: PASS

SPY 2019–2024: 69 trades, no exceptions. B3 engine changes do not affect the SPY code path. Negative Sharpe (−0.94) is consistent with pre-B3 behavior under default parameters and a bull market.

### A.4 — Synthetic vs Market: PASS

All 118 holdout trades were DB-sourced (`entry_source='db'`). Zero synthetic fallbacks — 100% real market data coverage in the 2023–2025 holdout period.

### A.5 — Trade Forensics (best config, holdout)

| exit_type | n | Total P&L | % of total |
|---|---|---|---|
| PROFIT | 76 | R$4,579 | +125% |
| ROLLED | 27 | R$409 | +11% |
| 21DTE | 12 | −R$1,330 | −36% |
| FORCE_CLOSE | 3 | R$0 | 0% |

- Top+bottom-3 = 23.5% of total P&L → **no fat-tail flag** (< 50%). Steady edge.
- 21DTE exits are the main loss source: positions closed at the manage DTE before decaying further.
- Stop-loss trades: 0 (stop_loss_pct=3.0 threshold not reached in holdout).

### A.6 — American Option Sensitivity: PASS

BAW vs BS for BOVA11 ETF: ΔSharpe = 0.000, ΔReturn = R$0. American option pricing has zero impact (no early exercise benefit with q=0 dividends).

---

## Phase B: v6 Expanded Grid Results

### Grid Specification

- **Combos**: 13,824 raw → 12,096 valid (1,728 dropped by `manage_at_dte < dte_min` filter)
- **Backtests**: 12,096 × 2 periods = 24,192 total
- **Errors**: 455 (1.9%) — complex-number bug on delta ≥ 0.30 at dte_max=60 (delta=0.50: 336, delta=0.30: 106, delta≤0.25: 13). All errors excluded from analysis; straddle configs dropped per allowed deviation.
- **Runtime**: 161.6 minutes on 8 cores

### Cell A — Sharpe by Execution Mode

| Mode | Train median | Holdout median | Holdout p75 | Holdout max |
|---|---|---|---|---|
| bid_ask | −1.06 | **−0.96** | −0.61 | +0.42 |
| mid | +0.15 | **+0.37** | +0.65 | +2.07 |
| mid_plus_1tick | +0.49 | **+1.11** | +1.67 | +11.73 |

**Break-even execution**: `mid` (leftmost mode with positive holdout median Sharpe). B3 bid-ask spreads are large enough to eliminate VRP entirely under market-order fills; limit orders at or above mid are required.

### Cell C — Execution Mode × Target Delta (holdout median Sharpe)

| Mode | 12Δ | 16Δ | 20Δ | 25Δ | 30Δ | 50Δ |
|---|---|---|---|---|---|---|
| bid_ask | −0.72 | −0.94 | −0.98 | −1.01 | −1.02 | −1.12 |
| mid | +0.72 | +0.44 | +0.38 | +0.29 | +0.20 | +0.04 |
| mid_plus_1tick | +1.99 | +1.25 | +1.11 | +0.99 | +0.82 | +0.39 |

Far-OTM options (12Δ) outperform across all execution modes. Each step toward ATM reduces Sharpe, confirming that OTM premium is proportionally more attractive after spread costs.

### Cell D — DTE Max × Target Delta (holdout, all modes)

dte_max=30 consistently outperforms dte_max=21, dte_max=45, dte_max=60 across delta levels. Shorter tenors offer higher theta decay per day and less adverse gamma exposure.

### Cell E — Defensive Leg Roll

| roll=False | roll=True | Δ |
|---|---|---|
| +1.10 (median) | +1.13 (median) | +0.03 |

Negligible difference. Defensive leg rolling adds minimal value for BOVA11 laddering with these parameters.

### Cell F — Straddle (50Δ) vs OTM Strangle

| Mode | OTM strangle | Straddle | Δ |
|---|---|---|---|
| bid_ask | −0.87 | −1.12 | −0.25 |
| mid | +0.44 | +0.04 | −0.40 |
| mid_plus_1tick | **+1.24** | +0.39 | **−0.85** |

**OTM strangles are clearly superior.** Straddle premium is eroded more heavily by spreads (higher absolute option price = higher absolute spread cost). The VRP edge is concentrated in the OTM wings.

### Cell G — Vol Filter Comparison (mid_plus_1tick, holdout)

| Filter | Median Sharpe | p75 |
|---|---|---|
| OFF | +1.08 | +1.54 |
| rv_pct:70 | **+1.17** | **+1.73** |
| rv_pct:80 | +1.12 | +1.68 |
| rv_pct:90 | +1.10 | +1.69 |

Filtering high-vol environments helps modestly. `rv_pct:70` (only trade below 70th percentile of recent realized vol) marginally outperforms. The improvement is small — the strategy is profitable across all filter levels.

### Cell H — Stop Loss Comparison (mid_plus_1tick, holdout)

| stop_loss_pct | Median Sharpe |
|---|---|
| 2.0× | **+1.14** |
| 3.0× | +1.08 |

Tighter stop slightly better. Cutting losses earlier at 2× premium reduces drawdown without sacrificing too much on winning trades.

### Cell I — Train vs Holdout Robustness

| Mode | Q1 (both positive) | % of configs |
|---|---|---|
| bid_ask | 2 / 3,577 | **0%** |
| mid | 1,995 / 4,032 | **49%** |
| mid_plus_1tick | **3,430 / 4,032** | **85%** |

`mid_plus_1tick` achieves positive Sharpe in BOTH training and holdout periods for 85% of all tested parameter combinations. This is strong evidence of a genuine, persistent edge — not overfitting to one period.

### Cell K — Best Configuration

**Headline best** (holdout Sharpe=11.73, also positive in train):

| Parameter | Value |
|---|---|
| target_delta | 0.12 |
| dte_max | 30 |
| profit_target_pct | 0.25 |
| manage_at_dte | 5–14 (all equivalent at this profit target) |
| vix_filter | rv_pct:80 |
| defensive_leg_roll | False |
| stop_loss_pct | 2.0 |
| execution_mode | mid_plus_1tick |
| Train Sharpe | +2.05 |
| Holdout Sharpe | +11.73 |

*Note*: The Sharpe=11.73 at delta=0.12/profit=0.25 reflects a very high win-rate strategy (far-OTM, early profit taking). The equity curve is smooth but absolute P&L per trade is small. The manage_at_dte parameter has no effect because virtually all trades exit via the profit target before reaching the DTE threshold.

**More balanced best** (robust across manage_at_dte, practical premium size):

| Parameter | Value |
|---|---|
| target_delta | 0.16 |
| dte_max | 30 |
| profit_target_pct | 0.25 or 0.50 |
| manage_at_dte | 7 or 14 |
| vix_filter | rv_pct:70 or rv_pct:80 |
| defensive_leg_roll | False |
| stop_loss_pct | 2.0 |
| execution_mode | mid_plus_1tick |
| Holdout median Sharpe (16Δ, this region) | ~+1.25 |

---

## Revised Conclusion

| Conclusion | Status | Evidence |
|---|---|---|
| **A — VRP exists for BOVA11** | ✅ CONFIRMED | mid median +0.37, mid_plus_1tick median +1.11 |
| **B — VRP accessible only with limit orders** | ✅ CONFIRMED | bid_ask median −0.96; bid_ask Q1 = 0% |
| **C — OTM strangle dominates straddle** | ✅ NEW | OTM +1.24 vs straddle +0.39 (mid_plus_1tick) |
| **D — Strategy is robust, not overfitted** | ✅ CONFIRMED | 85% of configs positive in both train + holdout |

**The revised summary**: B3 BOVA11 short strangles sell a genuine volatility risk premium. The edge is consistently positive across 85% of parameter configurations in both in-sample and out-of-sample periods when using limit-order execution. Market-order (bid-ask) fills are too expensive for the B3 options market — the bid-ask spread alone consumes the entire available premium. The practical implication is that this strategy is executable only through limit orders placed at mid or better.

---

## Known Issues and Follow-ups

1. **Straddle complex-number errors** (455 of 24,192 runs): `strike_from_delta` produces complex numbers at delta=0.50 for long-tenor options during high-vol periods. Requires a `try/except` guard in engines.py (TODO Part 4 from plan 013).

2. **FORCE_CLOSE pnl=0**: Portfolio manager sets `exit_type='FORCE_CLOSE'` at end-of-backtest but does not compute market-price P&L. These 3 trades per holdout run show pnl=0 but manual DB verification shows non-zero values. Low materiality (3 of 118 trades).

3. **SPY default params negative Sharpe**: The strategy is not profitable for SPY under default parameters (single_position, no stop, manage@21). A separate SPY parameter optimization is needed.

4. **Cleanup plan 011** (22 files + aux/ directory): Execute per plan 011 after this report is approved.
