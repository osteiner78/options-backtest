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
        <div class="tp"><div class="tp-title">Trades Summary</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
        <div class="tp"><div class="tp-title">VIX Regime</div><div style="padding:10px;color:var(--dim)">Run backtest...</div></div>
      </div>
    `;
  }

  const { metrics, trades } = results;
  const totalN = trades.length;

  const exitData = results.exit_stats ?? computeExitStats(trades);
  const vixData  = results.vix_regime_stats ?? computeVixRegimeStats(trades);

  // Options-only total P&L = sum of individual exit rows (excludes cash yield)
  const optionsTotalPnl = exitData.reduce((sum, d) => sum + d.totalPnl, 0);

  const winRateClass = (wr) => wr >= 0.7 ? 'c-pos' : (wr >= 0.5 ? 'c-amb' : 'c-neg');

  const sub = (label) => `<div class="tp-sub">${label}</div>`;
  const row = (label, val, cls = '') => `
    <tr>
      <td style="color:var(--dim)">${label}</td>
      <td class="r fw6 ${cls}">${val}</td>
    </tr>`;

  const avgPos  = metrics.avg_positions  ? metrics.avg_positions.toFixed(1)  : '--';
  const peakPos = metrics.peak_positions || '--';
  const maxStrk = metrics.max_streak     || '--';
  const skipped = results.vix_blocked_dates ? results.vix_blocked_dates.length : 0;
  const avgBpr  = metrics.avg_bpr_util_pct  ? formatPct(metrics.avg_bpr_util_pct)  : '--';
  const peakBpr = metrics.peak_bpr_util_pct ? formatPct(metrics.peak_bpr_util_pct) : '--';

  return `
    <div class="tables-row">

      <!-- ── Left: Trades Summary (positions + BPR + exit breakdown) ── -->
      <div class="tp">
        <div class="tp-title">Trades Summary</div>

        ${sub('Positions')}
        <table class="dt">
          <tbody>
            ${row('Avg positions',        avgPos)}
            ${row('Peak positions',       peakPos,  'c-amb')}
            ${row('Max consec. losses',   maxStrk,  maxStrk !== '--' ? 'c-neg' : '')}
            ${row('Skipped (VIX filter)', skipped,  skipped > 0 ? 'c-neg' : '')}
          </tbody>
        </table>

        ${sub('BPR Utilization')}
        <table class="dt">
          <tbody>
            ${row('Avg BPR util',  avgBpr)}
            ${row('Peak BPR util', peakBpr, 'c-amb')}
          </tbody>
        </table>

        ${sub('Exit Breakdown')}
        <table class="dt">
          <thead><tr>
            <th>Type</th><th class="r">N</th><th class="r">%</th>
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
          </tbody>
        </table>
        <div style="font-size:7px;color:var(--dim);margin-top:4px;text-align:right;">TOTAL = Options P&L only (excl. cash yield)</div>
      </div>

      <!-- ── Right: VIX Regime ── -->
      <div class="tp">
        <div class="tp-title">VIX Regime</div>
        <table class="dt">
          <thead><tr>
            <th>Regime</th><th class="r">Range</th><th class="r">N</th>
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
        <div style="font-size:7px;color:var(--dim);margin-top:4px;text-align:right;">TOTAL = Options P&L only (excl. cash yield)</div>
      </div>

    </div>
  `;
}

export { VIX_REGIMES };
