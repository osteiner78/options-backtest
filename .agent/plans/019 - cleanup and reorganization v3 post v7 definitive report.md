# 019 — Cleanup and Reorganization (v3 — post-v7 definitive report)

**Date:** 2026-05-16
**Status:** Ready for execution
**Replaces:** Prior Plan 011 (v2, 2026-05-14) and Plan 008
The v7 definitive research report is complete. All B3 research deliverables exist.
This pass removes every file that is not an active dependency of the final output.

---

## Files to DELETE

### aux/ — entire directory

| File                            | Why                                  |
| ------------------------------- | ------------------------------------ |
| `aux/data integrity test.ipynb` | Migration validation, served purpose |
| `aux/data integrity test.R`     | Migration validation, served purpose |

### data/B3/ — old artifacts

| File                                     | Why                                                 |
| ---------------------------------------- | --------------------------------------------------- |
| `b3_options.db` (226 MB)                 | Pre-rb3 database. Superseded by `b3_options_rb3.db` |
| `grid_heatmap_delta_dte.png`             | v1 chart                                            |
| `grid_heatmap_profit_manage.png`         | v1 chart                                            |
| `grid_scatter_ntrades_sharpe.png`        | v1 chart                                            |
| `grid_train_vs_holdout.png`              | v1 chart                                            |
| `qa_equity_price_reconciliation.png`     | Pre-rb3 QA                                          |
| `qa_iv_smile_bova11_2024.png`            | Pre-rb3 QA                                          |
| `qa_iv_smile_petr4__2024.png`            | Pre-rb3 QA                                          |
| `qa_iv_vs_vxewz.png`                     | Pre-rb3 QA                                          |
| `qa_spread_distribution.png`             | Pre-rb3 QA                                          |
| `v3_defensive_leg_roll.png`              | v3 chart                                            |
| `v3_heatmap_delta_dte.png`               | v3 chart                                            |
| `v3_heatmap_profit_manage.png`           | v3 chart                                            |
| `v3_scatter_nchains_sharpe.png`          | v3 chart                                            |
| `v3_stop_loss_impact.png`                | v3 chart                                            |
| `v3_train_vs_holdout.png`                | v3 chart                                            |
| `v3_vol_filter_boxplot.png`              | v3 chart                                            |
| `grid_search_results_strangle.parquet`   | v1 results                                          |
| `grid_search_results_volfilter.parquet`  | v1 results                                          |
| `bova11_backtest.parquet`                | Early single-run output                             |
| `petr4_backtest.parquet`                 | Early single-run output                             |
| `v3_grid_search_results.parquet`         | v3 results                                          |
| `v3_reproduction_results.parquet`        | v3 results                                          |
| `v4_grid_search_results.parquet`         | v4 results                                          |
| `v5_grid_search_results.parquet`         | v5 results                                          |
| `v5_grid_search_laddering.parquet`       | v5 results                                          |
| `v5_grid_search_laddering_fixed.parquet` | v5 results                                          |
| `v5_grid_search_singlepos_fixed.parquet` | v5 results                                          |
| `v6_grid_search_results.parquet`         | v6 results (known vol-cache bugs)                   |
| `build_log.txt`                          | Stale                                               |
| `db_build_log.txt`                       | Stale                                               |

### docs/ — misplaced or superseded

| File                                            | Action                                        |
| ----------------------------------------------- | --------------------------------------------- |
| `2026-05-13 - rb3 price validation.md`          | **Delete** (superseded by 2026-05-15 version) |
| `2026-05-15 - v6 final confirmation results.md` | **Move to** `.agent/reports/`                 |

### output/ — old exports and superseded data

| File/Dir                            | Action                                   |
| ----------------------------------- | ---------------------------------------- |
| All `.html` files in `output/`      | **Delete** (old notebook exports)        |
| `output/phase1_regression/`         | **Delete** entire directory (superseded) |
| `output/straddle_backtest.html`     | **Delete**                               |
| `output/Wireframe Terminal v3.html` | **Delete**                               |

### reports/ — entire directory

38 HTML portfolio backtest reports from April 2026 (~190 MB). All pre-v7. **Delete entire directory.**

### Root-level files

| File                                 | Why                                              |
| ------------------------------------ | ------------------------------------------------ |
| `straddle_backtest.html` (1.6 MB)    | Old backtest report                              |
| `Wireframe Terminal v3.html` (45 KB) | Terminal UI wireframe                            |
| `GEMINI.md`                          | Outdated SPY overview; Gemini CLI no longer used |

### scripts/ — one-off (served purpose)

