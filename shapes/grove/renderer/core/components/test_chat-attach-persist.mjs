// Persistence + GC for attachments, driven through the REAL storage path: chat.js →
// chat-store → chat-idb → chat-attachments, over an in-memory IndexedDB (_idb-shim).
// These are the steps plan 2 §7.4 asks a human to do in DevTools — a conversation that
// keeps its image across a reload, a blob whose bytes are gone, and a delete that must
// not take an image a second conversation still holds.
// Run: node --test components/test_chat-attach-persist.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resetIDB, dumpStore, failPuts } from './_idb-shim.mjs';
import { MAIN, CONFIG_EL, STRINGS_EL, makeEl, find, tick } from './_dom-shim.mjs';

const NS = '/hub/mira/';
const DB = 'grove-chat:' + NS;
const POLICY = { accept: ['image'], max_count: 3, max_bytes: 5000000 };

let VERIFY_BYTES = 'aW1n';                        // what the box returns for the next upload
let STREAM = null;                                // a test's own stream events; null → the complete one
const ASK_BODIES = [];                            // every /ask/ body as sent, parsed
let HOLD_ASK = null;                              // a promise the /ask/ fetch awaits: act mid-turn
globalThis.fetch = async (url, opts = {}) => {
  if (url.endsWith('/policy')) return { ok: true, status: 200, json: async () => ({ attachments: POLICY }) };
  if (url.includes('/verify/')) return { ok: true, status: 200,
    json: async () => ({ data: VERIFY_BYTES, signature: 'sig-' + VERIFY_BYTES, media_type: 'image/webp', bytes: 3 }) };
  if (url.includes('/ask/')) {                     // a complete stream: one token, a title, done
    ASK_BODIES.push(JSON.parse(opts.body));
    if (HOLD_ASK) await HOLD_ASK;
    const lines = (STREAM || [{ event: 'token', text: 'ok' }, { event: 'title', text: 'Sobre la imagen' }, { event: 'done' }])
      .map((e) => JSON.stringify(e) + '\n').join('');
    const bytes = new TextEncoder().encode(lines);
    let sent = false;
    return { ok: true, status: 200, body: { getReader: () => ({
      read: async () => (sent ? { done: true } : (sent = true, { value: bytes, done: false })),
      cancel: async () => {} }) } };
  }
  throw new Error('unexpected fetch ' + url);
};

STRINGS_EL._text = JSON.stringify(Object.fromEntries(
  ['chat_input_placeholder', 'chat_send', 'chat_stop', 'chat_working', 'chat_sources', 'chat_error_failed',
   'chat_unavailable', 'chat_offline', 'chat_attach', 'chat_attach_remove', 'chat_attach_wrong_type',
   'chat_attach_too_large', 'chat_attach_too_many', 'chat_attach_failed', 'chat_attach_missing',
   'chat_attach_not_saved', 'chat_attach_unavailable',
   'chat_revoked', 'chat_sidebar_label', 'chat_new', 'chat_delete', 'chat_untitled', 'chat_conversations',
   'chat_error_refused', 'chat_not_permitted', 'chat_gate_prompt', 'gate_label', 'chat_gate_submit',
   'chat_gate_rejected', 'chat_delete_confirm', 'chat_delete_cancel'].map((k) => [k, k])));
CONFIG_EL._text = JSON.stringify({ endpoint: 'https://relay.test/api',
  chats: { [NS]: { ask: 'mira', persist: 'local', name: 'Mira' } } });

// The chat owns its URL through the navigation contract, registered once at boot by
// app.js; the test registers the same contract over the shim's location/history.
const { registerNavigation } = await import('../navigation.js');
registerNavigation({
  navigate(route) { window.location.pathname = route; history.pushState(null, '', route); },
  buildHref: (route) => route,
  currentRoute: () => window.location.pathname.replace(/\/?$/, '/'),
  start() {},
  isInternal: () => true,
});

