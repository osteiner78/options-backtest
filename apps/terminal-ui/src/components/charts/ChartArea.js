import uPlot from 'uplot';
import { store, setActiveTab } from '../../store.js';

/**
 * Canvas-based time-series charts (uPlot).
 * Each tab rebuilds a single uPlot instance mounted in #chart-mount.
 * The full-tree innerHTML re-render in main.js wipes DOM, so we destroy
 * and recreate on every drawChart() call — cheap at this data scale.
 */

let chart = null;
let mountEl = null;

const legends = {
  equity:    `<div class="leg-item"><div class="leg-line" style="background:var(--pos)"></div>Portfolio</div><div class="leg-item"><div class="leg-line" style="background:var(--a2);opacity:0.8"></div>SPY B&H</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.7"></div>Drawdown %</div>`,
  bpr:       `<div class="leg-item"><div class="leg-line" style="background:var(--a2)"></div>Utilized BPR ($)</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.6"></div>BPR Cap</div>`,
  positions: `<div class="leg-item"><div class="leg-line" style="background:var(--a4)"></div>Open Positions</div>`,
  vix:       `<div class="leg-item" style="gap:5px;"><div style="width:8px;height:8px;border-radius:50%;background:var(--a2)"></div>Entry</div><div class="leg-item" style="gap:5px;"><div style="width:8px;height:8px;border-radius:50%;border:1.5px solid var(--neg);background:transparent"></div>Skipped</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.7"></div>VIX Max</div>`,
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
    if (!chart || !mountEl) return;
    chart.setSize({ width: mountEl.clientWidth, height: mountEl.clientHeight });
  });
}

function getColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function tsFromDate(d) {
  return Math.floor(new Date(d).getTime() / 1000);
}

function destroyChart() {
  if (chart) {
    try { chart.destroy(); } catch (e) { /* ignored */ }
    chart = null;
  }
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

  const width = mountEl.clientWidth;
  const height = mountEl.clientHeight;
  if (!width || !height) return;

  mountEl.innerHTML = '';

  if (activeTab === 'equity') {
    const dates = Object.keys(results.equity_curve);
    const eq = Object.values(results.equity_curve);
    const spy = results.spy_curve ? Object.values(results.spy_curve) : eq.map(() => null);
    const ts = dates.map(tsFromDate);
    const peak = [eq[0]];
    for (let i = 1; i < eq.length; i++) peak.push(Math.max(peak[i - 1], eq[i]));
    const dd = eq.map((v, i) => ((v - peak[i]) / (peak[i] || 1)) * 100);

    chart = new uPlot(
      equityOpts(width, height, params.initial_balance),
      [ts, eq, spy, dd],
      mountEl,
    );
  } else if (activeTab === 'bpr') {
    if (!results.has_portfolio_curves) {
      mountEl.innerHTML = `<div class="chart-empty">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</div>`;
      return;
    }
    const dates = Object.keys(results.bpr_curve);
    const ts = dates.map(tsFromDate);
    const bpr = Object.values(results.bpr_curve);
    const capVal = params.max_bpr_allocation * params.initial_balance;

    chart = new uPlot(
      bprOpts(width, height, capVal),
      [ts, bpr],
      mountEl,
    );
  } else if (activeTab === 'positions') {
    if (!results.has_portfolio_curves) {
      mountEl.innerHTML = `<div class="chart-empty">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</div>`;
      return;
    }
    const dates = Object.keys(results.pos_count_curve);
    const ts = dates.map(tsFromDate);
    const pos = Object.values(results.pos_count_curve);

    chart = new uPlot(
      positionsOpts(width, height),
      [ts, pos],
      mountEl,
    );
  } else if (activeTab === 'vix') {
    const dates = Object.keys(results.vix_curve);
    const ts = dates.map(tsFromDate);
    const vix = Object.values(results.vix_curve);
    const idx = new Map(dates.map((d, i) => [d, i]));

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

    chart = new uPlot(
      vixOpts(width, height, params.vix_entry_max),
      [ts, vix, entries, skipped],
      mountEl,
    );
  }
}

/* ────────── uPlot option builders ────────── */

