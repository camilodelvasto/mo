// _dom-shim.mjs — the hand DOM the chat.js behavioural tests mount into (no jsdom).
// Importing it installs document/window/sessionStorage globals. Shared by
// test_chat-stop.mjs and test_chat-attach-mount.mjs.
export const SCROLL_CALLS = [];
function detach(node) {
  const p = node && node.parentNode;
  if (!p || !Array.isArray(p.children)) return;
  const i = p.children.indexOf(node);
  if (i >= 0) p.children.splice(i, 1);
  node.parentNode = null;
}

export function makeEl(tag) {
  const el = {
    tagName: String(tag).toUpperCase(),
    _class: '', dataset: {}, style: {}, _attrs: {}, _listeners: {}, children: [], parentNode: null,
    rows: 0, type: '', disabled: false, value: '',
    scrollHeight: 0, scrollTop: 0, clientHeight: 0,
    get className() { return this._class; }, set className(v) { this._class = v; },
    classList: {
      _el: null,
      add(...c) { const s = new Set(this._el._class.split(' ').filter(Boolean)); c.forEach(x => s.add(x)); this._el._class = [...s].join(' '); },
      remove(...c) { const s = new Set(this._el._class.split(' ').filter(Boolean)); c.forEach(x => s.delete(x)); this._el._class = [...s].join(' '); },
      contains(c) { return this._el._class.split(' ').includes(c); },
      toggle(c) { this.contains(c) ? this.remove(c) : this.add(c); },
    },
    get textContent() { return this._text === undefined ? '' : this._text; }, set textContent(v) { this._text = String(v); this.children = []; },
    set innerHTML(v) { this._html = String(v); }, get innerHTML() { return this._html === undefined ? '' : this._html; },
    setAttribute(k, v) { this._attrs[k] = String(v); }, getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
    hasAttribute(k) { return k in this._attrs; },
    // Real DOM semantics: inserting a node MOVES it out of its previous parent.
    // Without this a node appended twice stays reachable from both, and a tree walk
    // counts it twice.
    appendChild(c) { detach(c); c.parentNode = this; this.children.push(c); return c; },
    append(...ns) { ns.forEach(n => { if (n && typeof n === 'object') { detach(n); n.parentNode = this; } this.children.push(n); }); },
    insertBefore(n, ref) { detach(n); n.parentNode = this; const i = this.children.indexOf(ref); i < 0 ? this.children.push(n) : this.children.splice(i, 0, n); return n; },
    replaceChildren(...ns) { this.children.forEach(c => c && typeof c === 'object' && (c.parentNode = null)); this.children = []; ns.forEach(n => { if (n && typeof n === 'object') { detach(n); n.parentNode = this; } this.children.push(n); }); },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    addEventListener(ev, fn, opts) { (this._listeners[ev] ||= []).push(fn); if (opts && opts.signal && opts.signal.addEventListener) opts.signal.addEventListener('abort', () => this.removeEventListener(ev, fn)); },
    removeEventListener(ev, fn) { this._listeners[ev] = (this._listeners[ev] || []).filter(f => f !== fn); },
    dispatchEvent(ev) { ev.target ||= this; (this._listeners[ev.type] || []).forEach(fn => fn(ev)); return !ev.defaultPrevented; },
    focus() { document.activeElement = this; }, scrollIntoView() { SCROLL_CALLS.push({ el: this }); },
    showModal() { this._open = true; }, close() { this._open = false; this.dispatchEvent({ type: 'close' }); },
    requestSubmit() { this.dispatchEvent({ type: 'submit', preventDefault() { this.defaultPrevented = true; } }); },
    closest(sel) { let n = this; while (n) { if (elMatches(n, sel)) return n; n = n.parentNode; } return null; },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { const out = []; findAll(this, sel, out); return out; },
  };
  el.classList._el = el;
  return el;
}
const camel = (a) => a.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function elMatches(node, sel) {
  if (!node.dataset) return false;
  if (sel.includes('data-chat-root')) {
    const rootOk = node.dataset.chatRoot !== undefined;
    return sel.includes(':not([data-mounted])') ? rootOk && node.dataset.mounted === undefined : rootOk;
  }
  if (sel.startsWith('.')) return typeof node._class === 'string' && node._class.split(' ').includes(sel.slice(1));
  if (sel.startsWith('[')) return node.dataset[camel(sel.slice(1, -1).split('=')[0])] !== undefined;
  return false;
}
export function find(node, sel) { for (const c of node.children || []) { if (c && elMatches(c, sel)) return c; const r = c && c.children && find(c, sel); if (r) return r; } return null; }
export function findAll(node, sel, out) { for (const c of node.children || []) { if (c && elMatches(c, sel)) out.push(c); if (c && c.children) findAll(c, sel, out); } }

export const MAIN = makeEl('div'); MAIN._attrs.id = 'main';
export const CONFIG_EL = makeEl('script'), STRINGS_EL = makeEl('script');
const byId = { main: MAIN, 'chat-config': CONFIG_EL, 'strings-data': STRINGS_EL };
globalThis.document = {
  getElementById: (id) => (id in byId ? byId[id] : null), createElement: (t) => makeEl(t),
  querySelector: (sel) => find(MAIN, sel), querySelectorAll: (sel) => { const out = []; findAll(MAIN, sel, out); return out; },
  body: makeEl('body'),
  _listeners: {},
  addEventListener(ev, fn, opts) { (this._listeners[ev] ||= []).push(fn); if (opts && opts.signal && opts.signal.addEventListener) opts.signal.addEventListener('abort', () => this.removeEventListener(ev, fn)); },
  removeEventListener(ev, fn) { this._listeners[ev] = (this._listeners[ev] || []).filter(f => f !== fn); },
  dispatchEvent(ev) { ev.target ||= this; [...(this._listeners[ev.type] || [])].forEach(fn => fn(ev)); return !ev.defaultPrevented; },
};
globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {},
  location: { pathname: '/hub/advisor', search: '', hash: '' },
  history: { pushState() {}, replaceState() {} }, navigator: { onLine: true },
};
globalThis.location = window.location; globalThis.history = window.history;
try { Object.defineProperty(globalThis, 'navigator', { value: window.navigator, configurable: true }); } catch {}
globalThis.matchMedia = window.matchMedia;
globalThis.sessionStorage = { _m: {}, getItem(k) { return k in this._m ? this._m[k] : null; }, setItem(k, v) { this._m[k] = String(v); }, removeItem(k) { delete this._m[k]; } };
globalThis.MutationObserver = class { observe() {} disconnect() {} };

export const tick = () => new Promise(r => setTimeout(r, 0));
