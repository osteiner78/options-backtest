Plan 016 — I-10 Sharpe Fix: Impact Measurement & Results Update
Date: 2026-05-15 | Target: Coding agent | Branch: b3-backtest

Context
Bug I-10 (metrics.py) has been fixed: `_compute_sharpe_from_daily_pnl` now divides
daily P&L by running equity instead of initial balance. This affects ALL
laddering-mode Sharpe numbers in v6, v7, and PETR4 parquet files. The directional
conclusion (VRP exists at mid) should survive, but the published Sharpe numbers
need updating.

Phase 1 verified the fix is applied (commit pending). This plan measures the
impact and updates results.

---

Phase 1: Measure I-10 Sharpe Impact on Key Configs

Run the following configs standalone with the fixed code. For each, report
old Sharpe (from parquet), new Sharpe, and Δ.

Step 1.1 — BOVA11 recommended 25Δ config (both periods)
```python
config = {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
          "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
          "execution_mode": "mid"}
# Old: train Sharpe=0.908, holdout Sharpe=1.292
```
Run standalone in both train (2018-2022) and holdout (2023-2025).

Step 1.2 — BOVA11 best 16Δ config (holdout)
```python
config = {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50,
          "manage_at_dte": 14, "vix_filter": "rv_pct:70", "stop_loss_pct": 3.0,
          "execution_mode": "mid"}
# Old: holdout Sharpe=1.883
```

Step 1.3 — BOVA11 12Δ mid_plus_1tick (holdout, tiny total_return baseline)
```python
config = {"target_delta": 0.12, "dte_max": 30, "profit_target_pct": 0.25,
          "manage_at_dte": 7, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0,
          "execution_mode": "mid_plus_1tick"}
# Old: holdout Sharpe=11.557, total_return=4.5%
# Expected: negligible Δ (account barely grows, denominator barely shifts)
```

Step 1.4 — PETR4 recommended 25Δ config (both periods)
```python
config = {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
          "manage_at_dte": 14, "vix_filter": "OFF", "stop_loss_pct": 2.0,
          "execution_mode": "mid"}
# Check both train and holdout from PETR4 parquet
```

Output format:
```
Config          | Old Sharpe | New Sharpe | Δ    | Old Return | Train/Holdout
25Δ BOVA11      | 0.908      | 0.XXX      | ±X.XX | 14.7%     | train
25Δ BOVA11      | 1.292      | X.XXX      | ±X.XX | 6.5%      | holdout
16Δ BOVA11      | 1.883      | X.XXX      | ±X.XX | ...       | holdout
12Δ BOVA11      | 11.557     | XX.XXX     | ±X.XX | 4.5%      | holdout
25Δ PETR4       | X.XXX      | X.XXX      | ±X.XX | ...       | both
```

---

Phase 2: Decision Gate

Based on the ΔSharpe from Phase 1:

If max ΔSharpe across all tested configs < 0.15:
- The fix is immaterial for practical conclusions
- Do NOT re-run the full grid
- Update report §5 (Cell A) with a note: "Sharpe values updated for I-10 fix;
  all previously reported numbers were computed with the corrected formula as of
  [date]. The maximum observed ΔSharpe was X.XX."
- Update only the "Key numbers" in §1 Executive Summary

If max ΔSharpe ≥ 0.15 for ANY config:
- Re-run the full v7 BOVA11 grid (Phase 3)
- Re-run the full v7 PETR4 grid (Phase 3)
- Update the v7 report with corrected numbers from fresh parquets
- Update the v7 BOVA11 notebook by re-executing Cell 4 (load from fresh parquet)
  and re-rendering cells A-K

---

Phase 3: Re-run Grid(s) — IF NEEDED

Delete old parquet and execute grid search:
```bash
rm data/B3/v7_grid_search_results.parquet
python scripts/run_v7_grid.py --n-workers 8
```
(~1-2 hours, 5,376 backtests)

Re-run PETR4 grid:
```bash
rm data/B3/v7_petr4_grid_search_results.parquet
python scripts/phase4_petr4_full_grid.py --n-workers 8
```
(~30 minutes, 5,376 backtests)

After re-runs, verify:
- 0 errors in both parquets
- `entry_db_pct` values are percentages (0-100), not fractions (confirm Phase 1 fix holds)
- n_trades ≥ 30 filter produces the same count of valid rows

---

Phase 4: Update Reports & Notebooks

Step 4.1 — Update v7 report (`.agent/reports/016 - v7 final confirmation results.md`)
- §1 Executive Summary: update "Key numbers" with corrected Sharpe
- §5 v7 Refined Grid Results: update Cell A medians and % positive values
- §6 Commission Sensitivity: update commission table if Sharpe changed
- §9 Final Recommendation: update the recommended config's Sharpe
- §10 Known Issues: remove I-10 from limitations (now fixed), add note on I-2/I-6

Step 4.2 — Update v7 follow-up report (`.agent/reports/017 - post-v7 follow-up results.md`)
- §2.1 16Δ standalone: update Sharpe if re-run
- §4.2 PETR4 full grid: update Cell A medians if re-run

Step 4.3 — Re-execute notebook cells (if grid was re-run)
Open `research/2026-05-15 - B3 - v7 refined grid.ipynb`:
- Re-execute Cell 4 (load from updated parquet)
- Re-execute Cells A-K (all analysis cells)
- Verify Cell I (DB coverage) still shows percentages (0-100), not fractions
- Save notebook

Step 4.4 — PETR4 notebook (if grid was re-run)
Open `research/2026-05-15 - B3 - v7 PETR4 grid.ipynb`:
- Re-execute Cell 4 (load from updated parquet)
- Re-execute all analysis cells
- Save notebook

---

Phase 5: Final Verification

After all updates:
- Run `pytest tests/ -v` — all 129+ tests must pass
- Spot-check 3 random configs from the parquet against standalone runs to confirm consistency
- Verify no git-tracked parquet files have stale (pre-fix) timestamps

---

Files Affected

| File | Action |
|------|--------|
| `data/B3/v7_grid_search_results.parquet` | Regenerate if Phase 3 triggers |
| `data/B3/v7_petr4_grid_search_results.parquet` | Regenerate if Phase 3 triggers |
| `.agent/reports/016 - v7 final confirmation results.md` | Update Sharpe numbers |
| `.agent/reports/017 - post-v7 follow-up results.md` | Update if affected |
| `research/2026-05-15 - B3 - v7 refined grid.ipynb` | Re-execute if parquet regenerated |
| `research/2026-05-15 - B3 - v7 PETR4 grid.ipynb` | Re-execute if parquet regenerated |

---

Definition of Done

- [ ] Phase 1: 5 standalone runs complete, ΔSharpe table populated
- [ ] Phase 2: Decision made (re-run full grid or document only)
- [ ] Phase 3: If triggered, both grids re-run successfully (0 errors)
- [ ] Phase 4: Reports updated with corrected numbers, notebooks re-executed
- [ ] Phase 5: 129+ tests pass, spot-checks confirm consistency
- [ ] Commit with message: "fix: update Sharpe numbers for I-10 denominator fix"
