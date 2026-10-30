/**
 * table.js — the ONLY file that knows Tabulator exists.
 * All Tabulator interaction is encapsulated here.
 */

import { tabulatorColumn, getEnterBehavior } from './fields.js';

// --- Module state for keyboard navigation ---
let _focusedCell = null;
let _table = null;
let _callbacks = null;

/**
 * Build column definitions from sheet fields.
 */
function _buildColumns(sheet, callbacks) {
  return sheet.fields.map(field => {
    const col = tabulatorColumn(field);

    if (col.editor && col.editor !== false) {
      col.cellEdited = (cell) => {
        const rowId = cell.getRow().getData().id;
        callbacks.onSetField(rowId, field.name, cell.getValue(), field.type);
      };
    }

    return col;
  });
}

/**
 * Creates a Tabulator instance with cell-by-cell keyboard navigation.
 */
export function createTable(el, sheet, rows, callbacks) {
  const columns = _buildColumns(sheet, callbacks);
  const visibilityField = sheet.view && sheet.view.visibility_field;

  const table = new Tabulator(el, {
    data: rows,
    columns,
    layout: 'fitDataFill',
    height: 'calc(100vh - 80px)',
    index: 'id',
    reactiveData: false,
    selectable: false,
    rowFormatter: (row) => {
      if (visibilityField) {
        const data = row.getData();
        if (data[visibilityField] === true || data[visibilityField] === 1) {
          row.getElement().classList.add('row-dimmed');
        } else {
          row.getElement().classList.remove('row-dimmed');
        }
      }
    },
  });

  // Store callbacks and field definitions on the table for cellClick/edit handlers
  table._sheetOnSetField = callbacks.onSetField;
  table._sheetOnLogAppend = callbacks.onLogAppend;
  table._sheetFields = sheet.fields;

  _table = table;
  _callbacks = callbacks;

  // Double-click row opens detail
  table.on('rowDblClick', (_e, row) => {
    callbacks.onOpenDetail(row.getData().id);
  });

  // Click a cell to focus it
  table.on('cellClick', (_e, cell) => {
    _setFocusedCell(cell);
  });

  return table;
}

// --- Cell focus management ---

function _setFocusedCell(cell) {
  // Remove previous focus
  if (_focusedCell) {
    try {
      _focusedCell.getElement()?.classList.remove('cell-focused');
      _focusedCell.getRow().getElement()?.classList.remove('row-active');
    } catch { /* cell may have been removed by data update */ }
  }

  _focusedCell = cell;
  const cellEl = cell.getElement();
  if (cellEl) {
    cellEl.classList.add('cell-focused');
    cellEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  const rowEl = cell.getRow().getElement();
  if (rowEl) rowEl.classList.add('row-active');
}

// --- Document-level keyboard navigation ---

document.addEventListener('keydown', (e) => {
  if (!_table || !_focusedCell) return;

  // Don't intercept when editing a cell, inside a modal, or typing in an input
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.target.isContentEditable) return;
  if (document.querySelector('dialog[open]')) return;
  if (_table.element?.querySelector('.tabulator-editing')) return;

  const key = e.key;
  if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter'].includes(key)) return;

  e.preventDefault();

  if (key === 'Enter') {
    const fieldName = _focusedCell.getColumn().getField();
    const behavior = getEnterBehavior(fieldName);
    if (behavior === 'edit') _focusedCell.edit();
    else if (behavior === 'click') {
      const def = _focusedCell.getColumn().getDefinition();
      if (def.cellClick) def.cellClick(e, _focusedCell);
    }
    return;
  }

  const allRows = _table.getRows('active');
  const allCols = _table.getColumns().filter(c => c.isVisible());

  let rowPos, colPos;
  try {
    rowPos = allRows.findIndex(r => r === _focusedCell.getRow());
    const colField = _focusedCell.getColumn().getField();
    colPos = allCols.findIndex(c => c.getField() === colField);
  } catch {
    return; // focused cell no longer valid
  }

  let newRow = rowPos;
  let newCol = colPos;

  if (key === 'ArrowUp' && rowPos > 0) newRow = rowPos - 1;
  if (key === 'ArrowDown' && rowPos < allRows.length - 1) newRow = rowPos + 1;
  if (key === 'ArrowLeft' && colPos > 0) newCol = colPos - 1;
  if (key === 'ArrowRight' && colPos < allCols.length - 1) newCol = colPos + 1;

  if (newRow !== rowPos || newCol !== colPos) {
    const targetRow = allRows[newRow];
    const targetField = allCols[newCol].getField();
    const targetCell = targetRow.getCell(targetField);
    if (targetCell) _setFocusedCell(targetCell);
  }
});

/**
 * Replace all table data.
 */
export function updateData(table, rows) {
  // Preserve focus across data refresh — remember position, restore after replace
  let savedRowId = null;
  let savedField = null;
  if (_focusedCell) {
    try {
      savedRowId = _focusedCell.getRow().getData().id;
      savedField = _focusedCell.getColumn().getField();
    } catch { /* cell already gone */ }
  }

  table.replaceData(rows);
  _focusedCell = null;

  // Restore focus to same row/column if it still exists
  if (savedRowId && savedField) {
    try {
      const row = table.getRow(savedRowId);
      if (row) {
        const cell = row.getCell(savedField);
        if (cell) _setFocusedCell(cell);
      }
    } catch { /* row removed */ }
  }
}

/**
 * Rebuild columns from new declaration.
 */
export function updateColumns(table, sheet, callbacks) {
  const columns = _buildColumns(sheet, callbacks);
  table.setColumns(columns);
  table._sheetOnSetField = callbacks.onSetField;
  table._sheetOnLogAppend = callbacks.onLogAppend;
  table._sheetFields = sheet.fields;
  _callbacks = callbacks;
  _focusedCell = null;
}

/**
 * Get the ID of the row that has focus.
 */
export function getFocusedRowId() {
  if (!_focusedCell) return null;
  try {
    return _focusedCell.getRow().getData().id;
  } catch {
    return null;
  }
}

/**
 * Get the field name of the focused cell.
 */
export function getFocusedFieldName() {
  if (!_focusedCell) return null;
  try {
    return _focusedCell.getColumn().getField();
  } catch {
    return null;
  }
}

/**
 * Trigger inline edit on the focused cell (if editable).
 */
export function editFocusedCell() {
  if (!_focusedCell) return;
  const fieldName = _focusedCell.getColumn().getField();
  const field = _table && _table._sheetFields
    ? _table._sheetFields.find(f => f.name === fieldName)
    : null;

  // Log fields open the append modal instead of inline editing
  if (field && field.type === 'log') {
    const cb = _table._sheetOnLogAppend;
    if (cb) {
      const rowId = _focusedCell.getRow().getData().id;
      cb(rowId, fieldName);
    }
    return;
  }

  _focusedCell.edit();
}
