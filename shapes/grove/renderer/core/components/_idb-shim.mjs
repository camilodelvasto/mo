// _idb-shim.mjs — a minimal in-memory IndexedDB, enough for chat-idb.js: open with
// onupgradeneeded, object stores keyed by keyPath, get/put/getAll/delete, and a
// transaction that settles via oncomplete (or fails via onerror: see failPuts). Importing it installs globalThis.indexedDB.
// It exists so the persistence tests drive the REAL chat-idb/chat-attachments code
// instead of stubbing the store away.
const DBS = new Map();                       // name → { version, stores: Map<store, Map<key, value>> }

export function resetIDB() { DBS.clear(); }
const FAIL_PUTS = new Set();                 // store names whose puts throw (quota/abort)
export function failPuts(store, on = true) { on ? FAIL_PUTS.add(store) : FAIL_PUTS.delete(store); }
export function dumpStore(dbName, store) {
  const db = DBS.get(dbName);
  return db && db.stores.has(store) ? [...db.stores.get(store).values()] : [];
}

const settle = (obj, ok) => queueMicrotask(() => { if (ok && obj.onsuccess) obj.onsuccess(); });

function makeRequest(run) {
  const req = { result: undefined, error: null, onsuccess: null, onerror: null, _run: run };
  return req;
}

function makeStore(map, keyPath, pending, storeName) {
  const enqueue = (fn) => { const req = makeRequest(fn); pending.push(req); return req; };
  return {
    get: (key) => enqueue(() => map.has(key) ? structuredClone(map.get(key)) : undefined),
    getAll: () => enqueue(() => [...map.values()].map((v) => structuredClone(v))),
    put: (value) => enqueue(() => {
      if (FAIL_PUTS.has(storeName)) throw new Error('QuotaExceededError');
      map.set(value[keyPath], structuredClone(value)); return value[keyPath]; }),
    delete: (key) => enqueue(() => { map.delete(key); return undefined; }),
  };
}

globalThis.indexedDB = {
  open(name, version) {
    const req = { result: null, error: null, onsuccess: null, onerror: null, onupgradeneeded: null };
    queueMicrotask(() => {
      let db = DBS.get(name);
      const fresh = !db || db.version < version;
      if (!db) { db = { version, stores: new Map() }; DBS.set(name, db); }
      const keyPaths = db.keyPaths || (db.keyPaths = new Map());
      const handle = {
        objectStoreNames: { contains: (s) => db.stores.has(s) },
        createObjectStore(s, opts) { db.stores.set(s, new Map()); keyPaths.set(s, opts.keyPath); },
        close() {},
        transaction(storeName, mode) {
          if (!db.stores.has(storeName)) throw new Error('no such store: ' + storeName);
          const pending = [];
          const tx = { error: null, oncomplete: null, onerror: null, onabort: null,
                       objectStore: () => makeStore(db.stores.get(storeName), keyPaths.get(storeName), pending, storeName) };
          queueMicrotask(() => {                    // run the requests, then commit
            for (const req of pending) {
              try { req.result = req._run(); } catch (err) {
                // A failed request aborts the tx, as in IDB: request onerror, then the
                // tx's onerror; oncomplete never fires. (Writes already made stay — the
                // shim has no rollback; the injected failure throws before its write.)
                req.error = err; tx.error = err;
                if (req.onerror) req.onerror();
                if (tx.onerror) tx.onerror();
                return;
              }
              settle(req, true);
            }
            queueMicrotask(() => { if (tx.oncomplete) tx.oncomplete(); });
          });
          return tx;
        },
      };
      req.result = handle;
      db.version = version;
      if (fresh && req.onupgradeneeded) req.onupgradeneeded();
      if (req.onsuccess) req.onsuccess();
    });
    return req;
  },
};
