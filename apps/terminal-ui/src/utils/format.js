export const formatPct = (v, digits = 1) =>
  v === null || v === undefined ? '--' : (v * 100).toFixed(digits) + '%';

export const formatNum = (v, digits = 2) =>
  v === null || v === undefined ? '--' : Number(v).toFixed(digits);

export const formatCurrency = (v, sym = '$') =>
  v === null || v === undefined ? '--' : sym + Math.round(v).toLocaleString();

export const formatPnl = (v, sym = '$') => {
  if (v === null || v === undefined) return '--';
  const sign = v >= 0 ? '+' : '−';
  return `${sign}${sym}${Math.abs(Math.round(v)).toLocaleString()}`;
};

export const formatSignedPct = (v, digits = 1) => {
  if (v === null || v === undefined) return '--';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(digits)}%`;
};

const MARKET_CURRENCIES = { bova11: 'R$', petr4: 'R$' };

/** Return the currency symbol for a market identifier. */
export const currencySymbol = (market) =>
  MARKET_CURRENCIES[market] ?? '$';
