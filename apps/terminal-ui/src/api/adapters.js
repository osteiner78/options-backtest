import { computeExitStats, computeVixRegimeStats } from '../utils/derive.js';

/**
 * Normalize a raw backtest response into the shape components consume.
 * For Phase 1 this preserves the backend's snake_case fields and adds
 * derived views on top. Later phases may restructure further.
 */
export function normalizeResults(raw) {
  if (!raw) return null;

  const trades = raw.trades ?? [];

  return {
    ...raw,
    trades,
    vix_blocked_dates: raw.vix_blocked_dates ?? [],
    has_portfolio_curves: Boolean(raw.bpr_curve && raw.pos_count_curve),
    exit_stats: computeExitStats(trades),
    vix_regime_stats: computeVixRegimeStats(trades),
  };
}
