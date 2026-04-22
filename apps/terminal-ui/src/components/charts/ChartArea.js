import { store, setActiveTab } from '../../store.js';
import { getVar, scaleY, yearGridlines, crosshair } from '../primitives/SvgChart.js';

const legends = {
  equity: `<div class="leg-item"><div class="leg-line" style="background:var(--pos)"></div>Portfolio</div><div class="leg-item"><div class="leg-line" style="background:var(--a2);opacity:0.6"></div>SPY B&H</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);height:8px;border-radius:1px;opacity:0.5"></div>Drawdown</div>`,
  bpr: `<div class="leg-item"><div class="leg-line" style="background:var(--a2)"></div>Utilized BPR ($)</div><div class="leg-item"><div class="leg-line" style="background:var(--neg);opacity:0.6"></div>BPR Cap</div>`,
  positions: `<div class="leg-item"><div class="leg-line" style="background:var(--a4)"></div>Open Positions</div>`,
  vix: `<div class="leg-item" style="gap:5px;"><div style="width:8px;height:8px;border-radius:50%;background:var(--a2)"></div>Entry</div><div class="leg-item" style="gap:5px;"><div style="width:8px;height:8px;border-radius:50%;border:1.5px solid var(--neg);background:transparent"></div>Skipped</div>`,
};

export function renderChartArea() {
  const { activeTab } = store;
  return `
    <div class="chart-tabs">
      <div class="chart-tab ${activeTab === 'equity' ? 'active' : ''}" data-tab="equity">EQUITY</div>
      <div class="chart-tab ${activeTab === 'bpr' ? 'active' : ''}" data-tab="bpr">BPR UTIL</div>
      <div class="chart-tab ${activeTab === 'positions' ? 'active' : ''}" data-tab="positions">POSITIONS</div>
      <div class="chart-tab ${activeTab === 'vix' ? 'active' : ''}" data-tab="vix">VIX</div>
      <div class="tab-spacer"></div>
      <div class="chart-legend">${legends[activeTab] || ''}</div>
    </div>
    <div class="chart-area" id="chart-area-container">
      <div class="chart-panel active">
        <div style="flex:1;position:relative;min-height:0;" id="chart-wrap">
          <svg id="main-chart" class="chart" preserveAspectRatio="none"></svg>
          <div id="chart-tooltip" style="position:fixed; pointer-events:none; background:var(--bg2); border:1px solid var(--bg4); padding:10px 14px; font-size:12px; color:var(--fg1); display:none; z-index:9999; border-radius:3px; box-shadow: 0 4px 15px rgba(0,0,0,0.6); backdrop-filter: blur(4px);"></div>
        </div>
      </div>
    </div>
  `;
}

let currentMX = -1, currentMY = -1;
let bound = false;

export function initChartArea() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', (e) => {
    const tab = e.target.closest('.chart-tab');
    if (tab) setActiveTab(tab.dataset.tab);
  });
  document.addEventListener('mousemove', (e) => {
    const wrap = document.getElementById('chart-wrap');
    if (!wrap || !store.results) return;
    const rect = wrap.getBoundingClientRect();
    if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
      currentMX = e.clientX - rect.left;
      currentMY = e.clientY - rect.top;
      handleTooltip(e, currentMX, currentMY, rect.width, rect.height);
      drawChart(currentMX, currentMY);
    } else if (currentMX !== -1) {
      currentMX = -1; currentMY = -1;
      const tt = document.getElementById('chart-tooltip');
      if (tt) tt.style.display = 'none';
      drawChart();
    }
  });
  window.addEventListener('resize', () => drawChart(currentMX, currentMY));
}

