import { store, toggleThemePanel } from '../../store.js';

/**
 * Placeholder for the bottom-right tweaks overlay from the wireframe.
 * Phase 2 will flesh this out with theme picker + font tweaks + arch notes.
 */
export function renderTweaksPanel() {
  const { themePanelOpen } = store;
  return `
    <div class="tweaks-panel ${themePanelOpen ? 'open' : ''}" id="tweaks-panel">
      <div class="tw-title">Tweaks</div>
      <div class="tw-section">Theme</div>
      <div class="tw-row"><span class="tw-label">Palette</span><span class="tw-val">Gruvbox Dark</span></div>
      <div class="tw-row"><span class="tw-label">Font</span><span class="tw-val">IBM Plex Mono</span></div>
    </div>
  `;
}

let bound = false;
export function initTweaksPanel() {
  if (bound) return;
  bound = true;
  // Theme button in TopBar currently toggles body class; Phase 2 will wire
  // the full panel open/close here. Kept minimal on purpose.
  void toggleThemePanel;
}
