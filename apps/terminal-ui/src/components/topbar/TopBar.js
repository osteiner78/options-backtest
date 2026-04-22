import { store, setStatus, setResults, setError, toggleThemePanel } from '../../store.js';
import { triggerBacktest, pollResults } from '../../api/client.js';
import { normalizeResults } from '../../api/adapters.js';
import { renderButton } from '../primitives/Button.js';

export function renderTopBar() {
  const { params, status, lastRun } = store;
  const running = status === 'running';
  const lastRunLabel = lastRun
    ? `Last run ${new Date(lastRun).toLocaleTimeString()}`
    : 'No runs yet';

  const configPill = [
    (params.strategy_mode || 'short_strangle').replace('_', ' ').toUpperCase(),
    'PORTFOLIO',
    (params.pricing_mode || params.mode || 'market').toUpperCase() + ' PRICING',
    `${params.start_date} → ${params.end_date}`,
    `Δ${params.target_delta}`,
    `PT ${Math.round(params.profit_target_pct * 100)}%`,
  ].join(' · ');

  return `
    <header class="topbar">
      <span class="brand">▸ SPY BACKTEST</span>
      <span class="sep">/</span>
      <span class="config-pill">${configPill}</span>
      <span class="spacer"></span>
      <span class="topbar-meta">${lastRunLabel}</span>
      ${renderButton({ id: 'btn-theme', label: '⚙ THEME' })}
      ${renderButton({ id: 'btn-save',  label: '💾 SAVE' })}
      ${renderButton({
        id: 'btn-run',
        label: running ? '● RUNNING' : '▶ RUN',
        variant: 'primary',
        disabled: running,
      })}
    </header>
  `;
}

let bound = false;
export function initTopBar() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', async (e) => {
    if (e.target.id === 'btn-theme') {
      toggleThemePanel();
      return;
    }

    if (e.target.id === 'btn-run') {
      if (store.status === 'running') return;
      try {
        setStatus('running');
        const { run_id } = await triggerBacktest(store.params);
        const raw = await pollResults(run_id);
        setResults(normalizeResults(raw));
      } catch (err) {
        console.error('Backtest error:', err);
        setError(err.message || String(err));
      }
    }
  });
}
