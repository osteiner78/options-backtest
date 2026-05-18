# 012 — Terminal-UI Update to v7 Parameters

**Date:** 2026-05-18  
**Status:** Ready for execution  
**Context:** The terminal-ui uses old parameter names (`vix_entry_filter_enabled`, `defensive_leg_roll_enabled`) that don't match the grid v7 naming (`vix_filter`, `defensive_leg_roll`) and is missing `execution_mode` entirely. The API also needs updating to accept the new names.

---

## Current State

| Parameter | params.py (internal) | API | Terminal-UI | grid v7 |
|-----------|:---:|:---:|:---:|:---:|
| VIX filter | `vix_entry_filter_enabled` | `vix_entry_filter_enabled` (bool) | `vix_entry_filter_enabled` (bool) | `vix_filter` (string) |
| Defensive roll | `defensive_leg_roll_enabled` | `defensive_leg_roll_enabled` | `defensive_leg_roll_enabled` | `defensive_leg_roll` |
| Execution mode | `execution_mode` | **MISSING** | **MISSING** | `execution_mode` |

The terminal-ui sends names the API already accepts, but neither supports grid v7 parameters.

---

## Phase 1 — Update API (`src/straddle/api.py`)

### 1a. Add `execution_mode` field to `BacktestRequest`

Insert after `stop_loss_pct` (line 75):

```python
execution_mode: Optional[str] = Field(
    default=None,
    pattern=r"^(bid_ask|mid|mid_plus_1tick|mid_minus_1tick)$",
)
```

### 1b. Add `vix_filter` field, deprecate old

Replace line 89:

```python
vix_filter: Optional[str] = Field(
    default=None,
    pattern=r"^(OFF|rv_pct:70|rv_pct:80|rv_pct:90|ivr:70|ivr:80|ivr:90)$",
)
vix_entry_filter_enabled: Optional[bool] = Field(default=None, deprecated=True)
vix_entry_max: Optional[float] = Field(default=None, ge=5, le=100, deprecated=True)
```

### 1c. Add `defensive_leg_roll` field, deprecate old

Replace lines 92-95:

```python
defensive_leg_roll: Optional[bool] = Field(default=None)
defensive_leg_roll_enabled: Optional[bool] = Field(default=None, deprecated=True)
defensive_trigger_delta: Optional[float] = Field(default=None, ge=0.1, le=0.5)
leg_roll_target_delta: Optional[float] = Field(default=None, ge=0.05, le=0.3)
max_leg_rolls_per_trade: Optional[int] = Field(default=None, ge=0, le=10)
```

### 1d. Add translation helper for `vix_filter`

Add this function after `_PARAM_REMAP` (around line 60):

```python
def _translate_vix_filter(overrides: dict) -> None:
    """Translate grid-style vix_filter string to internal boolean flags.

    Mirrors the logic in scripts/grid_search.py _apply_grid_overrides.
    """
    vf = overrides.pop("vix_filter", None)
    if vf is None or vf == "OFF":
        overrides["vix_entry_filter_enabled"] = False
    elif ":" in vf:
        mode, threshold_str = vf.split(":", 1)
        overrides["vix_entry_filter_enabled"] = True
        overrides["vol_filter_mode"] = mode        # "rv_pct" or "ivr"
        overrides["vol_filter_threshold"] = float(threshold_str)
```

### 1e. Add defensive_leg_roll remap

Add after the `_PARAM_REMAP` loop in `_run_backtest_task` (around line 377):

```python
if "defensive_leg_roll" in overrides:
    overrides["defensive_leg_roll_enabled"] = overrides.pop("defensive_leg_roll")
```

### 1f. Apply `_translate_vix_filter` before backtest

Call it after all remapping is done, before the params dict is used:

```python
_translate_vix_filter(overrides)
```

### 1g. Run tests

```bash
pytest tests/ -v
```

---

## Phase 2 — Update Terminal-UI

### 2a. `apps/terminal-ui/src/store.js` — update `defaultParams`

Remove (lines 44-45):

```js
vix_entry_filter_enabled: false,
vix_entry_max: 50,
```

Add:

