import { store, clearError } from '../../store.js';

export function renderErrorBanner() {
  const { error, status } = store;
  if (!error && status !== 'running') return '';

  if (status === 'running') {
    return `
      <div class="banner banner-info">
        <span class="banner-dot pulse"></span>
        <span class="banner-msg">Backtest running…</span>
      </div>
    `;
  }

  return `
    <div class="banner banner-error">
      <span class="banner-msg"><strong>Backtest failed:</strong> ${error}</span>
      <span class="banner-close" id="btn-banner-close">✕</span>
    </div>
  `;
}

let bound = false;
export function initErrorBanner() {
  if (bound) return;
  bound = true;
  document.addEventListener('click', (e) => {
    if (e.target.id === 'btn-banner-close') clearError();
  });
}
