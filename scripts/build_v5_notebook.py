#!/usr/bin/env python3
"""Generate the v5 confirmation grid notebook."""
import json
from pathlib import Path

OUT_PATH = Path(__file__).parent.parent / "research" / "2026-05-15 - B3 - v5 confirmation grid.ipynb"

cells = []

def md(source_lines):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": [l + "\n" for l in source_lines[:-1]] + [source_lines[-1]]})

def code(source_lines):
    cells.append({"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
                  "source": [l + "\n" for l in source_lines[:-1]] + [source_lines[-1]]})

# ── Title ────────────────────────────────────────────────────────────────
md([
    "# B3 v5 — Confirmation Grid (Expiration Fix + v3 Reproduction)",
    "",
    "Fixes applied in v5:",
    "1. **B3 expiration mismatch fixed**: B3 BOVA11 options used 3rd-Monday expirations before May 2021.",
    "   The strategy computed 3rd-Friday dates, causing ~70% of train-period entries to fall back to",
    "   synthetic pricing (5% adj vs ~40% real spread). Now fixed: MarketEngine queries the DB for",
    "   actual available expirations via `get_db_expiration()`.",
    "2. **volume_filtered mode removed**: Was always identical to mid — the global percentile",
    "   threshold of 12,900 was always exceeded by liquid 16-delta options. Correlation = 1.000.",
    "3. **v3 reproduction cell added** to explain the Sharpe contradiction (v3 holdout median = -1.17",
    "   vs v4 bid_ask holdout = +0.38).",
    "",
    "**Fixed**: market mode, cash_investment_mode=risk_free, cash_yield_annual=0, use_cdi_ivs=True",
    "**Grid**: 3×2×1×2×2×1×1×4 = 96 combos × 2 periods = **192 backtests**",
])

# ── Imports ──────────────────────────────────────────────────────────────
code([
    "%matplotlib inline",
    "import sys",
    "from pathlib import Path",
    "import numpy as np",
    "import pandas as pd",
    "import matplotlib.pyplot as plt",
    "import matplotlib.ticker as mticker",
    "import sqlite3",
    "",
    "plt.rcParams['figure.dpi'] = 120",
    "plt.rcParams['figure.figsize'] = (10, 5)",
    "",
    "ROOT = Path.cwd().parent if (Path.cwd().name == 'research') else Path.cwd()",
    "sys.path.insert(0, str(ROOT / 'scripts'))",
    "sys.path.insert(0, str(ROOT / 'src'))",
    "from grid_search import run_grid, enumerate_grid, GRID_DIMS, _apply_grid_overrides",
    "",
    "OUT_DIR = ROOT / 'data' / 'B3'",
    "RESULTS_PATH = OUT_DIR / 'v5_grid_search_results.parquet'",
    "DB_PATH = ROOT / 'data' / 'B3' / 'b3_options_rb3.db'",
])

# ── Grid Definition ──────────────────────────────────────────────────────
md([
    "## 1. v5 Grid Definition",
    "",
    "Same grid as v4 minus `volume_filtered` (3×2×1×2×2×1×1×4 = 96 combos).",
])

code([
    "GRID = {",
    "    'target_delta': [0.16, 0.20, 0.25],",
    "    'dte_max': [30, 45],",
    "    'profit_target_pct': [0.50],",
    "    'manage_at_dte': [7, 14],",
    "    'vix_filter': ['OFF', 'rv_pct:80'],",
    "    'defensive_leg_roll': [False],",
    "    'stop_loss_pct': [3.0],",
    "    'execution_mode': [",
    "        'bid_ask',",
    "        'mid_minus_1tick',",
    "        'mid',",
    "        'mid_plus_1tick',",
    "    ],",
    "}",
    "# 3 × 2 × 1 × 2 × 2 × 1 × 1 × 4 = 96 combos",
    "combos = enumerate_grid(GRID)",
    "print(f'Grid: {len(combos)} valid combos × 2 periods = {len(combos) * 2} backtests')",
])

# ── Run Configuration ────────────────────────────────────────────────────
md(["## 2. Run Configuration"])

code([
    "RUNS = [",
    "    ('train', 'bova11', '2018-01-02', '2022-12-31'),",
    "    ('holdout', 'bova11', '2023-01-02', '2025-11-30'),",
    "]",
    "for r in RUNS:",
    "    print(r)",
])

