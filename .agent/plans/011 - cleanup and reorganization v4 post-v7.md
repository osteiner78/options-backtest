# 011 — Cleanup and Reorganization (v4 — post-v7 definitive report)

**Date:** 2026-05-18  
**Status:** Ready for execution  
**Replaces:** Prior Plan 011 (v3, 2026-05-16)

The v7 definitive research report is complete. All B3 research deliverables exist.
This pass reorganizes the project into a clean two-tier structure: active files
needed to run the current research, and an `archive/` folder for all superseded
artifacts organized by research phase.

---

## Baseline Verification

```bash
pytest tests/ -v          # must pass 129/129
git status                # note any uncommitted changes
```

---

## Phase 1 — DELETE (~55 files + 2 directories, ~420 MB)

### 1a. reports/ — entire directory (~198 MB)

38 HTML portfolio backtest reports from April 2026. All superseded.

```bash
rm -rf reports/
```

### 1b. data/B3/ — old parquets and stale logs

```bash
git rm data/B3/grid_search_results_strangle.parquet
git rm data/B3/grid_search_results_volfilter.parquet
git rm data/B3/bova11_backtest.parquet
git rm data/B3/petr4_backtest.parquet
git rm data/B3/v3_grid_search_results.parquet
git rm data/B3/v3_reproduction_results.parquet
git rm data/B3/v4_grid_search_results.parquet
git rm data/B3/v5_grid_search_results.parquet
git rm data/B3/v5_grid_search_laddering.parquet
git rm data/B3/v5_grid_search_laddering_fixed.parquet
git rm data/B3/v5_grid_search_singlepos_fixed.parquet
git rm data/B3/v6_grid_search_results.parquet
git rm data/B3/build_log.txt
git rm data/B3/db_build_log.txt
git rm data/B3/b3_options.db
```

### 1c. Root files

```bash
git rm GEMINI.md
rm straddle_backtest.html
rm "Wireframe Terminal v3.html"
```

### 1d. output/ — old HTML and superseded data

```bash
find output -name "*.html" -delete
rm -rf output/phase1_regression/
```

### 1e. docs/ — superseded duplicate

```bash
git rm "docs/2026-05-13 - rb3 price validation.md"
```

---

## Phase 2 — ARCHIVE (move 35+ files into `archive/`)

The `archive/` folder is gitignored. Use `git mv` for tracked files, plain `mv` for untracked.

### 2a. Create archive structure

```bash
mkdir -p archive/aux
mkdir -p archive/v1-v3/charts
mkdir -p archive/v1-v3/notebooks
mkdir -p archive/v4-v5/notebooks
mkdir -p archive/scripts
mkdir -p archive/paper_trading
mkdir -p archive/apps/streamlit-ui
mkdir -p archive/misc
```

### 2b. archive/aux/ — data migration scripts

```bash
git mv "aux/data integrity test.ipynb" archive/aux/
git mv "aux/data integrity test.R" archive/aux/
rm -rf aux/
```

### 2c. archive/v1-v3/charts/ — all old PNGs

```bash
git mv data/B3/grid_heatmap_delta_dte.png archive/v1-v3/charts/
git mv data/B3/grid_heatmap_profit_manage.png archive/v1-v3/charts/
git mv data/B3/grid_scatter_ntrades_sharpe.png archive/v1-v3/charts/
git mv data/B3/grid_train_vs_holdout.png archive/v1-v3/charts/
git mv data/B3/qa_equity_price_reconciliation.png archive/v1-v3/charts/
git mv data/B3/qa_iv_smile_bova11_2024.png archive/v1-v3/charts/
git mv data/B3/qa_iv_smile_petr4__2024.png archive/v1-v3/charts/
git mv data/B3/qa_iv_vs_vxewz.png archive/v1-v3/charts/
git mv data/B3/qa_spread_distribution.png archive/v1-v3/charts/
git mv data/B3/v3_defensive_leg_roll.png archive/v1-v3/charts/
git mv data/B3/v3_heatmap_delta_dte.png archive/v1-v3/charts/
git mv data/B3/v3_heatmap_profit_manage.png archive/v1-v3/charts/
git mv data/B3/v3_scatter_nchains_sharpe.png archive/v1-v3/charts/
git mv data/B3/v3_stop_loss_impact.png archive/v1-v3/charts/
git mv data/B3/v3_train_vs_holdout.png archive/v1-v3/charts/
git mv data/B3/v3_vol_filter_boxplot.png archive/v1-v3/charts/
```

### 2d. archive/v1-v3/notebooks/ — old research notebooks

```bash
git mv "research/2026-05-01 - B3 - VRP harvesting research.ipynb" archive/v1-v3/notebooks/
git mv "research/2026-05-02 - B3 - data quality checks.ipynb" archive/v1-v3/notebooks/
git mv "research/2026-05-06 - B3 - parameter grid search.ipynb" archive/v1-v3/notebooks/
```

