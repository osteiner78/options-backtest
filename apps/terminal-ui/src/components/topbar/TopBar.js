import { store, setStatus, setResults } from '../../store.js';
import { triggerBacktest, pollResults } from '../../api/client.js';
import { normalizeResults } from '../../api/adapters.js';
import { renderButton } from '../primitives/Button.js';

export function renderTopBar() {
  const { params, status } = store;
  const running = status === 'running';

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
      const isTokyo = document.body.classList.toggle('theme-tokyo');
      e.target.textContent = isTokyo ? '⚙ GRUVBOX' : '⚙ TOKYO NIGHT';
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
        setStatus('failed');
        alert('Backtest failed: ' + err.message);
      }
    }
  });
}
