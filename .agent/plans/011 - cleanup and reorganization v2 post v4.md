# 011 — Cleanup and Reorganization (v2 — post v4 implementation)

**Date:** 2026-05-14  
**Status:** Ready for execution  
**Replaces/supersedes:** Plan 008

This plan reflects the current state of the `b3-backtest` branch after Part 1 (B3 validation) and Part 2 (v4 execution sensitivity grid) are complete. It updates plan 008 with the new files created and eliminates open questions.

---

## Phase 1 — DELETE (files + directories)

### 1.1 — Superseded old DB (226 MB)

| File | Why |
|------|-----|
| `data/B3/b3_options.db` | Old pre-rb3 database. Superseded by `b3_options_rb3.db`. Only referenced by one-off scripts (`phase1_regression.py`, `fit_b3_skew.py`, `build_b3_options_db.py`) and the v1 notebook. Already in `.gitignore` — needs `git rm --cached`. |

### 1.2 — Old research notebooks (superseded by v3/v4)

| File | Why |
|------|-----|
| `research/2026-05-01 - B3 - VRP harvesting research.ipynb` | Initial exploration notebook. All findings incorporated into v3/v4. |
| `research/2026-05-02 - B3 - data quality checks.ipynb` | Data quality checks. Superseded by `scripts/check_rb3_quality.py` and rb3-based v3 QA. |
| `research/2026-05-06 - B3 - parameter grid search.ipynb` | v1/v2 grid search. Superseded by v3 BOVA11 and PETR4 notebooks. References old `b3_options.db`. |

### 1.3 — One-off scripts (already served purpose)

| File | Purpose | Why delete |
|------|---------|------------|
| `scripts/build_b3_parquets.py` | Build raw parquets from COTAHIST | Only needed to produce the rb3_export parquets. Those exist and `build_b3_options_db.py` builds from COTAHIST directly. |
| `scripts/migrate_to_rb3_db.py` | Migrate parquets → SQLite rb3 DB | Migration is complete. |
| `scripts/recompute_iv_with_cdi.py` | Recompute IVs using daily CDI rates | CDI IVs are already computed and stored in `implied_volatility_cdi`/`delta_cdi` columns in rb3 DB. |
| `scripts/phase1_regression.py` | Parity check old `b3_options.db` vs rb3 | Phase 1 validation complete. References old DB that we're deleting. |
| `scripts/verify_sharpe_fix.py` | Verify daily MTM Sharpe fix | Fix verified by test suite (`test_metrics.py`). |
| `scripts/validate_cdi_ivs.py` | Validate CDI strike selection stability | Validation complete. |
| `scripts/build_v4_notebook.py` | One-off notebook generator | Notebook `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb` already generated. |

### 1.4 — Old grid search results (superseded by v3/v4)

| File | Why |
|------|-----|
| `data/B3/grid_search_results_strangle.parquet` | v1 strangle results — superseded by `v3_grid_search_results.parquet` |
| `data/B3/grid_search_results_volfilter.parquet` | v1 vol filter results — superseded by v3 |
| `data/B3/bova11_backtest.parquet` | Single backtest output from early exploration |
| `data/B3/petr4_backtest.parquet` | Single backtest output from early exploration |

### 1.5 — Old PNG artifacts (v1/v2 analyses, unreferenced by any active notebook)

| File | Why |
|------|-----|
| `data/B3/grid_heatmap_delta_dte.png` | v1 grid chart |
| `data/B3/grid_heatmap_profit_manage.png` | v1 grid chart |
| `data/B3/grid_scatter_ntrades_sharpe.png` | v1 grid chart |
| `data/B3/grid_train_vs_holdout.png` | v1 grid chart |
| `data/B3/qa_equity_price_reconciliation.png` | Old QA — pre-rb3 analysis |
| `data/B3/qa_iv_smile_bova11_2024.png` | Old QA — pre-rb3 analysis |
| `data/B3/qa_iv_smile_petr4__2024.png` | Old QA — pre-rb3 analysis |
| `data/B3/qa_iv_vs_vxewz.png` | Old QA — pre-rb3 analysis |
| `data/B3/qa_spread_distribution.png` | Old QA — pre-rb3 analysis |

### 1.6 — Miscellaneous cruft

| File | Why |
|------|-----|
| `src/straddle/paper_trading/runner.py.backup` | Stale backup of dead module. Not referenced anywhere. |
| `aux/data integrity test.R` | Orphan R test artifact. |
| `aux/data integrity test.ipynb` | Orphan notebook artifact. Delete entire `aux/` directory. |
| `data/B3/build_log.txt` | Stale DB build log. |
| `data/B3/db_build_log.txt` | Stale DB build log. |
| `data/paper_config.json` | Paper trading config, not actively used. |

---

## Phase 2 — UNTRACK from Git (stay on disk)

