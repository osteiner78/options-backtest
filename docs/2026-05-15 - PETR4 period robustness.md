# PETR4 Period Robustness

**Date:** 2026-05-15  
**Configs:** 15 top stable from v7  
**Windows:** 5 rolling 3-year periods 2015-2024  
**Total backtests:** 225

---

## Overall (all windows, all configs)

| Mode | % Positive | Median Sharpe | Plan target |
|------|-----------|--------------|------------|
| bid_ask | 17.3% | -0.527 | <50% |
| mid | 80.0% | 0.366 | >50% |
| mid_plus_1tick | 98.7% | 1.827 | >70% |

## By Window (mid execution)

| Window | % Positive | Median Sharpe | DB Coverage |
|--------|-----------|--------------|-------------|
| 2015-2017 | 66.7% | 0.089 | 25.6% |
| 2016-2018 | 40.0% | -0.171 | 43.1% |
| 2018-2020 | 93.3% | 0.263 | 60.9% |
| 2020-2022 | 100.0% | 0.747 | 82.9% |
| 2022-2024 | 100.0% | 1.066 | 96.9% |

## Recommended Config (25d/dte21/pt50%/OFF) by Window

| Window | bid_ask | mid | mid_plus_1tick | DB% |
|--------|---------|-----|----------------|-----|
| 2015-2017 | -0.56 | 0.15 | 0.54 | 27% |
| 2016-2018 | -1.40 | 0.02 | 0.84 | 46% |
| 2018-2020 | -0.57 | 0.55 | 1.83 | 63% |
| 2020-2022 | 0.02 | 0.60 | 1.98 | 85% |
| 2022-2024 | -0.24 | 1.19 | 2.12 | 96% |

## Conclusion

- Overall (mid): 80.0% configs positive across all windows
- Data-rich windows (2018-2024): 97.8% configs positive at mid
- **PETR4 is as robust as BOVA11** (97.8% vs BOVA11 78.7% in data-rich windows)