function handleTooltip(e, mx, my, w, h) {
  const tt = document.getElementById('chart-tooltip');
  if (!tt || !store.results) return;
  const { activeTab, results } = store;
  let dates = Object.keys(results.equity_curve);
  let vals = Object.values(results.equity_curve);
  const spyVals = results.spy_curve ? Object.values(results.spy_curve) : null;
  let label = 'Portfolio';
  let formatter = v => '$' + Math.round(v).toLocaleString();

  if (activeTab === 'bpr' && results.bpr_curve) {
    dates = Object.keys(results.bpr_curve); vals = Object.values(results.bpr_curve); label = 'BPR';
  } else if (activeTab === 'positions' && results.pos_count_curve) {
    dates = Object.keys(results.pos_count_curve); vals = Object.values(results.pos_count_curve); label = 'Positions'; formatter = v => v;
  } else if (activeTab === 'vix') {
    dates = Object.keys(results.vix_curve); vals = Object.values(results.vix_curve); label = 'VIX'; formatter = v => v.toFixed(2);
  }

  if (!dates.length) return;
  const idx = Math.max(0, Math.min(dates.length - 1, Math.round((mx / w) * (dates.length - 1))));
  const date = dates[idx], val = vals[idx];
  const chartH = h * 0.70;
  let html = `<div style="color:var(--dim);margin-bottom:6px;border-bottom:1px solid var(--bg3);padding-bottom:4px;font-size:11px;font-weight:700;">${date}</div>`;

  if (activeTab === 'equity' && my > chartH) {
    const peak = [vals[0]]; for (let i = 1; i <= idx; i++) peak.push(Math.max(peak[i - 1], vals[i]));
    const ddVal = (val - peak[idx]) / (peak[idx] || 1) * 100;
    html += `<div style="font-weight:700;display:flex;justify-content:space-between;gap:20px;"><span style="color:var(--neg)">DRAWDOWN</span> <span>${ddVal.toFixed(2)}%</span></div>`;
  } else {
    html += `<div style="font-weight:700;display:flex;justify-content:space-between;gap:20px;"><span style="color:var(--a1)">${label.toUpperCase()}</span> <span>${formatter(val)}</span></div>`;
    if (activeTab === 'equity' && spyVals) {
      html += `<div style="font-weight:700;display:flex;justify-content:space-between;gap:20px;margin-top:4px;"><span style="color:var(--a2)">SPY B&H</span> <span>${formatter(spyVals[idx])}</span></div>`;
    }
  }
  tt.innerHTML = html;
  tt.style.display = 'block';

  const ttRect = tt.getBoundingClientRect();
  const spaceRight = window.innerWidth - e.clientX;
  tt.style.left = (spaceRight < ttRect.width + 40) ? (e.clientX - ttRect.width - 20) + 'px' : (e.clientX + 20) + 'px';
  tt.style.top = (e.clientY - 40) + 'px';
}

