import 'uplot/dist/uPlot.min.css';
import './styles/theme.css';
import './styles/typography.css';
import './styles/layout.css';
import './styles/components.css';
import './styles/uplot-overrides.css';

import { subscribe, setConfig } from './store.js';
import { fetchConfig } from './api/client.js';
import { renderTopBar, initTopBar } from './components/topbar/TopBar.js';
import { renderErrorBanner, initErrorBanner } from './components/banner/ErrorBanner.js';
import { renderSidebar, initSidebar } from './components/sidebar/Sidebar.js';
import { renderPerformanceBar } from './components/perf/PerformanceBar.js';
import { renderChartArea, initChartArea, drawChart } from './components/charts/ChartArea.js';
import { renderTableGrid } from './components/tables/TableGrid.js';
import { renderPnLStrip, initPnLStrip, drawPnL } from './components/pnl/PnLStrip.js';
import { renderTradeLog, initTradeLog } from './components/tradelog/TradeLog.js';
import { renderTweaksPanel, initTweaksPanel } from './components/tweaks/TweaksPanel.js';
import { renderRunHistory, initRunHistory } from './components/history/RunHistory.js';

const app = document.getElementById('app');

function render() {
  app.innerHTML = `
    ${renderTopBar()}
    ${renderErrorBanner()}
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
    ${renderRunHistory()}
  `;

  // After DOM update, paint SVG charts on next frame.
  requestAnimationFrame(() => {
    drawChart();
    drawPnL();
  });
}

render();

initTopBar();
initErrorBanner();
initSidebar();
initChartArea();
initPnLStrip();
initTradeLog();
initTweaksPanel();
initRunHistory();

subscribe(render);

fetchConfig()
  .then(setConfig)
  .catch(err => console.warn('[/config] unavailable, using bundled defaults:', err.message));