const { init } = await import('./chat.js');

async function mountAt(path) {
  MAIN.children = []; document._listeners = {}; document.body.children = [];
  window.location.pathname = path;
  const root = makeEl('div');
  root.dataset.chatRoot = ''; root.dataset.ask = 'mira'; root.dataset.route = NS;
  MAIN.appendChild(root);
  init();
  for (let i = 0; i < 12; i++) await tick();
  return root;
}
const file = () => ({ size: 3, type: 'image/jpeg', arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer });
async function dropAndSend(question) {
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file()] } });
  for (let i = 0; i < 6; i++) await tick();
  find(MAIN, '.chat-input').value = question;
  find(MAIN, '.chat-send').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 14; i++) await tick();
}
// Delete conversation `slug` the way a visitor does: the sidebar's trash button for
// that title, then the confirm in the modal.
async function deleteConversation(slug) {
  const title = records().find((r) => r.slug === slug).title;
  const items = MAIN.querySelectorAll('.chat-sidebar-item');
  const li = [...items].find((el) => find(el, '.chat-sidebar-select').textContent === title);
  assert.ok(li, 'the conversation is listed in the sidebar');
  find(li, '.chat-sidebar-delete').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 4; i++) await tick();
  const ok = document.body.querySelectorAll('.chat-delete-confirm-ok')[0];
  assert.ok(ok, 'the delete confirm is open');
  ok.dispatchEvent({ type: 'click' });
  for (let i = 0; i < 12; i++) await tick();
}

const records = () => dumpStore(DB, 'conversations');
const blobs = () => dumpStore(DB, 'attachments');

test('a sent image is persisted with its conversation and restored on reload', async () => {
  resetIDB(); VERIFY_BYTES = 'aW1n';
  await mountAt('/hub/mira');
  await dropAndSend('¿qué es esto?');
  assert.equal(records().length, 1, 'the conversation was named and stored');
  const rec = records()[0];
  assert.equal(rec.title, 'Sobre la imagen');
  assert.deepEqual(rec.turns[0].attachments.length, 1, 'the stored turn references its image by id');
  assert.equal(typeof rec.turns[0].attachments[0], 'string', 'records hold ids, not bytes');
  assert.equal(blobs().length, 1, 'the bytes live in the separate attachments store');

  // reload: mount fresh at the conversation's deep link
  await mountAt('/hub/mira/' + rec.slug);
  const imgs = MAIN.querySelectorAll('.chat-turn-attachments');
  assert.equal(imgs.length, 1, 'the restored user turn shows its image block');
  assert.equal(MAIN.querySelectorAll('.chat-turn-attachment-missing').length, 0);
});

test('a conversation whose blob is gone renders it as missing and refuses to send', async () => {
  resetIDB(); VERIFY_BYTES = 'aW1n';
  await mountAt('/hub/mira');
  await dropAndSend('¿qué es esto?');
  const slug = records()[0].slug;
  dumpStore(DB, 'attachments').length && (await import('./chat-attachments.js'))
    .removeAttachments(NS, [records()[0].turns[0].attachments[0]]);
  for (let i = 0; i < 6; i++) await tick();
  assert.equal(blobs().length, 0, 'bytes gone from this browser');

  await mountAt('/hub/mira/' + slug);
  assert.equal(MAIN.querySelectorAll('.chat-turn-attachment-missing').length, 1,
    'the turn says the image is no longer stored — never silently text-only');
  const log = find(MAIN, '.chat-log');
  find(MAIN, '.chat-input').value = 'y la esquina?';
  find(MAIN, '.chat-send').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 10; i++) await tick();
  const errs = MAIN.querySelectorAll('.chat-turn-error');
  assert.ok([...errs].some((e) => e.textContent === 'chat_attach_missing'),
    'the send is refused with the keyed string, not sent without the image');
});

