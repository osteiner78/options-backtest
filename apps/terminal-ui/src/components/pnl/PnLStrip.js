import { store, toggleTradeLog } from '../../store.js';
import { getVar } from '../../utils/chartHelpers.js';
import { getPlotViewportRect } from '../charts/ChartArea.js';

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

// Trade rects for hover hit-testing: [{x1, x2, trade}]
let _rects = [];
// Flag set by pointer-enter/leave on the strip so the mousemove handler bails
// immediately for every cursor move that happens outside the P&L area.
let _inStrip = false;

let bound = false;
export function initPnLStrip() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', (e) => {
    if (e.target.closest('#pnl-strip-el') && !e.target.closest('#pnl-tip')) toggleTradeLog();
  });
  window.addEventListener('resize', drawPnL);

  // Track whether the cursor is inside the strip using capture-phase events so
  // we don't pay for getBoundingClientRect on every mousemove outside the strip.
  document.addEventListener('pointerover', (e) => {
    if (e.target.closest('#pnl-strip-el')) _inStrip = true;
  }, true);
  document.addEventListener('pointerout', (e) => {
    if (e.target.closest('#pnl-strip-el')) _inStrip = false;
  }, true);

  document.addEventListener('mousemove', (e) => {
    if (!_inStrip) return; // fast-exit for all cursor moves outside the strip
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

    const t    = hit.trade;
    const pnl  = t.pnl ?? 0;
    const sign = pnl >= 0 ? '+' : '−';
    const col  = pnl >= 0 ? 'var(--pos)' : 'var(--neg)';
    tip.style.display = 'block';
    tip.innerHTML = `
      <div class="ctt-date">${t.entry_date} → ${t.exit_date || '?'}</div>
      <div class="ctt-row"><span style="color:var(--dim)">Exit</span><span>${t.exit_type || '--'}</span></div>
      <div class="ctt-row"><span style="color:var(--dim)">P&L</span><span style="color:${col};font-weight:600">${sign}$${Math.abs(Math.round(pnl)).toLocaleString()}</span></div>
      ${t.net_credit != null ? `<div class="ctt-row"><span style="color:var(--dim)">Credit</span><span>$${Math.round(t.net_credit).toLocaleString()}</span></div>` : ''}
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

  // Use getBoundingClientRect for reliable dimensions (clientWidth/Height can be 0 for SVG)
  const svgRect = svg.getBoundingClientRect();
  const w = svgRect.width;
  const h = svgRect.height;
  if (!w || !h) return;

  const { results } = store;
  _rects = [];

  const bg3  = getVar('--bg3') || '#3c3836';
  const dim  = getVar('--dim') || '#665c54';
  const fg4  = getVar('--fg4') || '#a89984';
  const AXIS_H = 14; // px reserved at bottom for year labels

  if (!results) {
    svg.innerHTML = `<line x1="0" y1="${(h - AXIS_H) / 2}" x2="${w}" y2="${(h - AXIS_H) / 2}" stroke="${bg3}" stroke-width="0.5"/>`;
    return;
  }

  const pos = getVar('--pos') || '#b8bb26';
  const neg = getVar('--neg') || '#fb4934';
  const a3  = getVar('--a3') || '#b16286';
  const a2  = getVar('--a2') || '#458588';
  const a1  = getVar('--a1') || '#d79921';
  const colors = { PROFIT: pos, ROLLED: a3, '21DTE': a2, STOP: neg, EXPIRY: a1, FORCE_CLOSE: dim };

  // ── X-axis alignment: match equity chart plot area using viewport coordinates ──
  let LEFT, RIGHT, plotW;
  const plotRect = getPlotViewportRect();
  if (plotRect && plotRect.right > plotRect.left) {
    LEFT  = Math.max(0, plotRect.left  - svgRect.left);
    const rightEdge = Math.min(w, plotRect.right - svgRect.left);
    plotW = Math.max(10, rightEdge - LEFT);
    RIGHT = w - LEFT - plotW;
  } else {
    // Fallback: approximate y-axis width
    LEFT  = 50;
    RIGHT = 8;
    plotW = w - LEFT - RIGHT;
  }

  // ── Date range matches equity_curve (same as equity chart) ──
  const eqDates = Object.keys(results.equity_curve);
  const minMs   = dateMs(eqDates[0]);
  const maxMs   = dateMs(eqDates[eqDates.length - 1]);
  const span    = maxMs - minMs || 1;

  const toX = (ms) => LEFT + ((ms - minMs) / span) * plotW;

  const trades = results.trades.filter(t => t.exit_date && t.pnl != null);
  const maxAbs = Math.max(...trades.map(t => Math.abs(t.pnl)), 1);

  const plotH = h - AXIS_H;
  const PAD   = 3;
  const mid   = plotH / 2;
  const halfH = mid - PAD;

  // Uniform bar width: each trade gets a fair share of plot width, capped to avoid
  // bars that are too wide (long backtest, few trades) or too narrow (many trades).
  const bw = Math.max(2, Math.min(10, plotW / Math.max(trades.length, 1) * 0.75));

  let out = '';

  // Baseline
  out += `<line x1="${LEFT}" y1="${mid}" x2="${LEFT + plotW}" y2="${mid}" stroke="${bg3}" stroke-width="0.8"/>`;

  // Year separator lines + labels (same positions as equity chart)
  const minYear = new Date(minMs).getUTCFullYear();
  const maxYear = new Date(maxMs).getUTCFullYear();
  for (let y = minYear + 1; y <= maxYear; y++) {
    const x = toX(Date.UTC(y, 0, 1));
    if (x < LEFT || x > LEFT + plotW) continue;
    out += `<line x1="${x.toFixed(1)}" y1="0" x2="${x.toFixed(1)}" y2="${plotH}" stroke="${dim}" stroke-width="1" opacity="0.5"/>`;
    out += `<text x="${(x + 3).toFixed(1)}" y="${h - 2}" font-family="IBM Plex Mono,monospace" font-size="10" fill="${fg4}">${y}</text>`;
  }

  // Trade bars: each bar centered on its EXIT date, uniform width.
  // Using exit date avoids variable widths (entry→exit duration) and the
  // overlapping bars that occur in portfolio mode with concurrent positions.
  trades.forEach(t => {
    const cx  = toX(dateMs(t.exit_date));
    const x1  = Math.max(LEFT, cx - bw / 2);
    const x2  = Math.min(LEFT + plotW, cx + bw / 2);
    const bwi = Math.max(1.5, x2 - x1);
    const bh  = Math.abs(t.pnl) / maxAbs * halfH;
    const y   = t.pnl >= 0 ? mid - bh : mid;
    const color = colors[t.exit_type] || pos;
    out += `<rect x="${x1.toFixed(1)}" y="${y.toFixed(1)}" width="${bwi.toFixed(1)}" height="${bh.toFixed(1)}" fill="${color}" opacity="0.85"/>`;
    _rects.push({ x1, x2: x1 + bwi, trade: t });
  });

  svg.innerHTML = out;
}

function dateMs(dateStr) {
  return new Date(dateStr + 'T00:00:00Z').getTime();
}
