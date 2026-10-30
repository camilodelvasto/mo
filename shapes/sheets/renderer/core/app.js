/**
 * app.js — orchestrator. Boot, SSE, state, keymap.
 *
 * Every keyboard binding is derived from the sheet declaration.
 * The renderer does not interpret pipeline kinds or field semantics —
 * it reads what the declaration says and maps it to UI actions.
 */

import { applyTokens } from './tokens.js';
import { createTable, updateData, updateColumns, getFocusedRowId, getFocusedFieldName, editFocusedCell } from './table.js';

// --- State ---

let sheet = null;
let table = null;
let allRows = [];
let showHidden = false;
let searchQuery = '';

// --- Boot ---

async function boot() {
  const [sheetResp, rowsResp] = await Promise.all([
    fetch('/api/sheet'),
    fetch('/api/rows'),
  ]);

  if (!sheetResp.ok) throw new Error(`/api/sheet: ${sheetResp.status}`);
  if (!rowsResp.ok) throw new Error(`/api/rows: ${rowsResp.status}`);

  sheet = await sheetResp.json();
  allRows = await rowsResp.json();

  await applyTokens();

  document.title = sheet.title || 'sheets';

  _buildShell();

  const tableEl = document.getElementById('table');
  table = createTable(tableEl, sheet, filterRows(allRows), {
    onSetField,
    onOpenDetail,
    onLogAppend,
  });

  _updateStatusBar();
  _connectSSE();
  _startHeartbeat();
  _bindKeys();
}

// --- Shell ---

function _buildShell() {
  const app = document.getElementById('app');
  app.innerHTML = `
    <h1>${_esc(sheet.title || 'sheets')}</h1>
    <div id="table"></div>
    <div id="status-bar"></div>
  `;
}

// --- Filtering ---

export function filterRows(rows) {
  let result = rows;

  const visField = sheet && sheet.view && sheet.view.visibility_field;
  if (visField && !showHidden) {
    result = result.filter(r => {
      const v = r[visField];
      return !(v === true || v === 1 || v === 'true' || v === '1');
    });
  }

  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(row =>
      Object.values(row).some(v =>
        v != null && String(v).toLowerCase().includes(q)
      )
    );
  }

  return result;
}

// --- Callbacks ---

async function onSetField(rowId, fieldName, value, fieldType) {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z');

  // Log fields append; everything else updates
  const body = fieldType === 'log'
    ? { op: 'append', id: rowId, field: fieldName, entry: { ts: now, by: '', text: String(value) }, ts: now }
    : { op: 'update', id: rowId, values: { [fieldName]: value }, ts: now };

  try {
    const resp = await fetch('/api/entries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      _isDisconnected = true;
      _showDisconnected();
    }
  } catch (e) {
    _isDisconnected = true;
    _showDisconnected();
  }
}

function onLogAppend(rowId, fieldName) {
  // Find the pipeline input that targets this log field (op: append, target_field: fieldName)
  const inputs = (sheet.pipeline && sheet.pipeline.inputs) || {};
  for (const [kind, spec] of Object.entries(inputs)) {
    if (spec.op === 'append' && spec.target_field === fieldName) {
      onPipelineAction(kind, spec, rowId);
      return;
    }
  }
}

function onOpenDetail(rowId) {
  const row = rowId ? (allRows.find(r => r.id === rowId) || null) : null;
  import('./modal.js').then(({ openDetail }) => {
    openDetail(sheet, rowId, row, { onSetField, onIngest });
  });
}

async function onIngest(kind, payload) {
  await fetch('/api/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, payload }),
  });
}

/**
 * Open a freeform text modal for a pipeline action.
 * The modal collects text, the kind and context are known from the declaration.
 */
function onPipelineAction(kind, spec, rowId) {
  import('./modal.js').then(({ openIngestPrompt }) => {
    openIngestPrompt(kind, spec, rowId, { onIngest });
  });
}

/**
 * Run the declared action on a field (e.g., action: open → open URL).
 */
function onFieldAction(field, rowId) {
  const row = allRows.find(r => r.id === rowId);
  if (!row) return;
  const value = row[field.name];
  if (!value) return;

  if (field.action === 'open') {
    window.open(String(value), '_blank');
  }
}

// --- Status bar ---

function _updateStatusBar() {
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  const visible = filterRows(allRows).length;
  const total = allRows.length;
  const hidden = total - visible;
  const parts = [`${visible} rows`];
  if (hidden > 0) parts.push(`${hidden} hidden`);
  if (searchQuery) parts.push(`search: "${searchQuery}"`);
  bar.textContent = parts.join(' · ');
}

// --- Connection health ---

let _sseDebounceTimer = null;
let _disconnectTimer = null;
let _es = null;
let _isDisconnected = false;
let _heartbeatInterval = null;

function _startHeartbeat() {
  _heartbeatInterval = setInterval(async () => {
    try {
      const resp = await fetch('/api/rows');
      if (!resp.ok) throw new Error(resp.status);
      if (_isDisconnected) {
        _isDisconnected = false;
        _hideDisconnected();
        await _fullRefresh();
      }
    } catch (e) {
      if (!_isDisconnected) {
        _isDisconnected = true;
        _showDisconnected();
      }
    }
  }, 5000);
}

