import { store, toggleTradeLog } from '../../store.js';
import { getVar } from '../../utils/chartHelpers.js';

export function renderPnLStrip() {
  const { tradeLogOpen } = store;
  return `
    <div class="pnl-strip" id="pnl-strip-el">
      <span class="pnl-strip-lbl">P&L</span>
      <svg id="svg-pnl" style="flex:1;height:38px;" preserveAspectRatio="none"></svg>
      <div class="pnl-strip-actions">
        <span class="pnl-expand-hint" id="tl-hint">${tradeLogOpen ? '▼ CLOSE' : '▲ TRADE LOG'}</span>
      </div>
    </div>
  `;
}

let bound = false;
export function initPnLStrip() {
  if (bound) return;
  bound = true;
  document.addEventListener('click', (e) => {
    if (e.target.closest('#pnl-strip-el')) toggleTradeLog();
  });
  window.addEventListener('resize', drawPnL);
}

export function drawPnL() {
  const svg = document.getElementById('svg-pnl');
  if (!svg) return;
  const w = svg.clientWidth, h = 38;
  const { results } = store;

  const pos = getVar('--pos') || '#b8bb26';
  const neg = getVar('--neg') || '#fb4934';
  const a3  = getVar('--a3') || '#b16286';
  const a2  = getVar('--a2') || '#458588';
  const a1  = getVar('--a1') || '#d79921';
  const bg3 = getVar('--bg3') || '#3c3836';

  const colors = { PROFIT: pos, ROLLED: a3, '21DTE': a2, STOP: neg, EXPIRY: a1 };

  const N = 60;
  const pnls = [], types = [];

  if (!results) {
    // No data — render empty baseline
    svg.innerHTML = `<line x1="0" y1="${h * 0.52}" x2="${svg.clientWidth}" y2="${h * 0.52}" stroke="${bg3}" stroke-width="0.5"/>`;
    return;
  }

  results.trades.slice(-N).forEach(t => {
    pnls.push(t.pnl || 0);
    types.push(t.exit_type || 'PROFIT');
  });

  const maxAbs = Math.max(...pnls.map(Math.abs), 1);
  const mid = h * 0.52;
  const bw = Math.max(2, (w / (pnls.length || 1)) - 1);

  let bars = `<line x1="0" y1="${mid}" x2="${w}" y2="${mid}" stroke="${bg3}" stroke-width="0.5"/>`;
  pnls.forEach((v, i) => {
    const x = i * (w / pnls.length);
    const bh = Math.abs(v) / maxAbs * (h * 0.46);
    const y = v >= 0 ? mid - bh : mid;
    bars += `<rect x="${x}" y="${y}" width="${bw}" height="${bh}" fill="${colors[types[i]] || pos}" opacity="0.85"/>`;
  });
  svg.innerHTML = bars;
}
