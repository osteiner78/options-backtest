# Frontend Plan: Straddle Terminal UI

## Context

The user wants a custom frontend for the SPY short-strangle backtest engine, replacing the existing Streamlit UI (`apps/streamlit-ui/app.py`). The target design is in `Wireframe Terminal v3.html` — a single-file, self-contained dashboard in a Gruvbox-dark CRT-terminal aesthetic with hand-coded SVG charts, no framework, no chart library.

A Vite + vanilla-JS scaffold has been initialized at `apps/terminal-ui/` and the user has already begun laying down a component architecture (store, api client, 7 components, split stylesheets). The task is (a) to assess whether to keep or restart that scaffold, (b) break the wireframe into a clean component tree, (c) propose a folder layout, and (d) flag where the current FastAPI backend will block or constrain the design.

**Plan mode**: no code changes yet — just a detailed roadmap.

---

## 1. Current `apps/terminal-ui/` — Keep and Evolve

The existing scaffold is **not boilerplate**. It contains ~1,000 LOC of intentional, well-structured vanilla JS:

- **`src/main.js`** — composes full page tree, wires `subscribe()` → re-render (`main.js:49–51`).
- **`src/store.js`** — Proxy-based reactive store with `localStorage` persistence for `params` (`store.js:51–60`). Defaults already match the backend's `BacktestRequest` contract.
- **`src/api.js`** — `triggerBacktest` / `fetchResults` / `pollResults` with 2s polling loop (`api.js:28–47`).
- **`src/components/`** — 7 render/init-paired modules mirroring the wireframe regions (TopBar, Sidebar, PerformanceBar, ChartArea, TableGrid, PnLStrip, TradeLog).
- **`src/styles/`** — split into `theme.css`, `typography.css`, `layout.css` (333 LOC total).
- **`src/utils/chartHelpers.js`** — helper extraction already underway.

**Recommendation: keep.** Restarting would discard a sound architecture. The project name `terminal-ui` in `package.json:2` is fine — neutral and matches the `apps/` namespace. No rename needed (the `index.html` `<title>` is already "Straddle Terminal").

**Gaps to close before serious feature work** (deferred; do after structure lands):
- Add `vite.config.js` with `server.proxy` for `/backtest` → `http://127.0.0.1:8000` (removes the hardcoded `BASE_URL` in `api.js:5`).
- Use `import.meta.env.VITE_API_BASE_URL` so prod builds aren't pinned to localhost.
- Optional: ESLint + Prettier configs; not urgent for a single-author project.

---

## 2. Component Decomposition of `Wireframe Terminal v3.html`

The wireframe is a flex-column of **TopBar (36px)** + **Body (sidebar 188px | main grid)**. The main grid has 5 rows: perf bar → chart tabs → chart area → analytics tables → P&L strip. Two overlays float above: **TradeLogOverlay** (bottom drawer, 0–280px) and **TweaksPanel** (bottom-right, collapsible).

Proposed component tree (maps 1:1 onto existing `src/components/` where possible):

```
App (main.js)
├── TopBar                          [exists]
│   ├── BrandMark
│   ├── ConfigPill                  — summary of current params
│   ├── RunMetaBadge                — last-run timestamp + trade count
│   └── ActionButtons               — THEME / SAVE / ▶ RUN
├── Sidebar                         [exists — expand]
│   └── ParameterSection × 7        — BACKTEST, STRATEGY, PORTFOLIO,
│       ├── SectionHeader             ROLL MGMT, VIX FILTER,
│       └── ParameterRow × N          DEFENSIVE, PRICING
│           └── EditableValue       — inline <input> on click
├── MainContent
│   ├── PerformanceBar              [exists] — hierarchical table
│   │   (Portfolio row → strangles / SPY-cash / risk-free sub-rows;
│   │    SPY B&H row. Columns: TR, CAGR, Sharpe, MDD, Calmar,
│   │    Win%, AvgP&L, Final, AvgBPR, #Trades)
│   ├── ChartTabs + ChartLegend     [exists in ChartArea]
│   ├── ChartArea                   [exists — split into 4]
│   │   ├── EquityChart             — dual line + drawdown pane
│   │   ├── BPRChart                — util% area + 30% cap line
│   │   ├── PositionsChart          — step polyline
│   │   └── VIXChart                — line + entry/skip markers
│   ├── TableGrid                   [exists — split into 2]
│   │   ├── ExitBreakdownTable      — count/%, win%, avgP&L, totP&L
│   │   └── VIXRegimeTable          — regime bucket counts + P&L
│   └── PnLStrip                    [exists] — per-trade bar chart
├── TradeLogOverlay                 [exists]
│   ├── FilterBar                   — ALL/PROFIT/ROLLED/21DTE/STOP
│   └── TradeTable                  — sticky header, 13 columns
└── TweaksPanel                     [to add]
```

