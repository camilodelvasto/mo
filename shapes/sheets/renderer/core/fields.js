/**
 * fields.js — maps field definitions to Tabulator column config and modal HTML.
 *
 * No switch statements. Type-to-config mapping is data-driven.
 * Adding a new type = one entry in each map.
 */

// --- Tabulator column mapping ---

const COLUMN_MAP = {
  primary:  { visible: false, editor: false },
  string:   { editor: 'input', onEnter: 'edit' },
  number:   { sorter: 'number', hozAlign: 'right', editor: 'number', onEnter: 'edit' },
  boolean:  { hozAlign: 'center', editor: false, formatter: _boolToggleFormatter, cellClick: _boolToggleClick, onEnter: 'click' },
  enum:     { editor: 'list', onEnter: 'edit' },
  date:     { sorter: 'date', editor: 'input', onEnter: 'edit' },
  datetime: { editor: false },
  text:     { editor: 'textarea', onEnter: 'edit' },
  log:      { editor: false, formatter: _logFormatter, cellClick: _logCellClick, onEnter: 'click' },
};

/**
 * Maps a field object (from /api/sheet) to a partial Tabulator column definition.
 */
// Separate lookup for onEnter behavior — not a Tabulator property.
const _enterBehavior = {};

/**
 * Get the onEnter behavior for a field name.
 */
export function getEnterBehavior(fieldName) {
  return _enterBehavior[fieldName] || null;
}

export function tabulatorColumn(field) {
  const col = {
    title: field.label || field.name,
    field: field.name,
    resizable: false,
    formatter: 'textarea',
  };

  if (field.align) {
    col.hozAlign = field.align;
  }

  const typeConfig = COLUMN_MAP[field.type] || COLUMN_MAP.string;
  const { onEnter, ...tabulatorProps } = typeConfig;
  Object.assign(col, tabulatorProps);

  if (onEnter) {
    _enterBehavior[field.name] = onEnter;
  }

  // hozAlign from field declaration overrides the type default
  if (field.align) {
    col.hozAlign = field.align;
  }

  // enum needs values passed to editor
  if (field.type === 'enum' && field.values) {
    col.editorParams = { values: field.values };
  }

  return col;
}

// --- Modal input mapping ---

const INPUT_MAP = {
  enum:     (field, val) => {
    const options = (field.values || []).map(v => {
      const selected = v === val ? ' selected' : '';
      return `<option value="${_esc(v)}"${selected}>${_esc(v)}</option>`;
    }).join('');
    return `<select name="${_esc(field.name)}" data-field="${_esc(field.name)}">${options}</select>`;
  },

  boolean:  (field, val) => {
    const on = val === true || val === 'true' || val === 1;
    const checked = on ? ' checked' : '';
    return `<label class="toggle-label">
      <input type="checkbox" name="${_esc(field.name)}" data-field="${_esc(field.name)}"${checked}>
      <span class="toggle"><span class="toggle-knob"></span></span>
      <span class="toggle-text">${on ? 'On' : 'Off'}</span>
    </label>`;
  },

  text:     (field, val) => `<textarea name="${_esc(field.name)}" data-field="${_esc(field.name)}">${_esc(val)}</textarea>`,

  log:      (field, val) => {
    let entries;
    try {
      entries = val ? (typeof val === 'string' ? JSON.parse(val) : val) : [];
    } catch {
      entries = [];
    }
    let timeline = '';
    if (entries.length > 0) {
      const items = entries.map(e => {
        const ts = e.ts ? `<span class="log-ts">${_esc(e.ts)}</span>` : '';
        const text = e.text ? `<span class="log-text">${_esc(e.text)}</span>` : '';
        return `<div class="log-entry">${ts}${text}</div>`;
      }).join('');
      timeline = `<div class="log-timeline">${items}</div>`;
    }
    return `<div class="log-field-wrapper">${timeline}<input type="text" class="log-add" data-log-field="${_esc(field.name)}" placeholder="Add entry…"></div>`;
  },

  datetime: (field, val) => `<span class="readonly">${_esc(val)}</span>`,
  primary:  (field, val) => `<span class="readonly">${_esc(val)}</span>`,
};

const _defaultInput = (field, val) => `<input type="text" name="${_esc(field.name)}" data-field="${_esc(field.name)}" value="${_esc(val)}">`;

/**
 * Returns HTML string for a field in the detail modal.
 */
export function formInput(field, value) {
  const safeVal = value != null ? String(value) : '';
  const render = INPUT_MAP[field.type] || _defaultInput;
  return render(field, safeVal);
}

// --- Formatters ---

function _boolToggleFormatter(cell) {
  const val = cell.getValue();
  const on = val === true || val === 1 || val === 'true' || val === '1';
  const cls = on ? 'toggle on' : 'toggle';
  return `<span class="${cls}" role="switch" aria-checked="${on}"><span class="toggle-knob"></span></span>`;
}

function _boolToggleClick(e, cell) {
  const val = cell.getValue();
  const on = val === true || val === 1 || val === 'true' || val === '1';
  const table = cell.getTable();
  const cb = table._sheetOnSetField;
  if (cb) {
    const rowId = cell.getRow().getData().id;
    cb(rowId, cell.getColumn().getField(), !on);
  }
}

function _logCellClick(e, cell) {
  const table = cell.getTable();
  const cb = table._sheetOnLogAppend;
  if (cb) {
    const rowId = cell.getRow().getData().id;
    const fieldName = cell.getColumn().getField();
    cb(rowId, fieldName);
  }
}

function _logFormatter(cell) {
  const raw = cell.getValue();
  if (!raw) return '';

  let entries;
  try {
    entries = typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return '';
  }

  if (!Array.isArray(entries) || entries.length === 0) return '';

  const count = entries.length;
  const latest = entries[entries.length - 1];
  const latestText = (latest && latest.text) ? latest.text : '';
  const truncated = latestText.length > 60 ? latestText.slice(0, 60) + '…' : latestText;

  return `${count} | ${truncated}`;
}

/** HTML-escape a string. */
function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
