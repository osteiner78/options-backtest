B3 BOVA11/PETR4 Short Strangle VRP Research — Comprehensive Report
For adversarial review by another LLM (Claude Opus)
Date range: 2026-05-14 through 2026-05-15 (this conversation), building on prior work from 2026-05-12 onward
Branch: b3-backtest
Author of this report: Claude DeepSeek (research assistant)
Previous implementation work: Claude Sonnet 4.6 (coding agent)

---

1. Project Objective
   Determine whether a short strangle volatility risk premium (VRP) exists on B3 (Brazilian exchange) for BOVA11 (IBOVESPA ETF) and PETR4 (Petrobras), and whether it is capturable at realistic execution prices. The intended deployment mode is laddering (multiple concurrent positions with Reg-T margin). The desired confidence level is "maximum" before deploying capital.
2. Research Architecture
   The backtesting engine consists of:
   params.py → data.py → engines.py → strategy.py → metrics.py → plotting.py
   ↓
   grid_search.py (batch orchestration)
   Two pricing engines:

- SyntheticEngine — Black-Scholes + parametric vol skew. Works for any date range.
- MarketEngine — Real bid/ask from SQLite DB (b3_options_rb3.db, ~9.6 GB, 961K rows for PETR4, similar for BOVA11). Falls back to synthetic when DB data is missing.
  Execution modes (how fills are priced):
- bid_ask — Sell at bid, buy at ask (conservative, market orders)
- mid — Trade at mid-price (limit orders, our anchor conclusion)
- mid_plus_1tick — Mid + 1 tick, favorable to seller (optimistic upper bound)
- mid_minus_1tick — Dropped after v5 (63.9% of legs have bid > mark - tick — unrealistic on B3)
  Position modes:
- single_position — One active chain at a time (testing only)
- laddering — Multiple concurrent positions with Reg-T margin (deployment mode)
  Key parameters tested:
- target_delta: 0.12, 0.16, 0.20, 0.25 (dropped 0.30, 0.50/straddle in v7)
- dte_max: 21, 30, 45, 60
- profit_target_pct: 0.25, 0.50 (dropped 0.75 in v7)
- manage_at_dte: 5, 7, 14, 21
- execution_mode: bid_ask, mid, mid_plus_1tick
- vix_filter: OFF, rv_pct:70, rv_pct:80, rv_pct:90
- stop_loss_pct: 2.0, 3.0
- defensive_leg_roll: False (dropped in v7, ΔSharpe ±0.03)

3. Chronological Research Journey
   Pre-conversation work (v2–v6)
   This conversation began after v2 through v6 were already completed. The pre-conversation work involved:
   v2: Initial B3 grid search with corrupted DB — discarded.
   v3: BOVA11/PETR4 grid search (7,560 configs). Found deeply negative results at bid_ask. First indication that spread matters.
   v4: Added 4 execution modes (bid_ask, mid_minus1tick, mid, mid_plus1tick). First evidence that mid execution could be positive.
   v5: Expiration bug fix + confirmation grid. Discovered engine cache bug: \_worker_cache in grid_search.py was keyed by (market, start, end) but not execution_mode, causing all modes after the first to inherit the wrong engine. Fixed cache key and re-ran. Conclusion B: VRP exists but consumed by bid-ask spread.
   v5 laddering grid (Plan 012): 192 laddering backtests. Engine cache fix applied. Saved to v5_grid_search_laddering_fixed.parquet (authoritative).
   v6 expanded grid (Plan 013): 24,192 laddering backtests. 13,824 raw combos → 12,096 valid. 455 errors (1.9%) from complex-number bug at delta ≥ 0.30 with dte_max=60. Key findings:

- bid_ask median: -0.96, mid: +0.37, mid_plus_1tick: +1.11 (holdout)
- 85% of configs positive in both train+holdout for mid_plus_1tick
- Straddle (50Δ) worse than OTM strangle (+0.39 vs +1.24 at mid_plus_1tick)
- Defensive leg roll negligible (ΔSharpe +0.03)
- Cell J entry_db_pct display bug discovered (showing 0.5% instead of ~50%)
  Code review (report 015): Found 2 critical bugs, 7 important issues, 6 suggestions.
  Work during this conversation (v7 forward)
  Plan 014 — v7 refined grid (Phase 0-7):
