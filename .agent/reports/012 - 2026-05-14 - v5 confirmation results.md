# B3 BOVA11 Short Strangle — v5 Confirmation Results

**Date:** 2026-05-14 | **Status:** Final

## 1. Research Question

Which conclusion does the BOVA11 laddering data support?

A. VRP exists and is capturable even at bid_ask  
B. VRP exists but is consumed by bid-ask spread; capturable at mid+  
C. VRP is marginal — positive at mid, negative at bid_ask  
D. No capturable VRP — negative across all modes

## 2. Methodology

- **Strategy:** Short strangle on BOVA11 (Brazilian ETF tracking Ibovespa), selling OTM put + call at 16–25Δ, targeting 30–45 DTE.
- **Grid dimensions:** target_delta (0.16/0.20/0.25), dte_max (30/45), profit_target_pct (0.50), manage_at_dte (7/14), vix_filter (OFF/rv_pct:80), defensive_leg_roll (OFF), stop_loss_pct (3.0), execution_mode (bid_ask/mid_minus_1tick/mid/mid_plus_1tick).
- **96 combos × 2 periods = 192 backtests**, all in laddering (portfolio) mode.
- **Engine:** MarketEngine + CDI-based IVs with b3_options_rb3.db, DB-aware expiration resolution.
- **Periods:** Train 2018-01-02 → 2022-12-31, Holdout 2023-01-02 → 2025-11-30.
- **Position mode:** Laddering (multiple concurrent positions, Reg-T margin), max_bpr_allocation=30%.
- **Cash mode:** `cash_investment_mode="risk_free"`, `cash_yield_annual=0.0` — metrics reflect pure strangle P&L with no underlying contamination.
- **Key fixes applied:** expiration mismatch resolution (DB > calendar), volume_filter removed, CDI-based IVs.

## 3. Results — Laddering Grid

### 3.1 Execution Sensitivity

Median Sharpe ratio across all 24 configs per execution mode:

| Execution Mode | Train Median Sharpe | Holdout Median Sharpe |
|---------------|--------------------|----------------------|
| bid_ask | -0.93 | -0.58 |
| mid_minus_1tick | +0.05 | -0.14 |
| mid | +0.31 | +0.48 |
| mid_plus_1tick | +0.60 | +1.11 |

- **bid_ask is negative** in both periods — VRP consumed by spread.
- **mid is positive** in both periods — VRP capturable at mid or better execution.
- **mid_plus_1tick** delivers the best results — selling at better-than-mid prices (small market orders) is highly profitable.
- Train/holdout asymmetry persists — holdout outperforms train across all modes. The 2023 rescue effect (BOVA11 rallying +15% while IV compressed) inflates holdout results.

### 3.2 DB Coverage

| Period | Mean Entry DB Pct | Mean MTM DB Pct |
|--------|-------------------|-----------------|
| Train (2018–2022) | 76.3% | varies by config |
| Holdout (2023–2025) | 99.6% | varies by config |

Low coverage in train is due to limited B3 options data depth in earlier years. Holdout coverage is near-perfect because 2023–2025 has comprehensive DB data.

### 3.3 Spread Cost Analysis

From notebook Cell F — BOVA11 option spreads by delta bucket (train period):

| Delta Range | Median Spread (% of mark) |
|------------|---------------------------|
| 16Δ | ~40% |
| 20–30Δ | ~28% |
| 30–50Δ | ~23% |

At 16Δ (the default target delta in the best config), the median bid-ask spread is ~40% of mark. This is 8× wider than SPY options (~5%) and represents a substantial transaction cost.

### 3.4 v3 vs v5

| Metric | v3 Grid (single-position) | v5 Laddering Grid |
|--------|--------------------------|-------------------|
| v3 holdout median Sharpe | -1.32 | — |
| v5 laddering holdout median (mid) | — | +0.48 |
| v5 laddering holdout median (mid_plus_1tick) | — | +1.11 |

