import uPlot from 'uplot';
import { store, setActiveTab } from '../../store.js';

let chart = null;
let mountEl = null;

/**
 * Returns the chart plot-area edges in *viewport* CSS pixel coordinates.
 * uPlot stores bbox in device pixels, so we divide by devicePixelRatio.
 * PnLStrip uses this to pixel-align its SVG bars with the equity chart x-axis.
 */
export function getPlotViewportRect() {
  if (!chart || !mountEl || !chart.bbox) return null;
  const dpr  = window.devicePixelRatio || 1;
  const rect = mountEl.getBoundingClientRect();
  return {
    left:  rect.left + chart.bbox.left               / dpr,
    right: rect.left + (chart.bbox.left + chart.bbox.width)  / dpr,
  };
}

const legends = {
  equity:    `<div class="leg-item"><div class="leg-rect" style="background:var(--pos)"></div>Portfolio P&L ($)</div><div class="leg-item"><div class="leg-line" style="background:var(--a2);opacity:0.8"></div>SPY B&H P&L ($)</div><div class="leg-item"><div class="leg-rect" style="background:var(--neg);opacity:0.7"></div>Drawdown ($)</div>`,
  bpr:       `<div class="leg-item"><div class="leg-rect" style="background:var(--a2)"></div>Utilized BPR ($)</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.6;border-top:2px dashed var(--neg)"></div>BPR Cap</div>`,
  positions: `<div class="leg-item"><div class="leg-line" style="background:var(--a4)"></div>Open Positions</div>`,
  vix:       `<div class="leg-item" style="gap:5px;"><div style="width:10px;height:10px;border-radius:50%;background:var(--a2)"></div>Entry</div><div class="leg-item" style="gap:5px;"><div style="width:10px;height:10px;border-radius:50%;border:1.5px solid var(--neg);background:transparent"></div>Skipped</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.7"></div>VIX Max</div><div class="leg-sep"></div><div class="leg-item" style="gap:4px;"><div style="width:8px;height:8px;background:var(--a2);opacity:0.5"></div><span style="font-size:9.5px">LOW &lt;15</span></div><div class="leg-item" style="gap:4px;"><div style="width:8px;height:8px;background:var(--a1);opacity:0.5"></div><span style="font-size:9.5px">NORMAL 15–25</span></div><div class="leg-item" style="gap:4px;"><div style="width:8px;height:8px;background:var(--a3);opacity:0.5"></div><span style="font-size:9.5px">ELEVATED 25–35</span></div><div class="leg-item" style="gap:4px;"><div style="width:8px;height:8px;background:var(--neg);opacity:0.5"></div><span style="font-size:9.5px">HIGH &gt;35</span></div>`,
  pnl:       `<div class="leg-item"><div class="leg-rect" style="background:var(--pos)"></div>Strangles</div><div class="leg-item"><div class="leg-rect" style="background:var(--a2)"></div>SPY Cash</div><div class="leg-item"><div class="leg-rect" style="background:var(--a3)"></div>Risk-Free Cash</div><span style="font-size:9px;color:var(--dim);margin-left:4px">· SPY/RF split is approximate</span>`,
};

export function renderChartArea() {
  const { activeTab, results } = store;
  const portfolioOnly = activeTab === 'bpr' || activeTab === 'positions';
  const disabled = portfolioOnly && results && !results.has_portfolio_curves;

  const tab = (key, label) => `<div class="chart-tab ${activeTab === key ? 'active' : ''}" data-tab="${key}">${label}</div>`;

  return `
    <div class="chart-tabs">
      ${tab('equity', 'EQUITY')}
      ${tab('bpr', 'BPR UTIL')}
      ${tab('positions', 'POSITIONS')}
      ${tab('vix', 'VIX')}
      ${tab('pnl', 'CUM P&L')}
      <div class="tab-spacer"></div>
      <div class="chart-legend">${legends[activeTab] || ''}</div>
    </div>
    <div class="chart-area" id="chart-area-container">
      <div class="chart-panel active">
        <div class="chart-wrap" id="chart-mount">
          ${disabled ? `<div class="chart-empty">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</div>` : ''}
        </div>
      </div>
    </div>
  `;
}