| File                        | Purpose                                                |
| --------------------------- | ------------------------------------------------------ |
| `build_b3_parquets.py`      | Superseded by COTAHIST→db pipeline                     |
| `migrate_to_rb3_db.py`      | Migration complete                                     |
| `recompute_iv_with_cdi.py`  | CDI IVs stored in rb3 DB                               |
| `validate_cdi_ivs.py`       | Validation complete                                    |
| `verify_sharpe_fix.py`      | Fix verified by test suite                             |
| `build_v4_notebook.py`      | One-off generator                                      |
| `build_v5_notebook.py`      | One-off generator                                      |
| `build_v6_notebook.py`      | One-off generator                                      |
| `create_petr4_notebook.py`  | One-off generator                                      |
| `verify_position_mode.py`   | Verification complete                                  |
| `verify_single_position.py` | Verification complete                                  |
| `phase_a_checks.py`         | Served purpose                                         |
| `phase1_regression.py`      | Old DB parity check (references deleted b3_options.db) |

### src/straddle/paper_trading/ — entire directory

## Only contains `runner.py.backup`. Dead module. **Delete entire directory.**

## Files to ARCHIVE (move to `/archive/`)

Create `archive/scripts/` and `archive/research/`. These files were used once but repro
the methodology — keep them if the analysis ever needs rerunning.

### archive/scripts/

| File                         | Why archive                                               |
| ---------------------------- | --------------------------------------------------------- |
| `phase1_force_close.py`      | Phase 5 force-close P&L analysis                          |
| `phase2_16delta_deepdive.py` | 16Δ standalone runner (produces v7_16delta_deep_dive.csv) |
| `phase4_petr4_pilot.py`      | PETR4 pilot backtest                                      |
| `phase4_petr4_full_grid.py`  | PETR4 full grid runner (produces v7_petr4 parquet)        |
| `phase5_stress_scenarios.py` | Stress scenario runner (produces v7_stress_scenarios.csv) |

### archive/research/

| File                                               | Why archive              |
| -------------------------------------------------- | ------------------------ |
| `2026-05-01 - B3 - VRP harvesting research.ipynb`  | Initial exploration      |
| `2026-05-02 - B3 - data quality checks.ipynb`      | Data quality notebook    |
| `2026-05-06 - B3 - parameter grid search.ipynb`    | v1/v2 grid search        |
| `2026-05-13 - B3 - v3 grid search - BOVA11.ipynb`  | v3 BOVA11                |
| `2026-05-13 - B3 - v3 grid search - PETR4.ipynb`   | v3 PETR4                 |
| `2026-05-14 - B3 - v4 execution sensitivity.ipynb` | v4 execution sensitivity |
| `2026-05-14 - B3 - v5 confirmation grid.ipynb`     | v5 confirmation grid     |

---

## Files to KEEP (active/referenced)

### research/ (active)

| File                                                 | Why keep                               |
| ---------------------------------------------------- | -------------------------------------- |
| `2026-05-15 - B3 - definitive research report.ipynb` | **The authoritative document**         |
| `2026-05-15 - B3 - v7 refined grid.ipynb`            | BOVA11 v7 detailed analysis            |
| `2026-05-15 - B3 - v7 PETR4 grid.ipynb`              | PETR4 v7 detailed analysis             |
| `2026-05-15 - B3 - v6 expanded grid.ipynb`           | Methodology context (how v7 was built) |

### data/B3/ (active)

| File                                                    | Why keep                                           |
| ------------------------------------------------------- | -------------------------------------------------- |
| `b3_options_rb3.db` (266 MB)                            | **Active database** (already gitignored)           |
| `v7_grid_search_results.parquet`                        | BOVA11 v7 definitive results                       |
| `v7_petr4_grid_search_results.parquet`                  | PETR4 v7 definitive results                        |
| `v7_16delta_deep_dive.csv`                              | Referenced by definitive notebook                  |
| `v7_stress_scenarios.csv`                               | Referenced by definitive notebook                  |
| `skew_fit_bova11.png`, `skew_fit_petr4.png`             | Skew fitting output                                |
| `skew_stability_bova11.png`, `skew_stability_petr4.png` | Skew stability output                              |
| `COTAHIST_A*.TXT` (17 files, 303 MB)                    | Raw source data (already gitignored, keep on disk) |

### scripts/ (keep — reusable or core)

