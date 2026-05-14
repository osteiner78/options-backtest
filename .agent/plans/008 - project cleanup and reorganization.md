# 007 — Project Cleanup and Reorganization

**Date:** 2026-05-13  
**Status:** Planning complete — awaiting go/no-go decisions on open questions

---

## Phase 1 — Delete (disk space ~5 GB reclaimed)

| # | What | Why | Size |
|---|------|-----|------|
| 1.1 | `data/B3/COTAHIST_A*.TXT` (17 files) | Raw exchange files used only to build `b3_options_rb3.db`. DB is built, these are dead weight. Keep only if re-building is planned. | **4.5 GB** |
| 1.2 | `data/B3/b3_options.db` | Old pre-rb3 database. Already replaced by `b3_options_rb3.db`. Tracked in git — needs `git rm`. | **226 MB** |
| 1.3 | `reports/portfolio_backtest_*.html` (38 files) | Auto-generated backtest reports. Already in .gitignore, just taking disk space. | **~190 MB** |
| 1.4 | `data/paper_trades.db-wal` / `data/paper_trades.db-shm` | Stale SQLite WAL/journal from a prior run. Already gitignored. | **3.9 MB** |
| 1.5 | `straddle_backtest.html` (root) | Duplicate of `output/straddle_backtest.html`. Tracked in git. | **1.6 MB** |
| 1.6 | `Wireframe Terminal v3.html` (root) | Duplicate of `output/Wireframe Terminal v3.html`. Tracked in git. | **45 KB** |
| 1.7 | `src/straddle/paper_trading/runner.py.backup` | Backup file of dead module (no source, only `.pyc` remains). Tracked in git. | **55 KB** |
| 1.8 | `data/market_data_20*.parquet` (5 date-range files) | Cached subsets. Only `market_data_master.parquet` is used by `data.py`. | **~340 KB** |
| 1.9 | `data/market_data_master_v2.parquet` | Evidently superseded by v1 (master). | **76 KB** |
| 1.10 | `data/B3/build_log.txt`, `data/B3/db_build_log.txt` | Build logs — informational but no longer needed. | **small** |

---

## Phase 2 — Move / Reorganize

| # | From | To | Why |
|---|------|-----|-----|
| 2.1 | `aux/data integrity test.ipynb` | `research/` | `aux/` is an orphan directory. Merge into research. |
| 2.2 | `aux/data integrity test.R` | `research/` | Same — merge and delete `aux/`. |
| 2.3 | `data/B3/v3_*.png` (6 files) | `data/B3/artifacts/v3_grid/` | Diagnostic plots from grid search; clutter `data/B3/` root. |
| 2.4 | `data/B3/qa_*.png` (8 files) | `data/B3/artifacts/qa/` | Quality check plots clustered together. |
| 2.5 | `data/B3/skew_*.png` (4 files) | `data/B3/artifacts/skew/` | Skew fit diagnostic plots. |
| 2.6 | `data/B3/grid_*.png` (4 files) | `data/B3/artifacts/grid/` | Old grid search plots. |
| 2.7 | `data/B3/grid_search_results_*.parquet` (2 files) | `data/B3/artifacts/` | Old grid search output, not raw data. |
| 2.8 | `output/phase1_regression/` | `data/B3/artifacts/phase1/` | Regression output is data artifacts, not display output. |
| 2.9 | `output/synthetic_diagnostic/` | `data/B3/artifacts/synthetic/` | Diagnostic output, not display output. |
| 2.10 | `output/2026-05-13 - B3 - v3 grid search.html` | `data/B3/artifacts/v3_grid/` | Generated HTML, not meant for `output/`. |

---

## Phase 3 — .gitignore and Git Hygiene

| # | Change | Why |
|---|--------|-----|
| 3.1 | Add `.pytest_cache/` to .gitignore | Standard Python project hygiene. |
| 3.2 | Add `.agent/` to .gitignore | Debug reports and plans are local artifacts, not source. |
| 3.3 | Add `*.db-shm`, `*.db-wal` to .gitignore | More specific SQLite WAL pattern (current only matches `paper_trades.db-*`). |
| 3.4 | `git rm --cached .history/` | 138 IDE history files tracked in git despite .gitignore rule. |
| 3.5 | `git rm` root-level `.html` files | Remove duplicates, keep only `output/` copies. |
| 3.6 | `git rm data/B3/b3_options.db` | Remove old DB from tracking. |