let bound = false;

export function initChartArea() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', (e) => {
    const t = e.target.closest('.chart-tab');
    if (t && t.dataset.tab) setActiveTab(t.dataset.tab);
  });

  window.addEventListener('resize', () => {
    if (chart && mountEl) chart.setSize({ width: mountEl.clientWidth, height: mountEl.clientHeight });
  });
}

function getColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function tsFromDate(d) {
  return Math.floor(new Date(d).getTime() / 1000);
}

function destroyChart() {
  if (chart) { try { chart.destroy(); } catch (e) { /* ignored */ } chart = null; }
}

function makeTip(el) {
  const tip = document.createElement('div');
  tip.className = 'chart-tooltip';
  tip.style.display = 'none';
  el.appendChild(tip);
  return tip;
}

function positionTip(tip, u, html) {
  const { left, idx } = u.cursor;
  if (idx == null || left == null || left < 0) { tip.style.display = 'none'; return; }
  tip.style.display = 'block';
  tip.innerHTML = html;
  // Anchor to top corner opposite the cursor so it never covers the cursor area
  if (left > u.width / 2) {
    tip.style.left  = '8px';
    tip.style.right = 'auto';
  } else {
    tip.style.right = '8px';
    tip.style.left  = 'auto';
  }
  tip.style.top = '8px';
}

