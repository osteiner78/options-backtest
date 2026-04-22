export function renderCollapsibleSection({ id, title, bodyHtml, open = true }) {
  const caret = open ? '▼' : '▶';
  const display = open ? '' : ' style="display:none"';
  return `
    <div class="sec-hdr" data-section="${id}">
      <span>${title}</span><span class="caret">${caret}</span>
    </div>
    <div class="sec-body" id="sec-${id}"${display}>${bodyHtml}</div>
  `;
}

/**
 * Delegated click handler — toggles visibility of the sec-body paired with
 * any clicked sec-hdr inside `rootSelector`.
 */
export function bindCollapsibleSections(rootSelector = document) {
  const root = typeof rootSelector === 'string' ? document.querySelector(rootSelector) : rootSelector;
  if (!root) return;
  root.addEventListener('click', (e) => {
    const hdr = e.target.closest('.sec-hdr');
    if (!hdr || !root.contains(hdr)) return;
    const body = document.getElementById(`sec-${hdr.dataset.section}`);
    const caret = hdr.querySelector('.caret');
    if (!body) return;
    const isHidden = body.style.display === 'none';
    body.style.display = isHidden ? '' : 'none';
    if (caret) caret.textContent = isHidden ? '▼' : '▶';
  });
}
