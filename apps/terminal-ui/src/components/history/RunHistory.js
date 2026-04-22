import { store, toggleRunHistory, setRunHistory, setResults, setStatus } from '../../store.js';
import { fetchRunById, deleteRun, labelRun } from '../../api/client.js';
import { normalizeResults } from '../../api/adapters.js';
import { formatPct } from '../../utils/format.js';

function statusBadge(status) {
  const cls = status === 'completed' ? 'c-pos' : status === 'failed' ? 'c-neg' : 'c-dim';
  return `<span class="${cls} fw6">${status.toUpperCase()}</span>`;
}

function formatDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso + 'Z');
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

export function renderRunHistory() {
  const { runHistory, runHistoryOpen } = store;

  const rows = runHistory.length === 0
    ? `<tr><td colspan="5" style="text-align:center;color:var(--dim);padding:20px;">No runs yet</td></tr>`
    : runHistory.map(r => {
        const label = r.label || r.params?.start_date || '--';
        const mode = (r.params?.mode || r.params?.pricing_mode || '?').toUpperCase();
        return `
          <tr class="rh-row" data-runid="${r.run_id}">
            <td class="rh-label" title="${r.run_id}">${label}</td>
            <td>${statusBadge(r.status)}</td>
            <td class="c-dim">${mode}</td>
            <td class="c-dim">${formatDate(r.created_at)}</td>
            <td class="rh-actions">
              <span class="rh-btn rh-load" data-runid="${r.run_id}" title="Load this run">LOAD</span>
              <span class="rh-btn rh-del  c-neg" data-runid="${r.run_id}" title="Delete">DEL</span>
            </td>
          </tr>
        `;
      }).join('');

  return `
    <div class="run-history-overlay ${runHistoryOpen ? 'open' : ''}" id="run-history">
      <div class="tl-header">
        <span class="tl-title">Run History</span>
        <span style="font-size:9px;color:var(--dim);margin-left:4px;">${runHistory.length} runs</span>
        <span class="tl-close" id="btn-rh-close">▼ CLOSE</span>
      </div>
      <div class="tl-body">
        <table class="tl-table">
          <thead><tr>
            <th>Label / Date Range</th>
            <th>Status</th>
            <th>Mode</th>
            <th>Created</th>
            <th>Actions</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

let bound = false;
export function initRunHistory() {
  if (bound) return;
  bound = true;

  document.addEventListener('click', async (e) => {
    if (e.target.id === 'btn-rh-close') {
      toggleRunHistory();
      return;
    }

    const loadBtn = e.target.closest('#run-history .rh-load');
    if (loadBtn) {
      const runId = loadBtn.dataset.runid;
      try {
        const row = await fetchRunById(runId);
        if (row?.result) {
          // Reconstruct a BacktestResponse-like object the adapter can consume
          const raw = { ...row.result, params: row.params };
          setResults(normalizeResults(raw));
          setStatus('completed');
          toggleRunHistory();
        }
      } catch (err) {
        console.error('Failed to load run:', err);
      }
      return;
    }

    const delBtn = e.target.closest('#run-history .rh-del');
    if (delBtn) {
      const runId = delBtn.dataset.runid;
      if (!confirm(`Delete run ${runId}?`)) return;
      try {
        await deleteRun(runId);
        setRunHistory(store.runHistory.filter(r => r.run_id !== runId));
      } catch (err) {
        console.error('Failed to delete run:', err);
      }
    }
  });
}
