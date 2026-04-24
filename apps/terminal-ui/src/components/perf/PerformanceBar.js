import { store } from '../../store.js';
import { formatPct, formatNum, formatSignedPct, formatPnl } from '../../utils/format.js';

// ── Client-side metric derivations for sub-components ──────────────────────

/**
 * Max drawdown of the cumulative options P&L curve, expressed as a fraction
 * of initial_balance (so it's on the same % scale as portfolio MaxDD).
 */
function computeOptionsMDD(trades, init) {
  const sorted = trades
    .filter(t => t.exit_date && t.pnl != null)
    .slice()
    .sort((a, b) => a.exit_date.localeCompare(b.exit_date));
  let cum = 0, peak = 0, maxDD = 0;
  for (const t of sorted) {
    cum  += t.pnl;
    peak  = Math.max(peak, cum);
    // Express as fraction of initial balance (same basis as portfolio MaxDD)
    if (peak > 0) maxDD = Math.max(maxDD, (peak - cum) / init);
  }
  return maxDD;
}

/**
 * Sharpe, MaxDD, and Calmar from a daily value series.
 * cagr should be the annualised return of the same series (pre-computed).
 * rfAnnual: annualised risk-free rate used as excess-return benchmark (default 0 for simplicity).
 */
function curveMetrics(values, cagr, rfAnnual = 0) {
  if (!values || values.length < 2) return { sharpe: null, mdd: null, calmar: null };
  const rets    = values.slice(1).map((v, i) => (v - values[i]) / (values[i] || 1));
  const rfDaily = rfAnnual / 252;
  const excess  = rets.map(r => r - rfDaily);
  const mean    = excess.reduce((s, r) => s + r, 0) / excess.length;
  const std     = Math.sqrt(excess.reduce((s, r) => s + (r - mean) ** 2, 0) / excess.length);
  const sharpe  = std > 1e-10 ? (mean / std) * Math.sqrt(252) : 0;

  let peak = values[0], mdd = 0;
  for (const v of values) {
    peak = Math.max(peak, v);
    mdd  = Math.max(mdd, (peak - v) / (peak || 1));
  }

  const calmar = mdd > 1e-10 ? cagr / mdd : 0;
  return { sharpe, mdd, calmar };
}

// ───────────────────────────────────────────────────────────────────────────

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

  const { metrics, trades } = results;
  const init = metrics.initial_balance;

  const portPnl = metrics.final_balance - init;
  const optPnl  = metrics.ret_options  * init;
  const spyPnl  = metrics.ret_cash_spy * init;
  const rfPnl   = metrics.ret_cash_rf  * init;

  // ── Options component: MaxDD and Calmar derived from cumulative trade P&L curve ──
  // computeOptionsMDD returns a POSITIVE fraction (magnitude of max drawdown).
  // We display it negative to match the convention used in all other rows.
  const optMDD    = computeOptionsMDD(trades, init);
  const optCalmar = optMDD > 1e-4 ? metrics.cagr_options / optMDD : null;

  // ── SPY component: same underlying returns as SPY B&H, different allocation size ──
  // Sharpe is scale-invariant → same as SPY B&H.
  // MaxDD % is the same underlying drawdown sequence → same as SPY B&H.
  // Calmar uses cagr_cash_spy (component CAGR, differs from SPY B&H CAGR).
  // spy_max_drawdown is NEGATIVE (standard convention), so use Math.abs for Calmar.
  const spySharpe  = metrics.spy_sharpe;
  const spyMDD     = metrics.spy_max_drawdown;  // negative fraction, e.g. -0.254
  const spyCalmar  = Math.abs(spyMDD) > 1e-4 ? metrics.cagr_cash_spy / Math.abs(spyMDD) : null;

  // ── Risk-free: monotonically increasing → MaxDD = 0, Sharpe ≈ 0, Calmar = ∞ ──
  // Not meaningful to display; leave as --

  const na = `<td class="r c-dim">--</td>`;

  return `
    <div class="perf-bar">
      <div class="perf-bar-label">PERFORMANCE</div>
      <table class="perf-table">
        <thead><tr>
          <th style="min-width:155px"></th>
          <th class="r">Total Return</th><th class="r">Annual Return</th><th class="r">Sharpe</th>
          <th class="r">Max DD</th><th class="r">Calmar</th><th class="r">Total P&L</th>
        </tr></thead>
        <tbody>
          <tr class="pt-port">
            <td class="ptl c-amb fw6">PORTFOLIO</td>
            <td class="r c-pos fw6">${formatSignedPct(metrics.total_return)}</td>
            <td class="r c-pos fw6">${formatPct(metrics.annualized_return)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.sharpe)}</td>
            <td class="r c-neg fw6">${formatPct(metrics.max_drawdown)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.calmar)}</td>
            <td class="r c-pos fw6">${formatPnl(portPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w short strangles</td>
            <td class="r">${formatSignedPct(metrics.ret_options)}</td>
            <td class="r">${formatPct(metrics.cagr_options)}</td>
            ${na}
            <td class="r c-neg">${optMDD > 0 ? formatPct(-optMDD) : '--'}</td>
            <td class="r c-amb">${optCalmar != null ? formatNum(optCalmar) : '--'}</td>
            <td class="r ${optPnl >= 0 ? 'c-pos' : 'c-neg'}">${formatPnl(optPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w SPY</td>
            <td class="r">${formatSignedPct(metrics.ret_cash_spy)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_spy)}</td>
            <td class="r c-amb">${formatNum(spySharpe)}</td>
            <td class="r c-neg">${formatPct(spyMDD)}</td>
            <td class="r c-amb">${spyCalmar != null ? formatNum(spyCalmar) : '--'}</td>
            <td class="r ${spyPnl >= 0 ? 'c-pos' : 'c-neg'}">${formatPnl(spyPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w risk-free</td>
            <td class="r">${formatSignedPct(metrics.ret_cash_rf)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_rf)}</td>
            ${na}${na}${na}
            <td class="r ${rfPnl >= 0 ? 'c-pos' : 'c-neg'}">${formatPnl(rfPnl)}</td>
          </tr>

          <tr class="pt-spy">
            <td class="ptl c-blue fw6">SPY B&amp;H</td>
            <td class="r c-blue fw6">${formatSignedPct(metrics.spy_total_return)}</td>
            <td class="r c-blue fw6">${formatPct(metrics.spy_annualized_return)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.spy_sharpe)}</td>
            <td class="r c-blue fw6">${formatPct(metrics.spy_max_drawdown)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.spy_calmar)}</td>
            <td class="r c-blue fw6">${formatPnl(init * metrics.spy_total_return)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}
