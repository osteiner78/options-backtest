export function renderEditableValue({ key, value, color = '', displayValue, type }) {
  const shown = displayValue !== undefined ? displayValue : value;
  return `<span class="pv ${color}" data-key="${key}" data-type="${type || ''}">${shown}</span>`;
}

/**
 * Delegated edit binding. On click of any `.pv[data-key]` inside `root`,
 * replace its text with an <input>. Commit on blur or Enter; Escape cancels.
 */
export function bindEditableValues(root, onCommit) {
  const rootEl = typeof root === 'string' ? document.querySelector(root) : root;
  if (!rootEl) return;

  rootEl.addEventListener('click', (e) => {
    const pv = e.target.closest('.pv');
    if (!pv || !rootEl.contains(pv) || pv.querySelector('input')) return;

    const key  = pv.dataset.key;
    const type = pv.dataset.type;
    if (!key) return;

    const originalText = pv.textContent;
    const input = document.createElement('input');
    input.className = type === 'date' ? 'pv-input pv-date' : 'pv-input';
    input.value = originalText;
    input.autocomplete = 'off';
    if (type === 'date') input.placeholder = 'YYYY-MM-DD';

    pv.textContent = '';
    pv.appendChild(input);
    input.focus();
    input.select();

    let committed = false;
    const finish = (commit) => {
      if (committed) return;
      committed = true;
      const raw = input.value;
      input.remove();
      if (commit && raw !== '') onCommit(key, raw);
      else pv.textContent = originalText;
    };

    input.onblur = () => finish(true);

    input.onkeydown = (ev) => {
      if (ev.key === 'Enter')  { ev.preventDefault(); finish(true); }
      if (ev.key === 'Escape') { finish(false); }
    };
  });
}