function _connectSSE() {
  _es = new EventSource('/api/events');

  function _onMessage() {
    // Any successful message means we're connected
    clearTimeout(_disconnectTimer);
    if (_isDisconnected) {
      _isDisconnected = false;
      _hideDisconnected();
      _fullRefresh();
    }
  }

  _es.addEventListener('rows', () => {
    _onMessage();
    clearTimeout(_sseDebounceTimer);
    _sseDebounceTimer = setTimeout(async () => {
      const resp = await fetch('/api/rows');
      if (!resp.ok) return;
      allRows = await resp.json();
      updateData(table, filterRows(allRows));
      _updateStatusBar();
    }, 50);
  });

  _es.addEventListener('sheet', async () => {
    _onMessage();
    const resp = await fetch('/api/sheet');
    if (!resp.ok) return;
    sheet = await resp.json();
    document.title = sheet.title || 'sheets';
    updateColumns(table, sheet, { onSetField, onOpenDetail, onLogAppend });
  });

  _es.addEventListener('tokens', async () => {
    _onMessage();
    await applyTokens();
  });

  _es.onerror = () => {
    // EventSource retries on its own. Heartbeat handles disconnect detection.
  };
}

function _showDisconnected() {
  const banner = document.getElementById('disconnected-banner');
  if (banner) banner.style.display = 'block';
  const tableEl = document.querySelector('.tabulator');
  if (tableEl) {
    tableEl.style.pointerEvents = 'none';
    tableEl.style.opacity = '0.5';
  }
}

function _hideDisconnected() {
  const banner = document.getElementById('disconnected-banner');
  if (banner) banner.style.display = 'none';
  const tableEl = document.querySelector('.tabulator');
  if (tableEl) {
    tableEl.style.pointerEvents = '';
    tableEl.style.opacity = '';
  }
}

// No manual retry needed — EventSource retries natively.
// _onMessage() detects reconnection and triggers _fullRefresh().

async function _fullRefresh() {
  try {
    const sheetResp = await fetch('/api/sheet');
    if (sheetResp.ok) {
      sheet = await sheetResp.json();
      document.title = sheet.title || 'sheets';
      updateColumns(table, sheet, { onSetField, onOpenDetail, onLogAppend });
    }
  } catch (e) {}

  try {
    await applyTokens();
  } catch (e) {}

  try {
    const rowsResp = await fetch('/api/rows');
    if (rowsResp.ok) {
      allRows = await rowsResp.json();
      updateData(table, filterRows(allRows));
      _updateStatusBar();
    }
  } catch (e) {}
}

// --- Keys ---
// Every binding is derived from the sheet declaration.
// The renderer reads field.key, field.action, pipeline.inputs[].key,
// and pipeline.inputs[].context to decide what each key does.

function _bindKeys() {
  document.addEventListener('keydown', (e) => {
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (e.target.isContentEditable) return;
    if (document.querySelector('dialog[open]')) return;
    // Don't intercept keys while a Tabulator editor is open (e.g., list dropdown)
    if (document.querySelector('.tabulator-editing, .tabulator-edit-list')) return;

    const key = e.key;
    const rowId = getFocusedRowId();
    const fieldName = getFocusedFieldName();

    // Enter on log fields — Tabulator can't handle these (editor: false)
    // All other fields: let Tabulator's native enter handling work
    if (key === 'Enter' && rowId && fieldName) {
      const field = sheet.fields.find(f => f.name === fieldName);
      if (field && field.type === 'log') {
        e.preventDefault();
        editFocusedCell();
        return;
      }
      // Don't preventDefault — let Tabulator handle enter for editable fields
    }

    // Renderer capabilities — keys declared in sheet.keys
    const keys = sheet.keys;

    if (keys.search && key === keys.search) {
      e.preventDefault();
      import('./modal.js').then(({ openSearch }) => {
        openSearch(searchQuery, {
          onSearch(q) {
            searchQuery = q;
            updateData(table, filterRows(allRows));
            _updateStatusBar();
          },
        });
      });
      return;
    }

    if (keys.toggle_hidden && key === keys.toggle_hidden && sheet.view && sheet.view.visibility_field) {
      e.preventDefault();
      showHidden = !showHidden;
      updateData(table, filterRows(allRows));
      _updateStatusBar();
      return;
    }

    if (keys.view && key === keys.view && rowId) {
      e.preventDefault();
      onOpenDetail(rowId);
      return;
    }

    if (keys.open && key === keys.open && rowId) {
      const field = sheet.fields.find(f => {
        // If a cell is focused and that field has an action, use it
        if (fieldName && f.name === fieldName && f.action) return true;
        return false;
      }) || sheet.fields.find(f => f.action); // fallback: first field with action
      if (field) {
        e.preventDefault();
        onFieldAction(field, rowId);
        return;
      }
    }

    // Boolean field keys (driven by field.key + field.type === 'boolean')
    if (rowId && sheet.fields) {
      for (const field of sheet.fields) {
        if (field.key === key && field.type === 'boolean') {
          e.preventDefault();
          const row = allRows.find(r => r.id === rowId);
          if (!row) return;
          const current = row[field.name];
          const next = !(current === true || current === 1 || current === 'true');
          onSetField(rowId, field.name, next);
          return;
        }
      }
    }

    // Pipeline input keys (driven by pipeline.inputs[].key + .context)
    const inputs = sheet.pipeline && sheet.pipeline.inputs;
    if (inputs) {
      for (const [kind, spec] of Object.entries(inputs)) {
        if (spec.key !== key) continue;
        e.preventDefault();
        const ctx = spec.context || {};

        // context.cell: required → edit the focused cell inline
        if (ctx.cell) {
          if (rowId && fieldName) editFocusedCell();
          return;
        }

        // context.row_id: required → needs a selected row
        if (ctx.row_id && !rowId) return;

        // Open freeform text prompt for this kind
        onPipelineAction(kind, spec, ctx.row_id ? rowId : null);
        return;
      }
    }
  });
}

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// --- Entry point ---

boot().catch(err => {
  document.body.innerHTML = `<pre style="color:#e74c3c;padding:24px">${err}</pre>`;
});
