/**
 * modal.js — detail view and freeform ingest prompt.
 *
 * Two modes:
 *   openDetail()       — row detail view with editable fields
 *   openIngestPrompt() — freeform text input for a pipeline action
 *
 * The detail view is built from the sheet's view.sections declaration.
 * The ingest prompt is a single textarea — the renderer doesn't interpret
 * what the text means. The processor does.
 */

import { formInput } from './fields.js';

let _activeDialog = null;

function _openDialog(dialog) {
  if (_activeDialog) {
    _activeDialog.remove();
    _activeDialog = null;
  }
  _activeDialog = dialog;
  document.body.appendChild(dialog);

  dialog.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') dialog.close();
  });
  dialog.addEventListener('close', () => {
    dialog.remove();
    if (_activeDialog === dialog) _activeDialog = null;
  });
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close();
  });

  dialog.showModal();
}

// --- Detail view ---

export function openDetail(sheet, rowId, rowData, callbacks) {
  const dialog = document.createElement('dialog');
  _buildDetailDialog(dialog, sheet, rowId, rowData, callbacks);
  _openDialog(dialog);
}

function _buildDetailDialog(dialog, sheet, rowId, rowData, callbacks) {
  const fields = sheet.fields || [];
  const view = sheet.view || {};
  const notesFieldName = view.notes_field || null;

  dialog.innerHTML = `
    <header>
      <span>${_esc(rowData.id || rowId)}</span>
      <button class="close" aria-label="Close">\u00d7</button>
    </header>
    <div class="dialog-body"></div>
  `;

  const body = dialog.querySelector('.dialog-body');

  if (view.sections && view.sections.length > 0) {
    for (const section of view.sections) {
      const sec = document.createElement('section');
      sec.innerHTML = `<h3>${_esc(section.label)}</h3>`;
      for (const fname of (section.fields || [])) {
        if (fname === notesFieldName) continue;
        const field = fields.find(f => f.name === fname);
        if (field) sec.appendChild(_fieldRow(field, rowData[fname]));
      }
      body.appendChild(sec);
    }
  } else {
    for (const field of fields) {
      if (field.type === 'primary' || field.name === notesFieldName) continue;
      body.appendChild(_fieldRow(field, rowData[field.name]));
    }
  }

  if (notesFieldName) {
    const notesField = fields.find(f => f.name === notesFieldName);
    if (notesField) {
      const sec = document.createElement('section');
      sec.innerHTML = `<h3>${_esc(notesField.label || notesFieldName)}</h3>`;
      sec.appendChild(_fieldRow(notesField, rowData[notesFieldName]));
      body.appendChild(sec);
    }
  }

  // Wire change events — driven by field type
  dialog.querySelectorAll('[data-field]').forEach(el => {
    const fname = el.dataset.field;
    const field = fields.find(f => f.name === fname);
    if (!field) return;
    if (field.type === 'log' || field.type === 'datetime' || field.type === 'primary') return;

    el.addEventListener('change', () => {
      let value = el.type === 'checkbox' ? el.checked : el.value;
      if (field.type === 'boolean') {
        value = el.type === 'checkbox' ? el.checked : value === 'true';
      } else if (field.type === 'number') {
        value = value === '' ? null : Number(value);
      }
      callbacks.onSetField(rowId, fname, value);
    });
  });

  // Wire log entry inputs — Enter submits to /api/ingest
  dialog.querySelectorAll('.log-add').forEach(input => {
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const text = input.value.trim();
      if (!text) return;
      e.preventDefault();
      callbacks.onIngest('LOG', { row_id: rowId, text });
      input.value = '';
      dialog.close();
    });
  });

  dialog.querySelector('button.close').addEventListener('click', () => dialog.close());
}

function _fieldRow(field, value) {
  const row = document.createElement('div');
  row.className = 'field-row';

  const label = document.createElement('div');
  label.className = 'field-label';
  label.textContent = field.label || field.name;

  const valueDiv = document.createElement('div');
  valueDiv.className = 'field-value';
  valueDiv.innerHTML = formInput(field, value);

  row.appendChild(label);
  row.appendChild(valueDiv);
  return row;
}

// --- Freeform ingest prompt ---
// A single textarea. The kind and context are already known.
// The renderer doesn't interpret the text — the processor does.

export function openIngestPrompt(kind, spec, rowId, callbacks) {
  const dialog = document.createElement('dialog');
  const desc = spec.description || kind;

  dialog.innerHTML = `
    <header>
      <span>${_esc(desc)}</span>
      <button class="close" aria-label="Close">\u00d7</button>
    </header>
    <div class="dialog-body">
      <textarea id="ingest-text" placeholder="Type or paste content…" autofocus></textarea>
    </div>
    <footer>
      <button class="secondary btn-close">Cancel</button>
      <button id="ingest-submit">Submit</button>
    </footer>
  `;

  const textarea = dialog.querySelector('#ingest-text');

  function submit() {
    const text = textarea.value.trim();
    if (!text) return;
    const payload = { text };
    if (rowId) payload.row_id = rowId;
    callbacks.onIngest(kind, payload);
    dialog.close();
  }

  dialog.querySelector('#ingest-submit').addEventListener('click', submit);
  dialog.querySelector('.btn-close').addEventListener('click', () => dialog.close());
  dialog.querySelector('button.close').addEventListener('click', () => dialog.close());

  // Shift+Enter or Ctrl+Enter submits (Enter alone is newline in textarea)
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.shiftKey || e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    }
  });

  _openDialog(dialog);

  // Focus textarea after dialog opens
  requestAnimationFrame(() => textarea.focus());
}

// --- Search ---
// Single input. Shows current filter if active, with a clear button.
// Enter applies, Escape cancels.

export function openSearch(currentQuery, callbacks) {
  const dialog = document.createElement('dialog');
  const hasQuery = currentQuery && currentQuery.length > 0;

  dialog.innerHTML = `
    <header>
      <span>Search</span>
      <button class="close" aria-label="Close">\u00d7</button>
    </header>
    <div class="dialog-body">
      ${hasQuery ? `<div class="search-active">Filtering: <strong>${_esc(currentQuery)}</strong> <button class="search-clear">Clear</button></div>` : ''}
      <input id="search-input" type="text" placeholder="Filter rows…" value="${_esc(currentQuery || '')}" autofocus>
    </div>
    <footer>
      <button class="secondary btn-close">Cancel</button>
      <button id="search-submit">Search</button>
    </footer>
  `;

  const input = dialog.querySelector('#search-input');

  function apply(query) {
    callbacks.onSearch(query);
    dialog.close();
  }

  dialog.querySelector('#search-submit').addEventListener('click', () => apply(input.value.trim()));
  dialog.querySelector('.btn-close').addEventListener('click', () => dialog.close());
  dialog.querySelector('button.close').addEventListener('click', () => dialog.close());

  const clearBtn = dialog.querySelector('.search-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => apply(''));
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      apply(input.value.trim());
    }
  });

  _openDialog(dialog);
  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });
}

// --- Helpers ---

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