- Phase 0: Fixed all 12 code-review bugs (vol-cache key, force-close double-append, bare except, IVR inversion, label erase, DB path, dte validation, module-level globals, sigma=0 BAW crash, apply_market_preset overrides, plus 6 suggestions)
- Phase 1: Fixed Cell J entry_db_pct display bug (fraction → percentage)
- Phase 2: Investigated Sharpe=11.73 config (12Δ). Verdict: real but execution-sensitive. Spread/mark 41.1% makes fills at mid unlikely.
- Phase 3: v7 refined grid — 2,688 valid combos × 2 periods = 5,376 backtests, 0 errors
- Phase 4: Commission sensitivity (90 backtests) — mid never flips negative at 3× commission
- Phase 5: 10-trade manual P&L verification — 9/9 non-stop trades match DB marks to the cent
- Phase 6: Period robustness — 15 configs × 5 windows × 3 modes = 225 backtests
- Phase 7: Final report (016 - v7 final confirmation results.md)
  Post-v7 review (my analysis):
- Identified force-close P&L fix was committed AFTER v7 grid ran (low materiality: 0.7% of trades)
- Identified 6 rows with identical Sharpe=11.557057 (degenerate configs — non-bug)
- Identified train/holdout correlation at mid = -0.275 (weakens parameter optimization)
- Recommended: 2016-2018 investigation, 16Δ deep-dive, PETR4 analysis, 6-month stress scenarios
  Plan 015 — Post-v7 follow-up (5 phases):
- Phase 1: Force-close impact assessment — confirmed immaterial (1 of 134 trades, 0.8% of P&L)
- Phase 2: 16Δ deep-dive — confirmed tradable (spread/mark 33.4% < 35% gate), Sharpe premium +0.597 over 25Δ
- Phase 3: Grid degeneracy — 50 of 768 groups (6.5%) are degenerate; documented in notebook Cell L
- Phase 4: PETR4 full grid — 5,376 backtests, 0 errors. Holdout 76.9% viable at mid, median Sharpe 0.488
- Phase 5: Stress scenarios — worst 6-month window -3.70% for 25Δ. No gap events detected.
  Code review (report 018) — second full codebase review:
- Found I-10: Portfolio-mode Sharpe denominator used initial balance instead of running equity — systematically biased Sharpe for all laddering results
- Found I-2: API failed errors not persisted to SQLite
- Found I-6: Fallback expiry path missing daily_marks.append
- Found 7 other important issues and 10 suggestions (see §6)
  Plan 016 — I-10 impact measurement:
- Ran 6 key configs standalone with the fix
- Max |ΔSharpe| = 0.073 (12Δ BOVA11 holdout: 11.557 → 11.485)
- All other ΔSharpe values between -0.004 and +0.042
- Decision: no grid re-run needed. Impact immaterial.
- Updated both reports (016 and 017) with corrected numbers and footnotes
  Pending actions audit:
- Plan 011 cleanup (delete 22 files + aux/ dir, untrack 20 from git) — never executed, deferred across 3 plans
- Complex number NaN guard partially addressed (brentq already has try/except in \_baw_critical_put)
- S6 LRU eviction for \_results dict — deferred

4. Current State of Research Conclusions
   BOVA11 Recommended Config (confirmed deployable)
   target_delta: 0.25
   dte_max: 21
   profit_target_pct: 0.50
   manage_at_dte: 14
   vol_filter: OFF
   stop_loss_pct: 2.0
   execution_mode: mid
   portfolio_mode: laddering
   Performance (corrected for I-10 fix):

- Holdout Sharpe: 1.33 (was 1.29)
- Train Sharpe: 0.90 (was 0.91)
- Max 6-month drawdown: -4.2%
- Commission survival: positive at 3× commission
- Period robustness: 100% positive in all 3 data-rich 3-year windows (2018-2024)
  PETR4
- Holdout 76.9% viable at mid, median Sharpe 0.488
- Recommended config (25Δ/dte21/pt50%/OFF/mid): holdout Sharpe 1.21
- Train median at mid = -0.198 (inconsistent pre-2023)
- Same pattern as BOVA11: mid required, bid_ask negative
  16Δ Upgrade Path
- Holdout Sharpe premium over 25Δ: +0.60 (1.93 vs 1.33)
- Spread/mark: 33.4% (vs 20.3% for 25Δ)
- Recommended: start at 25Δ, upgrade to 16Δ after proving mid-fill execution

5. Complete Bug Inventory
   Bugs Fixed (all verified by tests)
   ID File:Line Severity
   #1 strategy.py:19 Critical
   #2 portfolio.py:473 Critical
   #3 engines.py:912 Important
   #4 api.py:37 Important
   #5 strategy.py:54 Important
   #6 runs_store.py:33 Important
   #7 runs_store.py:8 Important
   #8 api.py:55 Important
   #9 strategy.py:94, data.py:201 Important
   #10 engines.py:135 Important
   #11 params.py:289 Important
   I-10 metrics.py:198 Important
   I-2 api.py:297 Important
   I-6 strategy.py:905 Important
   — portfolio.py —
   — metrics.py —
   Bugs Deferred (not fixed)
   ID Severity Description
   I-1 Important engine.\_exec_mode mutation on cached object — fragile with threading (safe with loky)
   I-3 Important O(n²) loop in \_build_vol_filter for rv_pct/ivr modes
   I-4 Important run_backtest.py CLI final_balance diverges from equity curve
   I-5 Important apply_market_preset silently drops API overrides (API path)
   I-7 Important Portfolio cash/margin inconsistency on adverse moves
   I-8 Important 7-day max-gap threshold too loose in data.py
   I-9 Important risk_free_rate API field misleading name
   S-1 through S-10 Suggestion Various cosmetic/minor issues