# ── Execute / Load ───────────────────────────────────────────────────────
md([
    "## 3. Execute Grid Search",
    "",
    "Runs 192 backtests. Skips if results already cached.",
])

code([
    "if RESULTS_PATH.exists():",
    "    print(f'Loading cached results from {RESULTS_PATH}')",
    "    results = pd.read_parquet(RESULTS_PATH)",
    "else:",
    "    results = run_grid(GRID, RUNS, output_path=RESULTS_PATH)",
    "    print(f'Saved {len(results)} rows to {RESULTS_PATH}')",
    "",
    "# Filter to valid completed runs",
    "df = results[results['error'].isna() & (results['n_trades'] >= 30)].copy()",
    "df['execution_mode'] = pd.Categorical(",
    "    df['execution_mode'],",
    "    categories=['bid_ask', 'mid_minus_1tick', 'mid', 'mid_plus_1tick'],",
    "    ordered=True,",
    ")",
    "df['delta_label'] = df['target_delta'].apply(lambda x: f'{int(x*100)}Δ')",
    "print(f'Valid runs: {len(df)} / {len(results)}')",
    "print(f'Train: {len(df[df[\"period_label\"]==\"train\"])}, Holdout: {len(df[df[\"period_label\"]==\"holdout\"])}')",
])

# ── Cell A: Sharpe vs execution_mode boxplot ─────────────────────────────
md([
    "## 4. Cell A — Sharpe vs Execution Mode",
    "Most important chart. One subplot per period. Ordered x-axis. Horizontal line at y=0.",
])

code([
    "fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)",
    "for ax, (label, period_df) in zip(axes, df.groupby('period_label')):",
    "    period_df.boxplot(column='sharpe', by='execution_mode', ax=ax, grid=False, rot=45)",
    "    ax.set_title(f'{label}  (n={len(period_df)})', fontsize=12)",
    "    ax.set_xlabel('')",
    "    ax.set_ylabel('Sharpe Ratio')",
    "    ax.axhline(y=0, color='red', linestyle='--', linewidth=1, alpha=0.7)",
    "    ax.tick_params(axis='x', rotation=45)",
    "fig.suptitle('')",
    "plt.tight_layout()",
    "plt.show()",
])

# ── Cell B: Break-even execution level ───────────────────────────────────
md([
    "## 5. Cell B — Break-even Execution Level",
    "Leftmost execution mode where holdout median Sharpe crosses zero (if any).",
])

code([
    "modes = ['bid_ask', 'mid_minus_1tick', 'mid', 'mid_plus_1tick']",
    "holdout = df[df['period_label'] == 'holdout']",
    "train = df[df['period_label'] == 'train']",
    "",
    "break_even = None",
    "for mode in modes:",
    "    median_sharpe = holdout[holdout['execution_mode'] == mode]['sharpe'].median()",
    "    train_median = train[train['execution_mode'] == mode]['sharpe'].median()",
    "    print(f'  {mode:20s}  train_median={train_median:+.4f}  holdout_median={median_sharpe:+.4f}')",
    "    if break_even is None and median_sharpe > 0:",
    "        break_even = mode",
    "",
    "if break_even:",
    "    print(f'\\nBreak-even execution: **{break_even}** (leftmost mode with positive holdout median Sharpe)')",
    "else:",
    "    print(f'\\nNo break-even — all modes have negative median holdout Sharpe')",
])

# ── Cell C: Sharpe by execution_mode × target_delta ──────────────────────
md([
    "## 6. Cell C — Execution Sensitivity by Delta",
    "Does 16-delta have more execution sensitivity than 25-delta?",
    "Heatmap: rows = execution_mode, columns = target_delta, values = median Sharpe.",
])

