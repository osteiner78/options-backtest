export const formatPct = (v, digits = 1) =>
  v === null || v === undefined ? '--' : (v * 100).toFixed(digits) + '%';

export const formatNum = (v, digits = 2) =>
  v === null || v === undefined ? '--' : Number(v).toFixed(digits);

export const formatCurrency = (v) =>
  v === null || v === undefined ? '--' : '$' + Math.round(v).toLocaleString();

export const formatPnl = (v) => {
  if (v === null || v === undefined) return '--';
  const sign = v >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(Math.round(v)).toLocaleString()}`;
};

export const formatSignedPct = (v, digits = 1) => {
  if (v === null || v === undefined) return '--';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(digits)}%`;
};
