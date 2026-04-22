import { store } from '../../store.js';
import { formatPct, formatPnl } from '../../utils/format.js';
import { computeExitStats, computeVixRegimeStats, VIX_REGIMES } from '../../utils/derive.js';

const EXIT_COLORS = {
  PROFIT: 'c-pos', ROLLED: 'c-pur', '21DTE': 'c-blue',
  STOP: 'c-neg', EXPIRY: 'c-amb', FORCE_CLOSE: 'c-dim',
};

export function renderTableGrid() {
  const { results } = store;
  if (!results || !results.trades) {
    return `
      <div class="tables-row" style="grid-template-columns: 1fr 1fr 1fr;">
        <div class="tp"><div class="tp-title">Trades Summary</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
        <div class="tp"><div class="tp-title">Exit Breakdown</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
        <div class="tp"><div class="tp-title">VIX Regime</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
      </div>
    `;
  }

  const { metrics, trades } = results;
  const totalN = trades.length;

  const pnls = trades.map(t => t.pnl || 0);
  const minPnl = pnls.length ? Math.min(...pnls) : 0;
  const maxPnl = pnls.length ? Math.max(...pnls) : 0;

  const summaryRows = [
    { label: 'Number of trades',    val: metrics.n_trades },
    { label: 'Win rate',            val: formatPct(metrics.win_rate), color: 'c-blue' },
    { label: 'Avg P&L',             val: formatPnl(metrics.avg_pnl),  color: 'c-pos' },
    { label: 'P&L range',           val: `[${formatPnl(minPnl)} - ${formatPnl(maxPnl)}]`, color: 'c-dim' },
    { label: 'Avg positions',       val: metrics.avg_positions ? metrics.avg_positions.toFixed(1) : '--' },
    { label: 'Peak positions',      val: metrics.peak_positions || '--', color: 'c-amb' },
    { label: 'Max consec. losses',  val: metrics.max_streak || '--', color: 'c-neg' },
    { label: 'Skipped (VIX filter)', val: results.vix_blocked_dates ? results.vix_blocked_dates.length : 0, color: 'c-neg' },
    { label: 'Avg BPR util',        val: metrics.avg_bpr_util_pct ? formatPct(metrics.avg_bpr_util_pct) : '--' },
    { label: 'Peak BPR util',       val: metrics.peak_bpr_util_pct ? formatPct(metrics.peak_bpr_util_pct) : '--', color: 'c-amb' },
  ];

  const exitData = results.exit_stats ?? computeExitStats(trades);
  const vixData  = results.vix_regime_stats ?? computeVixRegimeStats(trades);

  const winRateClass = (wr) => wr >= 0.7 ? 'c-pos' : (wr >= 0.5 ? 'c-amb' : 'c-neg');

  return `
    <div class="tables-row" style="grid-template-columns: 1.1fr 1.3fr 1.3fr;">
      <div class="tp">
        <div class="tp-title">Trades Summary</div>
        <table class="dt">
          <tbody>
            ${summaryRows.map(r => `
              <tr>
                <td style="color:var(--dim);">${r.label}</td>
                <td class="r fw6 ${r.color || ''}">${r.val}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <div class="tp">
        <div class="tp-title">Exit Breakdown</div>
        <table class="dt">
          <thead><tr>
            <th>Type</th><th class="r">N</th><th class="r">%</th><th class="r">Win%</th><th class="r">Avg P&L</th><th class="r">Total P&L</th>
          </tr></thead>
          <tbody>
            ${exitData.map(d => `
              <tr>
                <td class="${EXIT_COLORS[d.type] || ''} fw6">${d.type}</td>
                <td class="r">${d.n}</td>
                <td class="r c-dim">${(d.pct * 100).toFixed(0)}%</td>
                <td class="r ${winRateClass(d.winRate)}">${(d.winRate * 100).toFixed(0)}%</td>
                <td class="r ${d.avgPnl >= 0 ? 'c-pos' : 'c-neg'}">${formatPnl(d.avgPnl)}</td>
                <td class="r ${d.totalPnl >= 0 ? 'c-pos' : 'c-neg'}">${formatPnl(d.totalPnl)}</td>
              </tr>
            `).join('')}
            <tr class="tot">
              <td>TOTAL</td><td class="r">${totalN}</td><td class="r">100%</td>
              <td class="r c-pos">${(metrics.win_rate * 100).toFixed(0)}%</td>
              <td class="r c-pos">${formatPnl(metrics.avg_pnl)}</td>
              <td class="r c-pos">${formatPnl(metrics.final_balance - metrics.initial_balance)}</td>
            </tr>
          </tbody>
        </table>
        <div style="font-size:7px; color:var(--dim); margin-top:5px; text-align:right;">TOTAL includes Options P&L + Cash Yield</div>
      </div>

      <div class="tp">
        <div class="tp-title">VIX Regime</div>
        <table class="dt">
          <thead><tr>
            <th>Regime</th><th class="r">Range</th><th class="r">N</th><th class="r">Win%</th><th class="r">Avg P&L</th><th class="r">Total P&L</th>
          </tr></thead>
          <tbody>
            ${vixData.map(d => `
              <tr>
                <td class="${d.color} fw6">${d.label}</td>
                <td class="r c-dim">${d.range}</td>
                <td class="r">${d.n}</td>
                <td class="r ${winRateClass(d.winRate)}">${d.n > 0 ? (d.winRate * 100).toFixed(0) + '%' : '--'}</td>
                <td class="r ${d.avgPnl >= 0 ? 'c-pos' : 'c-neg'}">${d.n > 0 ? formatPnl(d.avgPnl) : '--'}</td>
                <td class="r ${d.totalPnl >= 0 ? 'c-pos' : 'c-neg'}">${d.n > 0 ? formatPnl(d.totalPnl) : '--'}</td>
              </tr>
            `).join('')}
            <tr class="tot">
              <td>TOTAL</td><td class="r"></td><td class="r">${totalN}</td>
              <td class="r c-pos">${(metrics.win_rate * 100).toFixed(0)}%</td>
              <td class="r c-pos">${formatPnl(metrics.avg_pnl)}</td>
              <td class="r c-pos">${formatPnl(metrics.final_balance - metrics.initial_balance)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
}

export { VIX_REGIMES };