code([
    "pivot = holdout.pivot_table(values='sharpe', index='execution_mode', columns='target_delta', aggfunc='median')",
    "pivot.columns = [f'{int(c*100)}Δ' for c in pivot.columns]",
    "",
    "fig, ax = plt.subplots(figsize=(8, 6))",
    "im = ax.imshow(pivot.values, aspect='auto', cmap='RdYlGn', vmin=-2, vmax=0.5)",
    "ax.set_xticks(range(len(pivot.columns)))",
    "ax.set_xticklabels(pivot.columns)",
    "ax.set_yticks(range(len(pivot.index)))",
    "ax.set_yticklabels(pivot.index)",
    "ax.set_xlabel('Target Delta')",
    "ax.set_ylabel('Execution Mode')",
    "ax.set_title('Median Holdout Sharpe: Execution Mode × Target Delta')",
    "for i in range(len(pivot.index)):",
    "    for j in range(len(pivot.columns)):",
    "        ax.text(j, i, f'{pivot.iloc[i, j]:+.2f}', ha='center', va='center', fontsize=9)",
    "plt.colorbar(im, ax=ax, label='Median Sharpe')",
    "plt.tight_layout()",
    "plt.show()",
])

# ── Cell D: Entry DB coverage by period and mode ─────────────────────────
md([
    "## 7. Cell D — Entry DB Coverage by Period and Mode",
    "Replaces the volume_filter skip-rate cell. Shows `entry_db_pct` and `mtm_avg_db_pct` by period.",
    "",
    "**Key question**: did train-period entry_db_pct improve from v4's 30% to >85%",
    "thanks to the expiration mismatch fix?",
])

code([
    "modes = ['bid_ask', 'mid_minus_1tick', 'mid', 'mid_plus_1tick']",
    "for period in ['train', 'holdout']:",
    "    print(f'--- {period} ---')",
    "    for mode in modes:",
    "        sub = df[(df['period_label'] == period) & (df['execution_mode'] == mode)]",
    "        entry_pct = sub['entry_db_pct'].mean()",
    "        mtm_pct = sub['mtm_avg_db_pct'].mean()",
    "        print(f'  {mode:20s}: entry_db_pct={entry_pct:.1f}%, mtm_db_pct={mtm_pct:.1f}%')",
    "    print()",
    "",
    "# Global averages by period",
    "print('=== Global DB coverage ===')",
    "for period in ['train', 'holdout']:",
    "    sub = df[df['period_label'] == period]",
    "    print(f'{period}: entry_db_pct={sub[\"entry_db_pct\"].mean():.1f}%, mtm_db_pct={sub[\"mtm_avg_db_pct\"].mean():.1f}%')",
])

# ── Cell E: v3 Reproduction Cell ─────────────────────────────────────────
md([
    "## 8. Cell E — v3 Reproduction",
    "",
    "Runs the EXACT v3 grid configuration with the current codebase to compare:",
    "- v3 original: bid_ask only, wider grid, different holdout period (2024-2025)",
    "- Goal: reproduce v3's -1.17 median Sharpe and explain the contradiction with v4.",
])

