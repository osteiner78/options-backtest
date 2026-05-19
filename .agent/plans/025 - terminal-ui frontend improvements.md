# Terminal-UI Frontend Improvement Plan

**Date:** 2026-05-19
**Scope:** `apps/terminal-ui/` — no backend changes unless explicitly noted.
**Estimated effort:** 2–3 sessions (frontend-only items = 1 session; backend-frontend items = 1–2 sessions).

---

## 1. Font-size increases (sidebar + tables)

**Files:** `apps/terminal-ui/src/styles/components.css`

**Changes:**
- Sidebar parameter rows `.pr` → `13px` (from `12px`)
- Sidebar section headers `.sec-hdr` → `12px` (from `11px`)
- Indented sub-params `.pr.pr-indent .pl` → `12px` (from `11px`)
- Exit-breakdown / VIX-regime tables `table.dt` → `12px` (from `11px`)
- Table headers `table.dt th` → `11px` (from `10px`)
- Table sub-rows `table.dt tr.sub td` → `11.5px` (from `10.5px`)
- `tp-title` → `13px` (from `12px`)

**Why only one notch:** The sidebar is fixed at `188 px`; going larger will cause truncation of values (e.g. `50,000` or dates). The tables sit in a constrained two-column grid; one step up improves legibility without forcing horizontal scroll.

---

## 2. Add Information Ratio (IR) for the B&H row

**Backend file:** `src/straddle/metrics.py` (`_compute_benchmark_stats`)
**Frontend file:** `apps/terminal-ui/src/components/perf/PerformanceBar.js`

**Problem:** `_compute_benchmark_stats` computes `underlying_sharpe` (excess-over-risk-free) but does **not** compute the excess-over-zero version (IR).

**Backend change:**
```python
# In _compute_benchmark_stats, after computing underlying_sharpe:
underlying_ir = float((_daily.mean() / _daily.std(ddof=1)) * np.sqrt(252))
return {..., "underlying_ir": underlying_ir}
```

**API model change:** `src/straddle/api.py` `MetricsResponse`
- Add `underlying_info_ratio: Optional[float] = None`
- Wire it in `_build_metrics_response` (`_clean(metrics.get("underlying_ir", 0))`)

**Frontend change:**
- In `PerformanceBar.js`, add `<td class="r c-blue fw6">${formatNum(metrics.underlying_info_ratio)}</td>` in the `${market} B&H` row, matching the IR column position used for PORTFOLIO.

**Note:** `_compute_benchmark_stats` is also called inside `compute_metrics` (non-portfolio path) — same addition applies there.

---

## 3. Per-component Sharpe / IR / Max DD / Calmar columns

**Question:** *Does it make sense / is it possible?*

**Answer:** Partially — here is what is feasible with current data.