### 2e. archive/v4-v5/notebooks/ — v3, v4, v5 notebooks

```bash
git mv "research/2026-05-13 - B3 - v3 grid search - BOVA11.ipynb" archive/v4-v5/notebooks/
git mv "research/2026-05-13 - B3 - v3 grid search - PETR4.ipynb" archive/v4-v5/notebooks/
git mv "research/2026-05-14 - B3 - v4 execution sensitivity.ipynb" archive/v4-v5/notebooks/
git mv "research/2026-05-14 - B3 - v5 confirmation grid.ipynb" archive/v4-v5/notebooks/
```

### 2f. archive/scripts/ — 14 one-off scripts

```bash
git mv scripts/build_b3_parquets.py archive/scripts/
git mv scripts/migrate_to_rb3_db.py archive/scripts/
git mv scripts/recompute_iv_with_cdi.py archive/scripts/
git mv scripts/validate_cdi_ivs.py archive/scripts/
git mv scripts/verify_sharpe_fix.py archive/scripts/
git mv scripts/build_v4_notebook.py archive/scripts/
git mv scripts/build_v5_notebook.py archive/scripts/
git mv scripts/build_v6_notebook.py archive/scripts/
git mv scripts/create_petr4_notebook.py archive/scripts/
git mv scripts/verify_position_mode.py archive/scripts/
git mv scripts/verify_single_position.py archive/scripts/
git mv scripts/phase_a_checks.py archive/scripts/
git mv scripts/phase1_regression.py archive/scripts/
```

### 2g. archive/paper_trading/ — incomplete feature

The code has changed significantly since this was written. Restart from scratch when needed.

```bash
git mv src/straddle/paper_trading/runner.py.backup archive/paper_trading/
rm -rf src/straddle/paper_trading/
```

### 2h. archive/apps/streamlit-ui/ — broken, kept for reference

```bash
git mv apps/streamlit-ui/app.py archive/apps/streamlit-ui/
rm -rf apps/streamlit-ui/__pycache__/
```

### 2i. archive/misc/ — root artifacts

```bash
mv "Wireframe Terminal v3.html" archive/misc/
```

---

## Phase 3 — REHOME (move within active tree)

### 3a. Move v6 report from docs/ to .agent/reports/

```bash
git mv "docs/2026-05-15 - v6 final confirmation results.md" .agent/reports/
```

---

## Phase 4 — VERIFY active tree

Confirm these files/directories remain:

### research/ (4 active notebooks)

- `2026-05-15 - B3 - definitive research report.ipynb`
- `2026-05-15 - B3 - v7 refined grid.ipynb`
- `2026-05-15 - B3 - v7 PETR4 grid.ipynb`
- `2026-05-15 - B3 - v6 expanded grid.ipynb`

### data/B3/ (active data)

- `b3_options_rb3.db` (gitignored)
- `v7_grid_search_results.parquet`
- `v7_petr4_grid_search_results.parquet`
- `v7_16delta_deep_dive.csv`
- `v7_stress_scenarios.csv`
- `skew_fit_bova11.png`
- `skew_fit_petr4.png`
- `skew_stability_bova11.png`
- `skew_stability_petr4.png`
- `COTAHIST_A*.TXT` (17 files, gitignored)

### docs/ (3 final deliverables)

- `2026-05-15 - rb3 price validation.md`
- `2026-05-15 - extended commission sensitivity.md`
- `2026-05-15 - PETR4 period robustness.md`

### output/ (4 active subdirectories)

- `commission_extended/`
- `petr4_robustness/`
- `validation/`
- `synthetic_diagnostic/`

### scripts/ (16 reusable scripts)

- `run_backtest.py`
- `run_api.py`
- `run_v7_grid.py`
- `grid_search.py`
- `b3_parser.py`
- `build_b3_options_db.py`
- `check_rb3_quality.py`
- `fit_b3_skew.py`
- `quantify_synthetic_dominance.py`
- `b3_bulletin_fetcher.py`
- `validate_b3_prices.py`
- `extended_commission_sensitivity.py`
- `petr4_period_robustness.py`
- `measure_sharpe_impact.py`
- `spot_check_sharpe.py`
- `reprocess_v7_sharpes.py`

### src/ (core library)

- `src/straddle/` (10 modules, post-cleanup state)
- `src/straddle/paper_trading/` — DELETED in Phase 2g

### apps/

- `apps/streamlit-ui/` — DELETED in Phase 2h
- `apps/terminal-ui/` — keep as-is

### tests/ (7 test files)

- Keep all as-is.

---

## Phase 5 — UPDATE 4 files

### 5a. .gitignore

Add these entries (merge with existing):

```
# Project archive (superseded artifacts)
archive/

# Build artifacts
.pytest_cache/
.streamlit/
src/straddle.egg-info/

# Tool state
.opencode/

# Generated reports (pre-v7 backtest html output)
reports/
```