code([
    "V3_GRID = {",
    "    'target_delta': [0.16, 0.20, 0.25, 0.30, 0.50],",
    "    'dte_max': [21, 30, 45, 60],",
    "    'profit_target_pct': [0.25, 0.50, 0.75],",
    "    'manage_at_dte': [7, 10, 14, 21],",
    "    'vix_filter': ['OFF', 'rv_pct:70', 'rv_pct:80', 'rv_pct:90', 'ivr:30', 'ivr:50'],",
    "    'defensive_leg_roll': [True, False],",
    "    'stop_loss_pct': [1.5, 2.0, 3.0],",
    "    'execution_mode': ['bid_ask'],",
    "}",
    "",
    "# v3 original periods",
    "V3_RUNS = [",
    "    ('v3_train', 'bova11', '2020-04-01', '2023-12-31'),",
    "    ('v3_holdout', 'bova11', '2024-01-01', '2025-12-31'),",
    "    # Also: v3 grid on v4's holdout period (to isolate period effect)",
    "    ('v3_on_v4_holdout', 'bova11', '2023-01-02', '2025-11-30'),",
    "]",
    "",
    "v3_combos = enumerate_grid(V3_GRID)",
    "print(f'V3 grid: {len(v3_combos)} combos × {len(V3_RUNS)} runs = {len(v3_combos) * len(V3_RUNS)} backtests')",
    "",
    "# Check for cached results",
    "V3_PATH = OUT_DIR / 'v3_reproduction_results.parquet'",
    "if V3_PATH.exists():",
    "    print(f'Loading cached V3 results from {V3_PATH}')",
    "    v3_results = pd.read_parquet(V3_PATH)",
    "else:",
    "    # Temporarily switch GRID export so run_grid works with V3_GRID",
    "    v3_results = run_grid(V3_GRID, V3_RUNS, output_path=V3_PATH)",
    "    print(f'Saved {len(v3_results)} rows to {V3_PATH}')",
    "",
    "v3_valid = v3_results[v3_results['error'].isna() & (v3_results['n_trades'] >= 30)].copy()",
    "print(f'V3 valid runs: {len(v3_valid)} / {len(v3_results)}')",
    "",
    "# Key comparison: v3 holdout (2024-2025) median Sharpe",
    "v3_holdout = v3_valid[v3_valid['period_label'] == 'v3_holdout']",
    "v3_on_v4 = v3_valid[v3_valid['period_label'] == 'v3_on_v4_holdout']",
    "v3_train = v3_valid[v3_valid['period_label'] == 'v3_train']",
    "",
    "print(f'\\nv3_holdout (2024-2025): n={len(v3_holdout)}, median Sharpe={v3_holdout[\"sharpe\"].median():.4f}')",
    "print(f'v3_on_v4_holdout (2023-2025): n={len(v3_on_v4)}, median Sharpe={v3_on_v4[\"sharpe\"].median():.4f}')",
    "print(f'v3_train (2020-2023): n={len(v3_train)}, median Sharpe={v3_train[\"sharpe\"].median():.4f}')",
    "",
    "print(f'\\n=== Comparing with documented v3 values ===')",
    "print(f'Documented v3 holdout median Sharpe: -1.17')",
    "print(f'Our v3 reproduction holdout median Sharpe: {v3_holdout[\"sharpe\"].median():.4f}')",
    "print(f'(If dramatically different, suspect changes to other params: use_cdi_ivs, open_fill_adj, etc.)')",
    "",
    "# Compare: v3 grid on v4 period vs v4 grid on v4 period",
    "v4_holdout = df[df['period_label'] == 'holdout']",
    "v4_bid_ask = v4_holdout[v4_holdout['execution_mode'] == 'bid_ask']",
    "print(f'\\n=== v3 vs v4 on same holdout (2023-2025) ===')",
    "print(f'v3 config on v4 period median Sharpe: {v3_on_v4[\"sharpe\"].median():.4f}')",
    "print(f'v4 bid_ask on v4 period median Sharpe: {v4_bid_ask[\"sharpe\"].median():.4f}')",
    "print(f'v4 bid_ask expanded (2023-2025) median Sharpe: {v4_bid_ask[\"sharpe\"].median():.4f}')",
    "print(f'(Difference = effect of grid parameter space, not period selection)')",
])

# ── Cell F: Spread cost analysis ─────────────────────────────────────────
md([
    "## 9. Cell F — Spread Cost Analysis",
    "Query rb3 DB for (ask − bid) / mark distribution by delta bucket and year.",
    "Quantifies exactly how much 'sell at bid' costs relative to mid.",
])

