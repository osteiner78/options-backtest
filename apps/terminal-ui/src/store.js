/**
 * Minimal reactive store using Proxy.
 */

const PARAMS_KEY = 'straddle_params';
const THEME_KEY  = 'straddle_theme';

const defaultParams = {
  start_date: '2021-01-01',
  end_date: '2025-11-30',
  initial_balance: 50000,
  target_delta: 0.16,
  dte_min: 30,
  dte_max: 45,
  profit_target_pct: 0.50,
  stop_loss_pct: 2.00,
  max_bpr_allocation: 0.30,
  manage_at_dte: 21,
  roll_for_credit: true,
  max_rolls: 3,
  entry_cooldown_days: 3,
  cash_investment_mode: 'spy',
  vix_entry_filter_enabled: false,
  vix_entry_max: 35.0,
  mode: 'market',
};

const ENUM_FIELDS = ['mode', 'cash_investment_mode', 'portfolio_mode', 'strategy_mode'];

function loadParams() {
  const saved = localStorage.getItem(PARAMS_KEY);
  if (saved) {
    try {
      const stored = JSON.parse(saved);
      // Lowercase enum strings in case user typed uppercase values via sidebar edit
      for (const f of ENUM_FIELDS) {
        if (typeof stored[f] === 'string') stored[f] = stored[f].toLowerCase();
      }
      return { ...defaultParams, ...stored };
    } catch (e) {
      console.error('Failed to parse saved params', e);
    }
  }
  return defaultParams;
}

function loadTheme() {
  return localStorage.getItem(THEME_KEY) || 'gruvbox';
}

const initialState = {
  params: loadParams(),
  config: null, // { defaults, ranges, enums, capabilities } — fetched from /config
  results: null,
  status: 'idle', // 'idle' | 'running' | 'completed' | 'failed'
  progress: null, // { pct, trades_so_far, current_date } during run
  error: null,
  lastRun: null,
  activeTab: 'equity',
  tradeLogOpen: false,
  tradeLogFilter: 'ALL', // 'ALL' | 'PROFIT' | 'ROLLED' | '21DTE' | 'STOP' | 'EXPIRY'
  themePanelOpen: false,
  theme: loadTheme(), // 'gruvbox' | 'tokyo'
  runHistory: [], // [{run_id, created_at, status, label, params}]
  runHistoryOpen: false,
};

const listeners = new Set();

export const store = new Proxy(initialState, {
  set(target, key, value) {
    target[key] = value;
    if (key === 'params') localStorage.setItem(PARAMS_KEY, JSON.stringify(value));
    if (key === 'theme')  localStorage.setItem(THEME_KEY, value);
    listeners.forEach(l => l(target));
    return true;
  },
});

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function updateParams(newParams) {
  store.params = { ...store.params, ...newParams };
}

export function setStatus(status) {
  store.status = status;
}

export function setResults(results) {
  store.results = results;
  store.status = 'completed';
  store.error = null;
  store.progress = null;
  store.lastRun = new Date();
}

export function setProgress(progress) {
  store.progress = progress;
}

export function setRunHistory(runs) {
  store.runHistory = runs;
}

export function toggleRunHistory() {
  store.runHistoryOpen = !store.runHistoryOpen;
}

export function setError(error) {
  store.error = error;
  store.status = 'failed';
}

export function clearError() {
  store.error = null;
  if (store.status === 'failed') store.status = 'idle';
}

export function toggleTradeLog() {
  store.tradeLogOpen = !store.tradeLogOpen;
}

export function setTradeLogFilter(filter) {
  store.tradeLogFilter = filter;
}

export function toggleThemePanel() {
  store.themePanelOpen = !store.themePanelOpen;
}

export function setTheme(theme) {
  store.theme = theme;
}

export function setActiveTab(tab) {
  store.activeTab = tab;
}

export function setConfig(config) {
  store.config = config;
}

/**
 * Hydrate store.params with backend defaults from /config.
 * Only runs when the user has no saved params in localStorage, so existing
 * custom setups are never overwritten. New parameters added to the backend
 * flow in automatically without touching frontend code.
 */
export function applyConfigDefaults(config) {
  if (!config?.defaults) return;
  if (localStorage.getItem(PARAMS_KEY)) return; // user has saved params — don't touch
  // Backend defaults take precedence over frontend defaults for any shared key.
  // Frontend-only keys (e.g. 'mode' alias) are preserved in defaultParams.
  store.params = { ...defaultParams, ...config.defaults };
}
