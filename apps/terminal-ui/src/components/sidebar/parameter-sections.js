/**
 * Declarative sidebar schema. Each section renders as a CollapsibleSection.
 *
 * Per-row fields:
 *   key       — matches store.params key (and engine PARAMS key)
 *   label     — left-hand label (keep short — sidebar is 188px)
 *   type      — 'date' triggers a native <input type="date"> on click
 *   color     — optional .pv colour class
 *   format(v) — display transform returning a string
 *   transform(v) — simpler alternative for boolean/enum labels
 *   options   — array of allowed values; renders as a cycling .pv-cycle span
 *   showWhen  — { key, value } — row is hidden unless params[key] matches value
 *   indent    — render as a visually subordinate sub-param row
 *   tooltip   — short description shown on hover to the right of the sidebar
 */
export const parameterSections = [
  // ── BACKTEST ──────────────────────────────────────────────────────────────
  {
    id: 'BACKTEST', title: 'BACKTEST',
    params: [
      { key: 'start_date',      label: 'start',   color: 'amber', type: 'date',
        tooltip: 'Backtest start date. Market mode requires data from 2008 onwards.' },
      { key: 'end_date',        label: 'end',     color: 'amber', type: 'date',
        tooltip: 'Backtest end date.' },
      { key: 'initial_balance', label: 'balance', format: v => '$' + Number(v).toLocaleString(),
        tooltip: 'Starting portfolio value in dollars.' },
    ],
  },

  // ── STRATEGY ─────────────────────────────────────────────────────────────
  {
    id: 'STRATEGY', title: 'STRATEGY',
    params: [
      { key: 'mode', label: 'pricing', color: 'blue',
        transform: v => String(v).toUpperCase(), options: ['market', 'synthetic'],
        tooltip: 'Market: real bid/ask from options DB (2008–2025). Synthetic: Black-Scholes, works for any date range.' },

      { key: 'put_slope', label: 'put slope', format: v => Number(v).toFixed(2),
        showWhen: { key: 'mode', value: 'synthetic' }, indent: true,
        tooltip: 'Vol skew for puts: IV = base_vol × (1 + slope × Δ). Gruvbox default 0.30 ≈ real put skew at 16Δ.' },
      { key: 'call_slope', label: 'call slope', format: v => Number(v).toFixed(2),
        showWhen: { key: 'mode', value: 'synthetic' }, indent: true,
        tooltip: 'Vol skew for calls. Lower than put_slope models the typical negative skew. Default 0.10.' },

      { key: 'strategy_mode', label: 'strategy',
        transform: v => String(v).replace('_', ' ').toUpperCase(), options: ['short_strangle', 'iron_condor'],
        tooltip: 'Short strangle: sell naked put + call. Iron condor: adds long wings (defined risk).' },

      { key: 'wing_delta', label: 'wing Δ', format: v => Number(v).toFixed(2),
        showWhen: { key: 'strategy_mode', value: 'iron_condor' }, indent: true,
        tooltip: 'Delta of the long wing legs. 0.05 = 5Δ wings; smaller = wider spread, more credit.' },

      { key: 'target_delta', label: 'target Δ',
        tooltip: 'Delta at which to sell each leg. 0.16 ≈ 1 standard deviation (16% probability ITM).' },
      { key: 'dte_min', label: 'DTE min',
        tooltip: 'Minimum DTE for the chosen expiration. With dte_max=45, targets the 30–45 DTE window.' },
      { key: 'dte_max', label: 'DTE max',
        tooltip: 'Maximum DTE. The strategy uses the nearest 3rd-Friday expiration in [dte_min, dte_max].' },
      { key: 'profit_target_pct', label: 'profit tgt', color: 'green',
        format: v => Math.round(v * 100) + '%', pct: true,
        tooltip: 'Close position when P&L ≥ this fraction of net credit collected. TastyTrade standard: 50%.' },

      { key: 'use_price_stop', label: 'stop loss',
        color: v => v ? 'green' : 'red',
        transform: v => v ? 'ON' : 'OFF', options: [false, true],
        tooltip: 'Enable a price-based stop loss. Off by default — the strategy relies on time decay, not stop management.' },
      { key: 'stop_loss_pct', label: 'stop loss %',
        format: v => Math.round(v * 100) + '%', pct: true,
        showWhen: { key: 'use_price_stop', value: true }, indent: true,
        tooltip: 'Close when P&L ≤ −(stop × credit). 200% = lose up to 2× the premium received.' },
    ],
  },

  // ── PORTFOLIO ─────────────────────────────────────────────────────────────
  {
    id: 'PORTFOLIO', title: 'PORTFOLIO',
    params: [
      { key: 'portfolio_mode', label: 'mode', color: 'blue',
        transform: v => String(v).toUpperCase(), options: ['laddering', 'single'],
        tooltip: 'Laddering: multiple concurrent positions with Reg-T margin management. Single: one active chain at a time.' },
      { key: 'single_position', label: 'single barrier',
        color: v => v ? 'green' : 'red',
        transform: v => v ? 'ON' : 'OFF', options: [true, false],
        showWhen: { key: 'portfolio_mode', value: 'single' }, indent: true,
        tooltip: 'In single mode: skip new monthly entries while the current roll chain is still open.' },

      { key: 'max_bpr_allocation', label: 'max BPR',
        format: v => Math.round(v * 100) + '%', pct: true,
        tooltip: 'Max fraction of capital allocated to margin (Buying Power Reduction). 30% limits margin to $15k on a $50k account.' },
      { key: 'entry_cooldown_days', label: 'entry cooldown',
        format: v => v + ' days',
        tooltip: 'Minimum trading days between new entries in laddering mode. Prevents over-concentration in a single week.' },
      { key: 'cash_investment_mode', label: 'cash mode', color: 'amber',
        transform: v => String(v).toUpperCase(), options: ['spy', 'risk_free', 'blend'],
        tooltip: 'How uninvested cash earns return: SPY (equity-like), risk-free (T-bills), or a blend of both.' },
      { key: 'spy_allocation_pct', label: 'SPY split',
        format: v => Math.round(v * 100) + '% SPY', pct: true,
        showWhen: { key: 'cash_investment_mode', value: 'blend' }, indent: true,
        tooltip: 'In blend mode, fraction of uninvested cash invested in SPY. Remainder earns risk-free rate.' },
    ],
  },

  // ── ROLL MGMT ─────────────────────────────────────────────────────────────
  {
    id: 'ROLL_MGMT', title: 'ROLL MGMT',
    params: [
      { key: 'manage_at_dte', label: 'manage@DTE',
        tooltip: 'Days-to-expiration at which to roll or close the position. TastyTrade standard: 21 DTE.' },
      { key: 'roll_for_credit', label: 'roll credit',
        color: v => v ? 'green' : 'red',
        transform: v => v ? 'ON' : 'OFF', options: [true, false],
        tooltip: 'At manage_at_dte, roll to next expiration only if a net credit can be collected. Else close flat.' },
      { key: 'max_rolls', label: 'max rolls',
        tooltip: 'Maximum number of times a position can be rolled before it must be closed flat.' },
    ],
  },

  // ── DEFENSIVE ─────────────────────────────────────────────────────────────
  {
    id: 'DEFENSIVE', title: 'DEFENSIVE',
    params: [
      { key: 'defensive_leg_roll_enabled', label: 'leg rolls',
        color: v => v ? 'green' : 'red',
        transform: v => v ? 'ON' : 'OFF', options: [false, true],
        tooltip: 'Roll the profitable leg toward ATM when the tested leg reaches trigger delta. WARNING: historically hurts returns — default OFF.' },
      { key: 'defensive_trigger_delta', label: 'trigger Δ',
        showWhen: { key: 'defensive_leg_roll_enabled', value: true }, indent: true,
        tooltip: 'Tested-leg |delta| that triggers a defensive leg roll. Default 0.30 fires ~13×/year — see params.py for analysis.' },
      { key: 'leg_roll_target_delta', label: 'roll target Δ',
        showWhen: { key: 'defensive_leg_roll_enabled', value: true }, indent: true,
        tooltip: 'Delta target for the newly sold untested leg after a defensive roll. Matches entry delta by default.' },
      { key: 'max_leg_rolls_per_trade', label: 'max leg rolls',
        showWhen: { key: 'defensive_leg_roll_enabled', value: true }, indent: true,
        tooltip: 'Maximum defensive leg rolls per trade (put + call rolls combined).' },
    ],
  },

  // ── VIX FILTER ────────────────────────────────────────────────────────────
  {
    id: 'VIX_FILTER', title: 'VIX FILTER',
    params: [
      { key: 'vix_entry_filter_enabled', label: 'enabled',
        color: v => v ? 'green' : 'red',
        transform: v => v ? 'ON' : 'OFF', options: [true, false],
        tooltip: 'Skip new entries and rolls when VIX is above the threshold on the entry date.' },
      { key: 'vix_entry_max', label: 'max VIX',
        tooltip: 'VIX level above which entries are blocked. Also applies to 21-DTE roll continuations.' },
    ],
  },
];

// ── Condition helper ───────────────────────────────────────────────────────

export function matchesCondition(showWhen, params) {
  if (!showWhen) return true;
  const actual = params[showWhen.key];
  const expected = showWhen.value;
  if (typeof expected === 'boolean') {
    // Guard against boolean stored as string from older localStorage
    if (typeof actual === 'string') return expected === (actual.toLowerCase() === 'true');
    return Boolean(actual) === expected;
  }
  return String(actual ?? '').toLowerCase() === String(expected).toLowerCase();
}

// ── Param lookup ──────────────────────────────────────────────────────────

export function findParam(key) {
  for (const sec of parameterSections) {
    const p = sec.params.find(q => q.key === key);
    if (p) return p;
  }
  return null;
}

// ── Type coercion ──────────────────────────────────────────────────────────

export function coerceParamValue(rawString, originalValue) {
  const trimmed = String(rawString).trim();
  if (typeof originalValue === 'number') {
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : originalValue;
  }
  if (typeof originalValue === 'boolean') {
    const v = trimmed.toLowerCase();
    if (['true', 'on', '1', 'yes'].includes(v)) return true;
    if (['false', 'off', '0', 'no'].includes(v)) return false;
    return originalValue;
  }
  return trimmed.toLowerCase();
}
