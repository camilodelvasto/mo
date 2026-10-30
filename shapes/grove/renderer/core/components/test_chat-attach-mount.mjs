// Behavioural tests for the attach affordance's LIFECYCLE in chat.js: the policy is
// read from the box with the held secret, so on a gated chat it can only be read
// AFTER the gate accepts — reading it at mount (no secret yet) is a 401 and a chat
// that never shows the paperclip. Also: dropping a file anywhere on the page attaches
// it, not only on the composer. Run: node --test components/test_chat-attach-mount.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAIN, CONFIG_EL, STRINGS_EL, makeEl, find, tick } from './_dom-shim.mjs';

const POLICY = { accept: ['image'], max_count: 3, max_bytes: 5000000 };
let CALLS = [];
let GATED = false;                 // a gated box 401s anything without the bearer
let REVOKED = false;               // the box no longer accepts the held code
let HANG_ASK = false;              // the ask never answers (a turn in flight, to be stopped)
let POLICY_STATUS = 200;           // the box's answer to the policy read
let POLICY_BODY = { attachments: POLICY };
const NOT_JSON = Symbol('not-json');     // a 200 whose body does not parse
globalThis.fetch = async (url, opts = {}) => {
  const auth = opts.headers && opts.headers['Authorization'];   // undefined when the call carried none
  CALLS.push({ url, method: opts.method || 'GET', auth });
  if (url.endsWith('/check')) return { ok: true, status: 204 };
  if (url.endsWith('/policy')) {
    if (GATED && !auth) return { ok: false, status: 401 };
    if (POLICY_STATUS !== 200) return { ok: false, status: POLICY_STATUS };
    if (POLICY_BODY === NOT_JSON) return { ok: true, status: 200, json: async () => { throw new SyntaxError('not JSON'); } };
    return { ok: true, status: 200, json: async () => POLICY_BODY };
  }
  if (url.includes('/verify/')) {
    if (REVOKED) return { ok: false, status: 401 };
    return { ok: true, status: 200, json: async () => ({ data: 'aW1n', signature: 's', media_type: 'image/webp', bytes: 3 }) };
  }
  if (url.includes('/ask/') && HANG_ASK) return new Promise(() => {});
  throw new Error('unexpected fetch ' + url);
};
// node's own crypto.subtle serves sha256Hex

STRINGS_EL._text = JSON.stringify(Object.fromEntries(
  ['chat_input_placeholder', 'chat_send', 'chat_stop', 'chat_working', 'chat_sources', 'chat_error_failed',
   'chat_unavailable', 'chat_offline', 'chat_gate_prompt', 'gate_label', 'chat_gate_submit', 'chat_gate_rejected',
   'chat_attach', 'chat_attach_remove', 'chat_attach_wrong_type', 'chat_attach_too_large', 'chat_attach_too_many',
   'chat_attach_failed', 'chat_attach_missing', 'chat_attach_not_saved', 'chat_attach_unavailable', 'chat_revoked'].map(k => [k, k])));

const { init } = await import('./chat.js');

// `secret` is a code already held in this tab (a reload after the gate accepted): the
// chat boots straight to input and reads the policy with it.
async function mount({ gate, remount = false, policyStatus = 200, policyBody = { attachments: POLICY }, secret }) {
  GATED = !!gate; REVOKED = false; HANG_ASK = false; CALLS = []; MAIN.children = []; sessionStorage._m = {};
  POLICY_STATUS = policyStatus; POLICY_BODY = policyBody;
  if (secret) sessionStorage.setItem('grove-chat-secret:/hub/mira/', secret);
  if (!remount) document._listeners = {};   // a remount keeps whatever the previous mount left on the page
  CONFIG_EL._text = JSON.stringify({ endpoint: 'https://relay.test/api',
    gate: gate ? { scheme: 'access-code', check: 'https://relay.test/api/check' } : undefined,
    chats: { '/hub/mira/': { ask: 'mira', persist: 'none' } } });
  window.location.pathname = '/hub/mira';
  const root = makeEl('div');
  root.dataset.chatRoot = ''; root.dataset.ask = 'mira'; root.dataset.route = '/hub/mira/';
  MAIN.appendChild(root);
  init();
  await tick(); await tick(); await tick();
  return root;
}
const clip = () => find(MAIN, '.chat-attach');
const policyCalls = () => CALLS.filter(c => c.url.endsWith('/policy'));