The v3 grid (7560 rows, broader parameter space) had a holdout median Sharpe of -1.32 — deeply negative. The v5 grid uses the corrected engine (expiration mismatch fixed, volume_filter removed, CDI IVs) and laddering mode, producing fundamentally different results. The improvement is driven by: (a) engine fixes that correctly price B3 options, (b) laddering which maximizes capital utilization, and (c) the holdout period (2023–2025) being structurally favorable for short volatility.

### 3.5 Best Configuration

**Config:** delta=0.16, dte_max=30, manage_at_dte=14, vix_filter=rv_pct:80, execution_mode=mid_plus_1tick

| Metric | Train (2018–2022) | Holdout (2023–2025) |
|--------|-------------------|---------------------|
| N trades | 213 | 118 |
| Sharpe | 0.81 | 2.06 |
| Total return | 10.9% | 7.4% |
| Max drawdown | -3.5% | -1.2% |
| Calmar | 0.88 | 2.15 |
| Win rate (chain) | 75.8% | 83.5% |
| Entry DB pct | 57.3% | 100.0% |

Same config across all four execution modes (holdout):

| Mode | Sharpe | N Trades | Total Return | MDD |
|------|--------|---------|-------------|-----|
| bid_ask | -0.10 | 146 | -0.4% | -3.5% |
| mid_minus_1tick | -0.27 | 155 | -1.6% | -4.8% |
| mid | +1.25 | 147 | +6.6% | -1.7% |
| mid_plus_1tick | +2.06 | 118 | +7.4% | -1.2% |

## 4. Issues & Caveats

### 4.1 Mid_minus_1tick ordering anomaly

The anomaly persisted in laddering mode — bid_ask Sharpe (-0.10) exceeds mid_minus_1tick Sharpe (-0.27) for the best config, contradicting the expected ordering (bid_ask < mid_minus_1tick < mid < mid_plus_1tick).

**Root cause confirmed:** 63.9% of 16Δ BOVA11 option legs have `bid > mark - tick`. These are cheap OTM options trading at R$0.50–1.00 mark, where R$0.05 (one tick) represents 5–10% of premium. Subtracting a tick from the mark price frequently produces a price **below the actual bid**, making mid_minus_1tick an artificially unfavorable execution model.

**Entry credit comparison** (180 legs across 90 root trades in best config):

| Comparison | Count | Pct |
|-----------|-------|-----|
| bid > mid - tick | 115 | 63.9% |
| bid < mid - tick | 51 | 28.3% |
| bid = mid - tick | 14 | 7.8% |
| Mean (bid - (mid-tick)) | -0.003 BRL | — |
| Median (bid - (mid-tick)) | +0.020 BRL | — |

This is NOT a bug — it's a real consequence of B3's R$0.05 tick size being too large for cheap far-OTM options. The mid_minus_1tick mode does NOT represent realistic execution; a better model would cap the adjustment at `max(mid - tick, bid)`.

### 4.2 Period dependence: 2023 rescue effect

The holdout period (2023–2025) was structurally favorable: BOVA11 rallied ~15% while implied volatility compressed. This inflates all holdout Sharpes relative to train. The train period (2018–2022) includes the COVID crash (March 2020) and the 2022 rate-hike selloff, which stress-test the strategy negatively.

**Key risk:** if the holdout period is an outlier (declining vol + rising underlying), forward results will be worse. The train/holdout asymmetry (train median Sharpe -0.93 to +0.60 vs holdout -0.58 to +1.11) suggests the true out-of-sample Sharpe is somewhere between, closer to train.

### 4.3 Train/holdout asymmetry

Train median Sharpe ranges from -0.93 (bid_ask) to +0.60 (mid_plus_1tick). Holdout ranges from -0.58 to +1.11. This persistent gap is driven by:
1. COVID crash (March 2020) in train — a single event inflicting ~35% MDD across most configs
2. 2023–2025 being a "goldilocks" period for BOVA11 short vol — steady rally with declining vol
3. DB coverage gap (76% vs 99.6%) — train has more synthetic-fallback entries, which may introduce noise