code([
    "conn = sqlite3.connect(str(DB_PATH))",
    "query = '''",
    "SELECT date, delta, mark, bid, ask",
    "FROM options_data",
    "WHERE underlying = 'bova11'",
    "  AND bid > 0 AND ask > 0 AND ask >= bid",
    "  AND mark > 0 AND delta IS NOT NULL",
    "  AND ABS(delta) >= 0.05 AND ABS(delta) <= 0.50",
    "  AND implied_volatility < 2.0",
    "'''",
    "spread_df = pd.read_sql(query, conn)",
    "conn.close()",
    "",
    "spread_df['spread_pct'] = (spread_df['ask'] - spread_df['bid']) / spread_df['mark'] * 100",
    "spread_df['abs_delta'] = spread_df['delta'].abs()",
    "spread_df['year'] = pd.to_datetime(spread_df['date']).dt.year",
    "spread_df['delta_bucket'] = pd.cut(",
    "    spread_df['abs_delta'],",
    "    bins=[0.10, 0.20, 0.30, 0.50],",
    "    labels=['0.10–0.20', '0.20–0.30', '0.30–0.50'],",
    ")",
    "",
    "# By delta bucket",
    "delta_summary = spread_df.groupby('delta_bucket', observed=False)['spread_pct'].median()",
    "print('Median spread (% of mark) by delta bucket:')",
    "for bucket, val in delta_summary.items():",
    "    print(f'  {bucket}: {val:.1f}%')",
    "print(f'  16-delta bucket median spread: {delta_summary.get(\"0.10–0.20\", 0):.1f}%')",
    "",
    "# By year",
    "year_summary = spread_df.groupby('year')['spread_pct'].median()",
    "print(f'\\nMedian spread by year:')",
    "for year, val in year_summary.items():",
    "    print(f'  {int(year)}: {val:.1f}%')",
    "",
    "# Plot",
    "fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))",
    "spread_df.boxplot(column='spread_pct', by='delta_bucket', ax=ax1, grid=False)",
    "ax1.set_title('Spread (% of mark) by Delta Bucket')",
    "ax1.set_xlabel('Absolute Delta')",
    "ax1.set_ylabel('Spread % of Mark')",
    "ax1.set_ylim(0, spread_df['spread_pct'].quantile(0.95))",
    "",
    "spread_df.boxplot(column='spread_pct', by='year', ax=ax2, grid=False, rot=45)",
    "ax2.set_title('Spread (% of mark) by Year')",
    "ax2.set_xlabel('Year')",
    "ax2.set_ylabel('Spread % of Mark')",
    "ax2.set_ylim(0, spread_df['spread_pct'].quantile(0.95))",
    "fig.suptitle('')",
    "plt.tight_layout()",
    "plt.show()",
])

# ── Cell G: Per-trade P&L comparison ─────────────────────────────────────
md([
    "## 10. Cell G — Per-Trade P&L for Best Config",
    "Pick the config with best holdout Sharpe overall. Run a single backtest for each",
    "execution mode with identical parameters. Compare per-trade P&L side-by-side.",
])

code([
    "from straddle.params import PARAMS, apply_market_preset",
    "from straddle.data import load_market_data",
    "from straddle.engines import make_engine",
    "from straddle import run_portfolio_backtest",
    "from straddle.metrics import compute_portfolio_metrics",
    "",
    "# Find the best config overall (by holdout Sharpe)",
    "best_idx = holdout['sharpe'].idxmax()",
    "best_combo = holdout.loc[best_idx]",
    "print(f'Best config: delta={best_combo[\"target_delta\"]}, dte_max={best_combo[\"dte_max\"]}, ',",
    "      f'manage_at_dte={best_combo[\"manage_at_dte\"]}, vix_filter={best_combo[\"vix_filter\"]}, ',",
    "      f'execution_mode={best_combo[\"execution_mode\"]}')",
    "print(f'Holdout Sharpe: {best_combo[\"sharpe\"]:.4f}')",
    "",
    "# Run the same config with all 4 execution modes for holdout period",
    "start, end = '2023-01-02', '2025-11-30'",
    "perf_dict = {}",
    "for mode in modes:",
    "    params = dict(PARAMS)",
    "    params = apply_market_preset(params, 'bova11')",
    "    params.update({",
    "        'mode': 'market', 'start_date': start, 'end_date': end,",
    "        'portfolio_mode': 'laddering', 'cash_investment_mode': 'risk_free',",
    "        'cash_yield_annual': 0.0, 'use_cdi_ivs': True,",
    "        'execution_mode': mode,",
    "        'target_delta': best_combo['target_delta'],",
    "        'dte_max': int(best_combo['dte_max']),",
    "        'dte_min': {30: 20, 45: 30}.get(int(best_combo['dte_max']), 20),",
    "        'profit_target_pct': best_combo['profit_target_pct'],",
    "        'manage_at_dte': int(best_combo['manage_at_dte']),",
    "        'stop_loss_pct': best_combo['stop_loss_pct'],",
    "        'use_price_stop': True,",
    "        'defensive_leg_roll_enabled': False,",
    "    })",
    "    # Apply vol filter",
    "    vf = str(best_combo['vix_filter'])",
    "    if vf.upper() == 'OFF':",
    "        params['vol_filter_mode'] = 'off'",
    "        params['vix_entry_filter_enabled'] = False",
    "    elif vf.startswith('rv_pct:'):",
    "        params['vol_filter_mode'] = 'rv_pct'",
    "        params['vol_filter_threshold'] = float(vf.split(':')[1])",
    "",
    "    print(f'  Running {mode}...')",
    "    data = load_market_data(start, end, market='bova11')",
    "    engine = make_engine(params)",
    "    try:",
    "        trades, eq, _, _ = run_portfolio_backtest(data, params, engine)",
    "        perf_dict[mode] = {'trades': trades, 'equity': eq, 'params': params}",
    "        m = compute_portfolio_metrics(trades, eq, params, data)",
    "        print(f'    Sharpe={m[\"sharpe\"]:.4f}, n_trades={m[\"n\"]}, tot_ret={m[\"tot\"]:.3f}')",
    "    except Exception as e:",
    "        print(f'    ERROR: {e}')",
    "        perf_dict[mode] = None",
    "    finally:",
    "        if hasattr(engine, 'close'):",
    "            engine.close()",
    "",
    "# Build per-trade P&L DataFrame",
    "pnl_rows = []",
    "for mode in modes:",
    "    if perf_dict.get(mode) and perf_dict[mode]['trades']:",
    "        for t in perf_dict[mode]['trades']:",
    "            pnl_rows.append({",
    "                'trade_num': t.trade_num,",
    "                'entry_date': t.entry_date,",
    "                'exit_date': t.exit_date if hasattr(t, 'exit_date') and t.exit_date else None,",
    "                'execution_mode': mode,",
    "                'pnl': getattr(t, 'pnl', getattr(t, 'net_pnl', None)),",
    "            })",
    "",
    "if pnl_rows:",
    "    pnl_df = pd.DataFrame(pnl_rows)",
    "    pnl_pivot = pnl_df.pivot_table(values='pnl', index=['trade_num', 'entry_date'], columns='execution_mode', aggfunc='first')",
    "    display(pnl_pivot.describe())",
    "    print(f'\\nCorrelation matrix of trade PnL across execution modes:')",
    "    display(pnl_pivot.corr())",
    "else:",
    "    print('No per-trade P&L data available')",
])