test('ungated chat: policy read at mount, paperclip present', async () => {
  await mount({ gate: false });
  assert.ok(clip(), 'paperclip in the composer');
  assert.equal(policyCalls().length, 1);
});

test('gated chat: policy is read with the secret AFTER the gate accepts — paperclip appears', async () => {
  await mount({ gate: true });
  assert.ok(find(MAIN, '.gate-form'), 'gate shown first');
  assert.equal(policyCalls().filter(c => !c.auth).length, 0, 'never asks the box for the policy without the secret');
  const gform = find(MAIN, '.gate-form');
  gform.querySelector('.gate-form') ;                     // (no-op; keeps shim honest)
  const codeInput = gform.children[0].children[0];       // label > input
  codeInput.value = 'dev-local';
  gform.dispatchEvent({ type: 'submit', preventDefault() {} });
  await tick(); await tick(); await tick();
  assert.equal(sessionStorage.getItem('moui-chat-secret') || Object.values(sessionStorage._m)[0], 'dev-local');
  assert.ok(clip(), 'paperclip after the gate accepted');
  const authed = policyCalls().filter(c => c.auth === 'Bearer dev-local');
  assert.equal(authed.length, 1, 'exactly one policy read, with the secret');
});

test('a file dropped anywhere on the page attaches (not only on the composer)', async () => {
  await mount({ gate: false });
  const file = { size: 3, type: 'image/jpeg', arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  let prevented = false;
  document.dispatchEvent({ type: 'dragover', preventDefault() { prevented = true; }, dataTransfer: { types: ['Files'] } });
  assert.ok(prevented, 'dragover on the document is claimed so the browser will not navigate');
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file] } });
  await tick(); await tick(); await tick();
  assert.ok(CALLS.some(c => c.url.includes('/verify/mira')), 'the dropped file went to /verify');
  assert.ok(find(MAIN, '.chat-attach-thumb'), 'thumbnail in the tray');
});

test('a sent turn renders its image as a block ABOVE the text, not a thumbnail below', async () => {
  await mount({ gate: false });
  const file = { size: 3, type: 'image/jpeg', arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file] } });
  await tick(); await tick(); await tick();
  // send the turn: the stream mock is not wired here, so stub the ask fetch to fail fast
  const input = find(MAIN, '.chat-input'); const send = find(MAIN, '.chat-send');
  input.value = 'qué hay en la foto';
  send.dispatchEvent({ type: 'click' });
  await tick(); await tick();
  const turn = find(MAIN, '.chat-turn-user');
  assert.ok(turn, 'user turn rendered');
  const kinds = turn.children.map(c => c.className);
  assert.deepEqual(kinds, ['chat-turn-attachments', ''], 'image block first, then the text <p>');
  assert.ok(find(turn, '.chat-turn-attachments').children.length === 1, 'one image');
});


const FILE = { size: 3, type: 'image/jpeg', arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
const dropOne = async () => {
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [FILE] } });
  await tick(); await tick(); await tick();
};
const verifies = () => CALLS.filter(c => c.url.includes('/verify/')).length;

test('remount does not stack page-drop listeners: one drop, one upload', async () => {
  await mount({ gate: false });
  await mount({ gate: false, remount: true });   // the router swapped the chat root: a fresh mount
  await mount({ gate: false, remount: true });
  CALLS = [];
  await dropOne();
  assert.equal(verifies(), 1, 'exactly one verify for one dropped file after three mounts');
  assert.equal(document.querySelectorAll('.chat-attach-thumb').length, 1);
});

test('a send that fails before the stream keeps the verified images in the tray', async () => {
  await mount({ gate: false });
  await dropOne();
  const input = find(MAIN, '.chat-input'); const send = find(MAIN, '.chat-send');
  input.value = 'hola';
  send.dispatchEvent({ type: 'click' });   // the ask fetch throws (unexpected fetch) → pre-stream failure
  await tick(); await tick(); await tick();
  assert.equal(find(MAIN, '.chat-attach-tray').children.length, 1, 'thumbnail still there');
});

test('stopping a turn keeps its verified images in the tray, like it keeps the question', async () => {
  await mount({ gate: false });
  await dropOne();
  HANG_ASK = true;
  const input = find(MAIN, '.chat-input'); const send = find(MAIN, '.chat-send');
  input.value = 'hola';
  send.dispatchEvent({ type: 'click' });
  await tick();
  assert.equal(send.getAttribute('aria-label'), 'chat_stop', 'turn in flight');
  send.dispatchEvent({ type: 'click' });   // stop
  await tick(); await tick();
  assert.equal(input.value, 'hola', 'question restored');
  assert.equal(find(MAIN, '.chat-attach-tray').children.length, 1, 'thumbnail still there');
});