These files are in `.gitignore` but were force-tracked. Use `git rm --cached` to stop tracking while preserving local copies.

| File | Size | Why |
|------|------|-----|
| `data/B3/COTAHIST_A*.TXT` (17 files) | 303 MB | Raw B3 exchange data. Kept on disk if DB rebuild is ever needed. Already in `.gitignore`. |
| `data/B3/b3_options_rb3.db` | 266 MB | Active database. Already in `.gitignore`. |
| `data/B3/rb3_export/bova11_options_rb3.parquet` | 18 MB | Source data for DB. Already gitignored. |
| `data/B3/rb3_export/petr4_options_rb3.parquet` | 36 MB | Source data for DB. Already gitignored. |

---

## Phase 3 — KEEP (files that stay tracked)

### 3.1 — Active research notebooks
- `research/2026-05-13 - B3 - v3 grid search - BOVA11.ipynb` — definitive v3 BOVA11
- `research/2026-05-13 - B3 - v3 grid search - PETR4.ipynb` — definitive v3 PETR4
- `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb` — active v4 execution sensitivity

### 3.2 — Active data outputs
- `data/B3/v3_grid_search_results.parquet` — v3 7,560-row grid output (referenced by v3 notebooks)
- `data/B3/v4_grid_search_results.parquet` — v4 240-row grid output (referenced by v4 notebook)
- `data/B3/v3_*.png` (5 files) — v3 analysis charts referenced by v3 notebooks
- `data/B3/skew_fit_*.png` + `skew_stability_*.png` (4 files) — output of `scripts/fit_b3_skew.py`

### 3.3 — Reusable scripts (tools that may be needed again)
- `scripts/b3_parser.py` — B3 COTAHIST parser (needed for DB rebuild)
- `scripts/build_b3_options_db.py` — DB build pipeline from COTAHIST → SQLite
- `scripts/check_rb3_quality.py` — Data quality checks (reusable validation)
- `scripts/fit_b3_skew.py` — Skew fitting tool (refit if underlying data changes)
- `scripts/grid_search.py` — Active grid search module (used by v3/v4 notebooks)
- `scripts/quantify_synthetic_dominance.py` — Analysis tool (reference)
- `scripts/b3_bulletin_fetcher.py` — B3 bulletin API fetcher (Part 1, reusable)
- `scripts/validate_b3_prices.py` — B3 price validation (Part 1, reusable)

### 3.4 — New tests and docs
- `tests/test_execution_modes.py` — 15 execution mode unit tests
- `docs/2026-05-13 - rb3 price validation.md` — Part 1 validation report

### 3.5 — Agent plans
- `.agent/plans/` — all 11 plan files kept for project history

---

## Phase 4 — Final Directory Structure (post-cleanup)

```
options-backtest/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── .gitignore
├── src/straddle/                   # Core library
│   ├── __init__.py
│   ├── api.py
│   ├── data.py
│   ├── engines.py
│   ├── metrics.py
│   ├── params.py
│   ├── plotting.py
│   ├── portfolio.py
│   ├── runs_store.py
│   └── strategy.py
├── scripts/                        # Tools (reusable)
│   ├── run_backtest.py
│   ├── run_api.py
│   ├── grid_search.py
│   ├── b3_parser.py
│   ├── build_b3_options_db.py
│   ├── check_rb3_quality.py
│   ├── fit_b3_skew.py
│   ├── quantify_synthetic_dominance.py
│   ├── b3_bulletin_fetcher.py
│   └── validate_b3_prices.py
├── tests/
│   ├── conftest.py
│   ├── test_engines.py
│   ├── test_execution_modes.py
│   ├── test_iron_condor.py
│   ├── test_metrics.py
│   ├── test_portfolio.py
│   └── test_strategy.py
├── research/                       # Active notebooks only
│   ├── 2026-05-13 - B3 - v3 grid search - BOVA11.ipynb
│   ├── 2026-05-13 - B3 - v3 grid search - PETR4.ipynb
│   └── 2026-05-14 - B3 - v4 execution sensitivity.ipynb
├── data/B3/                        # Active data only
│   ├── v3_grid_search_results.parquet
│   ├── v4_grid_search_results.parquet
│   ├── v3_*.png (5 files)
│   └── skew_*.png (4 files)
├── docs/
│   └── 2026-05-13 - rb3 price validation.md
└── .agent/plans/                   # Project history
    └── 000 .. 011
```

---

## Summary

| Phase | Files affected | Net result |
|-------|---------------|------------|
| 1 — Delete | 22 files + 1 directory (`aux/`) | ~226 MB reclaimed (old DB) |
| 2 — Untrack | 20 files | ~623 MB removed from git (stay on disk) |
| 3 — Keep | 30 files | Remaining lean project |
| **Total** | **72 files touched** | **~849 MB removed from git history** |
