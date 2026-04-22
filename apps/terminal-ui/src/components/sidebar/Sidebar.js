import { store, updateParams } from '../../store.js';
import { renderCollapsibleSection, bindCollapsibleSections } from '../primitives/CollapsibleSection.js';
import { renderEditableValue, bindEditableValues } from '../primitives/EditableValue.js';
import { parameterSections, coerceParamValue } from './parameter-sections.js';

function renderSectionBody(section, params) {
  return section.params
    .map(p => {
      const val = params[p.key];
      const displayValue = p.format
        ? p.format(val)
        : (p.transform ? p.transform(val) : val);
      return `
        <div class="pr">
          <span class="pl">${p.label}</span>
          ${renderEditableValue({ key: p.key, value: val, color: p.color, displayValue })}
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

  // Toggle collapsible sections anywhere in the sidebar.
  bindCollapsibleSections(document);

  // Inline-edit any pv[data-key] inside the sidebar.
  bindEditableValues(document, (key, raw) => {
    const original = store.params[key];
    updateParams({ [key]: coerceParamValue(raw, original) });
  });
}