test('a 401 from /verify re-gates like the ask path (a revoked code is not "try again")', async () => {
  await mount({ gate: true });
  const gform = find(MAIN, '.gate-form');
  gform.children[0].children[0].value = 'dev-local';
  gform.dispatchEvent({ type: 'submit', preventDefault() {} });
  await tick(); await tick(); await tick();
  assert.ok(clip(), 'paperclip after the gate');
  REVOKED = true;
  await dropOne();
  assert.ok(find(MAIN, '.gate-form'), 'gate shown again');
  assert.equal(sessionStorage.getItem('grove-chat-secret:/hub/mira/'), null, 'held secret dropped');
  assert.equal(document.querySelectorAll('.chat-attach-thumb').length, 0);
});

const errors = () => [...MAIN.querySelectorAll('.chat-turn-error')].map((e) => e.textContent);

test('a failed policy read is said — never a silent text-only chat', async () => {
  await mount({ gate: false, policyStatus: 500 });
  assert.ok(!clip(), 'no paperclip for a capability we could not confirm');
  assert.deepEqual(errors(), ['chat_attach_unavailable']);
});

test('a policy response without an attachments field is said, not read as text-only', async () => {
  await mount({ gate: false, policyBody: {} });
  assert.ok(!clip());
  assert.deepEqual(errors(), ['chat_attach_unavailable']);
});

test('a policy response that is not JSON is said, and the chat still mounts', async () => {
  await mount({ gate: false, policyBody: NOT_JSON });
  assert.ok(!clip());
  assert.deepEqual(errors(), ['chat_attach_unavailable']);
  assert.ok(find(MAIN, '.chat-input'), 'text chat still usable');
});

test("the box's explicit attachments: null is text-only by declaration — nothing to say", async () => {
  await mount({ gate: false, policyBody: { attachments: null } });
  assert.ok(!clip());
  assert.deepEqual(errors(), []);
});

test('a 401 on the policy read is a revoked code, not a missing capability', async () => {
  // A reload with a held code: the chat boots to input and reads the policy with it; the
  // box no longer accepts it. Same path as /verify's 401: drop the code, say so, re-gate.
  await mount({ gate: true, secret: 'old-code', policyStatus: 401 });
  const reads = policyCalls();
  assert.equal(reads.length, 1);
  assert.equal(reads[0].auth, 'Bearer old-code', 'the policy read carried the held code');
  assert.deepEqual(errors(), ['chat_revoked'], 'revoked, not "images unavailable"');
  assert.ok(find(MAIN, '.gate-form'), 'gate shown again');
  assert.equal(sessionStorage.getItem('grove-chat-secret:/hub/mira/'), null, 'held code dropped');
  assert.ok(!clip());
});

// After an image is picked, dropped, or the picker is cancelled, the caret goes back to
// the composer: focus left on the paperclip turns the next Enter into "open the picker
// again" instead of "send".
test('after a drop the composer has focus, so Enter sends', async () => {
  await mount({ gate: false });
  document.activeElement = find(MAIN, '.chat-attach');
  const file = { size: 3, type: 'image/jpeg', arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file] } });
  assert.equal(document.activeElement, find(MAIN, '.chat-input'));
});

test('a picked or cancelled file dialog hands focus back through onPicked', async () => {
  const { createAttachTray } = await import('./chat-attach.js');
  let picked = 0;
  const tray = createAttachTray({ endpoint: 'https://relay.test/api', ask: 'mira', policy: POLICY,
    secretProvider: () => null, onError() {}, onRevoked() {}, onPicked: () => { picked++; } });
  tray.input.files = [];
  tray.input.dispatchEvent({ type: 'change' });
  tray.input.dispatchEvent({ type: 'cancel' });
  assert.equal(picked, 2);
});

test('a tray without onPicked is refused — focus handling is not optional', async () => {
  const { createAttachTray } = await import('./chat-attach.js');
  assert.throws(() => createAttachTray({ endpoint: 'x', ask: 'mira', policy: POLICY,
    secretProvider: () => null, onError() {}, onRevoked() {} }), /onPicked/);
});