| File                                 | Why keep                                   |
| ------------------------------------ | ------------------------------------------ |
| `run_backtest.py`                    | CLI entry point                            |
| `run_api.py`                         | API entry point                            |
| `grid_search.py`                     | **Core grid search module**                |
| `run_v7_grid.py`                     | v7 grid runner                             |
| `b3_parser.py`                       | B3 COTAHIST parser (needed for DB rebuild) |
| `build_b3_options_db.py`             | DB build pipeline                          |
| `check_rb3_quality.py`               | Data quality checks                        |
| `fit_b3_skew.py`                     | Skew fitting (refit if data changes)       |
| `quantify_synthetic_dominance.py`    | Source tracking analysis                   |
| `b3_bulletin_fetcher.py`             | B3 bulletin API fetcher                    |
| `validate_b3_prices.py`              | B3 price validation                        |
| `extended_commission_sensitivity.py` | Extended commission analysis               |
| `petr4_period_robustness.py`         | PETR4 period robustness                    |
| `measure_sharpe_impact.py`           | I-10/rf impact measurement                 |
| `spot_check_sharpe.py`               | Sharpe spot-check tool                     |
| `reprocess_v7_sharpes.py`            | Parquet reprocessing tool                  |

### docs/ (keep — final deliverables)

| File                                              | Why keep                        |
| ------------------------------------------------- | ------------------------------- |
| `2026-05-15 - rb3 price validation.md`            | B3 bulletin validation results  |
| `2026-05-15 - extended commission sensitivity.md` | Commission sensitivity results  |
| `2026-05-15 - PETR4 period robustness.md`         | PETR4 period robustness results |

### output/ (keep — active data outputs)

| File/Dir                                               | Why keep                        |
| ------------------------------------------------------ | ------------------------------- |
| `commission_extended/bova11_commission_extended.csv`   | Extended commission source data |
| `commission_extended/petr4_commission_extended.csv`    | Extended commission source data |
| `petr4_robustness/petr4_robustness_results.csv`        | PETR4 robustness source data    |
| `validation/validation_targets.csv`                    | B3 validation source data       |
| `validation/validation_comparison.csv`                 | B3 validation source data       |
| `synthetic_diagnostic/bova11_source_breakdown.parquet` | Source tracking data            |

### apps/ (keep — frontends)

- `apps/streamlit-ui/` — Streamlit UI (keep, needs terminal-ui key fix)
- `apps/terminal-ui/` — Terminal UI (keep, needs terminal-ui key fix)

### src/ (keep — core library)

- `src/straddle/` — Keep as-is. Package name is `straddle`; renaming breaks all imports.
- Delete only `src/straddle/paper_trading/`

### tests/ (keep — test suite)

- All 129 tests, as-is.

### .agent/ (keep — project history)

- `.agent/plans/` — all 18 plan files
- `.agent/reports/` — all report files

---

## Files to UPDATE

### .gitignore — add entries

Build artifacts
.pytest_cache/
.streamlit/
Tool state
.opencode/
Archive (moved old files)
archive/
Reports (generated backtest output)
reports/

### README.md — rewrite

Replace SPY-focused content with B3 BOVA11/PETR4 overview:

```markdown
# B3 Options Short Strangle Backtest

BOVA11 and PETR4 short strangle backtesting engine with B3 options data (rb3 database, 2015–2025).

## Strategy

- Sells monthly OTM strangles (12–25Δ) on BOVA11 (ETF) and PETR4 (single stock)
- Mid-price execution, laddering mode, Reg-T margin accounting
- 21-DTE roll management, 50% profit target, 2.0× stop loss

## Key Findings

See `research/2026-05-15 - B3 - definitive research report.ipynb` for the complete analysis.

- BOVA11 VRP confirmed at mid execution (86.3% configs positive in holdout)
- Recommended config: 25Δ/dte21/pt50%/OFF/mid/laddering
- PETR4 VRP confirmed with stronger period robustness than BOVA11

## Quick Start

pip install -e ".[dev]"
pytest tests/ -v
python scripts/run_backtest.py --market bova11
Final Directory Structure (post-cleanup)
options-backtest/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── .gitignore
├── .agent/
│ ├── plans/ (18 files)
│ └── reports/ (all agent reports + moved v6 report)
├── archive/ (for reproducibility)
│ ├── scripts/ (6 phase scripts)
│ └── research/ (7 superseded notebooks)
├── src/straddle/ (core library, 10 modules)
├── scripts/ (16 reusable scripts)
├── tests/ (7 test files, 129 tests)
├── research/ (4 active notebooks: definitive + v6/v7)
├── data/B3/ (active data: 2 parquets, 2 CSVs, 4 PNGs, COTAHIST, rb3 DB)
├── docs/ (3 final validation reports)
├── output/ (4 active output directories)
└── apps/
├── streamlit-ui/
└── terminal-ui/
Summary
Phase
Delete
Archive
Keep
Update
Total
```
