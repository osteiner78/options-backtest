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

function loadParams() {
  const saved = localStorage.getItem(PARAMS_KEY);
  if (saved) {
    try {
      return { ...defaultParams, ...JSON.parse(saved) };
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
  error: null,
  lastRun: null,
  activeTab: 'equity',
  tradeLogOpen: false,
  tradeLogFilter: 'ALL', // 'ALL' | 'PROFIT' | 'ROLLED' | '21DTE' | 'STOP' | 'EXPIRY'
  themePanelOpen: false,
  theme: loadTheme(), // 'gruvbox' | 'tokyo'
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
  store.lastRun = new Date();
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