export function drawChart(mx = -1, my = -1) {
  const svg = document.getElementById('main-chart');
  if (!svg) return;
  const w = svg.clientWidth, h = svg.clientHeight;
  if (!w || !h) return;

  const { activeTab, results } = store;
  const dim = getVar('--dim');
  const bg3 = getVar('--bg3');
  const pos = getVar('--pos');
  const neg = getVar('--neg');
  const a2  = getVar('--a2');
  const a4  = getVar('--a4');

  if (!results) {
    svg.innerHTML = `<text x="${w / 2}" y="${h / 2}" text-anchor="middle" fill="${dim}" font-size="16" font-weight="700">RUN BACKTEST TO GENERATE CHARTS</text>`;
    return;
  }

  const dates = Object.keys(results.equity_curve);
  const N = dates.length;
  const xs = i => (i / (N - 1)) * w;
  const yrTicks = yearGridlines(dates, w, h, { strokeColor: bg3, textColor: dim });
  const cross = crosshair(mx, my, w, h, dim);

  if (activeTab === 'equity') {
    const p = Object.values(results.equity_curve);
    const s = results.spy_curve ? Object.values(results.spy_curve) : p.map(v => v * 0.9);
    const chartH = h * 0.70, ddTop = h * 0.70;
    const lo = Math.min(...p, ...s, store.params.initial_balance * 0.8) * 0.98;
    const hi = Math.max(...p, ...s) * 1.02;
    const peak = [p[0]]; for (let i = 1; i < N; i++) peak.push(Math.max(peak[i - 1], p[i]));
    const dd = p.map((v, i) => (v - peak[i]) / (peak[i] || 1) * 100);
    const ddLo = Math.min(...dd, -5) * 1.2;
    const ePts = p.map((v, i) => `${xs(i)},${scaleY(v, lo, hi, 15, chartH - 15)}`).join(' ');
    const sPts = s.map((v, i) => `${xs(i)},${scaleY(v, lo, hi, 15, chartH - 15)}`).join(' ');
    const dPts = dd.map((v, i) => `${xs(i)},${scaleY(v, ddLo, 0, h - 15, ddTop + 5)}`).join(' ');
    let yAxis = '';
    [lo, (lo + hi) / 2, hi].forEach(val => {
      const y = scaleY(val, lo, hi, 15, chartH - 15);
      yAxis += `<line x1="0" y1="${y}" x2="${w}" y2="${y}" stroke="${bg3}" stroke-width="0.8" stroke-dasharray="2,4"/><text x="${w - 70}" y="${y - 8}" font-size="12" fill="${dim}" font-weight="800">$${Math.round(val / 1000)}k</text>`;
    });
    svg.innerHTML = `<defs><linearGradient id="gp" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${pos}" stop-opacity="0.25"/><stop offset="100%" stop-color="${pos}" stop-opacity="0"/></linearGradient><linearGradient id="gd" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${neg}" stop-opacity="0.45"/><stop offset="100%" stop-color="${neg}" stop-opacity="0.05"/></linearGradient></defs>${yrTicks}${yAxis}<line x1="0" y1="${ddTop}" x2="${w}" y2="${ddTop}" stroke="${dim}" stroke-width="2.5"/><polygon points="${ePts} ${w},${chartH} 0,${chartH}" fill="url(#gp)"/><polyline points="${sPts}" stroke="${a2}" stroke-width="2" fill="none" stroke-dasharray="6,4" opacity="0.8"/><polyline points="${ePts}" stroke="${pos}" stroke-width="3.5" fill="none"/><polygon points="${dPts} 0,${ddTop + 5} ${w},${ddTop + 5}" fill="url(#gd)"/><polyline points="${dPts}" stroke="${neg}" stroke-width="2.2" fill="none"/><text x="15" y="${ddTop + 25}" font-size="16" fill="${neg}" font-weight="950" letter-spacing="0.05em">MAX DRAWDOWN %</text>${cross}`;
  } else if (activeTab === 'bpr' && results.bpr_curve) {
    const vals = Object.values(results.bpr_curve);
    const hi = Math.max(...vals, store.params.initial_balance * store.params.max_bpr_allocation) * 1.3;
    const chartH = h * 0.85;
    const bPts = vals.map((v, i) => `${xs(i)},${scaleY(v, 0, hi, 15, chartH - 15)}`).join(' ');
    const capVal = store.params.max_bpr_allocation * store.params.initial_balance;
    const capY = scaleY(capVal, 0, hi, 15, chartH - 15);
    svg.innerHTML = `<defs><linearGradient id="gbpr" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${a2}" stop-opacity="0.4"/><stop offset="100%" stop-color="${a2}" stop-opacity="0.05"/></linearGradient></defs>${yrTicks}<polygon points="${bPts} ${w},${chartH} 0,${chartH}" fill="url(#gbpr)"/><polyline points="${bPts}" stroke="${a2}" stroke-width="4" fill="none"/><line x1="0" y1="${capY}" x2="${w}" y2="${capY}" stroke="${neg}" stroke-width="3" stroke-dasharray="10,6"/><text x="15" y="${capY - 15}" font-size="16" fill="${neg}" font-weight="950">BPR CAP: $${Math.round(capVal / 1000)}k</text>${cross}`;
  } else if (activeTab === 'positions' && results.pos_count_curve) {
    const vals = Object.values(results.pos_count_curve);
    const hi = Math.max(...vals, 4) + 1;
    let stepPts = `0,${scaleY(vals[0], 0, hi, 25, h - 35)}`;
    for (let i = 1; i < N; i++) {
      const x = xs(i);
      stepPts += ` ${x},${scaleY(vals[i - 1], 0, hi, 25, h - 35)} ${x},${scaleY(vals[i], 0, hi, 25, h - 35)}`;
    }
    svg.innerHTML = `${yrTicks}<polyline points="${stepPts}" stroke="${a4}" stroke-width="6" fill="none"/>${cross}`;
  } else if (activeTab === 'vix') {
    const vals = Object.values(results.vix_curve);
    const lo = 5, hi2 = Math.max(...vals, 45) + 5;
    const currentFilter = store.params.vix_entry_max;
    const rMaxY = scaleY(currentFilter, lo, hi2, 25, h - 45);
    let dots = '';
    const vixDates = Object.keys(results.vix_curve);
    results.trades.forEach(t => {
      const dIdx = vixDates.indexOf(t.entry_date);
      if (dIdx !== -1) dots += `<circle cx="${xs(dIdx)}" cy="${scaleY(t.entry_vix, lo, hi2, 25, h - 45)}" r="7" fill="${a2}" stroke="${bg3}" stroke-width="1.5"/>`;
    });
    if (results.vix_blocked_dates) {
      results.vix_blocked_dates.forEach(dStr => {
        const dIdx = vixDates.indexOf(dStr);
        if (dIdx !== -1) dots += `<circle cx="${xs(dIdx)}" cy="${scaleY(vals[dIdx], lo, hi2, 25, h - 45)}" r="8" fill="none" stroke="${neg}" stroke-width="4"/>`;
      });
    }
    const vixPts = vals.map((v, i) => `${xs(i)},${scaleY(v, lo, hi2, 25, h - 45)}`).join(' ');
    svg.innerHTML = `${yrTicks}<line x1="0" y1="${rMaxY}" x2="${w}" y2="${rMaxY}" stroke="${neg}" stroke-width="3.5" stroke-dasharray="8,5"/><polyline points="${vixPts}" stroke="${getVar('--fg4')}" stroke-width="2.5" fill="none" opacity="0.9"/>${dots}<text x="15" y="${rMaxY - 15}" font-size="16" fill="${neg}" font-weight="950">VIX FILTER: ${currentFilter}</text>${cross}`;
  } else {
    // Portfolio-only curve not present — show placeholder.
    svg.innerHTML = `<text x="${w / 2}" y="${h / 2}" text-anchor="middle" fill="${dim}" font-size="14" font-weight="600">NO DATA FOR THIS VIEW (PORTFOLIO MODE REQUIRED)</text>`;
  }
}
