# Code Review — `apps/terminal-ui/`

- **Target:** `apps/terminal-ui/src/` (16 components + 3 utils + 2 api modules)
- **Date:** 2026-05-18
- **Verdict:** Minor issues — 2 real runtime bugs, no critical data-loss bugs reachable at current runtime

---

## Architecture: Why the shallow Proxy isn't a runtime bug

The store uses a shallow `Proxy` (store.js:89-97). If a component mutates `store.params.target_delta` directly, the `set` trap never fires — listeners are not notified, localStorage is not persisted.

**Counterpoint:** No component in the current codebase does this. Every interactive component (`TopBar`, `Sidebar`, `RunHistory`, `TweaksPanel`, `CollapsibleSection`, `EditableValue`) uses event delegation on `document` or `window`. Nothing binds to render-generated DOM nodes. The `ChartArea` component binds to `mountEl.addEventListener(...)` but `drawChart()` re-initializes listeners on every `requestAnimationFrame` cycle. The `main.js` `render()` → `innerHTML` replacement destroys bindings on generated nodes, but none of the components use direct binding.

**Documentation risk:** A future component that uses direct `el.addEventListener()` on a render-generated node would break silently on first store update. Document the convention.

---

## 🔴 Critical

### C1 — SSE `EventSource` leaks connection when `onProgress` callback throws

**File:** `apps/terminal-ui/src/api/client.js:65-101`

```javascript
es.onmessage = async (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    if (onProgress) onProgress(data);   // line 73 — THROWS? → skips es.close()

    if (data.status === 'completed') {  // never reached
        es.close();
        // ...
    }
};
```

**Problem:** If `onProgress` callback throws (e.g., a DOM manipulation error during a store update), execution leaves `onmessage` before the completion/failure branches. The `EventSource` stays open, the Promise never settles, and the caller hangs indefinitely.

**Fix:**

```javascript
es.onmessage = async (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }

    try {
        if (onProgress) onProgress(data);
    } catch (_) {
        // callback errors must not abort the SSE stream
    }

    if (data.status === 'completed') {
        es.close();
        // ...
    }
};
```

**Confidence:** Certain — code path demonstrable by providing a throwing `onProgress`.

**Impact:** Backtest hangs forever if progress rendering fails.

---

### C2 — `EXIT_TYPES` is hardcoded — new server exit types silently disappear from UI

**File:** `apps/terminal-ui/src/utils/derive.js:1,13-28`

```javascript
const EXIT_TYPES = ['PROFIT', 'ROLLED', '21DTE', 'EXPIRY', 'STOP', 'FORCE_CLOSE'];
```

**Problem:** If the backend adds a new exit type (e.g., `'MANUAL_CLOSE'`), the client never discovers it. The function iterates over the fixed list and does not inspect actual trade data. New exit types silently produce zero reported stats.

**Fix:** Derive from incoming data:

```javascript
export function computeExitStats(trades) {
    if (!trades?.length) return [];
    const groups = new Map();
    for (const t of trades) {
        const type = t.exit_type ?? 'UNKNOWN';
        if (!groups.has(type)) groups.set(type, []);
        groups.get(type).push(t);
    }
    const total = trades.length;
    return [...groups.entries()].map(([type, filtered]) => {
        const n = filtered.length;
        const wins = filtered.filter(t => (t.pnl || 0) > 0).length;
        const totalPnl = filtered.reduce((sum, t) => sum + (t.pnl || 0), 0);
        return { type, n, pct: n / total, winRate: n > 0 ? wins / n : 0,
            avgPnl: n > 0 ? totalPnl / n : 0, totalPnl };
    }).filter(d => d.n > 0);
}
```

**Confidence:** Certain — the fixed array is never updated from server data.

**Impact:** Silent data loss in the UI whenever the backend introduces a new exit type. Currently there are no new types, so the bug is dormant.

---

## 🟡 Important

### I1 — `setResults()` triggers 5 sequential full-DOM rebuilds

**File:** `apps/terminal-ui/src/store.js:112-118`, `main.js:59`

```javascript
export function setResults(results) {
  store.results = results;      // → fires render()
  store.status = 'completed';   // → fires render()
  store.error = null;           // → fires render()
  store.progress = null;        // → fires render()
  store.lastRun = new Date();   // → fires render()
}
```

Each assignment hits the Proxy `set` trap, which calls all listeners, which calls `render()`, which replaces `app.innerHTML`. **The entire DOM is destroyed and rebuilt 5 times in a single synchronous call.** Same pattern in `setError()` (2 extra renders).

**Fix:** Add batch support:

