import { store, toggleTradeLog } from '../../store.js';
import { getVar } from '../../utils/chartHelpers.js';
import { currencySymbol } from '../../utils/format.js';

export function renderPnLStrip() {
  const { tradeLogOpen } = store;
  return `
    <div class="pnl-strip" id="pnl-strip-el">
      <span class="pnl-strip-lbl">P&L</span>
      <div class="pnl-chart-wrap" id="pnl-chart-wrap">
        <svg id="svg-pnl" width="100%" height="100%" preserveAspectRatio="none"></svg>
        <div id="pnl-tip" class="pnl-tooltip" style="display:none"></div>
      </div>
      <div class="pnl-strip-actions">
        <span class="pnl-expand-hint" id="tl-hint">${tradeLogOpen ? '▼ CLOSE' : '▲ TRADE LOG'}</span>
      </div>
    </div>
  `;
}

// Bucket rects for hover hit-testing: [{x1, x2, date, pnl, trades: []}]
let _rects = [];
let _inStrip = false;

let bound = false;
export function initPnLStrip() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', (e) => {
    if (e.target.closest('#pnl-strip-el') && !e.target.closest('#pnl-tip')) toggleTradeLog();
  });
  window.addEventListener('resize', drawPnL);

  document.addEventListener('pointerover', (e) => {
    if (e.target.closest('#pnl-strip-el')) _inStrip = true;
  }, true);
  document.addEventListener('pointerout', (e) => {
    if (e.target.closest('#pnl-strip-el')) _inStrip = false;
  }, true);

  document.addEventListener('mousemove', (e) => {
    if (!_inStrip) return;
    const svg = document.getElementById('svg-pnl');
    const tip = document.getElementById('pnl-tip');
    if (!svg || !tip) return;
    const svgRect = svg.getBoundingClientRect();
    const inSvg = e.clientX >= svgRect.left && e.clientX <= svgRect.right &&
                  e.clientY >= svgRect.top  && e.clientY <= svgRect.bottom;
    if (!inSvg || !_rects.length) { tip.style.display = 'none'; return; }

    const mx  = e.clientX - svgRect.left;
    const hit = _rects.find(r => mx >= r.x1 && mx <= r.x2);
    if (!hit) { tip.style.display = 'none'; return; }

    const pnl  = hit.pnl;
    const sign = pnl >= 0 ? '+' : '−';
    const col  = pnl >= 0 ? 'var(--pos)' : 'var(--neg)';
    const sym  = currencySymbol(store.params.market);
    const trades = hit.trades;

    let tradeRows = '';
    if (trades.length > 0) {
      const top = trades.slice().sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 3);
      for (const t of top) {
        const s = t.pnl >= 0 ? '+' : '−';
        const c = t.pnl >= 0 ? 'var(--pos)' : 'var(--neg)';
        tradeRows += `<div class="ctt-row"><span style="color:var(--dim)">${t.exit_type || 'TRADE'}</span><span style="color:${c};font-weight:600">${s}${sym}${Math.abs(Math.round(t.pnl)).toLocaleString()}</span></div>`;
      }
      if (trades.length > 3) {
        tradeRows += `<div class="ctt-row"><span style="color:var(--dim)">+${trades.length - 3} more</span><span></span></div>`;
      }
    }

    tip.style.display = 'block';
    tip.innerHTML = `
      <div class="ctt-date">${hit.date}</div>
      <div class="ctt-row"><span style="color:var(--dim)">Net P&L</span><span style="color:${col};font-weight:600">${sign}${sym}${Math.abs(Math.round(pnl)).toLocaleString()}</span></div>
      <div class="ctt-row"><span style="color:var(--dim)">Trades</span><span>${trades.length}</span></div>
      ${tradeRows}
    `;

    const wrap = document.getElementById('pnl-chart-wrap');
    if (wrap) {
      const wRect = wrap.getBoundingClientRect();
      if (e.clientX - wRect.left > wRect.width / 2) {
        tip.style.left = '8px'; tip.style.right = 'auto';
      } else {
        tip.style.right = '8px'; tip.style.left = 'auto';
      }
    }
    tip.style.top = '4px';
  });

  document.addEventListener('mouseleave', (e) => {
    if (e.target.id === 'svg-pnl') {
      const tip = document.getElementById('pnl-tip');
      if (tip) tip.style.display = 'none';
    }
  }, true);
}

