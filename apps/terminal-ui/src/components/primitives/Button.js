export function renderButton({ id, label, variant = 'default', disabled = false }) {
  const cls = variant === 'primary' ? 'btn btn-primary' : 'btn';
  const idAttr = id ? ` id="${id}"` : '';
  const dis = disabled ? ' disabled' : '';
  return `<button class="${cls}"${idAttr}${dis}>${label}</button>`;
}
