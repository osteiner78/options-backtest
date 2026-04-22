export function renderEditableValue({ key, value, color = '', displayValue }) {
  const shown = displayValue !== undefined ? displayValue : value;
  return `<span class="pv ${color}" data-key="${key}">${shown}</span>`;
}

/**
 * Delegated edit binding. On click of any `.pv[data-key]` inside `rootSelector`,
 * replace its text with an <input>; commit on blur/Enter via `onCommit(key, rawValue)`.
 */
export function bindEditableValues(rootSelector, onCommit) {
  const root = typeof rootSelector === 'string' ? document.querySelector(rootSelector) : rootSelector;
  if (!root) return;
  root.addEventListener('click', (e) => {
    const pv = e.target.closest('.pv');
    if (!pv || !root.contains(pv) || pv.querySelector('input')) return;

    const key = pv.dataset.key;
    if (!key) return;
    const originalText = pv.textContent;
    const input = document.createElement('input');
    input.className = 'pv-input';
    input.value = originalText;
    pv.textContent = '';
    pv.appendChild(input);
    input.focus();
    input.select();

    const finish = (commit) => {
      const raw = input.value;
      input.remove();
      if (commit) onCommit(key, raw);
      else pv.textContent = originalText;
    };

    input.onblur = () => finish(true);
    input.onkeydown = (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
      if (ev.key === 'Escape') { finish(false); }
    };
  });
}
