import { store } from '../../store.js';
import { formatPct, formatNum, formatSignedPct, formatCurrency } from '../../utils/format.js';

export function renderPerformanceBar() {
  const { results } = store;
  if (!results) {
    return `
      <div class="perf-bar">
        <div class="perf-bar-label">PERFORMANCE</div>
        <div style="padding:10px;font-size:11px;color:var(--dim)">Run backtest to see performance data...</div>
      </div>
    `;
  }

  const { metrics } = results;

  return `
    <div class="perf-bar">
      <div class="perf-bar-label">PERFORMANCE</div>
      <table class="perf-table">
        <thead><tr>
          <th style="min-width:140px"></th>
          <th class="r">Total Ret</th><th class="r">Annual Return</th><th class="r">Sharpe</th>
          <th class="r">Max DD</th><th class="r">Calmar</th><th class="r">Final Bal</th><th class="r">Trades</th>
          <th class="r">Win Rate</th><th class="r">Avg P&L</th>
        </tr></thead>
        <tbody>
          <tr class="pt-port">
            <td class="ptl c-amb fw6">PORTFOLIO</td>
            <td class="r c-pos fw6">${formatSignedPct(metrics.total_return)}</td>
            <td class="r c-pos fw6">${formatPct(metrics.annualized_return)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.sharpe)}</td>
            <td class="r c-neg fw6">${formatPct(metrics.max_drawdown)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.calmar)}</td>
            <td class="r c-pos fw6">${formatCurrency(metrics.final_balance)}</td>
            <td class="r fw6">${metrics.n_trades}</td>
            <td class="r c-blue fw6">${formatPct(metrics.win_rate)}</td>
            <td class="r c-pos fw6">+${formatCurrency(metrics.avg_pnl)}</td>
          </tr>
          <tr class="pt-sub">
            <td class="ptl">  o/w options</td>
            <td class="r">${formatPct(metrics.ret_options)}</td>
            <td class="r">${formatPct(metrics.cagr_options)}</td>
            <td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td>
          </tr>
          <tr class="pt-sub">
            <td class="ptl">  o/w SPY cash</td>
            <td class="r">${formatPct(metrics.ret_cash_spy)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_spy)}</td>
            <td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td>
          </tr>
          <tr class="pt-sub">
            <td class="ptl">  o/w risk-free</td>
            <td class="r">${formatPct(metrics.ret_cash_rf)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_rf)}</td>
            <td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td><td class="r">--</td>
          </tr>
          <tr class="pt-spy">
            <td class="ptl c-blue fw6">SPY B&amp;H</td>
            <td class="r c-blue fw6">${formatSignedPct(metrics.spy_total_return)}</td>
            <td class="r c-blue fw6">${formatPct(metrics.spy_annualized_return)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.spy_sharpe)}</td>
            <td class="r c-neg fw6">${formatPct(metrics.spy_max_drawdown)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.spy_calmar)}</td>
            <td class="r c-blue fw6">${formatCurrency(metrics.initial_balance * (1 + metrics.spy_total_return))}</td>
            <td class="r c-dim">--</td><td class="r c-dim">--</td><td class="r c-dim">--</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}
