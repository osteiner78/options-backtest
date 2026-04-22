export { getVar, rnd, scaleY } from '../../utils/chartHelpers.js';

/**
 * Build SVG year-boundary gridlines from an ordered list of date strings.
 * Returns the inner SVG markup (lines + year labels).
 */
export function yearGridlines(dates, w, h, { strokeColor, textColor }) {
  if (!dates?.length) return '';
  let out = '';
  const xs = i => (i / (dates.length - 1)) * w;
  dates.forEach((d, i) => {
    if (i === 0) return;
    if (d.split('-')[0] !== dates[i - 1].split('-')[0]) {
      const x = xs(i);
      out += `<line x1="${x}" y1="0" x2="${x}" y2="${h}" stroke="${strokeColor}" stroke-width="1.5" stroke-dasharray="4,4"/>`;
      out += `<text x="${x + 8}" y="${h - 15}" font-size="14" font-weight="900" fill="${textColor}">${d.split('-')[0]}</text>`;
    }
  });
  return out;
}

/**
 * Vertical+horizontal crosshair pair at (mx, my). Returns '' if mx === -1.
 */
export function crosshair(mx, my, w, h, color) {
  if (mx === -1) return '';
  return (
    `<line x1="${mx}" y1="0" x2="${mx}" y2="${h}" stroke="${color}" stroke-width="1.2" stroke-dasharray="3,3" opacity="0.9"/>` +
    `<line x1="0" y1="${my}" x2="${w}" y2="${my}" stroke="${color}" stroke-width="1.2" stroke-dasharray="3,3" opacity="0.9"/>`
  );
}
