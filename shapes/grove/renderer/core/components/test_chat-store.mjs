import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeRecord, slugFor, dedupeSlug, sortByRecency, slugFromRoute, toWireTurns, answeredTurns, toStoredTurns, hydrateTurns, unreferencedIds } from './chat-store.js';

describe('chat-store', () => {
  it('builds a record from a title and turns', () => {
    const r = makeRecord('Contratos de alquiler', [{ role: 'user', content: 'q' }]);
    assert.equal(r.title, 'Contratos de alquiler');
    assert.equal(r.slug, 'contratos-de-alquiler');
    assert.equal(r.turns.length, 1);
    assert.ok(r.id && r.created);
  });

  it('slugifies: lowercase, hyphens, strips punctuation and accents', () => {
    assert.equal(slugFor('¿Qué dice la ley?'), 'que-dice-la-ley');
  });

  it('returns the sentinel "chat" when a title slugifies to empty', () => {
    // Punctuation-only, emoji-only, non-Latin, and empty titles all strip to ''.
    // They must not collapse onto the empty-string IDB key — each gets a stable,
    // non-empty key that the caller then dedupes.
    assert.equal(slugFor('!!!'), 'chat');
    assert.equal(slugFor('🔥'), 'chat');
    assert.equal(slugFor('你好'), 'chat');
    assert.equal(slugFor(''), 'chat');
  });

  it('sentinel slug composes with dedupe (two unsluggable titles stay unique)', () => {
    const s = dedupeSlug('chat', new Set(['chat']));
    assert.notEqual(s, 'chat');
    assert.ok(s.startsWith('chat-'));
  });

  it('dedupes a colliding slug with a short suffix', () => {
    const taken = new Set(['ley-de-vivienda']);
    const s = dedupeSlug('ley-de-vivienda', taken);
    assert.notEqual(s, 'ley-de-vivienda');
    assert.ok(s.startsWith('ley-de-vivienda-'));
  });

  it('sorts conversations newest-first', () => {
    const a = { updated: 1 }, b = { updated: 2 };
    assert.deepEqual(sortByRecency([a, b]), [b, a]);
  });

  it('reads the slug from a route under the base', () => {
    assert.equal(slugFromRoute('/assistant/contratos-de-alquiler/', '/assistant/'), 'contratos-de-alquiler');
  });

  it('returns empty for the bare base route (fresh entry state)', () => {
    assert.equal(slugFromRoute('/assistant/', '/assistant/'), '');
    assert.equal(slugFromRoute('/assistant', '/assistant/'), ''); // missing trailing slash
  });

  it('keeps only the first segment of a deeper tail', () => {
    assert.equal(slugFromRoute('/assistant/my-convo/extra/', '/assistant/'), 'my-convo');
  });

  it('throws when the route is not under the base (call-site bug, not a guess)', () => {
    assert.throws(() => slugFromRoute('/other/x/', '/assistant/'));
  });
});

describe('toWireTurns', () => {
  it('maps to EXACTLY { role, content }, stripping sources off assistant turns', () => {
    const history = [
      { role: 'user', content: 'q' },
      { role: 'assistant', content: 'a [1]', sources: [{ n: 1, title: 'doc-a.md' }] },
    ];
    assert.deepEqual(toWireTurns(history), [
      { role: 'user', content: 'q' },
      { role: 'assistant', content: 'a [1]' },
    ]);
  });

  it('leaves user turns untouched and never adds a sources key', () => {
    const out = toWireTurns([{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'yo' }]);
    assert.deepEqual(out, [{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'yo' }]);
    assert.ok(!('sources' in out[0]));
  });

  it('throws on a non-array (call-site bug, not a guess)', () => {
    assert.throws(() => toWireTurns(null));
  });

  // An older client committed a user turn even when its stream brought no answer, so a
  // stored record can hold a user turn nothing answered. The box requires alternation;
  // that turn is shown, never sent.
  it('omits an unanswered user turn in the middle: [A, B, b] → [B, b]', () => {
    const history = [
      { role: 'user', content: 'A' },
      { role: 'user', content: 'B' },
      { role: 'assistant', content: 'b' },
    ];
    assert.deepEqual(toWireTurns(history), [
      { role: 'user', content: 'B' },
      { role: 'assistant', content: 'b' },
    ]);
  });

  it('omits a trailing unanswered user turn as stored: [A, a, C] → [A, a]', () => {
    const history = [
      { role: 'user', content: 'A' },
      { role: 'assistant', content: 'a' },
      { role: 'user', content: 'C' },
    ];
    assert.deepEqual(toWireTurns(history), [
      { role: 'user', content: 'A' },
      { role: 'assistant', content: 'a' },
    ]);
  });

  it('leaves an alternating history unchanged', () => {
    const history = [
      { role: 'user', content: 'A' }, { role: 'assistant', content: 'a' },
      { role: 'user', content: 'B' }, { role: 'assistant', content: 'b' },
    ];
    assert.deepEqual(toWireTurns(history), history);
  });

  it('repairs nothing else: assistant-first and assistant-assistant go out as they are', () => {
    const history = [
      { role: 'assistant', content: 'x' },
      { role: 'user', content: 'A' }, { role: 'assistant', content: 'a' }, { role: 'assistant', content: 'a2' },
    ];
    assert.deepEqual(toWireTurns(history), history);
  });
});