```javascript
let batching = false;

export function batch(fn) {
    batching = true;
    fn();
    batching = false;
    listeners.forEach(l => l(store));
}

// In Proxy set trap:
set(target, key, value) {
    target[key] = value;
    if (key === 'params') localStorage.setItem(PARAMS_KEY, JSON.stringify(value));
    if (key === 'theme')  localStorage.setItem(THEME_KEY, value);
    if (!batching) listeners.forEach(l => l(target));
    return true;
}
```

Then:

```javascript
export function setResults(results) {
    batch(() => {
        store.results = results;
        store.status = 'completed';
        store.error = null;
        store.progress = null;
        store.lastRun = new Date();
    });
}
```

**Confidence:** Certain — the synchronous multi-fire is verifiable by inspection.

**Impact:** Visible performance jank on complex dashboards. Chart canvases are torn down and recreated redundantly.

---

### I2 — `setStatus('running')` does not clear previous `error`

**File:** `apps/terminal-ui/src/store.js:108-110`, `TopBar.js:60`

```javascript
export function setStatus(status) {
  store.status = status;
}
```

**Problem:** When a backtest fails, `store.error` holds the failure message. When the user clicks Run again, `setStatus('running')` changes only `status`. `store.error` retains the stale value. `ErrorBanner.js` handles this by checking `status === 'running'` first, but if any new component reads `store.error` directly, it would display the old error during the new run.

**Fix:**

```javascript
export function setStatus(status) {
    store.status = status;
    if (status === 'running') {
        store.error = null;
        store.progress = null;
    }
}
```

**Confidence:** Certain.

---

### I3 — Corrupted localStorage never cleaned

**File:** `apps/terminal-ui/src/store.js:59-61`

```javascript
try {
    const stored = JSON.parse(saved);
    // ...
    return { ...defaultParams, ...stored };
} catch (e) {
    console.error('Failed to parse saved params', e);
}
```

**Problem:** Invalid JSON in localStorage (manual edit, truncated write, browser extension) causes a `console.error` on every page load, forever. The corrupted value is never removed.

**Fix:** Add `localStorage.removeItem(PARAMS_KEY);` in the catch block.

**Confidence:** Certain.

---

### I4 — No timeout on SSE or fallback fetch

**File:** `apps/terminal-ui/src/api/client.js:66-101`

**Problem:** Both the `EventSource` and the fallback `fetchResults` call can hang indefinitely with no `AbortController` or timeout. On a hung TCP connection, the caller blocks forever.

**Fix:** Wrap `fetchResults` with a 30-second timeout using `AbortController`. For EventSource, add a `setTimeout` fallback that calls `es.close()` and rejects after a configurable duration.

**Confidence:** Certain — no timeout mechanism exists in the current code.

---

### I5 — `currencySymbol` hardcoded per-market

**File:** `apps/terminal-ui/src/utils/format.js:23-24`

```javascript
export const currencySymbol = (market) =>
  (market === 'bova11' || market === 'petr4') ? 'R$' : '$';
```

**Problem:** Adding a new market (e.g., Chilean IPSA, Mexican IPC) silently gets `'$'` instead of the correct local symbol.

**Fix:**

```javascript
const MARKET_CURRENCIES = { bova11: 'R$', petr4: 'R$' };
export const currencySymbol = (market) => MARKET_CURRENCIES[market] ?? '$';
```

**Confidence:** Certain.

---

### I6 — `applyConfigDefaults` cannot deliver new backend parameters to users with saved localStorage

**File:** `apps/terminal-ui/src/store.js:172-178`

```javascript
if (localStorage.getItem(PARAMS_KEY)) return; // user has saved params — don't touch
```

**Problem:** If the backend introduces a new parameter and the user has ever customized any param via the sidebar, they will never receive the new default — their saved params lack the new key.

**Fix:** Deep-merge: fill in backend defaults for keys the user hasn't saved, only overwriting missing keys.

**Confidence:** Likely — depends on whether backend tolerates missing optional keys.

---

## 🟢 Suggestions

### S1 — `new Date()` breaks JSON-compatibility of store state

**File:** `apps/terminal-ui/src/store.js:117`

```javascript
store.lastRun = new Date();
```

Every other store property is JSON-compatible. `Date` objects don't serialize cleanly. Store as `Date.now()` or ISO string.

### S2 — Missing JSDoc types on `initialState` and exports

**File:** `apps/terminal-ui/src/store.js:70-85,104-164`

No type documentation on `progress` shape, `runHistory` array element shape, or what each exported setter modifies.

### S3 — Non-standard `Error` properties

**File:** `apps/terminal-ui/src/api/client.js:51-53`

```javascript
const e = new Error(msg);
e.status = response.status;
e.detail = err.detail;
throw e;
```

Custom error properties don't survive `JSON.stringify`. Define a `class ApiError extends Error {}`.

