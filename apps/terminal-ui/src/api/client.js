const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

function flattenValidationErrors(detail) {
  if (!Array.isArray(detail)) return typeof detail === 'string' ? detail : 'Invalid request';
  return detail
    .map(d => {
      const field = Array.isArray(d.loc) ? d.loc.filter(x => x !== 'body').join('.') : 'request';
      return `${field}: ${d.msg}`;
    })
    .join('; ');
}

export async function fetchConfig() {
  const response = await fetch(`${BASE_URL}/config`);
  if (!response.ok) throw new Error(`Failed to fetch /config (HTTP ${response.status})`);
  return response.json();
}

export async function triggerBacktest(params) {
  const response = await fetch(`${BASE_URL}/backtest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const msg = response.status === 422
      ? flattenValidationErrors(err.detail)
      : (typeof err.detail === 'string' ? err.detail : `Failed to start backtest (HTTP ${response.status})`);
    const e = new Error(msg);
    e.status = response.status;
    e.detail = err.detail;
    throw e;
  }
  return response.json();
}

export async function fetchResults(runId) {
  const response = await fetch(`${BASE_URL}/backtest/${runId}`);
  if (!response.ok) throw new Error(`Failed to fetch results (HTTP ${response.status})`);
  return response.json();
}

export function streamResults(runId, onProgress) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${BASE_URL}/backtest/${runId}/stream`);

    es.onmessage = async (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }

      if (onProgress) onProgress(data);

      if (data.status === 'completed') {
        es.close();
        try {
          const result = await fetchResults(runId);
          resolve(result);
        } catch (e) {
          reject(e);
        }
      } else if (data.status === 'failed') {
        es.close();
        reject(new Error('Backtest failed'));
      }
    };

    es.onerror = () => {
      es.close();
      // Fall back to a single poll attempt
      fetchResults(runId)
        .then(r => {
          if (r.status === 'completed') resolve(r);
          else if (r.status === 'failed') reject(new Error(r.error || 'Backtest failed'));
          else reject(new Error('SSE connection lost'));
        })
        .catch(reject);
    };
  });
}

export async function fetchRuns(limit = 50) {
  const r = await fetch(`${BASE_URL}/runs?limit=${limit}`);
  if (!r.ok) throw new Error(`Failed to fetch runs (HTTP ${r.status})`);
  return r.json();
}

export async function fetchRunById(runId) {
  const r = await fetch(`${BASE_URL}/runs/${runId}`);
  if (!r.ok) throw new Error(`Failed to fetch run ${runId} (HTTP ${r.status})`);
  return r.json();
}

export async function deleteRun(runId) {
  const r = await fetch(`${BASE_URL}/runs/${runId}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`Failed to delete run (HTTP ${r.status})`);
  return r.json();
}

export async function labelRun(runId, label) {
  const r = await fetch(`${BASE_URL}/runs/${runId}/label`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label }),
  });
  if (!r.ok) throw new Error(`Failed to label run (HTTP ${r.status})`);
  return r.json();
}

export async function compareRuns(runIds) {
  const r = await fetch(`${BASE_URL}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_ids: runIds }),
  });
  if (!r.ok) throw new Error(`Failed to compare runs (HTTP ${r.status})`);
  return r.json();
}
