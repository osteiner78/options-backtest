import { store, updateParams } from '../../store.js';
import { renderCollapsibleSection, bindCollapsibleSections } from '../primitives/CollapsibleSection.js';
import { renderEditableValue, bindEditableValues } from '../primitives/EditableValue.js';
import { parameterSections, coerceParamValue, matchesCondition } from './parameter-sections.js';

const escAttr = s => String(s).replace(/"/g, '&quot;');

function renderSectionBody(section, params) {
  return section.params
    .filter(p => matchesCondition(p.showWhen, params))
    .map(p => {
      const val = params[p.key] ?? '';
      const displayValue = p.format
        ? p.format(val)
        : (p.transform ? p.transform(val) : val);

      const cls   = `pr${p.indent ? ' pr-indent' : ''}`;
      const tipAt = p.tooltip ? ` data-tooltip="${escAttr(p.tooltip)}"` : '';

      if (p.options) {
        const opts = JSON.stringify(p.options).replace(/'/g, '&#39;');
        return `
          <div class="${cls}"${tipAt}>
            <span class="pl">${p.label}</span>
            <span class="pv-cycle ${p.color || ''}" data-key="${p.key}" data-options='${opts}'>${displayValue}</span>
          </div>
        `;
      }

      return `
        <div class="${cls}"${tipAt}>
          <span class="pl">${p.label}</span>
          ${renderEditableValue({ key: p.key, value: val, color: p.color, displayValue, type: p.type })}
        </div>
      `;
    })
    .join('');
}

export function renderSidebar() {
  const { params } = store;
  const sectionsHtml = parameterSections
    .map(sec =>
      renderCollapsibleSection({
        id: sec.id,
        title: sec.title,
        bodyHtml: renderSectionBody(sec, params),
        open: true,
      })
    )
    .join('');
  return `<aside class="sidebar" id="sidebar-root">${sectionsHtml}</aside>`;
}

let bound = false;
export function initSidebar() {
  if (bound) return;
  bound = true;

  bindCollapsibleSections(document);

  bindEditableValues(document, (key, raw) => {
    const original = store.params[key];
    updateParams({ [key]: coerceParamValue(raw, original) });
  });

  // Cycle through fixed-option params on click
  document.addEventListener('click', (e) => {
    const el = e.target.closest('#sidebar-root .pv-cycle[data-key]');
    if (!el) return;
    const key = el.dataset.key;
    const options = JSON.parse(el.dataset.options);
    const current = store.params[key];
    let idx = options.findIndex(o => String(o) === String(current));
    if (idx === -1) idx = 0;
    updateParams({ [key]: options[(idx + 1) % options.length] });
  });

  // ── Tooltip singleton ──────────────────────────────────────────────────
  const tipEl = document.createElement('div');
  tipEl.id  = 'sidebar-param-tip';
  tipEl.className = 'sidebar-tip';
  document.body.appendChild(tipEl);

  document.addEventListener('mousemove', (e) => {
    const row = e.target.closest?.('#sidebar-root .pr[data-tooltip]');
    if (!row) { tipEl.style.display = 'none'; return; }

    tipEl.textContent = row.dataset.tooltip;
    const sbRect = document.getElementById('sidebar-root')?.getBoundingClientRect();
    tipEl.style.left = ((sbRect?.right ?? 188) + 6) + 'px';
    tipEl.style.top  = Math.max(4, Math.min(e.clientY - 15, window.innerHeight - 120)) + 'px';
    tipEl.style.display = 'block';
  });
}
