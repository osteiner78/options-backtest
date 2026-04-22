/**
 * Render a `table.dt` with a declarative column + row model.
 * columns: [{ key, label, align: 'left'|'right', headerClass }]
 * rows: [{ cls?: 'bld'|'sub'|'tot', cells: { [key]: { value, cls } } }]
 */
export function renderDataTable({ columns, rows }) {
  const thead = `<thead><tr>${columns
    .map(c => `<th class="${c.align === 'right' ? 'r' : ''}${c.headerClass ? ' ' + c.headerClass : ''}">${c.label ?? ''}</th>`)
    .join('')}</tr></thead>`;

  const tbody = `<tbody>${rows
    .map(row => {
      const rowCls = row.cls ? ` class="${row.cls}"` : '';
      const tds = columns
        .map(c => {
          const cell = row.cells?.[c.key] ?? {};
          const alignCls = c.align === 'right' ? 'r' : '';
          const cellCls = [alignCls, cell.cls].filter(Boolean).join(' ');
          return `<td class="${cellCls}">${cell.value ?? ''}</td>`;
        })
        .join('');
      return `<tr${rowCls}>${tds}</tr>`;
    })
    .join('')}</tbody>`;

  return `<table class="dt">${thead}${tbody}</table>`;
}
