# Terminal UI — Pending TODOs

## Medium priority

### Iron Condor sidebar params
The backend and TradeLog both support iron condor (`strategy_mode: 'iron_condor'`), and
TradeLog shows long-leg columns (LP/LC) when IC trades are present. But the sidebar has no
field for `wing_delta`, so users cannot configure the IC wings from the UI.

**What to add to `parameter-sections.js`:**
```js
{ key: 'wing_delta', label: 'wing Δ', format: v => Number(v).toFixed(2) }
```
(Only meaningful when `strategy_mode === 'iron_condor'` — consider showing it conditionally.)

### Side-by-side run comparison UI
The backend exposes `POST /compare {run_ids: [...]}` which returns a dict of
`run_id → metrics`. The RunHistory overlay only supports LOAD (replacing the current view).
A proper compare view would show two or more metric rows side-by-side in the PerformanceBar,
with diffs highlighted.

---

## Low priority / Phase C

### Expose remaining strategy params in sidebar
The following knobs exist in `params.py` but are not reachable from the UI:
- `commission_per_leg` (default $1.00/leg)
- `open_fill_adj` / `close_fill_adj` — bid/ask fill adjustment
- `overshoot_*` — gap-open overshoot model
- `spy_allocation_pct` — blend mode split
- `vix_to_iv_multiplier` — synthetic pricing scale

### CSV / JSON export endpoints
Add `GET /backtest/{id}/trades.csv` and `GET /backtest/{id}/equity.json` so results
can be exported for external analysis without screen-scraping.

---

## Open questions

### Streamlit UI fate
`apps/streamlit-ui/` still exists alongside the new terminal UI. Decide whether to:
- Keep it as a low-maintenance fallback (useful for quick ad-hoc runs without the API server)
- Deprecate and remove once terminal-ui reaches full parity

### Keyboard shortcuts
Dense terminal-style UIs benefit from shortcuts. Candidates:
- `R` → Run backtest
- `T` → open Trade Log
- `H` → open Run History
- `Esc` → close any open overlay
- `← →` → switch chart tabs