function fmtDate(ts) {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function fmtPnl(v) {
  if (v == null) return '--';
  return (v >= 0 ? '+' : '−') + '$' + Math.abs(Math.round(v)).toLocaleString();
}

// ── Year separator lines on every chart ──
function drawYearSeps(u) {
  const ctx = u.ctx;
  const dim = getColor('--dim');
  const [minX, maxX] = [u.scales.x.min, u.scales.x.max];
  if (!minX || !maxX) return;
  const minYear = new Date(minX * 1000).getUTCFullYear();
  const maxYear = new Date(maxX * 1000).getUTCFullYear();
  ctx.save();
  ctx.strokeStyle = dim + 'cc';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([]);
  for (let y = minYear + 1; y <= maxYear; y++) {
    const ts = Date.UTC(y, 0, 1) / 1000;
    const x = u.valToPos(ts, 'x', true);
    if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
    ctx.beginPath();
    ctx.moveTo(x, u.bbox.top);
    ctx.lineTo(x, u.bbox.top + u.bbox.height);
    ctx.stroke();
  }
  ctx.restore();
}

// ── VIX regime background fills and separator lines ──
function drawVixRegimes(u) {
  const ctx = u.ctx;
  const a2  = getColor('--a2');
  const a1  = getColor('--a1');
  const a3  = getColor('--a3');
  const neg = getColor('--neg');

  // Background fills (very subtle)
  const fills = [
    { lo: 0,  hi: 15,  color: a2  + '14' },
    { lo: 15, hi: 25,  color: a1  + '12' },
    { lo: 25, hi: 35,  color: a3  + '14' },
    { lo: 35, hi: 100, color: neg + '16' },
  ];
  ctx.save();
  for (const { lo, hi, color } of fills) {
    const yLo = u.valToPos(lo, 'y', true);
    const yHi = u.valToPos(hi, 'y', true);
    if (yLo == null || yHi == null) continue;
    const top    = Math.min(yLo, yHi);
    const bottom = Math.max(yLo, yHi);
    ctx.fillStyle = color;
    ctx.fillRect(u.bbox.left, top, u.bbox.width, bottom - top);
  }

  // Separator lines with labels
  const lines = [
    { val: 15, color: a1  + '99', label: 'NORMAL'   },
    { val: 25, color: a3  + '99', label: 'ELEVATED'  },
    { val: 35, color: neg + '99', label: 'HIGH'      },
  ];
  ctx.setLineDash([4, 6]);
  ctx.lineWidth = 1;
  ctx.font = `500 9px "IBM Plex Mono", monospace`;
  ctx.textBaseline = 'bottom';
  for (const { val, color, label } of lines) {
    const y = u.valToPos(val, 'y', true);
    if (y == null || Number.isNaN(y)) continue;
    ctx.strokeStyle = color;
    ctx.fillStyle   = color;
    ctx.beginPath();
    ctx.moveTo(u.bbox.left, y);
    ctx.lineTo(u.bbox.left + u.bbox.width, y);
    ctx.stroke();
    ctx.fillText(label, u.bbox.left + u.bbox.width - 62, y - 2);
  }
  ctx.restore();
}

export function drawChart() {
  destroyChart();
  mountEl = document.getElementById('chart-mount');
  if (!mountEl) return;

  const { activeTab, results, params } = store;
  if (!results) {
    mountEl.innerHTML = `<div class="chart-empty">RUN BACKTEST TO GENERATE CHARTS</div>`;
    return;
  }

  const w = mountEl.clientWidth;
  const h = mountEl.clientHeight;
  if (!w || !h) return;
  mountEl.innerHTML = '';

  if (activeTab === 'equity') {
    const dates = Object.keys(results.equity_curve);
    const eq    = Object.values(results.equity_curve);
    const spy   = results.spy_curve ? Object.values(results.spy_curve) : eq.map(() => null);
    const ts    = dates.map(tsFromDate);
    const init  = results.metrics.initial_balance;

    // Convert to P&L ($) relative to initial_balance
    const eq_pnl  = eq.map(v => v - init);
    const spy_pnl = spy.map(v => v != null ? v - init : null);

    // Drawdown in dollars: current equity minus running peak
    const peak = [eq[0]];
    for (let i = 1; i < eq.length; i++) peak.push(Math.max(peak[i - 1], eq[i]));
    const dd_dollars = eq.map((v, i) => v - peak[i]);  // always <= 0

    const tip = makeTip(mountEl);
    chart = new uPlot(
      {
        ...equityOpts(w, h),
        hooks: {
          setCursor: [(u) => {
            const i = u.cursor.idx;
            positionTip(tip, u, `
              <div class="ctt-date">${fmtDate(ts[i])}</div>
              <div class="ctt-row"><span style="color:var(--pos)">Portfolio P&L</span><span>${fmtPnl(eq_pnl[i])}</span></div>
              <div class="ctt-row"><span style="color:var(--a2)">SPY B&H P&L</span><span>${spy_pnl[i] != null ? fmtPnl(spy_pnl[i]) : '--'}</span></div>
              <div class="ctt-row"><span style="color:var(--neg)">Drawdown</span><span>${fmtPnl(dd_dollars[i])} · ${((dd_dollars[i] / (peak[i] || 1)) * 100).toFixed(1)}%</span></div>
            `);
          }],
          draw: [drawYearSeps],
        },
      },
      [ts, eq_pnl, spy_pnl, dd_dollars],
      mountEl,
    );
    mountEl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

  } else if (activeTab === 'bpr') {
    if (!results.has_portfolio_curves) {
      mountEl.innerHTML = `<div class="chart-empty">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</div>`;
      return;
    }
    const dates   = Object.keys(results.bpr_curve);
    const ts      = dates.map(tsFromDate);
    const bpr     = Object.values(results.bpr_curve);
    const capVal  = params.max_bpr_allocation * params.initial_balance;
    const capArr  = bpr.map(() => capVal);
    const initial = params.initial_balance;
    const tip = makeTip(mountEl);
    chart = new uPlot(
      {
        ...bprOpts(w, h, capVal, initial),
        hooks: {
          setCursor: [(u) => positionTip(tip, u, `
            <div class="ctt-date">${fmtDate(ts[u.cursor.idx])}</div>
            <div class="ctt-row"><span style="color:var(--a2)">Utilized BPR</span><span>$${Math.round(bpr[u.cursor.idx]).toLocaleString()} · ${(bpr[u.cursor.idx] / initial * 100).toFixed(1)}%</span></div>
            <div class="ctt-row"><span style="color:var(--neg)">Cap</span><span>$${Math.round(capVal).toLocaleString()} · ${(capVal / initial * 100).toFixed(1)}%</span></div>
          `)],
          draw: [drawYearSeps],
        },
      },
      [ts, bpr, capArr],
      mountEl,
    );
    mountEl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

  } else if (activeTab === 'positions') {
    if (!results.has_portfolio_curves) {
      mountEl.innerHTML = `<div class="chart-empty">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</div>`;
      return;
    }
    const dates = Object.keys(results.pos_count_curve);
    const ts    = dates.map(tsFromDate);
    const pos   = Object.values(results.pos_count_curve);
    const tip = makeTip(mountEl);
    chart = new uPlot(
      {
        ...positionsOpts(w, h),
        hooks: {
          setCursor: [(u) => positionTip(tip, u, `
            <div class="ctt-date">${fmtDate(ts[u.cursor.idx])}</div>
            <div class="ctt-row"><span style="color:var(--a4)">Open positions</span><span>${pos[u.cursor.idx]}</span></div>
          `)],
          draw: [drawYearSeps],
        },
      },
      [ts, pos],
      mountEl,
    );
    mountEl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

  } else if (activeTab === 'vix') {
    const dates   = Object.keys(results.vix_curve);
    const ts      = dates.map(tsFromDate);
    const vix     = Object.values(results.vix_curve);
    const idx     = new Map(dates.map((d, i) => [d, i]));
    const entries = new Array(dates.length).fill(null);
    results.trades.forEach(t => {
      const i = idx.get(t.entry_date);
      if (i != null) entries[i] = t.entry_vix;
    });
    const skipped = new Array(dates.length).fill(null);
    (results.vix_blocked_dates || []).forEach(d => {
      const i = idx.get(d);
      if (i != null) skipped[i] = vix[i];
    });
    const tip = makeTip(mountEl);
    const vixMax = params.vix_entry_max;
    const neg    = getColor('--neg');
    chart = new uPlot(
      {
        ...vixOpts(w, h),
        hooks: {
          setCursor: [(u) => {
            const i = u.cursor.idx;
            positionTip(tip, u, `
              <div class="ctt-date">${fmtDate(ts[i])}</div>
              <div class="ctt-row"><span style="color:var(--fg4)">VIX</span><span>${vix[i] != null ? vix[i].toFixed(1) : '--'}</span></div>
              ${entries[i] != null ? `<div class="ctt-row"><span style="color:var(--a2)">Entry</span><span>${entries[i].toFixed(1)}</span></div>` : ''}
              ${skipped[i] != null ? `<div class="ctt-row"><span style="color:var(--neg)">Skipped</span><span>${skipped[i].toFixed(1)}</span></div>` : ''}
            `);
          }],
          draw: [
            drawVixRegimes,
            (u) => drawHLine(u, vixMax, neg, `VIX MAX ${vixMax}`),
            drawYearSeps,
          ],
        },
      },
      [ts, vix, entries, skipped],
      mountEl,
    );
    mountEl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

  } else if (activeTab === 'pnl') {
    const dates   = Object.keys(results.equity_curve);
    const ts      = dates.map(tsFromDate);
    const initial = results.metrics.initial_balance;

    const cum_total = Object.values(results.equity_curve).map(v => v - initial);

    const dailyOptPnl = {};
    results.trades.forEach(t => {
      if (t.exit_date && t.pnl != null) {
        dailyOptPnl[t.exit_date] = (dailyOptPnl[t.exit_date] || 0) + t.pnl;
      }
    });
    let optRunning = 0;
    const cum_options = dates.map(d => { optRunning += (dailyOptPnl[d] || 0); return optRunning; });

    const cum_cash = cum_total.map((v, i) => v - cum_options[i]);
    const cashMode = (params.cash_investment_mode || 'spy').toLowerCase();
    const spyPct   = cashMode === 'spy' ? 1.0 : cashMode === 'risk_free' ? 0.0 : (params.spy_allocation_pct || 0.5);
    const cum_rf   = cum_cash.map(v => v * (1 - spyPct));
    const cum_spy  = cum_cash.map(v => v * spyPct);

    const zeros     = dates.map(() => 0);
    const stack_rf  = cum_rf;
    const stack_spy = cum_rf.map((v, i) => v + cum_spy[i]);
    const dimColor  = getColor('--dim');

    const tip = makeTip(mountEl);
    chart = new uPlot(
      {
        ...pnlOpts(w, h),
        hooks: {
          setCursor: [(u) => {
            const i = u.cursor.idx;
            positionTip(tip, u, `
              <div class="ctt-date">${fmtDate(ts[i])}</div>
              <div class="ctt-row"><span style="color:var(--fg3)">Total P&L</span><span>${fmtPnl(cum_total[i])}</span></div>
              <div class="ctt-row"><span style="color:var(--pos)">Strangles</span><span>${fmtPnl(cum_options[i])}</span></div>
              ${spyPct > 0 ? `<div class="ctt-row"><span style="color:var(--a2)">SPY Cash</span><span>${fmtPnl(cum_spy[i])}</span></div>` : ''}
              ${spyPct < 1 ? `<div class="ctt-row"><span style="color:var(--a3)">Risk-Free</span><span>${fmtPnl(cum_rf[i])}</span></div>` : ''}
            `);
          }],
          draw: [
            (u) => drawHLine(u, 0, dimColor, ''),
            drawYearSeps,
          ],
        },
      },
      [ts, zeros, stack_rf, stack_spy, cum_total],
      mountEl,
    );
    mountEl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
  }
}

/* ────────── uPlot option builders ────────── */

const AXIS_FONT = '10px "IBM Plex Mono", monospace';

function baseAxes() {
  const dim = getColor('--dim');
  const bg3 = getColor('--bg3');
  return {
    axes: [
      { stroke: dim, font: AXIS_FONT, grid: { stroke: bg3, width: 0.5, dash: [2, 4] }, ticks: { stroke: bg3, width: 0.5 } },
      { stroke: dim, font: AXIS_FONT, grid: { stroke: bg3, width: 0.5, dash: [2, 4] }, ticks: { stroke: bg3, width: 0.5 } },
    ],
    cursor: {
      drag: { x: false, y: false },  // TODO: zoom-to-select — uPlot mouseup never fires setScale in this build; investigate and re-enable
      points: { size: 6, stroke: getColor('--a1'), fill: getColor('--bg0'), width: 2 },
    },
    legend: { show: false },
  };
}

function equityOpts(w, h) {
  const base = baseAxes();
  const pos = getColor('--pos');
  const a2  = getColor('--a2');
  const neg = getColor('--neg');
  const dim = getColor('--dim');
  const bg3 = getColor('--bg3');
  return {
    width: w, height: h, ...base,
    axes: [
      base.axes[0],
      {
        ...base.axes[1],
        values: (_, splits) => splits.map(v => (v >= 0 ? '+' : '') + '$' + Math.round(Math.abs(v) / 1000) + 'k'),
      },
    ],
    scales: {
      // Allow negative values (drawdown goes below zero)
      y: { range: (u, dmin, dmax) => [Math.min(dmin, 0), dmax] },
    },
    series: [
      { label: 'Date' },
      { label: 'Portfolio P&L', stroke: pos, width: 2, fill: pos + '30' },
      { label: 'SPY B&H P&L',   stroke: a2,  width: 1.5, dash: [6, 4] },
      { label: 'Drawdown $',    stroke: neg, width: 1.5, fill: neg + '35' },
    ],
  };
}

function bprOpts(w, h, capVal, initial) {
  const base = baseAxes();
  const a2   = getColor('--a2');
  const neg  = getColor('--neg');
  const dim  = getColor('--dim');
  return {
    width: w, height: h, ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => '$' + Math.round(v / 1000) + 'k') },
      // Secondary right axis: % of initial balance
      {
        scale: 'y', side: 1, size: 52,
        stroke: dim, font: AXIS_FONT,
        grid: { show: false }, ticks: { show: false },
        values: (_, splits) => splits.map(v => (v / initial * 100).toFixed(0) + '%'),
      },
    ],
    scales: {
      y: { range: (u, dmin, dmax) => [0, Math.max(dmax, capVal * 1.05)] },
    },
    series: [
      { label: 'Date' },
      { label: 'BPR',     stroke: a2,  width: 2,   fill: a2  + '33' },
      { label: 'BPR Cap', stroke: neg, width: 1.5,  dash: [8, 5] },
    ],
  };
}

