# Phase 6 End — Period Robustness Complete

**Date:** 2026-05-15
**Backtests:** 225 (15 configs × 5 windows × 3 modes)

---

## Setup

**Top 15 configs** (by min(train,holdout) Sharpe at mid from Phase 3 Cell K)  
**5 rolling 3-year windows:**

| Window | entry_db_pct (mid) | DB Coverage |
|--------|-------------------|-------------|
| 2015-2017 | **22.5%** | Synthetic-dominant (<30%) ⚠ |
| 2016-2018 | 41.0% | Mixed |
| 2018-2020 | 64.8% | Moderate |
| 2020-2022 | 84.5% | Good |
| 2022-2024 | 99.5% | Near-complete |

---

## Results — % Positive Sharpe by Mode

| Mode | % Positive | Median Sharpe | Plan Target | Met? |
|------|-----------|--------------|------------|------|
| bid_ask | 4.0% | -0.814 | < 50% | ✓ |
| mid | **78.7%** | **0.514** | > 50% | ✓ |
| mid_plus_1tick | **89.3%** | **1.296** | > 70% | ✓ |

All three plan targets exceeded.

---

## By Window (mid execution)

| Window | % Positive | Median Sharpe | Note |
|--------|-----------|--------------|------|
| 2015-2017 | 53.3% | 0.071 | ⚠ Synthetic-dominant (22.5% DB) |
| 2016-2018 | 40.0% | -0.093 | Mixed DB coverage (41%) |
| 2018-2020 | 100.0% | 1.030 | Good DB coverage |
| 2020-2022 | 100.0% | 0.820 | Good |
| 2022-2024 | 100.0% | 1.090 | Near-complete DB |

---

## Key Findings

**1. Strong robustness in 2018–2024 (3 windows):** Every single config-window pair is profitable at mid in 2018–2024. This covers the COVID crash (2020), Brazil's election volatility (2022), and the post-pandemic normalization.

**2. 2016–2018 is the weak window (40% positive):** This window has 41% DB coverage, meaning ~59% of entry P&L comes from the synthetic engine. Whether this represents actual market conditions or synthetic model limitations is unclear. Results should be viewed cautiously for this period.

**3. 2015–2017 is synthetic-dominant (22.5% DB):** Per plan, results from this window should be flagged. The 53.3% positive rate might be driven by synthetic model assumptions rather than real market behavior. However, the 2015-2017 bova11 DB has limited coverage from inception.

**4. The VRP is period-robust:** Across all 5 windows, 78.7% of config-window pairs are profitable at mid. The 3 most data-complete windows (2018–2024) show 100% profitability. The strategy is not a one-period artifact.

**5. mid_plus_1tick shows 89.3% robustness** but remains execution-sensitive — the higher Sharpe assumes favorable mid+1tick fills which may not be consistently achievable.

---

## Note on 2015-2017 Window

Per plan: "If DB coverage is < 30% for this period, flag it in the report and use a shorter window (2016-2018) if possible." 
- 2015-2017 coverage: 22.5% → flagged as synthetic-dominant ⚠
- 2016-2018 coverage: 41% → included but with caveat
- Both early windows (pre-2018) should be treated as lower-confidence results

---

## Confidence Rating: **likely-good**

225/225 runs completed, 0 errors. The robustness claim (>50% positive at mid) is soundly supported for 2018-2024. The 2016-2018 window slightly underperforms (40%) which could be real or synthetic-model artifacts — flagged per plan instructions.