describe('answeredTurns', () => {
  it('keeps only user turns an assistant turn follows, and every assistant turn', () => {
    const a = { role: 'user', content: 'A' };
    const b = { role: 'user', content: 'B' };
    const bb = { role: 'assistant', content: 'b' };
    const c = { role: 'user', content: 'C' };
    assert.deepEqual(answeredTurns([a, b, bb, c]), [b, bb]);
  });

  it('throws on a non-array (call-site bug, not a guess)', () => {
    assert.throws(() => answeredTurns(undefined));
  });
});

describe('toStoredTurns', () => {
  it('keeps sources on an assistant turn, drops nothing else', () => {
    const sources = [{ n: 1, title: 'doc-a.md' }, { n: 2, title: 'doc-b.md' }];
    const history = [
      { role: 'user', content: 'q' },
      { role: 'assistant', content: 'a [1] [2]', sources },
    ];
    assert.deepEqual(toStoredTurns(history), [
      { role: 'user', content: 'q' },
      { role: 'assistant', content: 'a [1] [2]', sources },
    ]);
  });

  it('user turns never carry a sources key even if one slipped in', () => {
    const out = toStoredTurns([{ role: 'user', content: 'q', sources: [{ n: 1, title: 'x' }] }]);
    assert.deepEqual(out, [{ role: 'user', content: 'q' }]);
    assert.ok(!('sources' in out[0]));
  });

  it('an assistant turn with no sources stores no sources key (legacy/no-citation)', () => {
    const out = toStoredTurns([{ role: 'assistant', content: 'plain reply' }]);
    assert.deepEqual(out, [{ role: 'assistant', content: 'plain reply' }]);
    assert.ok(!('sources' in out[0]));
  });

  it('throws on a non-array (call-site bug, not a guess)', () => {
    assert.throws(() => toStoredTurns(undefined));
  });

  it('toWireTurns carries a user turn\'s attachments (id dropped)', () => {
    const wire = toWireTurns([
      { role: 'user', content: 'look', attachments: [
        { id: 'aa', data: 'B64', signature: 'sig', media_type: 'image/webp' }] },
      { role: 'assistant', content: 'ok', sources: [{ n: 1, title: 'x' }] },
    ]);
    assert.deepEqual(wire[0].attachments, [{ data: 'B64', signature: 'sig', media_type: 'image/webp' }]);
    assert.equal('attachments' in wire[1], false);   // assistant carries none
    assert.equal('sources' in wire[1], false);        // sources never ride the wire
  });

  it('toWireTurns omits attachments when a turn has none', () => {
    const wire = toWireTurns([{ role: 'user', content: 'hi' }, { role: 'assistant', content: 'yo' }]);
    assert.deepEqual(wire[0], { role: 'user', content: 'hi' });
  });

  it('toStoredTurns stores attachment IDS only', () => {
    const stored = toStoredTurns([
      { role: 'user', content: 'look', attachments: [
        { id: 'aa', data: 'B64', signature: 'sig', media_type: 'image/webp' }] }]);
    assert.deepEqual(stored[0], { role: 'user', content: 'look', attachments: ['aa'] });
  });

  it('hydrateTurns replaces ids with full attachments from the map', () => {
    const byId = new Map([['aa', { id: 'aa', data: 'B64', signature: 'sig', media_type: 'image/webp' }]]);
    const turns = hydrateTurns([{ role: 'user', content: 'look', attachments: ['aa'] }], byId);
    assert.deepEqual(turns[0].attachments[0], byId.get('aa'));
  });

  it('hydrateTurns keeps a missing id as a MARKED placeholder — never silently a different conversation', () => {
    const turns = hydrateTurns([{ role: 'user', content: 'x', attachments: ['gone'] }], new Map());
    assert.deepEqual(turns[0].attachments, [{ id: 'gone', missing: true }]);
  });

  it('toWireTurns refuses a history with a missing attachment (kind attachment_missing)', () => {
    const history = [{ role: 'user', content: 'x', attachments: [{ id: 'gone', missing: true }] },
                     { role: 'assistant', content: 'ok' }];
    assert.throws(() => toWireTurns(history), (e) => e.kind === 'attachment_missing');
  });

  it('toWireTurns does not refuse over an UNANSWERED turn\'s missing image — it is never sent', () => {
    const history = [
      { role: 'user', content: 'x', attachments: [{ id: 'gone', missing: true }] },
      { role: 'user', content: 'y' },
      { role: 'assistant', content: 'ok' },
      { role: 'user', content: 'z', attachments: [{ id: 'gone2', missing: true }] },
    ];
    assert.deepEqual(toWireTurns(history), [
      { role: 'user', content: 'y' },
      { role: 'assistant', content: 'ok' },
    ]);
  });
});

describe('attachment GC', () => {
  it('unreferencedIds: only ids no REMAINING record still references', () => {
    const deleted = { slug: 'a', turns: [{ role: 'user', content: 'x', attachments: ['shared', 'only-a'] }] };
    const remaining = [{ slug: 'b', turns: [{ role: 'user', content: 'y', attachments: ['shared'] }] },
                       { slug: 'c', turns: [{ role: 'user', content: 'z' }] }];
    assert.deepEqual(unreferencedIds(deleted, remaining), ['only-a']);
  });
  it('unreferencedIds: the deleted record itself never counts as a reference', () => {
    const deleted = { slug: 'a', turns: [{ role: 'user', content: 'x', attachments: ['k'] }] };
    assert.deepEqual(unreferencedIds(deleted, [deleted]), ['k']);
  });
});
