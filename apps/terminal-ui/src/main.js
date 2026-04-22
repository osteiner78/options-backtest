import './styles/theme.css';
import './styles/typography.css';
import './styles/layout.css';
import './styles/components.css';

import { subscribe } from './store.js';
import { renderTopBar, initTopBar } from './components/topbar/TopBar.js';
import { renderSidebar, initSidebar } from './components/sidebar/Sidebar.js';
import { renderPerformanceBar } from './components/perf/PerformanceBar.js';
import { renderChartArea, initChartArea, drawChart } from './components/charts/ChartArea.js';
import { renderTableGrid } from './components/tables/TableGrid.js';
import { renderPnLStrip, initPnLStrip, drawPnL } from './components/pnl/PnLStrip.js';
import { renderTradeLog, initTradeLog } from './components/tradelog/TradeLog.js';
import { renderTweaksPanel, initTweaksPanel } from './components/tweaks/TweaksPanel.js';

const app = document.getElementById('app');

function render() {
  app.innerHTML = `
    ${renderTopBar()}
    <div class="body">
      ${renderSidebar()}
      <main class="main">
        ${renderPerformanceBar()}
        ${renderChartArea()}
        ${renderTableGrid()}
        ${renderPnLStrip()}
      </main>
    </div>
    ${renderTradeLog()}
    ${renderTweaksPanel()}
  `;

  // After DOM update, paint SVG charts on next frame.
  requestAnimationFrame(() => {
    drawChart();
    drawPnL();
  });
}

render();

initTopBar();
initSidebar();
initChartArea();
initPnLStrip();
initTradeLog();
initTweaksPanel();

subscribe(render);
