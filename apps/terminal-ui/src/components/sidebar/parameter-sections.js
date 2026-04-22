/**
 * Declarative schema that drives the Sidebar. Each entry produces one
 * CollapsibleSection of ParameterRows. Adding/removing a knob is a one-line
 * change here.
 *
 * Per-row fields:
 *   key       — matches store.params key
 *   label     — left-hand label
 *   color     — optional .pv colour class ('green' | 'red' | 'blue' | 'amber' | 'dim' | 'purple')
 *   format(v) — optional display transform returning a string
 *   transform(v) — simpler alternative to format, used for boolean/enum labels
 */
export const parameterSections = [
  {
    id: 'BACKTEST',
    title: 'BACKTEST',
    params: [
      { key: 'start_date',      label: 'start',   color: 'amber' },
      { key: 'end_date',        label: 'end',     color: 'amber' },
      { key: 'initial_balance', label: 'balance', format: v => '$' + Number(v).toLocaleString() },
    ],
  },
  {
    id: 'STRATEGY',
    title: 'STRATEGY',
    params: [
      { key: 'mode',              label: 'mode',       color: 'blue',  transform: v => String(v).toUpperCase() },
      { key: 'target_delta',      label: 'target Δ' },
      { key: 'dte_min',           label: 'DTE min' },
      { key: 'dte_max',           label: 'DTE max' },
      { key: 'profit_target_pct', label: 'profit tgt', color: 'green', format: v => (v * 100) + '%' },
      { key: 'stop_loss_pct',     label: 'stop loss',                  format: v => (v * 100) + '%' },
    ],
  },
  {
    id: 'PORTFOLIO',
    title: 'PORTFOLIO',
    params: [
      { key: 'max_bpr_allocation',   label: 'max BPR',   format: v => (v * 100) + '%' },
      { key: 'entry_cooldown_days',  label: 'cooldown',  format: v => v + ' days' },
      { key: 'cash_investment_mode', label: 'cash mode', color: 'amber', transform: v => String(v).toUpperCase() },
    ],
  },
  {
    id: 'ROLL_MGMT',
    title: 'ROLL MGMT',
    params: [
      { key: 'manage_at_dte',   label: 'manage@DTE' },
      { key: 'roll_for_credit', label: 'roll credit', color: 'green', transform: v => v ? 'ON' : 'OFF' },
      { key: 'max_rolls',       label: 'max rolls' },
    ],
  },
  {
    id: 'VIX_FILTER',
    title: 'VIX FILTER',
    params: [
      { key: 'vix_entry_filter_enabled', label: 'enabled', color: 'dim', transform: v => v ? 'ON' : 'OFF' },
      { key: 'vix_entry_max',            label: 'max VIX' },
    ],
  },
];

/**
 * Parse a raw input string back into a typed value, using the original stored
 * value as a hint. Numbers stay numbers, booleans stay booleans, everything
 * else stays a string.
 */
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
  return trimmed;
}