test('a blob that cannot be stored keeps its record unwritten and says so', async () => {
  resetIDB(); VERIFY_BYTES = 'aW1n';
  await mountAt('/hub/mira');
  failPuts('attachments');
  await dropAndSend('¿qué es esto?');
  failPuts('attachments', false);
  assert.equal(records().length, 0, 'no record names a blob that is not stored');
  assert.ok([...MAIN.querySelectorAll('.chat-turn-error')].some((e) => e.textContent === 'chat_attach_not_saved'),
    'the visitor is told the conversation was not saved');
});

test('deleting one conversation keeps an image a second conversation still holds', async () => {
  resetIDB(); VERIFY_BYTES = 'c2hy';                 // the SAME bytes for both conversations
  await mountAt('/hub/mira');
  await dropAndSend('primera');
  const first = records()[0].slug;
  await mountAt('/hub/mira');            // fresh conversation, same image bytes
  await dropAndSend('segunda');
  assert.equal(records().length, 2);
  assert.equal(blobs().length, 1, 'content-addressed: one blob for identical bytes');

  await deleteConversation(first);
  assert.equal(records().length, 1, 'one conversation deleted');
  assert.equal(blobs().length, 1, 'the shared image survives — the other conversation still holds it');
});

test('deleting the last conversation holding an image collects it', async () => {
  resetIDB(); VERIFY_BYTES = 'b25l';                 // distinct bytes → its own content address
  await mountAt('/hub/mira');
  await dropAndSend('única');
  assert.equal(blobs().length, 1);
  await deleteConversation(records()[0].slug);
  assert.equal(records().length, 0);
  assert.equal(blobs().length, 0, 'no orphan bytes left behind');
});

test('a stream that ends done with no answer is a failure: no lone user turn, the image stays', async () => {
  resetIDB(); VERIFY_BYTES = 'dmFj'; ASK_BODIES.length = 0;
  await mountAt('/hub/mira');
  STREAM = [{ event: 'title', text: 'Vacía' }, { event: 'done' }];   // no token
  await dropAndSend('¿qué es esto?');
  STREAM = null;
  const errs = MAIN.querySelectorAll('.chat-turn-error');
  assert.ok([...errs].some((e) => e.textContent === 'chat_error_failed'), 'said as a failure');
  assert.equal(records().length, 0, 'nothing persisted for a turn with no answer');
  assert.equal(blobs().length, 0, 'no blob without a record');
  assert.equal(MAIN.querySelectorAll('.chat-attach-thumb').length, 1, 'the image stays in the tray');

  find(MAIN, '.chat-input').value = 'otra vez';
  find(MAIN, '.chat-send').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 14; i++) await tick();
  const resent = ASK_BODIES[ASK_BODIES.length - 1];
  assert.deepEqual(resent.history, [], 'the failed turn never entered the history');
  assert.equal(resent.attachments.length, 1, 'the pending image is sent with the retry');
  assert.deepEqual(records()[0].turns.map((t) => t.role), ['user', 'assistant']);
});

test('a whitespace-only answer is no answer: a failure, never a blank assistant turn', async () => {
  resetIDB(); VERIFY_BYTES = 'YmxrCg=='; ASK_BODIES.length = 0;
  await mountAt('/hub/mira');
  STREAM = [{ event: 'token', text: ' \n\t ' }, { event: 'title', text: 'En blanco' }, { event: 'done' }];
  await dropAndSend('¿qué es esto?');
  STREAM = null;
  const errs = MAIN.querySelectorAll('.chat-turn-error');
  assert.ok([...errs].some((e) => e.textContent === 'chat_error_failed'), 'said as a failure');
  assert.equal(records().length, 0, 'nothing persisted for a blank answer');
  assert.equal(MAIN.querySelectorAll('.chat-attach-thumb').length, 1, 'the image stays in the tray');

  find(MAIN, '.chat-input').value = 'otra vez';
  find(MAIN, '.chat-send').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 14; i++) await tick();
  assert.deepEqual(ASK_BODIES[ASK_BODIES.length - 1].history, [],
    'the blank turn never entered the history');
});