function positionsOpts(w, h) {
  const base = baseAxes();
  const a4   = getColor('--a4');
  return {
    width: w, height: h, ...base,
    axes: [
      base.axes[0],
      {
        ...base.axes[1],
        // Fixed signature: (u, axisIdx, scaleMin, scaleMax, ...)
        splits: (u, _, scaleMin, scaleMax) => {
          const lo = Math.ceil(scaleMin), hi = Math.floor(scaleMax);
          const arr = [];
          for (let i = lo; i <= hi; i++) arr.push(i);
          return arr.length ? arr : [0];
        },
        values: (_, splits) => splits.map(v => String(Math.round(v))),
      },
    ],
    scales: {
      y: { range: (u, dmin, dmax) => [0, Math.max(dmax + 1, 2)] },
    },
    series: [{ label: 'Date' }, { label: 'Open', stroke: a4, width: 2, paths: uPlot.paths.stepped({ align: 1 }) }],
  };
}

function vixOpts(w, h) {
  const base = baseAxes();
  const fg4  = getColor('--fg4');
  const a2   = getColor('--a2');
  const neg  = getColor('--neg');
  const bg3  = getColor('--bg3');
  return {
    width: w, height: h, ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => v.toFixed(0)) },
    ],
    scales: { y: { range: (u, dmin, dmax) => [0, Math.max(dmax, 40)] } },
    series: [
      { label: 'Date' },
      { label: 'VIX',     stroke: fg4, width: 1.5 },
      { label: 'Entry',   stroke: a2,  fill: a2,  width: 0, paths: () => null, points: { show: true, size: 10, stroke: bg3, fill: a2,           width: 1 } },
      { label: 'Skipped', stroke: neg,             width: 0, paths: () => null, points: { show: true, size: 11, stroke: neg, fill: 'transparent', width: 2 } },
    ],
  };
}

