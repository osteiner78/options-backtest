# Plan 015 — Phase 5 End Report: Max-Drawdown Stress Scenarios

**Date:** 2026-05-15  
**Commit:** 3356b96  
**Output file:** `data/B3/v7_stress_scenarios.csv` (9 rows)

## Configs Tested (full period 2018-01-02 to 2025-11-30)

| Config | n_trades |
|--------|---------|
| 25δ/mid | 374 |
| 16δ/mid | 280 |
| 12δ/mid+1tick | 239 |

## Step 5.1: Worst 3 Six-Month Rolling Windows

### 25δ / mid (recommended config)

| Window Start | Window End | 6-Month Return | Intra-Window MDD |
|-------------|-----------|--------------|-----------------|
| 2022-01-24 | 2022-08-16 | **-3.70%** | -4.20% |
| 2022-01-21 | 2022-08-15 | -3.50% | -4.13% |
| 2022-01-20 | 2022-08-12 | -3.48% | -4.13% |

All worst windows cluster around Jan–Aug 2022 (post-COVID rate-hike volatility spike).

### 16δ / mid

| Window Start | Window End | 6-Month Return | Intra-Window MDD |
|-------------|-----------|--------------|-----------------|
| 2018-04-19 | 2018-12-26 | **-3.13%** | -3.33% |
| 2021-11-16 | 2022-06-28 | -1.70% | -2.09% |
| 2021-11-12 | 2022-06-27 | -1.70% | -2.09% |

### 12δ / mid_plus_1tick

| Window Start | Window End | 6-Month Return | Intra-Window MDD |
|-------------|-----------|--------------|-----------------|
| 2018-03-22 | 2019-03-27 | **+0.02%** | -0.84% |
| 2018-03-29 | 2019-04-03 | +0.04% | -0.84% |
| 2018-02-28 | 2019-03-25 | +0.07% | -0.84% |

12δ config's "worst" 6-month windows are all mildly positive. Consistent with the ultra-high Sharpe and tight profit targeting.

## Step 5.2: Gap Events (>5% MTM Daily Drop)

**None detected** for any of the three configs over the full 2018–2025 period.

This is expected: the overshoot model caps extreme-event P&L via gap pricing, and the strategy's small premium per trade (R$~1-4 per share) limits single-day MTM exposure. No daily MTM drop exceeded 5% of initial capital in any configuration.

## Step 5.3: Summary Assessment

| Config | Worst 6M Return | Worst Intra-MDD | Gap Events |
|--------|----------------|----------------|-----------|
| 25δ/mid | -3.70% | -4.20% | None |
| 16δ/mid | -3.13% | -3.33% | None |
| 12δ/mid+1tick | +0.02% | -0.84% | None |

**Key finding:** All configs show very contained drawdowns. The worst scenario for the recommended 25δ/mid config is a ~4% drawdown during the Jan–Aug 2022 rate-hike period — well within manageable risk parameters. No catastrophic tail events detected.

**Caveat:** The 2018 train data period has lower DB coverage (~65%), so the 25δ/mid worst window (2022) is more reliable than the 16δ/mid worst window (2018) which may be partially synthetic-engine-based.

## Confidence

**Likely-good** — Computed from the same trade simulation used throughout the research. Gap event detection relies on MTM equity from daily_marks, which has been verified against DB in prior phases.
