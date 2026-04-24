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
      <div class="tables-row">
        <div class="tp"><div class="tp-title">Exit Breakdown</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
        <div class="tp"><div class="tp-title">VIX Regime</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
      </div>
    `;
  }

  const { metrics, trades } = results;
  const totalN   = trades.length;
  const skipped  = results.vix_blocked_dates ? results.vix_blocked_dates.length : 0;

  const exitData = results.exit_stats ?? computeExitStats(trades);
  const vixData  = results.vix_regime_stats ?? computeVixRegimeStats(trades);

  // Options-only total P&L = sum of exit rows (excludes cash yield)
  const optionsTotalPnl = exitData.reduce((sum, d) => sum + d.totalPnl, 0);

  const winRateClass = (wr) => wr >= 0.7 ? 'c-pos' : (wr >= 0.5 ? 'c-amb' : 'c-neg');

  return `
    <div class="tables-row">

      <!-- ── Left: Exit Breakdown (with SKIPPED row) ── -->
      <div class="tp">
        <div class="tp-title">Exit Breakdown</div>
        <table class="dt">
          <thead><tr>
            <th>Type</th><th class="r">n</th><th class="r">%</th>
            <th class="r">Win%</th><th class="r">Avg P&L</th><th class="r">Total P&L</th>
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
              <td class="r c-pos">${formatPnl(optionsTotalPnl)}</td>
            </tr>
            <!-- SKIPPED row: below TOTAL, not included in % or P&L accounting -->
            <tr class="skipped-sep"><td colspan="6"></td></tr>
            <tr class="skipped-row">
              <td class="c-neg fw6" style="font-size:10px;letter-spacing:0.02em">SKIPPED · VIX</td>
              <td class="r c-neg">${skipped}</td>
              <td class="r c-dim">--</td>
              <td class="r c-dim">--</td>
              <td class="r c-dim">--</td>
              <td class="r c-dim">--</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── Right: VIX Regime ── -->
      <div class="tp">
        <div class="tp-title">VIX Regime</div>
        <table class="dt">
          <thead><tr>
            <th>Regime</th><th class="r">Range</th><th class="r">n</th>
            <th class="r">Win%</th><th class="r">Avg P&L</th><th class="r">Total P&L</th>
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
              <td class="r c-pos">${formatPnl(optionsTotalPnl)}</td>
            </tr>
          </tbody>
        </table>
      </div>

    </div>
  `;
}

export { VIX_REGIMES };