function pnlOpts(w, h) {
  const base = baseAxes();
  const pos  = getColor('--pos');
  const a2   = getColor('--a2');
  const a3   = getColor('--a3');
  return {
    width: w, height: h, ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => (v >= 0 ? '+$' : '-$') + Math.round(Math.abs(v) / 1000) + 'k') },
    ],
    scales: { y: { range: (u, dmin, dmax) => [Math.min(dmin, 0), dmax] } },
    series: [
      {},
      { stroke: 'transparent', fill: 'transparent', width: 0 },
      { label: 'RF',      stroke: a3 + 'aa', width: 1, fill: a3 + '55' },
      { label: 'SPY',     stroke: a2 + 'aa', width: 1, fill: a2 + '55' },
      { label: 'Options', stroke: pos,        width: 2, fill: pos + '44' },
    ],
    bands: [
      { series: [1, 2], fill: a3 + '55' },
      { series: [2, 3], fill: a2 + '55' },
      { series: [3, 4], fill: pos + '44' },
    ],
  };
}

function drawHLine(u, yVal, color, label) {
  const ctx = u.ctx;
  const y = u.valToPos(yVal, 'y', true);
  if (y == null || Number.isNaN(y)) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.setLineDash([8, 5]);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(u.bbox.left, y);
  ctx.lineTo(u.bbox.left + u.bbox.width, y);
  ctx.stroke();
  ctx.setLineDash([]);
  if (label) {
    ctx.fillStyle = color;
    ctx.font = `600 13px "IBM Plex Mono", monospace`;
    ctx.textBaseline = 'bottom';
    ctx.fillText(label, u.bbox.left + 8, y - 2);
  }
  ctx.restore();
}