### 4.4 Complex number bug

524 errors in v3 grid (edge configs only: delta ≥ 0.30 + dte ≥ 60). Not present in v5 (max delta=0.25, max dte=45). Root cause: brentq IV solver produces complex numbers for deep-ITM options at B3's high CDI rates. Fix: add NaN guard in `implied_volatility()` in `engines.py`. Already naturally filtered by the `iv < 2.0` check. Low priority.

### 4.5 American exercise risk

34% of BOVA11 CALLs in the DB are AMER (American-style). The engine treats all BOVA11 options as European (cash-settled). Early exercise is possible on deep-ITM calls (especially near dividend dates or when rates are high). For a short strangle, early exercise risk is asymmetric — only the in-the-money side can be assigned. This is NOT modeled and represents an unquantified tail risk.

### 4.6 Bid_ask liquidity caveat

bid_ask results should carry a "conditional on sufficient liquidity at entry" caveat. The bid_ask mode requires `bid > 0` on both legs for DB entries. In train, this reduces entries from ~243 (mid mode) to ~231 — a ~5% reduction. The filtered entries may be those with the widest spreads (worst expected P&L), creating a positive selection bias in bid_ask results. The 53% entry DB pct in train (vs 84% for mid modes) further shows that bid_ask relies heavily on synthetic fallback when real bid data is unavailable.

## 5. Conclusion

**Conclusion B: VRP exists but is consumed by bid-ask spread; capturable at mid+**

The laddering grid shows that the median mid-price configuration delivers a positive Sharpe (+0.48 holdout, +0.31 train), confirming that the volatility risk premium on BOVA11 options is real and capturable. However, the median bid_ask configuration is negative (-0.58 holdout, -0.93 train), meaning the bid-ask spread fully consumes the VRP for a typical retail trader paying the full spread.

The best configuration (16Δ, 30 DTE, manage at 14 DTE, vol-filtered at 80th RV percentile, mid_plus_1tick execution) achieves Sharpe 2.06 in holdout and 0.81 in train. This suggests that a trader who can achieve better-than-mid fills (e.g., limit orders near mid, electronic market-making access) can capture meaningful VRP. However, at full bid_ask this same config has Sharpe -0.10 — essentially flat.

**Key evidence:**
- bid_ask holdout median = -0.58 (negative)
- mid holdout median = +0.48 (positive)
- Best config mid_plus_1tick holdout = +2.06 (very positive)
- Best config bid_ask holdout = -0.10 (flat/slightly negative)
- Train/holdout gap suggests true forward Sharpe is lower than holdout, closer to train levels

**Risk factors to monitor:**
- If BOVA11 enters a sustained bear market with elevated vol, short strangle losses will exceed the COVID-era drawdowns seen in train
- The 2023–2025 bull market with declining vol is an ideal tailwind — reversal would hurt
- American exercise risk on deep-ITM calls is unmodeled
- 24% of train entries lack DB data and rely on synthetic pricing (may introduce bias)

## 6. Appendices

- **Grid data:** `data/B3/v5_grid_search_laddering.parquet` (192 rows)
- **Grid search:** `scripts/grid_search.py` (added portfolio_mode dimension + exec_mode cache fix)
- **Database:** `data/B3/b3_options_rb3.db` (~280 MB, 2008–2025 B3 options)
- **Notebook:** `research/2026-05-14 - B3 - v5 confirmation grid.ipynb`
- **v3 grid:** `data/B3/v3_reproduction_results.parquet` (22,680 rows)

### Engine cache fix

The original `grid_search.py` cached the MarketEngine by `(market, start_date, end_date)` — but the engine stores `execution_mode` at construction time. This caused all combos to use the first combo's execution mode, producing identical results across modes. The fix updates `engine._exec_mode` and `engine.uses_real_fills` from `params` before each backtest run. Both `scripts/grid_search.py` and `scripts/_run_v5_laddering_grid.py` include this fix.