| Component | Sharpe & IR | Max DD | Calmar | Feasibility |
|---|---|---|---|---|
| **Short strangles (options only)** | Needs daily-return series. Backend already builds `mtm_equity` in `compute_portfolio_metrics`. We can extend the API to return `options_sharpe`, `options_ir`, `options_mdd`, `options_calmar`. | Already derived client-side from trade P&L (`computeOptionsMDD`). | Already derived client-side (`optCalmar`). | **Backend + frontend work.** |
| **BOVA11 / underlying cash** | `underlying_sharpe` returned. IR can be added (see #2). | `underlying_max_drawdown` returned. | `underlying_calmar` returned. | **Add IR only (see #2).** |
| **Risk-free cash** | Monotonically increasing → Sharpe ≈ 0, IR meaningless. | Zero (or near-zero). | Infinite / meaningless. | **Do not add — would clutter table with `--` or nonsensical values.** |

**Recommendation:**
1. **Backend:** extend `compute_portfolio_metrics` to compute and return `options_sharpe`, `options_ir`, `options_mdd`, `options_calmar` from the existing `mtm_equity` series (the same way portfolio-level metrics are computed, but using only the options-leg daily P&L).
2. **Frontend:** add those four columns to the `o/w short strangles` row in `PerformanceBar.js`.
3. For `o/w ${market}` row, add the IR column (already have Sharpe, MaxDD, Calmar).
4. Leave `o/w risk-free` row as-is (all four columns stay `--`).

**Backend API additions:**
- `MetricsResponse`: add `options_sharpe`, `options_info_ratio`, `options_max_drawdown`, `options_calmar`
- `_build_metrics_response`: wire them from `metrics` dict.

**Frontend additions:**
- Replace the two `na` cells in the `o/w short strangles` row with the four new metrics.
- Replace the `na` cell in the `o/w ${market}` row with IR.

---

## 4. History & Save buttons

### 4a. History button
**Status: Already functional.**
- `TopBar.js` line 49–54: fetches `/runs?limit=50`, stores in `runHistory`, opens overlay.
- `RunHistory.js` renders a scrollable table with LOAD / DEL actions.

**Possible UX improvement (optional):** The user may have clicked it and seen “No runs yet” because the backend `/runs` endpoint requires a SQLite table that only exists when the API has been started with the database module. If the API is running in-memory or the DB is missing, the list is empty. This is expected behavior, not a bug. No code change needed unless we want to add a more explicit empty-state message.

### 4b. Save button
**Status: No-op.**
- `TopBar.js` line 27 renders `btn-save` but there is no click handler for it.

**Proposed implementation:**
Make **Save** label the most recent completed run. The backend already supports `PATCH /runs/{run_id}/label`.

**Frontend changes:**
1. `store.js`: add `lastRunId: null` to state; set it when `setResults` is called (`store.lastRunId = raw.run_id`).
2. `TopBar.js` `initTopBar`: add `e.target.id === 'btn-save'` handler:
   - If `store.status === 'completed'` and `store.lastRunId`, prompt the user for a label (e.g. `window.prompt('Label this run:')`).
   - Call `labelRun(store.lastRunId, label)`.
   - Show a transient banner confirming the save.
   - If no completed run yet, show an alert or banner: “Run a backtest first.”
3. If we want to avoid `window.prompt`, render a small inline input inside the topbar, but a prompt is acceptable for a dev tool.

**Difficulty:** Low — ~15 lines of frontend code, zero backend changes.

---

## 5. Exit-breakdown table still shows “21DTE” when `manage_at_dte` is changed

**Root cause:** The exit type is hardcoded to the string `"21DTE"` in two places:
1. `src/straddle/strategy.py` line 833: `exit_type="21DTE"`
2. `src/straddle/metrics.py` line 240: `exit_types = [..., "21DTE", ...]`

**Fix:** Make the label dynamic based on `params["manage_at_dte"]`.

**Backend changes:**
1. In `strategy.py` `_manage_at_dte`:
   ```python
   exit_type = f"{manage_at_dte}DTE"
   ```
   (or keep the internal key as `"21DTE"` for backwards compatibility and only change the display label — but that still leaks the hardcoded number into the JSON response).
2. In `metrics.py` `_compute_exit_stats`:
   - Derive the exit-type list from the actual trade data instead of a hardcoded array (the frontend adapter already does this as a fallback, but the server-side path is preferred and currently hardcoded).
   - Alternatively, keep the hardcoded list but rename the constant to `"MGMT_DTE"` and let the frontend translate it to `"{manage_at_dte}DTE"`.

**Recommended approach (cleanest, minimal blast radius):**
- **Backend:** change `exit_type="21DTE"` to `exit_type="DTE_MGMT"` in `strategy.py`. In `metrics.py`, derive `exit_types` dynamically from the unique `exit_type` values present in the trade list (already what the client-side fallback `computeExitStats` does). This automatically handles any DTE value.
- **Frontend:** in `TableGrid.js`, when rendering the exit type name, translate `"DTE_MGMT"` → `"{params.manage_at_dte}DTE"`. Add a simple map:
  ```js
  const exitTypeLabel = {
    DTE_MGMT: `${params.manage_at_dte}DTE`,
    PROFIT: 'PROFIT', ROLLED: 'ROLLED', STOP: 'STOP',
    EXPIRY: 'EXPIRY', FORCE_CLOSE: 'FORCE_CLOSE',
  };
  ```
  Use `exitTypeLabel[d.type] || d.type` in the table cell.

**Why not change the raw trade data:** The trade log overlay shows `exit_type` directly in `TradeLog.js`. Changing raw trade data would make the log show `30DTE` for some trades and `21DTE` for others if the user re-ran with different params — which is actually desirable. If we prefer consistency, we can still use the raw numeric label in trades and the frontend map in tables.

**Even simpler alternative (pure frontend, zero backend):**
- Leave backend as-is (trades still carry `"21DTE"`).
- In `TableGrid.js`, map `"21DTE"` → `"{params.manage_at_dte}DTE"` only for display.
- This is a 3-line change and solves the visual issue immediately. However, it is technically a lie if the backend ever introduces a true `"30DTE"` exit type. Given the current architecture, this is the pragmatic fix.

**Decision:** Implement the **pure-frontend 3-line fix** first. Document that a backend refactor to `"DTE_MGMT"` is the cleaner long-term solution.

---

## 6. Trade-log chart (PnLStrip) — visual improvements

**Current issues observed:**
- Bars are extremely narrow when many trades exist (portfolio laddering mode).
- X-axis alignment with the equity chart above is approximate (relies on `getPlotViewportRect` which can drift on resize or when uPlot paddings change).
- Year labels at bottom are small and sparse.
- The strip looks like a sparse collection of hairlines rather than a readable histogram.

**Constraint:** The trade log overlay (click-to-open table) must remain untouched.

### Proposed redesign

**Option A — Daily aggregated P&L histogram (recommended):**
Instead of drawing one bar per trade, group trades by exit date (or calendar week) and draw a single bar whose height = net P&L of that bucket. This solves the narrow-bar problem entirely, aligns naturally with the equity chart’s daily x-axis, and gives a much cleaner visual.

- **X-axis:** Use the exact same `ts` array as the equity chart (`Object.keys(results.equity_curve).map(tsFromDate)`). This guarantees pixel-perfect alignment.
- **Data:** Build a `dailyNetPnl` array aligned to `ts`. For each date, sum `t.pnl` of all trades that exited on that date. Unchanged dates = 0.
- **Bars:** Draw one rect per day (or per week if >500 trades). Width = `plotW / nDays`. Color = green if net P&L >= 0, red if < 0. Use a faint opacity so overlapping trades in laddering mode naturally blend.
- **Baseline:** Draw a strong zero line.
- **Year separators:** Re-use the same year-loop logic as `ChartArea.js` (`drawYearSeps`).
- **Tooltip:** Keep existing per-trade tooltip, but find the trade(s) closest to the mouse X position. If multiple trades share the same exit date, show the top 3 by |P&L| and a “+N more” hint.

**Option B — Duration-based bars:**
Each bar spans from entry date to exit date (width = trade duration). This conveys holding period but causes massive overlap in laddering mode and makes the chart unreadable. **Not recommended.**

**Option C — Uniform width with minimum visibility:**
Keep the current design but increase `bw` minimum to `4 px`, add a small gap between bars, and reduce opacity so overlapping trades create a heatmap effect. Simpler but still suffers from alignment issues.

**Decision:** Implement **Option A (daily aggregated histogram)**. It directly addresses all complaints (narrow bars, alignment, readability) and is a well-known pattern in backtest UIs.

**Files to change:**
- `apps/terminal-ui/src/components/pnl/PnLStrip.js` — rewrite `drawPnL` to use daily aggregation and shared x-axis scale.
- `apps/terminal-ui/src/components/charts/ChartArea.js` — optionally export `getEquityDatesTs()` helper so PnLStrip can import the exact same date array instead of recomputing it.

**Detailed steps:**
1. In `drawPnL`, get `ts` and `dates` from `results.equity_curve` (same source as equity chart).
2. Build `dailyNetPnl` aligned to `dates`: initialize with 0, then iterate trades and add `t.pnl` to the index matching `t.exit_date`.
3. Compute `maxAbs = Math.max(...dailyNetPnl.map(Math.abs), 1)`.
4. Draw bars: for each day with non-zero P&L, compute `x = toX(ts[i])`, `bw = plotW / dates.length` (or bucket by week if too many points), `bh = (pnl / maxAbs) * halfH`.
5. For tooltip hit-testing, instead of `_rects` per trade, build a date-index map of trades: `tradesByDate[exit_date] = [trade, ...]`. On mousemove, find the date bucket under the cursor and show the aggregated tooltip.
6. Remove the current `getPlotViewportRect` dependency — instead, compute `LEFT` and `RIGHT` by matching the uPlot x-axis padding directly. uPlot exposes `u.bbox` in device pixels; we already use this in `getPlotViewportRect`. We can keep that helper but make it more robust by reading uPlot scales after draw.

---

## 7. Synthetic pricing — market-calibrated defaults for B3

**Problem:** When the user switches `pricing` to `SYNTHETIC` and `market` to `BOVA11` or `PETR4`, the `put_slope` and `call_slope` values remain at the SPY defaults (`0.30` / `0.10`) stored in the frontend `defaultParams`. The backend `apply_market_preset` corrects them at run time, but the sidebar shows stale numbers, which is confusing.

**Backend calibrated values (from `params.py` MARKET_PRESETS):**
- BOVA11: `put_slope = 0.746`, `call_slope = 0.074`
- PETR4:  `put_slope = 0.522`, `call_slope = -0.046`

**Proposed fix:** In the frontend, when `market` changes, if `mode === 'synthetic'`, automatically update `put_slope` and `call_slope` to the market-appropriate defaults.

**Files:** `apps/terminal-ui/src/store.js` and/or `apps/terminal-ui/src/components/sidebar/Sidebar.js`

**Implementation:**
1. Add a `MARKET_SYNTHETIC_DEFAULTS` map in `store.js` (or a new `constants.js`):
   ```js
   const MARKET_SYNTHETIC_DEFAULTS = {
     spy:    { put_slope: 0.30,  call_slope: 0.10 },
     bova11: { put_slope: 0.746, call_slope: 0.074 },
     petr4:  { put_slope: 0.522, call_slope: -0.046 },
   };
   ```
2. In `updateParams`, detect when `market` is changing:
   ```js
   export function updateParams(newParams) {
     const current = store.params;
     const next = { ...current, ...newParams };
     if (newParams.market && newParams.market !== current.market && next.mode === 'synthetic') {
       const defs = MARKET_SYNTHETIC_DEFAULTS[next.market];
       if (defs) {
         next.put_slope = defs.put_slope;
         next.call_slope = defs.call_slope;
       }
     }
     store.params = next;
   }
   ```
3. Also handle the inverse: when `mode` changes to `synthetic` and `market` is already `bova11`/`petr4`, apply the defaults at that moment too (same logic, just check `newParams.mode`).

**Edge case:** What if the user intentionally customized `put_slope` for BOVA11 and then switches to PETR4 and back? The auto-update will overwrite their custom value. This is acceptable because:
- The calibrated values are the scientifically derived defaults.
- The user can still edit them afterwards.
- We can add a small annotation in the tooltip: “Auto-set to market-calibrated default.”

**Alternative (no code change):** Document in the tooltip that synthetic slopes are SPY defaults and the backend will override them. This is a poorer UX.

---

## 8. Execution mode when in synthetic mode — should it be changeable?

**Analysis:**
- `SyntheticEngine` (`src/straddle/engines.py` lines 232–350) does **not** read `execution_mode`.
- It uses hardcoded `open_fill_adj = -0.05` and `close_fill_adj = +0.05`, which is effectively a fixed “mid minus 5 %” synthetic slippage model.
- `MarketEngine` is the only engine that respects `execution_mode` (`bid_ask`, `mid`, `mid_plus_1tick`).

**Conclusion:** It does **not** make sense to allow changing `execution_mode` in synthetic mode because it has zero effect.

**Proposed fix:** Hide the `execution_mode` row in the sidebar when `mode === 'synthetic'`.

**Implementation:**
- In `parameter-sections.js`, add `showWhen: { key: 'mode', value: 'market' }` to the `execution_mode` parameter definition.
- The existing `matchesCondition` logic in `Sidebar.js` already supports this — no extra code needed.

**Additional consideration:** If we ever extend `SyntheticEngine` to support synthetic execution modes (e.g. “mid”, “mid ± tick”), we can remove the `showWhen` restriction. For now, hiding it eliminates confusion.

---

## Summary of files to touch

| # | Issue | Files |
|---|---|---|
| 1 | Font sizes | `apps/terminal-ui/src/styles/components.css` |
| 2 | IR for B&H | `src/straddle/metrics.py`, `src/straddle/api.py`, `apps/terminal-ui/src/components/perf/PerformanceBar.js` |
| 3 | Per-component metrics | `src/straddle/metrics.py`, `src/straddle/api.py`, `apps/terminal-ui/src/components/perf/PerformanceBar.js` |
| 4b | Save button | `apps/terminal-ui/src/store.js`, `apps/terminal-ui/src/components/topbar/TopBar.js` |
| 5 | DTE label | `apps/terminal-ui/src/components/tables/TableGrid.js` (frontend-only fix) |
| 6 | PnLStrip redesign | `apps/terminal-ui/src/components/pnl/PnLStrip.js`, `apps/terminal-ui/src/components/charts/ChartArea.js` |
| 7 | Synthetic defaults | `apps/terminal-ui/src/store.js` (or new constants file) |
| 8 | Hide execution_mode | `apps/terminal-ui/src/components/sidebar/parameter-sections.js` |

---

## Recommended implementation order

1. **Quick wins (session 1):**
   - #1 Font sizes (pure CSS)
   - #5 DTE label (3-line frontend)
   - #8 Hide execution_mode in synthetic (1-line schema)
   - #7 Synthetic market defaults (small store.js change)
   - #4b Save button (small TopBar.js change)

2. **Backend-frontend pair (session 2):**
   - #2 IR for B&H (backend metric + frontend cell)
   - #3 Per-component metrics (backend metric additions + frontend table expansion)

3. **Larger redesign (session 3):**
   - #6 PnLStrip daily-aggregation redesign

This ordering lets us ship visible improvements early while isolating the riskier chart refactor to its own session.