### 5b. pyproject.toml

Change the `description` field under `[project]`:

```toml
description = "BOVA11/PETR4 short strangle backtesting engine (B3 options)"
```

### 5c. CLAUDE.md — full rewrite

```markdown
# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

B3 short strangle backtesting engine — sells monthly OTM put + call options at
12–25Δ on BOVA11 (ETF) and PETR4 (single stock), targeting 21–60 DTE, with
21-DTE roll management. Mid-price execution, laddering mode, Reg-T margin accounting.

**Database:** `data/B3/b3_options_rb3.db` (SQLite, BOVA11 + PETR4, 2015–2025,
~9.6 GB). Uses CDI-based implied volatilities and deltas. American-style pricing
(BAW approximation) enabled for PETR4; European-style (BSM) for BOVA11.

## Commands

```bash
pip install -e ".[dev,frontend,api]"
pytest tests/ -v
python scripts/run_backtest.py --mode market --market bova11
python scripts/run_v7_grid.py --n-workers 4
```

## Architecture

```
params.py (PARAMS dict + B3 market presets)
  → data.py (load_market_data → COTAHIST parquet / Yahoo Finance)
  → engines.py (make_engine → SyntheticEngine | MarketEngine)
  → strategy.py (run_backtest → trades[], equity_curve)
     → portfolio.py (run_portfolio_backtest → laddering mode)
  → metrics.py (compute_metrics / compute_portfolio_metrics)
  → plotting.py (plot_backtest)
```

## Key Concepts

- **Two engines** share identical interface: `SyntheticEngine` (BSM + parametric vol skew)
  and `MarketEngine` (real bid/ask from SQLite DB, falls back to synthetic).
- **B3 presets** in `params.py` override SPY defaults (CDI rates, BVMF calendar,
  BRL currency, calibrated skew slopes, tick_size=0.05).
- **Laddering mode** via `run_portfolio_backtest` — Reg-T margin, entry cooldown,
  concurrent positions per expiry.
- **Metrics:** Information ratio (primary, for config comparison), true Sharpe
  (CDI-subtracted, for transparency), Calmar ratio, DB source tracking %.
- **Information Ratio:** The grid search Sharpe values are technically information
  ratios (excess-over-zero). The Brazilian risk-free rate (CDI, 10-13%)
  exceeds the strategy's absolute return (2-3%), making the standard Sharpe
  negative for most configs. See the definitive notebook methodology section.

## Definitive Research

`research/2026-05-15 - B3 - definitive research report.ipynb` — all findings,
executed cells, charts. Recommended config: 25Δ/dte21/pt50%/OFF/mid/laddering.

## Code Quality

- Review 027 applied: all print() → logging, named constants extracted, long
  functions split, dead code removed, duplicated blocks extracted to helpers.
- 129 tests pass at `pytest tests/ -v`.
- All known bugs from code reviews 015–027 are fixed or documented as immaterial.
```

### 5d. README.md — full rewrite

```markdown
# B3 Options Short Strangle Backtest

BOVA11 and PETR4 short strangle backtesting engine with B3 options data
(rb3 database, 2015–2025).

## Strategy

Sells monthly OTM strangles (12–25Δ), mid-price execution, laddering mode,
Reg-T margin accounting. 21-DTE roll management, 50% profit target, 2.0× stop.

## Key Finding

VRP confirmed on both BOVA11 (86.3% configs positive in holdout at mid)
and PETR4 (76.9%). Recommended config: 25Δ / dte21 / pt50% / OFF / mid /
laddering. See `research/2026-05-15 - B3 - definitive research report.ipynb`
for the complete analysis.

## Quick Start

```bash
pip install -e ".[dev]"
pytest tests/ -v
python scripts/run_backtest.py --mode market --market bova11
python scripts/run_v7_grid.py
```
```

---

## Phase 6 — Verify

```bash
# All tests still pass
pytest tests/ -v

# Backtest still works
python scripts/run_backtest.py --mode synthetic --no-plot

# Archive structure is correct
find archive -type f | sort

# Active tree is clean
ls research/ data/B3/ docs/ scripts/ output/

# Git status shows expected changes
git status
```

**If any tests fail or backtest output differs from baseline, STOP and report.**

---

## Commit

```bash
git add -A
git commit -m "chore: post-v7 cleanup — archive superseded artifacts, delete 420MB of old reports"
```

---

## Summary

| Phase | Files affected | Net result |
|-------|---------------|------------|
| 1 — Delete | ~55 files + 2 directories | ~420 MB reclaimed |
| 2 — Archive | 35+ files into 8 archive subdirs | Project history preserved |
| 3 — Rehome | 1 file | v6 report moved to correct location |
| 4 — Verify | Active tree confirmed | Only current artifacts remain |
| 5 — Update | 4 files | .gitignore, pyproject.toml, CLAUDE.md, README.md |
| **Total** | **~95 files touched** | **Clean two-tier project** |
