/**Contract test for sw.js _matchesSpaRoot — runs with `node --test`.
 *
 * sw.js is a classic service-worker script (no exports), so this mirrors the
 * router test precedent: the function body is copied verbatim and its contract
 * pinned. Keep this identical to _matchesSpaRoot in sw.js.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

function makeMatcher(BASE_PATH, OWNED_SPA_ROOTS) {
  return function _matchesSpaRoot(pathname) {
    for (const root of OWNED_SPA_ROOTS) {
      const abs = BASE_PATH + root;
      const prefix = abs.endsWith('/') ? abs : abs + '/';
      if (pathname === abs || pathname === prefix || pathname.startsWith(prefix)) {
        return prefix;
      }
    }
    return null;
  };
}

describe('_matchesSpaRoot — chat subtree', () => {
  const m = makeMatcher('/hub', ['/advisor', '/audiencias']);

  it('slug under a chat root serves that root page', () => {
    assert.equal(m('/hub/advisor/conversation-abc123/'),
                 '/hub/advisor/');
  });

  it('bare chat page matches its own page', () => {
    assert.equal(m('/hub/advisor/'), '/hub/advisor/');
  });

  it('second chat root is matched independently', () => {
    assert.equal(m('/hub/audiencias/tipos/'),
                 '/hub/audiencias/');
  });

  it('a non-chat path returns null', () => {
    assert.equal(m('/hub/about/'), null);
  });

  it('a prefix collision does not false-match', () => {
    // /advisors/ must not match the /advisor root
    assert.equal(m('/hub/advisors/'), null);
  });
});

describe('_matchesSpaRoot — encrypted grove backward compatibility', () => {
  const m = makeMatcher('/hub', ['/']);

  it('any navigation serves the grove root, as before', () => {
    assert.equal(m('/hub/anything/deep/'), '/hub/');
    assert.equal(m('/hub/'), '/hub/');
  });
});

describe('_matchesSpaRoot — no roots', () => {
  const m = makeMatcher('/hub', []);

  it('returns null when nothing is owned', () => {
    assert.equal(m('/hub/advisor/x/'), null);
  });
});