---

## Phase 4 — Recommended Final Structure

```
options-backtest/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── GEMINI.md
├── .gitignore
├── src/
│   └── straddle/                    # Core library (unchanged)
│       ├── __init__.py
│       ├── api.py
│       ├── data.py
│       ├── engines.py
│       ├── metrics.py
│       ├── params.py
│       ├── plotting.py
│       ├── portfolio.py
│       ├── runs_store.py
│       └── strategy.py
├── scripts/
│   ├── run_backtest.py              # User-facing CLI
│   ├── run_api.py
│   ├── grid_search.py
│   ├── fit_b3_skew.py
│   ├── check_rb3_quality.py
│   ├── build_b3_options_db.py       # DB builders
│   ├── build_b3_parquets.py
│   ├── b3_parser.py
│   ├── migrate_to_rb3_db.py
│   ├── recompute_iv_with_cdi.py
│   ├── phase1_regression.py
│   ├── quantify_synthetic_dominance.py
│   ├── validate_cdi_ivs.py
│   └── verify_sharpe_fix.py
├── tests/                           # Unchanged
├── apps/
│   └── streamlit-ui/
│       └── app.py
├── research/                        # Notebooks + analysis
│   ├── 2026-05-01 - B3 - VRP harvesting research.ipynb
│   ├── 2026-05-02 - B3 - data quality checks.ipynb
│   ├── 2026-05-06 - B3 - parameter grid search.ipynb
│   ├── 2026-05-13 - B3 - v3 grid search - BOVA11.ipynb
│   ├── 2026-05-13 - B3 - v3 grid search - PETR4.ipynb
│   ├── data integrity test.ipynb     # from aux/
│   └── data integrity test.R         # from aux/
├── data/
│   ├── Spy Options Database.db       # External, gitignored
│   ├── market_data_master.parquet    # SPY cache
│   ├── runs.db                       # Backtest run history
│   ├── paper_trades.db               # Paper trading state
│   ├── paper_config.json
│   └── B3/
│       ├── b3_options_rb3.db         # Active DB
│       ├── rb3_export/               # Source parquets for DB
│       │   ├── bova11_options_rb3.parquet
│       │   └── petr4_options_rb3.parquet
│       ├── bova11_backtest.parquet   # Backtest input parquets
│       ├── petr4_backtest.parquet
│       ├── v3_grid_search_results.parquet
│       └── artifacts/                # All generated outputs
│           ├── v3_grid/
│           ├── qa/
│           ├── skew/
│           ├── grid/
│           ├── phase1/
│           └── synthetic/
├── output/                           # User-facing HTML outputs
│   ├── straddle_backtest.html
│   └── B3 - parameter grid search v3.html
└── .agent/                           # Local debug/plan artifacts
    ├── plans/                        # 7 plans (000-006)
    └── reports/                      # Bug reports + checkpoint summaries
```

---

## Open Questions

1. **Raw COTAHIST files:** Delete all 17 files (~4.5 GB) or keep a subset? If you ever need to rebuild the DB from scratch, you'll need them. Alternative: archive to external drive.

2. **`reports/` HTML files:** Delete all 38? They're backtest output that can be regenerated.

3. **`data/B3/rb3_export/` parquets:** These are the source for `b3_options_rb3.db`. Keep as backup, or delete now that the DB is built?

4. **`src/straddle/paper_trading/`:** The directory has only compiled `.pyc` files and a backup. The actual source code was apparently deleted. Should we remove this dead module entirely?

5. **`apps/terminal-ui/`:** The Vue frontend has its own `dist/`, `node_modules/`, and build config. Is this actively used or dead code?

6. **Old market_data parquets:** `market_data_2011-01-01_2025-11-30.parquet` and `market_data_2021-01-01_2025-11-30.parquet` — are these used by any workflow or just leftover caches?
