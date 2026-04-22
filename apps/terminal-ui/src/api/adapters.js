import { computeExitStats, computeVixRegimeStats, VIX_REGIMES } from '../utils/derive.js';

/**
 * Normalize a raw backtest response into the shape components consume.
 *
 * Server-side exit_stats / vix_regime_stats (Phase 3+) are preferred;
 * client-side derivations remain as a fallback for older API builds.
 * Both paths emit the same field names so downstream rendering is uniform.
 */
export function normalizeResults(raw) {
  if (!raw) return null;

  const trades = raw.trades ?? [];
  const metrics = raw.metrics ?? {};

  const exitStats = metrics.exit_stats?.length
    ? mapExitStatsFromServer(metrics.exit_stats)
    : computeExitStats(trades);

  const vixRegimeStats = metrics.vix_regime_stats?.length
    ? mapVixStatsFromServer(metrics.vix_regime_stats)
    : computeVixRegimeStats(trades);

  return {
    ...raw,
    trades,
    vix_blocked_dates: raw.vix_blocked_dates ?? [],
    has_portfolio_curves: Boolean(raw.bpr_curve && raw.pos_count_curve),
    exit_stats: exitStats,
    vix_regime_stats: vixRegimeStats,
  };
}

function mapExitStatsFromServer(rows) {
  return rows
    .filter(r => r.type !== 'TOTAL' && r.count > 0)
    .map(r => ({
      type: r.type,
      n: r.count,
      pct: r.pct,
      winRate: r.win_pct ?? 0,
      avgPnl: r.avg_pnl ?? 0,
      totalPnl: r.total_pnl ?? 0,
    }));
}

function mapVixStatsFromServer(rows) {
  const regimesByName = Object.fromEntries(VIX_REGIMES.map(r => [r.label, r]));
  return rows
    .filter(r => r.regime !== 'TOTAL')
    .map(r => {
      const client = regimesByName[r.regime] ?? { color: 'c-dim', range: r.range };
      return {
        label: r.regime,
        range: client.range,
        color: client.color,
        min: client.min,
        max: client.max,
        n: r.count,
        winRate: r.win_pct ?? 0,
        avgPnl: r.avg_pnl ?? 0,
        totalPnl: r.total_pnl ?? 0,
      };
    });
}