test('an image attached while a turn is in flight stays in the tray', async () => {
  resetIDB(); VERIFY_BYTES = 'aW1n';
  await mountAt('/hub/mira');
  let release; HOLD_ASK = new Promise((r) => { release = r; });
  await dropAndSend('primera');                   // A goes out; the answer (the default, non-empty) is held
  VERIFY_BYTES = 'Yg==';                          // B: distinct bytes, its own id
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file()] } });
  for (let i = 0; i < 6; i++) await tick();
  HOLD_ASK = null; release();
  for (let i = 0; i < 14; i++) await tick();
  assert.equal(records().length, 1, 'A\'s turn committed');
  const thumbs = MAIN.querySelectorAll('.chat-attach-thumb');
  assert.equal(thumbs.length, 1, 'B is still pending after A\'s turn committed');
});

// A record an older client stored: it committed the user turn even when the stream
// brought no answer, so a user turn can stand with no assistant turn after it.
async function seedLegacy(turns, blobsToStore = []) {
  const { put } = await import('./chat-idb.js');
  const { putAttachment } = await import('./chat-attachments.js');
  for (const b of blobsToStore) assert.ok(await putAttachment(NS, b));
  const rec = { id: 'legacy', title: 'Vieja', slug: 'vieja', turns, created: 1, updated: 1 };
  assert.ok(await put(NS, rec));
  return rec;
}

test('an old conversation with an unanswered turn is shown whole and still followed up', async () => {
  resetIDB(); ASK_BODIES.length = 0;
  await seedLegacy([
    { role: 'user', content: 'sin respuesta' },
    { role: 'user', content: 'otra' },
    { role: 'assistant', content: 'respondida' },
  ]);
  await mountAt('/hub/mira/vieja');
  assert.equal(MAIN.querySelectorAll('.chat-turn-user').length, 2, 'the unanswered turn still renders');
  find(MAIN, '.chat-input').value = 'y ahora?';
  find(MAIN, '.chat-send').dispatchEvent({ type: 'click' });
  for (let i = 0; i < 14; i++) await tick();
  assert.equal(ASK_BODIES.length, 1, 'the follow-up was sent');
  assert.deepEqual(ASK_BODIES[0].history, [
    { role: 'user', content: 'otra' },
    { role: 'assistant', content: 'respondida' },
  ], 'the wire history alternates: the unanswered turn is never sent');
  assert.deepEqual(records()[0].turns.map((t) => t.role), ['user', 'user', 'assistant', 'user', 'assistant'],
    'the stored record keeps what happened');
});

test('images on an unanswered turn never reach the box, so they do not count toward max_count', async () => {
  resetIDB(); VERIFY_BYTES = 'bmV3'; ASK_BODIES.length = 0;
  const olds = ['o1', 'o2', 'o3'].map((id) => ({ id, data: 'b2xk', signature: 'sig', media_type: 'image/webp' }));
  await seedLegacy([
    { role: 'user', content: 'tres imágenes, sin respuesta', attachments: ['o1', 'o2', 'o3'] },
    { role: 'user', content: 'otra' },
    { role: 'assistant', content: 'respondida' },
  ], olds);
  await mountAt('/hub/mira/vieja');
  document.dispatchEvent({ type: 'drop', preventDefault() {}, dataTransfer: { files: [file()] } });
  for (let i = 0; i < 6; i++) await tick();
  assert.ok(![...MAIN.querySelectorAll('.chat-turn-error')].some((e) => e.textContent === 'chat_attach_too_many'),
    'the pre-check counts only turns the wire sends');
  assert.equal(MAIN.querySelectorAll('.chat-attach-thumb').length, 1, 'the new image is pending');
});