**Shared primitives to extract into `src/components/primitives/`:**
- `Button` (`.btn`, `.btn-primary`)
- `CollapsibleSection` (used 7× in Sidebar + TweaksPanel + TradeLog drawer)
- `DataTable` (generic — drives ExitBreakdown, VIXRegime, TradeLog)
- `SvgChart` base (viewBox, gridlines, gradient `<defs>` boilerplate — consumed by all 4 charts + PnLStrip)
- `EditableValue` (click-to-edit, Esc-cancel, blur-save — reused across every `ParameterRow`)

**Chart rendering**: use **[uPlot](https://github.com/leeoniya/uPlot)** (~45KB, canvas-based, MIT) for the 4 main time-series charts. The user wants gridlines, crosshair, tooltips, and optional zoom — uPlot gives all of these out of the box, whereas hand-coding them across 4 charts in raw SVG is significant surface area (and zoom-on-drag in particular is genuinely fiddly). uPlot themes cleanly to Gruvbox via CSS vars; IBM Plex Mono and the colour palette transfer unchanged, so wireframe fidelity stays ~95%. The only visible difference is canvas vs. SVG paths, which is imperceptible at the intended density.

The **P&L strip** stays hand-coded SVG — it's a simple vertical-bar distribution with per-bar click-to-focus-trade, not a time-series with axes, and doesn't benefit from uPlot's model.

Rejected alternatives: Chart.js/ECharts/Plotly are all ≥2× the bundle size and harder to style into the terminal aesthetic.

**State shape** (extend `store.js`'s `initialState`):
```js
{
  params,           // user inputs — already persisted
  results,          // { metrics, trades[], equity_curve, spy_curve,
                    //   bpr_curve?, pos_count_curve?, vix_curve,
                    //   vix_blocked_dates? }
  status,           // 'idle' | 'pending' | 'running' | 'completed' | 'failed'
  lastRun,
  activeChartTab,   // 'equity' | 'bpr' | 'positions' | 'vix'
  tradeLogOpen,
  tradeLogFilter,   // 'all' | 'profit' | 'rolled' | '21dte' | 'stop' — to add
  tweaksOpen,       // to add
  error,            // to add — surface failed runs
}
```

**Re-render strategy**: the current `subscribe(() => render())` does a full-tree rebuild via `innerHTML`. That's fine for v1 given the small DOM. It will start to flicker when the user is mid-edit in an `EditableValue` — at that point, scope re-renders to the changed region (pass a selector to `subscribe`, or adopt a 50-line diff helper).

---

## 3. Proposed Folder Layout

### Inside `apps/terminal-ui/`

```
apps/terminal-ui/
├── index.html
├── package.json
├── vite.config.js              [new — api proxy, env vars]
├── public/
│   ├── favicon.svg
│   └── icons.svg
└── src/
    ├── main.js                 — entry, composes regions
    ├── store.js                — reactive state
    ├── api/
    │   ├── client.js           — (was api.js) fetch wrappers
    │   └── adapters.js         [new] — normalize backend response
    │                             into shape the components expect
    │                             (derive VIX-regime buckets,
    │                              exit-breakdown stats, etc.)
    ├── components/
    │   ├── primitives/         [new]
    │   │   ├── Button.js
    │   │   ├── CollapsibleSection.js
    │   │   ├── DataTable.js
    │   │   ├── EditableValue.js
    │   │   └── SvgChart.js
    │   ├── topbar/
    │   │   └── TopBar.js
    │   ├── sidebar/
    │   │   ├── Sidebar.js
    │   │   └── parameter-sections.js    — declarative schema
    │   │                                  (label, key, type, range)
    │   ├── perf/
    │   │   └── PerformanceBar.js
    │   ├── charts/
    │   │   ├── ChartArea.js    — tab host + legend
    │   │   ├── EquityChart.js
    │   │   ├── BPRChart.js
    │   │   ├── PositionsChart.js
    │   │   └── VIXChart.js
    │   ├── tables/
    │   │   ├── TableGrid.js
    │   │   ├── ExitBreakdownTable.js
    │   │   └── VIXRegimeTable.js
    │   ├── pnl/
    │   │   └── PnLStrip.js
    │   ├── tradelog/
    │   │   ├── TradeLog.js
    │   │   ├── FilterBar.js
    │   │   └── TradeTable.js
    │   └── tweaks/
    │       └── TweaksPanel.js
    ├── styles/
    │   ├── theme.css           — CSS vars (Gruvbox + future Tokyo)
    │   ├── typography.css
    │   ├── layout.css          — grid/flex scaffolding
    │   └── components.css      [new] — per-component class rules,
    │                             currently bleeding into layout.css
    ├── utils/
    │   ├── chartHelpers.js
    │   ├── format.js           [new] — $, %, date formatters
    │   └── derive.js           [new] — client-side stats
    │                             (VIX-regime grouping, per-exit P&L)
    └── assets/
        └── hero.png
```

Motivation:
- **Group components by region**, not by atomic type — makes it obvious where to add a new sidebar subsection vs. a new chart.
- **`api/adapters.js`** is the key new seam: the backend's response shape doesn't match every wireframe widget (see §5), so one place must own the fan-out. Components consume a normalized view, never raw API JSON.
- **`parameter-sections.js`** turns the Sidebar from handwritten HTML into a schema-driven render — adding/removing a parameter becomes a one-line edit, and the same schema can later validate edits.

### At the project root

The repo already follows a sensible `apps/` pattern:

```
options-backtest/
├── apps/
│   ├── streamlit-ui/           [existing legacy UI — keep for now]
│   └── terminal-ui/            [this plan]
├── src/straddle/               — backend package
├── scripts/                    — CLI entry points
├── tests/
├── data/                       — SQLite + Parquet
└── docs/                       — CLAUDE.md, README.md, etc.
```

**One suggestion**: move `Wireframe Terminal v3.html` into `apps/terminal-ui/docs/wireframe.html` (or `design/`) so the design reference lives next to the code that implements it. Leaving it at the repo root is fine for now; flag it as a cleanup when the UI stabilises.

No other reorg needed — `src/straddle/`, `scripts/`, `tests/`, and `data/` are already clean.

---

## 4. Design Commentary & Architectural Blind Spots

### Strengths of the wireframe

- **Information density** fits the user (a quant running parameter sweeps). All critical outputs visible without navigation.
- **Single-file reference** trivial to diff against the implementation.
- **CSS variables** make theming (Gruvbox → Tokyo Night → user themes) a 20-line change.
- **No chart library** keeps the bundle tiny and the aesthetic exact — at the cost of hover/tooltip interactivity.

### Blind spots in the *design*

1. **No loading / progress state for long runs.** A 2021–2025 market-mode backtest can take 30–60s. The wireframe has no spinner, progress bar, or streaming trade count. The RUN button must at minimum show `running` state, a cancel affordance, and ideally a rolling trade count.

2. **No error surface.** `BacktestResponse.status === "failed"` returns an error string; the wireframe has nowhere to display it. Needs a dismissible banner in the TopBar or overlaid toast.

3. **No iron-condor representation.** The backend supports `strategy_mode: "iron_condor"` (4-leg), but the Sidebar only shows short-strangle params (target Δ, not wing Δ). Trade log columns (`Put K`, `Call K`) don't accommodate long-leg wings.

4. **No run history / comparison.** The wireframe assumes one live run. There's no way to flip between last week's run and today's — a basic need given the parameter-sweep workflow.

5. **Portfolio-vs-single-position mode asymmetry.** BPR UTIL and POSITIONS chart tabs are only meaningful in portfolio mode; the wireframe doesn't disable or hide them in single-position mode, which will produce empty or misleading plots.

6. **`innerHTML` re-render** on every param edit will blow away focus from any open `<input>` mid-keystroke. Tolerable only if edits commit on blur (as the wireframe's `editParam` already does) — worth confirming early, not late.

7. **No keyboard affordances.** A dense terminal UI invites shortcuts (`R` to run, `/` to focus param search, `Esc` to close overlays). Absent from the wireframe; easy to layer in.

8. **Accessibility is minimal.** Click-to-edit spans aren't focusable, tables lack captions, colour is the sole channel for P&L sign. For a personal tool this is acceptable; flag it if the UI ever goes multi-user.

---

## 5. Backend API Suitability — What Works, What's Missing

The FastAPI in `src/straddle/api.py` supports the happy path but has **several gaps the wireframe will expose**.

### What the API covers cleanly
- POST `/backtest` + GET `/backtest/{id}` matches the existing client polling loop.
- Metrics payload has every field the PerformanceBar needs: `total_return`, `annualized_return`, `sharpe`, `max_drawdown`, `calmar`, `win_rate`, `avg_pnl`, `final_balance`, plus SPY comparators and attribution (`ret_options`, `ret_cash_spy`, `ret_cash_rf`).
- Equity curves for all 4 chart tabs (`equity_curve`, `bpr_curve`, `pos_count_curve`, `vix_curve`) — including `vix_blocked_dates` to plot skip markers on the VIX chart.
- CORS is wide-open (`allow_origins=["*"]`) — Vite dev server (5173) works out of the box.
- `exit_breakdown` dict provides per-type counts (PROFIT, STOP, 21DTE, EXPIRY, ROLLED, FORCE_CLOSE).

### Gaps — blocking for full wireframe parity

| # | Missing | Impact on UI |
|---|---------|--------------|
| G1 | **No progress/streaming** (no SSE, no percentage) | RUN button can only show binary running/done; no ETA |
| G2 | **Results in-memory only** (`_results` dict wiped on restart) | No run history, no post-restart resume; TopBar's "last run" is meaningless across sessions |
| G3 | **No `/config` endpoint** exposing PARAMS defaults, ranges, enums | Frontend duplicates defaults in `store.js:7–25`; drift is inevitable |
| G4 | **TradeSummary is lean** — missing `leg_rolls`, iron-condor wing strikes, `roll_count`, `parent_trade_num`, `stop_regime`, `used_market_data` | TradeLog can't show roll lineage or IC wings; no way to distinguish synthetic-fallback fills |
| G5 | **Per-exit P&L stats not computed** — backend returns only counts, not Avg P&L / Total P&L / Win% per exit type | ExitBreakdownTable must derive these client-side from `trades[]` |
| G6 | **VIX-regime breakdown not computed** | VIXRegimeTable must bucket `trades[].entry_vix` client-side against hardcoded thresholds |
| G7 | **~40% of PARAMS unreachable** — `commission_per_leg`, `open_fill_adj`, `close_fill_adj`, `wing_delta`, `overshoot_*`, `vix_to_iv_multiplier`, `spy_allocation_pct` | Sidebar can't configure slippage, IC wings, or overshoot model — users must edit `params.py` directly |
| G8 | **No `/health` or `/capabilities`** | Frontend can't detect API down, nor advertise allowed DB date ranges (market mode fails silently outside DB coverage) |
| G9 | **No validation schema** — errors come back as free-text strings in `BacktestResponse.error` | Sidebar can't show per-field validation; user gets a generic banner |
| G10 | **Portfolio-mode curves (`bpr_curve`, `pos_count_curve`) are optional** in response but the frontend has no signal other than `undefined` | ChartArea should disable BPR/Positions tabs when absent |

### Recommended backend work, sequenced

**Phase A — unblocks core frontend (required before wire-up):**
1. Add `GET /config` returning defaults, per-field enums/ranges, and a capabilities object (`supports_iron_condor`, `market_data_min_date`, `market_data_max_date`).
2. Extend `TradeSummary` with `long_put_strike`, `long_call_strike`, `roll_count`, `parent_trade_num`, `leg_rolls[]`, `used_market_data`.
3. Add server-side `exit_stats` and `vix_regime_stats` blocks to `MetricsResponse` (computed once in `metrics.py`) so the client isn't recomputing on every re-render.
4. Return 422 with field-level Pydantic errors on bad params, not 200 + error string.

**Phase B — quality of life (post-MVP):**
5. SSE endpoint `GET /backtest/{id}/stream` emitting `{pct, trades_so_far, current_date}` events — replaces polling for progress UI.
6. Persist runs to SQLite (`data/runs.db`): `GET /runs`, `GET /runs/{id}`, `DELETE /runs/{id}`. Enables run history + comparison.
7. `POST /compare` taking a list of `run_id`s, returning aligned metrics for side-by-side rendering.

**Phase C — not-blocking, nice-to-have:**
8. Expose the remaining PARAMS (fees, overshoot model, wing Δ) as optional request fields.
9. Add CSV/JSON export endpoints for trades and equity curves.

The frontend can ship an MVP against the current API by computing stats client-side (G5, G6) and hiding unimplemented controls (G7). G1–G4 are the shortest path to making the wireframe truly faithful.

---

## 6. Phased Execution Plan

Once this plan is approved, execution should proceed in ordered phases so each step is independently verifiable:

**Phase 1 — Structural cleanup (frontend only, no backend changes)**
- Add `vite.config.js` with `VITE_API_BASE_URL` + dev proxy.
- Reorganise `src/components/` into the grouped layout above.
- Extract `primitives/` (Button, CollapsibleSection, DataTable, EditableValue, SvgChart).
- Introduce `api/adapters.js` and route all component reads through it.
- Introduce `parameter-sections.js` schema; rewrite Sidebar to render from it.
- Split `layout.css` → `layout.css` + `components.css`.

**Phase 2 — Wireframe fidelity pass**
- Port each of the 4 SVG charts from the wireframe into its own component.
- Port PerformanceBar hierarchical layout, ExitBreakdown + VIXRegime tables (deriving stats client-side until G5/G6 land).
- Port PnLStrip bar chart + TradeLog overlay + filters.
- Add TweaksPanel.
- Add error banner + running-state visuals.

**Phase 3 — Backend extensions (Phase A items from §5)**
- `GET /config`; richer `TradeSummary`; server-side `exit_stats`/`vix_regime_stats`; structured validation errors.
- Frontend swaps client-side derivations for server values; schema-driven validation in Sidebar.

**Phase 4 — Streaming + history (Phase B items)**
- SSE progress; persisted runs; comparison endpoint; run-switcher UI in TopBar.

---

## 7. Critical Files (for reference during execution)

**Frontend (keep & extend):**
- `apps/terminal-ui/package.json`
- `apps/terminal-ui/src/main.js`
- `apps/terminal-ui/src/store.js`
- `apps/terminal-ui/src/api.js` → move to `apps/terminal-ui/src/api/client.js`
- `apps/terminal-ui/src/components/*.js` (all 7)
- `apps/terminal-ui/src/styles/layout.css` (to split)

**Backend (touch points for Phase A):**
- `src/straddle/api.py` — add `/config`, enrich `TradeSummary`, add stats blocks, structured errors
- `src/straddle/params.py` — source for `/config` payload
- `src/straddle/metrics.py` — implement `exit_stats`, `vix_regime_stats`
- `src/straddle/strategy.py` — expose `leg_rolls`, wing strikes on `Trade`

**Design reference:**
- `Wireframe Terminal v3.html` (consider moving to `apps/terminal-ui/design/wireframe.html`)

---

## 8. Verification

After each phase:

**Phase 1:**
- `npm run dev` in `apps/terminal-ui/` — app loads, no console errors, all regions render.
- Edit a sidebar param → reloads persist via `localStorage`.
- `api/client.js` hits `/backtest` through the Vite proxy (check Network tab).

**Phase 2:**
- Visual diff against `Wireframe Terminal v3.html` open side-by-side — colors, spacing, SVG shapes match.
- Run a backtest (`python scripts/run_api.py` + click RUN) → metrics, trades, and all 4 charts populate.
- Toggle chart tabs; expand TradeLog; filter by exit type; expand TweaksPanel.

**Phase 3:**
- `curl http://127.0.0.1:8000/config` returns defaults + ranges; Sidebar loads from it.
- Submit invalid params → 422 surfaces per-field errors in the Sidebar.
- TradeLog shows wing strikes in iron-condor mode; roll-count badge in rolled trades.

**Phase 4:**
- Start a long backtest; Network tab shows SSE stream; progress UI ticks.
- Kill + restart the API; previous run still listed in `/runs` and loadable.

---

## Decisions Locked

- **Charts: uPlot for the 4 time-series panels, hand-coded SVG for the P&L strip.** User confirmed wireframe fidelity is a guide, not a constraint, and wants gridlines + crosshair + tooltips + optional zoom.
- **Iron-condor UX: deferred to Phase 3.** Phase 2 targets short-strangle parity only. Sidebar gains `wing_delta` and TradeLog gains long-leg columns once the backend adds `long_put_strike`/`long_call_strike` to `TradeSummary` (Phase A, item 2).

## Open Questions (non-blocking — can be answered later)

1. **Streamlit UI fate** — keep `apps/streamlit-ui/` indefinitely as a fallback, or remove once `terminal-ui` reaches parity?
2. **Persistence scope** — for the Phase 4 run history, is SQLite-on-disk enough, or do you want runs exportable/shareable (JSON export, git-tracked)?
