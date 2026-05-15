# rb3 Price Validation Against B3 Official Bulletin

**Date completed:** 2026-05-13
**Method:** Automated — B3 official daily bulletin API
**Source:** `scripts/validate_b3_prices.py`

---

## Summary

| Metric | Value |
|--------|-------|
| Validation dates | 10 |
| Target contracts | 20 |
| B3 contract matched | 20 (100%) |
|   — Puts matched | 10/10 |
|   — Calls matched | 10/10 |
| rb3_mark vs B3 LastPrice (±10%) | 70% |
| Median mark diff | 0.0% |
| rb3 implied spread (median) | 27.4% of mark |
| rb3 implied spread (75th pct) | 33.2% of mark |
| rb3 bid ≤ B3 last (feasibility) | 94% |
| rb3 ask ≥ B3 last (feasibility) | 89% |
| rb3 volume / B3 TradeQty (median ratio) | 969× |

**Verdict: PARTIAL**

---

## BOVA11 Option Exercise Style

**Date:** 20250110

- **AMER**: 567 total (567 CALL, 0 PUT) — e.g. ['BOVAJ4', 'BOVAA128', 'BOVAA138', 'BOVAJ152', 'BOVAB126']
- **EURO**: 1103 total (268 CALL, 835 PUT) — e.g. ['BOVAV4', 'BOVAU15', 'BOVAI15', 'BOVAM138', 'BOVAM128']

**Note:** BOVA11 options come in both AMER and EURO styles. This backtest's codebase assumes European-style (no early exercise). If AMER-style contracts are used, early exercise risk exists and the backtest may overstate returns. All PUT contracts observed are EURO; CALLs are mixed AMER/EURO.

---

## Volume Interpretation

rb3 volume is 969× B3 TradeQty. This indicates rb3 reports cumulative contract volume (turnover in units), while B3 TradeQty reports the number of individual trades executed. The rb3 volume column should not be compared 1:1 with B3 TradeQty.

---

## Detailed Comparison

validation_date rb3_type  rb3_strike rb3_expiration  rb3_mark  rb3_bid  rb3_ask  rb3_volume b3_ticker  b3_last_price  b3_avg_price  b3_trade_qty b3_style  b3_found
       20180615      put        65.0     2018-07-16      0.88     0.65     0.89       10490   BOVAS65           0.88          0.78            11     EURO      True
       20180615     call        73.0     2018-07-16      0.21     0.00     0.00       13000   BOVAG73           0.21          0.20             7     AMER      True
       20190412      put        84.0     2019-05-20      0.76     0.73     0.80        3750   BOVAQ84           0.76          0.67             7     EURO      True
       20190412     call        96.5     2019-05-20      0.48     0.00     0.00        1500   BOVAE97           0.33          0.34             3     AMER      True
       20200316      put        54.0     2020-04-20      2.60     2.47     3.00        1000   BOVAP54           2.60          2.60             1     EURO      True
       20200316     call        89.0     2020-04-20      1.20     1.20     2.00         300   BOVAD89           1.20          1.29             2     AMER      True
       20200915      put        85.0     2020-10-19      0.70     0.66     0.74      132890  BOVAV850           0.70          0.68           116     EURO      True
       20200915     call       104.0     2020-10-19      0.51     0.41     0.58       28090   BOVAJ98           0.51          0.51           131     AMER      True
       20210512      put       106.0     2021-06-18      1.15     0.65     1.15      123764  BOVAR105           1.01          0.79           202     EURO      True
       20210512     call       124.0     2021-06-18      0.55     0.01     0.99      134441  BOVAF121           0.55          0.60           500     AMER      True
       20220831      put        96.0     2022-10-21      1.14     0.90     1.22       55818  BOVAV960           1.14          1.01            34     EURO      True
       20220831     call       120.0     2022-10-21      0.91     0.75     1.00       35541  BOVAJ111           0.92          0.98           210     EURO      True
       20221031      put       103.0     2022-12-16      0.94     0.84     1.15       12820  BOVAX104           1.29          1.07            23     EURO      True
       20221031     call       124.0     2022-12-16      0.69     0.48     2.51      260467  BOVAL124           0.69          0.55           225     AMER      True
       20230815      put       107.0     2023-09-15      0.60     0.55     0.62      120770  BOVAU108           0.71          0.64           212     EURO      True
       20230815     call       120.0     2023-09-15      0.50     0.40     0.50      922021    BOVAI1           0.50          0.52           936     AMER      True
       20241015      put       122.0     2024-11-14      0.68     0.66     0.76     1344878  BOVAW122           0.68          0.72           325     EURO      True
       20241015     call       134.0     2024-11-14      0.49     0.47     0.57     1979620  BOVAK135           0.37          0.38           325     EURO      True
       20250110      put       112.0     2025-02-21      0.59     0.45     0.64      224007  BOVAN111           0.50          0.47           131     EURO      True
       20250110     call       123.0     2025-02-21      0.46     0.43     0.50      768295  BOVAB123           0.46          0.47           434     EURO      True

---

## Interpretation

rb3 mark prices partially match B3 official data. Some discrepancies exist — possibly different settlement times or data vendors. V4 mid-price conclusions should be treated with caution. Consider running v4 with wider tolerance analysis.
