import { store } from '../../store.js';
import { formatPct, formatNum, formatSignedPct, formatPnl, currencySymbol } from '../../utils/format.js';

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
  const { results, params } = store;
  const market = (params.market || 'spy').toUpperCase();
  const sym    = currencySymbol(params.market);
  const fp     = (v) => formatPnl(v, sym);
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
  const underlyingPnl = metrics.ret_cash_underlying * init;
  const rfPnl         = metrics.ret_cash_rf  * init;

  // ── Options component: MaxDD and Calmar derived from cumulative trade P&L curve ──
  // computeOptionsMDD returns a POSITIVE fraction (magnitude of max drawdown).
  // We display it negative to match the convention used in all other rows.
  const optMDD    = computeOptionsMDD(trades, init);
  const optCalmar = optMDD > 1e-4 ? metrics.cagr_options / optMDD : null;

  // ── Underlying component: same returns as B&H, different allocation size ──
  // Sharpe is scale-invariant → same as B&H.
  // MaxDD % is the same underlying drawdown sequence → same as B&H.
  // Calmar uses cagr_cash_underlying (component CAGR, differs from B&H CAGR).
  // underlying_max_drawdown is NEGATIVE (standard convention), so use Math.abs for Calmar.
  const underlyingSharpe = metrics.underlying_sharpe;
  const underlyingMDD    = metrics.underlying_max_drawdown;  // negative fraction
  const underlyingCalmar = Math.abs(underlyingMDD) > 1e-4 ? metrics.cagr_cash_underlying / Math.abs(underlyingMDD) : null;

  // ── Risk-free: monotonically increasing → MaxDD = 0, Sharpe ≈ 0, Calmar = ∞ ──
  // Not meaningful to display; leave as --

  const na = `<td class="r c-dim">--</td>`;

  return `
    <div class="perf-bar">
      <div class="perf-bar-label">PERFORMANCE</div>
      <table class="perf-table">
        <thead><tr>
          <th style="min-width:155px"></th>
          <th class="r">Total Return</th><th class="r">Annual Return</th>          <th class="r">Sharpe</th><th class="r">IR</th>
          <th class="r">Max DD</th><th class="r">Calmar</th><th class="r">Total P&L</th>
        </tr></thead>
        <tbody>
          <tr class="pt-port">
            <td class="ptl c-amb fw6">PORTFOLIO</td>
            <td class="r c-pos fw6">${formatSignedPct(metrics.total_return)}</td>
            <td class="r c-pos fw6">${formatPct(metrics.annualized_return)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.sharpe)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.info_ratio)}</td>
            <td class="r c-neg fw6">${formatPct(metrics.max_drawdown)}</td>
            <td class="r c-amb fw6">${formatNum(metrics.calmar)}</td>
            <td class="r c-pos fw6">${fp(portPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w short strangles</td>
            <td class="r">${formatSignedPct(metrics.ret_options)}</td>
            <td class="r">${formatPct(metrics.cagr_options)}</td>
            ${na}${na}
            <td class="r c-neg">${optMDD > 0 ? formatPct(-optMDD) : '--'}</td>
            <td class="r c-amb">${optCalmar != null ? formatNum(optCalmar) : '--'}</td>
            <td class="r ${optPnl >= 0 ? 'c-pos' : 'c-neg'}">${fp(optPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w ${market}</td>
            <td class="r">${formatSignedPct(metrics.ret_cash_underlying)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_underlying)}</td>
            <td class="r c-amb">${formatNum(underlyingSharpe)}</td>
            ${na}
            <td class="r c-neg">${formatPct(underlyingMDD)}</td>
            <td class="r c-amb">${underlyingCalmar != null ? formatNum(underlyingCalmar) : '--'}</td>
            <td class="r ${underlyingPnl >= 0 ? 'c-pos' : 'c-neg'}">${fp(underlyingPnl)}</td>
          </tr>

          <tr class="pt-sub">
            <td class="ptl">  o/w risk-free</td>
            <td class="r">${formatSignedPct(metrics.ret_cash_rf)}</td>
            <td class="r">${formatPct(metrics.cagr_cash_rf)}</td>
            ${na}${na}${na}${na}
            <td class="r ${rfPnl >= 0 ? 'c-pos' : 'c-neg'}">${fp(rfPnl)}</td>
          </tr>

          <tr class="pt-spy">
            <td class="ptl c-blue fw6">${market} B&amp;H</td>
            <td class="r c-blue fw6">${formatSignedPct(metrics.underlying_total_return)}</td>
            <td class="r c-blue fw6">${formatPct(metrics.underlying_annualized_return)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.underlying_sharpe)}</td>
            ${na}
            <td class="r c-blue fw6">${formatPct(metrics.underlying_max_drawdown)}</td>
            <td class="r c-blue fw6">${formatNum(metrics.underlying_calmar)}</td>
            <td class="r c-blue fw6">${fp(init * metrics.underlying_total_return)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
}