# ── Cell H: Period-overlap diagnostic ─────────────────────────────────────
md([
    "## 11. Cell H — Period-Overlap Diagnostic",
    "",
    "Compare the same parameter set across different holdout periods to isolate",
    "the period-selection effect from code differences.",
    "",
    "Compares v5 holdout (2023-2025) vs v3 holdout (2024-2025) for overlapping",
    "parameter combos if any exist.",
])

code([
    "# Find the best v5 config (from the v5 grid) and check if similar params",
    "# exist in the v3 reproduction results",
    "print('=== Best v5 config details ===')",
    "print(f'delta={best_combo[\"target_delta\"]}, dte_max={best_combo[\"dte_max\"]}, ',",
    "      f'manage={best_combo[\"manage_at_dte\"]}, ',",
    "      f'vix_filter={best_combo[\"vix_filter\"]}, stop={best_combo[\"stop_loss_pct\"]}, ',",
    "      f'exec={best_combo[\"execution_mode\"]}')",
    "print(f'Holdout Sharpe: {best_combo[\"sharpe\"]:.4f}')",
    "",
    "# If v3 reproduction ran, compare same period spans",
    "if 'v3_valid' in dir():",
    "    print(f'\\n=== Period effect on same params ===')",
    "    # Isolate: best v5 combo's parameters, check v3 results for matches",
    "    v3_best_match = v3_valid[",
    "        (v3_valid['target_delta'] == best_combo['target_delta']) &",
    "        (v3_valid['dte_max'] == best_combo['dte_max']) &",
    "        (v3_valid['profit_target_pct'] == best_combo['profit_target_pct']) &",
    "        (v3_valid['manage_at_dte'] == best_combo['manage_at_dte'])",
    "    ]",
    "    if len(v3_best_match) > 0:",
    "        for _, row in v3_best_match.iterrows():",
    "            print(f'  v3_{row[\"period_label\"]}: Sharpe={row[\"sharpe\"]:.4f}, n_trades={row[\"n_trades\"]}')",
    "    else:",
    "        print('  No exact match in v3 grid (v3 used wider grid)')",
    "else:",
    "    print('\\n(Re-run Cell E to populate v3 reproduction results)')",
])

# ── Write notebook ───────────────────────────────────────────────────────
notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12.0"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)
print(f"Wrote {OUT_PATH} ({len(cells)} cells)")