### S4 — `generateMockEquityData` unprotected division

**File:** `apps/terminal-ui/src/utils/chartHelpers.js:20-21`

```javascript
const pScale = 84 / portPnl[N - 1];
const sScale = 72 / spyPnl[N - 1];
```

If cumulative random walk lands at zero or negative, produces `Infinity` or inverted data. Mock data only — low risk.

### S5 — `getVar` couples to browser-only `document`

**File:** `apps/terminal-ui/src/utils/chartHelpers.js:5`

```javascript
export const getVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
```

Prevents unit-testing chart helpers in Node.js. Add `typeof document` guard.

### S6 — `plt.style.use` at module scope in plotting.py (not terminal-ui, but same repo)

Already fixed in Phase 4 code cleanup. Noted for completeness.

---

## Architectural Concerns

1. **Store-based architecture with full DOM replacement.** The `render()` → `innerHTML` pattern is reminiscent of early 2010s jQuery apps. It works because event delegation is used consistently, but it is fragile — a single component that binds directly to a rendered DOM node would break. A vDOM approach (Preact, vanilla diff, or even a `replaceChild` strategy) would eliminate this class of bug permanently.

2. **No request deduplication or cancellation.** Clicking "Run" twice in rapid succession starts two parallel backtests with no AbortController to cancel the first. The SSE connections pile up.

3. **Mock data functions live alongside production code.** `generateMockEquityData`, `generateMockExitData`, `generateMockPositionsData`, and `generateMockVixData` in `chartHelpers.js` are only used when `store.results` is null. They should be in a separate `mockData.js` file or gated behind a dev-only import.

---

## Top 3 Things to Fix First

1. **C1 — SSE EventSource leak** (`client.js:73`). Wrap `onProgress(data)` in try/catch. One-line fix that prevents an unrecoverable hang.

2. **C2 — Hardcoded `EXIT_TYPES`** (`derive.js:1`). Derive exit types from actual trade data instead of a fixed array. ~20-line refactor that future-proofs against server changes.

3. **I1 — Batch store writes** (`store.js:112-118`). Add a `batch()` helper so `setResults` triggers one render instead of five. ~15 lines. Visible UX improvement on complex dashboards.

---

## Untested Areas

- **SSE reconnection** — what happens when the server closes the stream mid-transfer? No `onerror` handler on the EventSource.
- **Concurrent backtest submissions** — double-clicking Run starts two SSE streams with no cancellation.
- **Malformed server responses** — `normalizeResults` in `adapters.js` assumes specific JSON shapes. Missing fields cause `undefined` propagation.
- **`/config` endpoint failure** — `catch` path in `main.js:66` only logs to console. No user-visible notification.

---

## Files Reviewed

- `apps/terminal-ui/src/main.js` — Entry point, render loop, init
- `apps/terminal-ui/src/store.js` — Proxy state management
- `apps/terminal-ui/src/api/client.js` — API client, SSE streaming
- `apps/terminal-ui/src/api/adapters.js` — Response normalization
- `apps/terminal-ui/src/utils/derive.js` — Exit stats, VIX regime stats
- `apps/terminal-ui/src/utils/format.js` — Currency, percentage formatting
- `apps/terminal-ui/src/utils/chartHelpers.js` — SVG chart rendering, mock data
- `apps/terminal-ui/src/components/topbar/TopBar.js` — Run button, status bar
- `apps/terminal-ui/src/components/sidebar/Sidebar.js` — Parameter panel
- `apps/terminal-ui/src/components/sidebar/parameter-sections.js` — Section definitions
- `apps/terminal-ui/src/components/charts/ChartArea.js` — uPlot charts
- `apps/terminal-ui/src/components/perf/PerformanceBar.js` — Metrics table
- `apps/terminal-ui/src/components/banner/ErrorBanner.js` — Error display
- `apps/terminal-ui/src/components/history/RunHistory.js` — Run list
- `apps/terminal-ui/src/components/tweaks/TweaksPanel.js` — Theme/settings
- `apps/terminal-ui/src/components/primitives/CollapsibleSection.js` — Section toggle
- `apps/terminal-ui/src/components/primitives/EditableValue.js` — Inline editing
- `apps/terminal-ui/src/components/primitives/Button.js` — Button render
- `apps/terminal-ui/src/components/primitives/DataTable.js` — Table render
- `apps/terminal-ui/src/components/primitives/SvgChart.js` — SVG chart render
- `apps/terminal-ui/src/components/pnl/PnLStrip.js` — P&L bar chart
- `apps/terminal-ui/src/components/tradelog/TradeLog.js` — Trade table
- `apps/terminal-ui/src/components/tables/TableGrid.js` — Grid layout

---

*End of review.*
