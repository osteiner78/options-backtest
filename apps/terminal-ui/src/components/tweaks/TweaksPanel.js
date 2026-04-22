import { store, setTheme, toggleThemePanel } from '../../store.js';

const THEMES = [
  { id: 'gruvbox',    label: 'Gruvbox Dark' },
  { id: 'tokyo',      label: 'Tokyo Night' },
  { id: 'solarized',  label: 'Solarized Dark' },
  { id: 'onedark',    label: 'One Dark' },
  { id: 'nord',       label: 'Nord' },
  { id: 'catppuccin', label: 'Catppuccin Macchiato' },
  { id: 'bloomberg',  label: 'Bloomberg Terminal' },
];

const ALL_THEME_CLASSES = THEMES.map(t => `theme-${t.id}`);

export function renderTweaksPanel() {
  const { themePanelOpen, theme } = store;

  const themeOptions = THEMES.map(t => `
    <span class="tw-theme-option ${t.id === theme ? 'active' : ''}" data-theme="${t.id}">
      ${t.label}
    </span>
  `).join('');

  return `
    <div class="tweaks-panel ${themePanelOpen ? 'open' : ''}" id="tweaks-panel">
      <div class="tw-head">
        <span class="tw-title">Tweaks</span>
        <span class="tw-close" id="btn-tw-close">✕</span>
      </div>
      <div class="tw-section">Theme</div>
      <div class="tw-theme-list">
        ${themeOptions}
      </div>
      <div class="tw-section">Architecture</div>
      <div class="tw-row"><span class="tw-label">Renderer</span><span class="tw-val">vanilla + uPlot</span></div>
      <div class="tw-row"><span class="tw-label">State</span><span class="tw-val">Proxy store</span></div>
    </div>
  `;
}

export function applyTheme(theme) {
  document.body.classList.remove(...ALL_THEME_CLASSES);
  document.body.classList.add(`theme-${theme}`);
}

let bound = false;
export function initTweaksPanel() {
  if (bound) return;
  bound = true;

  applyTheme(store.theme);

  document.addEventListener('click', (e) => {
    if (e.target.id === 'btn-tw-close') {
      toggleThemePanel();
      return;
    }
    const opt = e.target.closest('#tweaks-panel .tw-theme-option');
    if (opt && opt.dataset.theme) {
      setTheme(opt.dataset.theme);
      applyTheme(opt.dataset.theme);
    }
  });
}
