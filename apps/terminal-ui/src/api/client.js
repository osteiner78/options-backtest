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

export async function pollResults(runId, onStatusUpdate, intervalMs = 2000) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const result = await fetchResults(runId);
        if (onStatusUpdate) onStatusUpdate(result.status);

        if (result.status === 'completed') {
          clearInterval(interval);
          resolve(result);
        } else if (result.status === 'failed') {
          clearInterval(interval);
          reject(new Error(result.error || 'Backtest failed'));
        }
      } catch (e) {
        clearInterval(interval);
        reject(e);
      }
    }, intervalMs);
  });
}