function baseAxes() {
  const dim = getColor('--dim');
  const bg3 = getColor('--bg3');
  return {
    axes: [
      { stroke: dim, grid: { stroke: bg3, width: 0.5, dash: [2, 4] }, ticks: { stroke: bg3, width: 0.5 } },
      { stroke: dim, grid: { stroke: bg3, width: 0.5, dash: [2, 4] }, ticks: { stroke: bg3, width: 0.5 } },
    ],
    cursor: {
      drag: { x: true, y: false, uni: 10 },
      points: { size: 6, stroke: getColor('--a1'), fill: getColor('--bg0'), width: 2 },
    },
  };
}

function equityOpts(w, h, initial) {
  const base = baseAxes();
  const pos = getColor('--pos');
  const a2  = getColor('--a2');
  const neg = getColor('--neg');
  return {
    width: w,
    height: h,
    ...base,
    scales: {
      x:  { time: true },
      $:  { auto: true },
      dd: { auto: true },
    },
    axes: [
      base.axes[0],
      { ...base.axes[1], scale: '$',  values: (_, splits) => splits.map(v => '$' + Math.round(v / 1000) + 'k') },
      { ...base.axes[1], scale: 'dd', side: 1, values: (_, splits) => splits.map(v => v.toFixed(0) + '%') },
    ],
    series: [
      { label: 'Date' },
      { label: 'Portfolio', scale: '$', stroke: pos, width: 2, fill: pos + '22' },
      { label: 'SPY B&H',  scale: '$', stroke: a2, width: 1.5, dash: [6, 4] },
      { label: 'DD %',     scale: 'dd', stroke: neg, width: 1.5, fill: neg + '1a' },
    ],
  };
}

function bprOpts(w, h, capVal) {
  const base = baseAxes();
  const a2  = getColor('--a2');
  const neg = getColor('--neg');
  return {
    width: w,
    height: h,
    ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => '$' + Math.round(v / 1000) + 'k') },
    ],
    series: [
      { label: 'Date' },
      { label: 'BPR', stroke: a2, width: 2, fill: a2 + '33' },
    ],
    hooks: {
      draw: [u => drawHLine(u, capVal, neg, `CAP $${Math.round(capVal / 1000)}k`)],
    },
  };
}

function positionsOpts(w, h) {
  const base = baseAxes();
  const a4 = getColor('--a4');
  return {
    width: w,
    height: h,
    ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => Math.round(v)) },
    ],
    series: [
      { label: 'Date' },
      { label: 'Open', stroke: a4, width: 2, paths: uPlot.paths.stepped({ align: 1 }) },
    ],
  };
}

function vixOpts(w, h, vixMax) {
  const base = baseAxes();
  const fg4 = getColor('--fg4');
  const a2  = getColor('--a2');
  const neg = getColor('--neg');
  const bg3 = getColor('--bg3');
  return {
    width: w,
    height: h,
    ...base,
    axes: [
      base.axes[0],
      { ...base.axes[1], values: (_, splits) => splits.map(v => v.toFixed(0)) },
    ],
    series: [
      { label: 'Date' },
      { label: 'VIX', stroke: fg4, width: 1.5 },
      {
        label: 'Entry',
        stroke: a2,
        fill: a2,
        width: 0,
        paths: () => null,
        points: { show: true, size: 5, stroke: bg3, fill: a2, width: 1 },
      },
      {
        label: 'Skipped',
        stroke: neg,
        width: 0,
        paths: () => null,
        points: { show: true, size: 6, stroke: neg, fill: 'transparent', width: 2 },
      },
    ],
    hooks: {
      draw: [u => drawHLine(u, vixMax, neg, `VIX MAX ${vixMax}`)],
    },
  };
}

function drawHLine(u, yVal, color, label) {
  const ctx = u.ctx;
  const y = u.valToPos(yVal, u.series[1].scale || 'y', true);
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
  ctx.fillStyle = color;
  ctx.font = '600 10px "IBM Plex Mono", monospace';
  ctx.textBaseline = 'bottom';
  ctx.fillText(label, u.bbox.left + 8, y - 2);
  ctx.restore();
}