6. Verification Layers (what gives us confidence)
7. Manual P&L verification: 9/9 mid-execution trades match raw DB marks to R$0.00. 1 STOP trade discrepancy explained by overshoot model (by design).
8. SPY regression: Engine changes don't break the original SPY code path (69 trades, no exceptions).
9. Synthetic vs market comparison: 100% DB-sourced entries in holdout — zero synthetic fallback. No systematic pricing mismatch.
10. American option sensitivity: BAW vs BS for BOVA11 ETF: ΔSharpe = 0.000. Zero early exercise impact.
11. Period robustness: 78.7% of config-window pairs positive at mid across 5 rolling 3-year windows. 100% in the 3 data-rich windows.
12. Commission sensitivity: All top configs survive 3× commission at mid. B3 real commissions (~R$0.45-0.50/option) are well below tested levels.
13. Stress scenarios: Max 6-month drawdown -4.2%. No gap events. No fat-tail flag (top+bottom 3 trades < 25% of total P&L).
14. Test suite: 129 tests pass covering BS primitives, execution modes, vol filter cache, portfolio accounting, iron condor, runs_store.
15. Code review (2 full passes): Reports 015 and 018 together found and fixed 15 bugs.
16. Key Limitations and Honest Assessment
    What the backtest CAN tell us

- A VRP existed in BOVA11 and PETR4 option prices during 2018-2025
- The VRP is large enough to survive conservative execution assumptions at mid
- The strategy is robust across parameter variations (86% of v7 configs positive in holdout)
- The edge is not driven by fat tails (P&L distribution is well-behaved)
  What the backtest CANNOT guarantee

1. Mid fills are an assumption, not verified. The backtest assumes every trade fills at mid at EOD. Real limit orders may:
   - Not fill at all (especially for 12Δ/16Δ with 33-41% spread/mark)
   - Fill at worse prices during volatility events
   - Be partially filled
   - Be rejected by the broker or exchange
2. EOD marks ≠ trade-execution prices. The backtest uses 5pm closing marks. An order placed at 10am may see different mid prices. There is no intraday fill simulation.
3. 7-year sample is short for tail-risk strategies. BOVA11 data starts in 2015 with sparse DB coverage; reliable data is 2018-2025. This window does NOT include:
   - A 2008-style financial crisis
   - A sustained Brazilian hyperinflation/currency crisis
   - A multi-year bear market with rising rates and falling equities simultaneously (2013-2015 Brazil recession not covered)
4. The 2016-2018 window had only 40% configs positive at mid (41% DB coverage). This is the one available data point for a "stress period" and it showed weakness. We dismissed it as "low DB coverage" but never fully investigated.
5. The overshoot model for stop-loss fills is a heuristic. It applies multipliers to the spread during "gap" events but has never been validated against real gap-fill data. The 1 STOP trade in manual verification showed R$1.50 discrepancy — small, but the model is untested for extreme events.
6. No assignment risk modeling. Early assignment of short options (especially for PETR4, a stock with dividends) is not simulated. The backtest assumes all positions are closed via the strategy logic, not via broker action. On B3, option exercise is automatic at expiration, but early exercise/assignment risk for single stocks exists.
7. Single market, single instrument. All conclusions are specific to BOVA11 (ETF) and PETR4 (stock). The engine may need recalibration for other B3 underlyings.
8. Position sizing doesn't account for market depth. The backtest enters positions at any size. In reality, BOVA11 options have finite open interest. A R$500,000 position on a 16Δ strike could exceed available liquidity.
9. The train/holdout correlation at mid is negative (-0.275). Parameter optimization from training data does not strongly predict holdout performance. The stability rank (min(train, holdout) Sharpe) helps but is a conservative criterion.
10. I-10 fix verified on 6 configurations only. The full v7 grid (5,376 backtests) still has pre-fix Sharpe numbers. Max observed Δ was 0.073, but this was measured on 6 of 5,376 rows. Extrapolating to the full grid is reasonable (the effect is mathematically bounded by the return level) but not verified.
11. The force-close P&L fix was applied after the v7 grid. The v7 parquet still has old force-close P&L (0.00 for force-closed trades). Impact assessed as 0.7% of trades per config — immaterial, but technically the parquet is not bit-perfect with the current code.
12. Remaining Code Smells Worth Scrutinizing
    These didn't make the "bug" list but deserve adversarial attention:
13. \_compute_mtm_equity in metrics.py rebuilds equity curve independently from the one in run_portfolio_backtest. Two implementations of the same logic is a maintenance risk.
14. **del** in engines.py still exists even with the except Exception: fix. Python's **del** is not guaranteed to run. Better pattern: context manager.
15. Grid search uses module-level \_worker_cache that's keyed by (market, start_date, end_date). If the user changes any parameter between runs that doesn't affect the (data, engine) pair, the cache returns stale references. This was the source of the v5 cache bug. The fix was partial (key now includes execution_mode), but the fundamental design is fragile.
16. No test exercies evaluate_trade_step directly. The most complex financial logic is only tested through integration tests. A unit test with synthetic data forcing each exit type would catch regressions earlier.
17. The PARAMS dict is a mutable module-level global. All callers do dict(PARAMS) to copy, which is safe. But if any test accidentally does PARAMS["key"] = value, it silently contaminates other tests.
18. B3 market preset sets dividend_yield=0.0. For BOVA11 ETF this is correct (Brazilian ETFs don't distribute dividends). For PETR4 stock it's wrong — Petrobras pays significant dividends. The backtest undervalues put protection slightly (higher dividends = less put value = more premium for the seller = optimistic bias). The v7 report says "marginal undervaluation" but gives no quantification.
19. Merge Readiness
    Git status: b3-backtest is 50 commits ahead of master. Master is a direct ancestor — clean fast-forward merge with zero conflicts.
    Tests: 129/129 pass.
    Untracked files: reports/ (38 HTML files) and .opencode/ — won't be part of merge.
    Post-merge cleanup needed:

- Plan 011 (delete aux/, b3_options.db 226 MB, 9 old PNGs, 4 old parquets, 7 deprecated scripts)
- .gitignore missing rules: .pytest_cache/, .agent/, _.db-shm, _.db-wal
- .history/ (53 files) tracked in git — should be git rm --cached
- Terminal-ui has parameter key mismatches with current API (vix_entry_filter_enabled → vix_filter, defensive_leg_roll_enabled → defensive_leg_roll, missing execution_mode)

10. Future Steps (in priority order)
1. Merge b3-backtest to master — unblocks everything else
1. Plan 011 cleanup on master — remove dead files, update .gitignore
1. Fix terminal-ui — address parameter key mismatches identified in §9
1. Paper trade the 25Δ config — 2-3 months on B3 to verify mid-fill quality
1. After mid fills confirmed → upgrade to 16Δ — captures +0.60 Sharpe premium
1. PETR4 period robustness — the plan says "run period robustness" but it wasn't done yet
1. Deferred bug cleanup — I-1 through I-9 and S-1 through S-10 from report 018 (low priority)
1. Live deployment — only after paper trading confirms fills
1. Adversarial Questions to Probe
   Here are the lines of attack an adversarial reviewer should take:
1. "86% of configs positive" is a survivorship-biased statistic. The grid drops configs with < 30 trades. How many combos were dropped? Do they represent systematically worse market regimes?
1. The 12Δ mid_plus_1tick config has 98.9% win rate but 41.1% spread/mark. Is this data mining? Every leg's mid price is book-level; the 12Δ strikes may have wide enough spreads that mid is simply the midpoint of a quote from a single market maker — not an achievable fill.
1. The period robustness uses 5 overlapping windows (2015-2017, 2016-2018, 2018-2020, 2020-2022, 2022-2024). These are NOT independent — 2018 appears in 3 windows, 2020 in 2. The claimed "100% profitability" in 3 windows is less impressive when the windows overlap heavily.
1. No out-of-sample period. The train/holdout split (2018-2022 vs 2023-2025) optimized parameters on train, but the holdout period (2023-2025) was the B3 bull market. The parameters that work best in a bull market may not work in a bear market.
1. The recommended config has vol_filter: OFF. This means entries are unconstrained even during high-vol regimes. The VRP is theoretically larger during high-vol — but the backtest may benefit from a structural regime (2018-2025 was low-to-moderate vol for Brazil) that wouldn't persist.
1. **Commission = R$2.00 per trade and it's tested at 3×.** But R$2.00 is a B3 institutional rate. Retail commissions in Brazil can be R$5-20/contract. What commission level makes mid execution unprofitable?
1. No comparison to simpler strategies. The Sharpe of simply holding BOVA11 over the same period isn't prominently featured. Is the strategy actually adding alpha, or just levered beta with option premium?
1. The max drawdown of -4.2% was measured on the recommended config in the holdout period — the period where it performed well. The worst 6-month window might be in an untested regime. What happens if 2016 repeats?
   The report should help them find every weakness.
