// Smoke test for resolveEffects — run with: node tests/smoke_resolve_effects.mjs
// Exits 0 on success, 1 on failure.
import { resolveEffects } from '../shapes/deck/renderer/core/theme.js';

const themeData = {
  palette: {
    'warm-yellow': '#fbbf24',
    'warm-red': '#ef4444',
    'accent': '#06b6d4',
  },
  effects: {
    shimmer: {
      stripe: 'warm-yellow',
      duration: '5s',
      loop: false,
    },
    glow: {
      color: 'accent',
      radius: '120px',
      opacity: 0.3,
    },
  },
};

function assertEqual(actual, expected, label) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    console.error(`FAIL: ${label}\n  expected: ${e}\n  actual:   ${a}`);
    process.exit(1);
  }
  console.log(`ok: ${label}`);
}

// String form uses theme default, resolves palette name
assertEqual(
  resolveEffects('shimmer', themeData),
  [{ name: 'shimmer', config: { stripe: '#fbbf24', duration: '5s', loop: false } }],
  'string form resolves theme default with palette',
);

// Array form produces one entry per name
assertEqual(
  resolveEffects(['shimmer', 'glow'], themeData),
  [
    { name: 'shimmer', config: { stripe: '#fbbf24', duration: '5s', loop: false } },
    { name: 'glow', config: { color: '#06b6d4', radius: '120px', opacity: 0.3 } },
  ],
  'array form produces one entry per name',
);

// Object form with partial override — theme provides untouched fields, slide wins on overlap
assertEqual(
  resolveEffects({ shimmer: { duration: '3s', loop: true } }, themeData),
  [{ name: 'shimmer', config: { stripe: '#fbbf24', duration: '3s', loop: true } }],
  'object form shallow-merges slide over theme',
);

// Object form that overrides stripe with raw hex — no palette lookup for pre-hex values
assertEqual(
  resolveEffects({ shimmer: { stripe: '#ff00ff' } }, themeData),
  [{ name: 'shimmer', config: { stripe: '#ff00ff', duration: '5s', loop: false } }],
  'object form accepts raw hex stripe',
);

// Effect with no theme default produces empty-base config merged with slide overrides
assertEqual(
  resolveEffects({ underline: { width: '120px' } }, themeData),
  [{ name: 'underline', config: { width: '120px' } }],
  'effect missing from theme defaults still resolves',
);

// Empty input produces empty array
assertEqual(
  resolveEffects(undefined, themeData),
  [],
  'undefined effectRef produces empty array',
);
assertEqual(
  resolveEffects(null, themeData),
  [],
  'null effectRef produces empty array',
);

// null themeData throws clearly
let threw = false;
try {
  resolveEffects('shimmer', null);
} catch (e) {
  threw = true;
  if (!e.message.includes('themeData is required')) {
    console.error(`FAIL: null themeData error message: ${e.message}`);
    process.exit(1);
  }
}
if (!threw) {
  console.error('FAIL: null themeData did not throw');
  process.exit(1);
}
console.log('ok: null themeData throws with clear message');

console.log('\nAll smoke tests passed.');