```js
vix_filter: 'OFF',               // 'OFF' | 'rv_pct:70' | 'rv_pct:80' | 'rv_pct:90'
execution_mode: 'mid',           // 'bid_ask' | 'mid' | 'mid_plus_1tick'
```

Rename (line 39):

```js
// defensive_leg_roll_enabled → defensive_leg_roll
defensive_leg_roll: false,
```

### 2b. `apps/terminal-ui/src/store.js` — update `ENUM_FIELDS` (line 48)

Add `'execution_mode'` to the array.

### 2c. `apps/terminal-ui/src/components/sidebar/parameter-sections.js`

Replace the vix_entry_filter_enabled toggle + vix_entry_max input with `vix_filter` dropdown:

```js
{
  key: 'vix_filter',
  label: 'Vol Filter',
  type: 'select',
  options: [
    { value: 'OFF', label: 'Off' },
    { value: 'rv_pct:70', label: 'RV %ile > 70th' },
    { value: 'rv_pct:80', label: 'RV %ile > 80th' },
    { value: 'rv_pct:90', label: 'RV %ile > 90th' },
  ],
  default: 'OFF',
},
```

Add `execution_mode` section (after `dte_max`, before `profit_target_pct`):

```js
{
  key: 'execution_mode',
  label: 'Execution',
  type: 'select',
  options: [
    { value: 'bid_ask', label: 'Bid/Ask (conservative)' },
    { value: 'mid', label: 'Mid (realistic)' },
    { value: 'mid_plus_1tick', label: 'Mid+1 tick (optimistic)' },
  ],
  default: 'mid',
},
```

Rename `defensive_leg_roll_enabled` → `defensive_leg_roll`:

```js
// Change key from 'defensive_leg_roll_enabled' to 'defensive_leg_roll'
{
  key: 'defensive_leg_roll',
  label: 'Defensive Roll',
  type: 'toggle',
  default: false,
},
// Update showWhen references:
// showWhen: { key: 'defensive_leg_roll', value: true }
```

### 2d. `apps/terminal-ui/src/api/client.js`

Add to `enumFields` array (line 25):

```js
const enumFields = ['market', 'pricing_mode', 'cash_investment_mode', 'portfolio_mode', 'strategy_mode', 'execution_mode'];
```

### 2e. `apps/terminal-ui/src/components/perf/PerformanceBar.js`

Add `info_ratio` display alongside `sharpe`:

```js
// After the existing sharpe display, add:
const infoRatio  = metrics.info_ratio?.toFixed(2) ?? '—';
// Label it "IR" (information ratio) vs "Sharpe" (true, rf-subtracted)
```

### 2f. Remove `roll_for_credit` references

The v7 grid always rolls for credit (it's implicit). Remove `roll_for_credit` from `store.js` defaultParams and `parameter-sections.js`.

### 2g. Build and verify

```bash
cd apps/terminal-ui && npm install && npm run build
```

---

## Phase 3 — Verify End-to-End

```bash
# 1. API accepts new params
curl -s -X POST http://localhost:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "market": "bova11",
    "execution_mode": "mid",
    "vix_filter": "OFF",
    "defensive_leg_roll": false,
    "target_delta": 0.25,
    "dte_max": 21,
    "profit_target_pct": 0.5,
    "portfolio_mode": "single",
    "initial_balance": 100000
  }' | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('run_id','ERROR'))"

# 2. Wait for completion, check metrics
curl -s http://localhost:8000/backtest/<RUN_ID> | python -c "import json,sys; d=json.load(sys.stdin); print(d['metrics']['sharpe'], d['metrics']['info_ratio'])"

# 3. Launch terminal-ui and run a visual backtest
# Navigate to http://localhost:<port>, select bova11, mid execution, OFF vol filter, run
```

---

## Summary

| Phase | Files | Effort |
|-------|-------|:------:|
| 1 — API | `api.py` (+40 lines) | 30 min |
| 2 — Terminal-UI | `store.js`, `parameter-sections.js`, `client.js`, `PerformanceBar.js` (~60 lines changed) | 45 min |
| 3 — Verify | CLI + curl + UI | 10 min |
| **Total** | | **~1.5 hrs** |
