import { store, setStatus, setResults, setError, setProgress, toggleThemePanel, toggleRunHistory, setRunHistory } from '../../store.js';
import { triggerBacktest, streamResults, fetchRuns } from '../../api/client.js';
import { normalizeResults } from '../../api/adapters.js';
import { renderButton } from '../primitives/Button.js';

export function renderTopBar() {
  const { params, status, lastRun, progress } = store;
  const running = status === 'running';

  let runLabel = 'No runs yet';
  if (running && progress) {
    const pct = Math.round((progress.pct ?? 0) * 100);
    const date = progress.current_date ? ` · ${progress.current_date}` : '';
    runLabel = `Running ${pct}%${date} · ${progress.trades_so_far ?? 0} trades`;
  } else if (lastRun) {
    runLabel = `Last run ${new Date(lastRun).toLocaleTimeString()}`;
  }

  return `
    <header class="topbar">
      <span class="brand">▸ SPY BACKTEST</span>
      <span class="spacer"></span>
      <span class="topbar-meta">${runLabel}</span>
      ${renderButton({ id: 'btn-history', label: '◷ HISTORY' })}
      ${renderButton({ id: 'btn-theme',   label: '⚙ THEME' })}
      ${renderButton({ id: 'btn-save',    label: '💾 SAVE' })}
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

    if (e.target.id === 'btn-history') {
      // Refresh list from server, then open
      fetchRuns(50)
        .then(runs => { setRunHistory(runs); toggleRunHistory(); })
        .catch(() => toggleRunHistory());
      return;
    }

    if (e.target.id === 'btn-run') {
      if (store.status === 'running') return;
      try {
        setStatus('running');
        setProgress({ pct: 0, trades_so_far: 0, current_date: null });
        const { run_id } = await triggerBacktest(store.params);
        const raw = await streamResults(run_id, (prog) => setProgress(prog));
        setResults(normalizeResults(raw));
        // Refresh history list silently
        fetchRuns(50).then(runs => setRunHistory(runs)).catch(() => {});
      } catch (err) {
        console.error('Backtest error:', err);
        setError(err.message || String(err));
      }
    }
  });
}