export function drawPnL() {
  const svg = document.getElementById('svg-pnl');
  if (!svg) return;

  const svgRect = svg.getBoundingClientRect();
  const w = svgRect.width;
  const h = svgRect.height;
  if (!w || !h) return;

  const { results } = store;
  _rects = [];

  const bg3  = getVar('--bg3') || '#3c3836';
  const dim  = getVar('--dim') || '#665c54';
  const fg4  = getVar('--fg4') || '#a89984';
  const pos  = getVar('--pos') || '#b8bb26';
  const neg  = getVar('--neg') || '#fb4934';
  const AXIS_H = 14;

  if (!results) {
    svg.innerHTML = `<line x1="0" y1="${(h - AXIS_H) / 2}" x2="${w}" y2="${(h - AXIS_H) / 2}" stroke="${bg3}" stroke-width="0.5"/>`;
    return;
  }

  // ── X-axis: use equity_curve dates (same domain as equity chart) ──
  const dates = Object.keys(results.equity_curve);
  if (!dates.length) return;

  // Bucket trades by calendar week (Mon–Sun) to get wider, visible bars
  const weekPnl = new Map();   // weekStartDate -> netPnl
  const weekTrades = new Map(); // weekStartDate -> [trades]

  function weekStart(d) {
    const date = new Date(d + 'T00:00:00Z');
    const day = date.getUTCDay(); // 0=Sun, 1=Mon...
    const diff = (day === 0 ? 6 : day - 1); // days since Monday
    date.setUTCDate(date.getUTCDate() - diff);
    return date.toISOString().slice(0, 10);
  }

  for (const t of results.trades) {
    if (t.exit_date == null || t.pnl == null) continue;
    const ws = weekStart(t.exit_date);
    weekPnl.set(ws, (weekPnl.get(ws) || 0) + t.pnl);
    if (!weekTrades.has(ws)) weekTrades.set(ws, []);
    weekTrades.get(ws).push(t);
  }

  // Only weeks with non-zero P&L
  const activeWeeks = [...weekPnl.entries()].filter(([, pnl]) => pnl !== 0);
  if (!activeWeeks.length) return;

  // Fixed padding — no uPlot bbox dependency
  const PAD_X = 10;
  const LEFT  = PAD_X;
  const RIGHT = PAD_X;
  const plotW = Math.max(10, w - LEFT - RIGHT);

  const plotH = h - AXIS_H;
  const PAD   = 3;
  const mid   = plotH / 2;
  const halfH = mid - PAD;
  const maxAbs = Math.max(...activeWeeks.map(([, pnl]) => Math.abs(pnl)), 1);

  // Compute x using same proportional mapping as equity chart (timestamp-based)
  const minMs = dateMs(dates[0]);
  const maxMs = dateMs(dates[dates.length - 1]);
  const span  = maxMs - minMs || 1;
  const toX = (ms) => LEFT + ((ms - minMs) / span) * plotW;

  // Bar width: span 5 days (Wed–next Tue) centered on week start, clamped to visible area
  const weekSpanMs = 5 * 24 * 60 * 60 * 1000; // visual width ~5 days

  let out = '';

  // Baseline
  out += `<line x1="${LEFT}" y1="${mid}" x2="${LEFT + plotW}" y2="${mid}" stroke="${bg3}" stroke-width="0.8"/>`;

  // Year separator lines + labels
  const minYear = new Date(minMs).getUTCFullYear();
  const maxYear = new Date(maxMs).getUTCFullYear();
  for (let y = minYear + 1; y <= maxYear; y++) {
    const x = toX(Date.UTC(y, 0, 1));
    if (x < LEFT || x > LEFT + plotW) continue;
    out += `<line x1="${x.toFixed(1)}" y1="0" x2="${x.toFixed(1)}" y2="${plotH}" stroke="${dim}" stroke-width="1" opacity="0.5"/>`;
    out += `<text x="${(x + 3).toFixed(1)}" y="${h - 2}" font-family="IBM Plex Mono,monospace" font-size="10" fill="${fg4}">${y}</text>`;
  }

  // Weekly aggregated bars
  for (const [ws, pnl] of activeWeeks) {
    const cx = toX(dateMs(ws));
    const bw = Math.max(6, Math.min(20, (weekSpanMs / span) * plotW));
    const x  = Math.max(LEFT, cx - bw / 2);
    const bh = Math.abs(pnl) / maxAbs * halfH;
    const y  = pnl >= 0 ? mid - bh : mid;
    const color = pnl >= 0 ? pos : neg;
    out += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${color}" opacity="0.75"/>`;
    _rects.push({ x1: x, x2: x + bw, date: ws, pnl, trades: weekTrades.get(ws) || [] });
  }

  svg.innerHTML = out;
}

function dateMs(dateStr) {
  return new Date(dateStr + 'T00:00:00Z').getTime();
}
