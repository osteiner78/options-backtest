import { store, toggleTradeLog, setTradeLogFilter } from '../../store.js';
import { formatPnl, formatPct, formatNum } from '../../utils/format.js';

const EXIT_COLORS = {
  PROFIT: 'c-pos', ROLLED: 'c-pur', '21DTE': 'c-blue',
  STOP: 'c-neg', EXPIRY: 'c-amb', FORCE_CLOSE: 'c-dim',
};

const FILTERS = ['ALL', 'PROFIT', 'ROLLED', '21DTE', 'STOP', 'EXPIRY'];

function filterTrades(trades, filter) {
  if (filter === 'ALL') return trades;
  return trades.filter(t => t.exit_type === filter);
}

export function renderTradeLog() {
  const { results, tradeLogOpen, tradeLogFilter } = store;
  const allTrades = results ? results.trades : [];
  const trades = filterTrades(allTrades, tradeLogFilter);

  const chips = FILTERS.map(f => `
    <span class="tl-filter ${f === tradeLogFilter ? 'active' : ''}" data-filter="${f}">${f}</span>
  `).join('');

  return `
    <div class="trade-log-overlay ${tradeLogOpen ? 'open' : ''}" id="trade-log">
      <div class="tl-header">
        <span class="tl-title">Trade Log</span>
        ${chips}
        <span style="font-size:9px;color:var(--dim);margin-left:4px;">${trades.length} of ${allTrades.length} trades</span>
        <span class="tl-close" id="btn-tl-close">▼ CLOSE</span>
      </div>
      <div class="tl-body">
        <table class="tl-table">
          <thead><tr>
            <th>#</th><th>Entry</th><th>Expiry</th><th class="r">DTE</th><th class="r">VIX</th>
            <th class="r">Put K</th><th class="r">Call K</th><th class="r">Credit</th>
            <th>Exit Date</th><th>Type</th><th class="r">P&L $</th><th class="r">P&L %</th>
          </tr></thead>
          <tbody>
            ${trades.map(t => `
              <tr>
                <td>${t.trade_num}</td>
                <td>${t.entry_date}</td>
                <td>${t.expiration}</td>
                <td class="r">--</td>
                <td class="r">${formatNum(t.entry_vix, 1)}</td>
                <td class="r">${t.put_strike}</td>
                <td class="r">${t.call_strike}</td>
                <td class="r">$${formatNum(t.net_credit, 2)}</td>
                <td>${t.exit_date || '--'}</td>
                <td class="${EXIT_COLORS[t.exit_type] || ''} fw6">${t.exit_type || '--'}</td>
                <td class="r ${t.pnl >= 0 ? 'c-pos' : 'c-neg'}">${t.pnl != null ? formatPnl(t.pnl) : '--'}</td>
                <td class="r ${t.pnl_pct >= 0 ? 'c-pos' : 'c-neg'}">${t.pnl_pct != null ? formatPct(t.pnl_pct) : '--'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

let bound = false;
export function initTradeLog() {
  if (bound) return;
  bound = true;
  document.addEventListener('click', (e) => {
    if (e.target.id === 'btn-tl-close') {
      toggleTradeLog();
      return;
    }
    const filterEl = e.target.closest('#trade-log .tl-filter');
    if (filterEl && filterEl.dataset.filter) {
      setTradeLogFilter(filterEl.dataset.filter);
    }
  });
}
