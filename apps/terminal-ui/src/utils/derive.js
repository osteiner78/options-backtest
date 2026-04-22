const EXIT_TYPES = ['PROFIT', 'ROLLED', '21DTE', 'EXPIRY', 'STOP', 'FORCE_CLOSE'];

export const VIX_REGIMES = [
  { label: 'LOW',      range: '0–15',  color: 'c-blue', min: 0,  max: 15  },
  { label: 'NORMAL',   range: '15–25', color: 'c-amb',  min: 15, max: 25  },
  { label: 'ELEVATED', range: '25–35', color: 'c-pur',  min: 25, max: 35  },
  { label: 'HIGH',     range: '>35',   color: 'c-neg',  min: 35, max: 999 },
];

export function computeExitStats(trades) {
  if (!trades?.length) return [];
  const total = trades.length;
  return EXIT_TYPES
    .map(type => {
      const filtered = trades.filter(t => t.exit_type === type);
      const n = filtered.length;
      const wins = filtered.filter(t => (t.pnl || 0) > 0).length;
      const totalPnl = filtered.reduce((sum, t) => sum + (t.pnl || 0), 0);
      return {
        type,
        n,
        pct: n / total,
        winRate: n > 0 ? wins / n : 0,
        avgPnl: n > 0 ? totalPnl / n : 0,
        totalPnl,
      };
    })
    .filter(d => d.n > 0);
}

export function computeVixRegimeStats(trades) {
  if (!trades?.length) return VIX_REGIMES.map(r => ({ ...r, n: 0, winRate: 0, avgPnl: 0, totalPnl: 0 }));
  return VIX_REGIMES.map(r => {
    const filtered = trades.filter(t => t.entry_vix >= r.min && t.entry_vix < r.max);
    const n = filtered.length;
    const wins = filtered.filter(t => (t.pnl || 0) > 0).length;
    const totalPnl = filtered.reduce((sum, t) => sum + (t.pnl || 0), 0);
    return {
      ...r,
      n,
      winRate: n > 0 ? wins / n : 0,
      avgPnl: n > 0 ? totalPnl / n : 0,
      totalPnl,
    };
  });
}
