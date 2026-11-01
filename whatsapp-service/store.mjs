import { DatabaseSync } from 'node:sqlite';
import { createCipheriv, createDecipheriv, createHmac, randomBytes } from 'node:crypto';
import { chmodSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const CANDIDATE_ID = /^[a-f0-9]{32,64}$/;
const ACTIVE_CANDIDATE_STATES = new Set(['preparing', 'awaiting_pairing', 'connecting', 'ready']);
const PROMOTED_CANDIDATE_STATE = 'promoted';
const CANDIDATE_STATES = new Set([...ACTIVE_CANDIDATE_STATES, 'failed', 'cancelled', 'expired']);

function candidatePrefix(id) {
  if (!CANDIDATE_ID.test(id || '')) throw new Error('Invalid candidate identifier');
  return `candidate:${id}:`;
}

// A single sender instance owns this local persistent database. Values are
// encrypted independently; key material is supplied out of band, never in Git.
export function openStore(path, key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) throw new Error('Invalid storage key');
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const db = new DatabaseSync(path);
  try { chmodSync(path, 0o600); } catch { /* Windows ACLs are managed externally. */ }
  db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS auth (id TEXT PRIMARY KEY, value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS sends (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, recipient TEXT NOT NULL); CREATE TABLE IF NOT EXISTS pairing_requests (id TEXT PRIMARY KEY, phone TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS candidate_sessions (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, expected_phone_hash TEXT); CREATE TABLE IF NOT EXISTS switch_requests (id TEXT PRIMARY KEY, created_at INTEGER NOT NULL);');
  // The first candidate implementation did not store an operation binding. This
  // additive migration leaves existing active credentials and candidate rows
  // untouched; old incomplete candidate rows are safely failed on restart.
  if (!db.prepare("SELECT 1 FROM pragma_table_info('candidate_sessions') WHERE name='expected_phone_hash'").get())
    db.exec('ALTER TABLE candidate_sessions ADD COLUMN expected_phone_hash TEXT');
  // Retain longer than the longest link lifetime (30 days), including replay
  // tolerance. Pending/indeterminate records remain protected throughout it.
  db.exec("CREATE INDEX IF NOT EXISTS sends_created_at ON sends(created_at); CREATE INDEX IF NOT EXISTS sends_recipient_time ON sends(recipient, created_at); CREATE INDEX IF NOT EXISTS pairing_requests_phone_time ON pairing_requests(phone, created_at); CREATE INDEX IF NOT EXISTS candidate_sessions_expiry ON candidate_sessions(expires_at); CREATE INDEX IF NOT EXISTS switch_requests_created_at ON switch_requests(created_at); CREATE UNIQUE INDEX IF NOT EXISTS candidate_sessions_one_active ON candidate_sessions((1)) WHERE status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready');");
  const seal = (value) => {
    const nonce = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', key, nonce);
    const ciphertext = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
    return Buffer.concat([nonce, cipher.getAuthTag(), ciphertext]);
  };
  const open = (value) => {
    const data = Buffer.from(value);
    const decipher = createDecipheriv('aes-256-gcm', key, data.subarray(0, 12));
    decipher.setAuthTag(data.subarray(12, 28));
    return Buffer.concat([decipher.update(data.subarray(28)), decipher.final()]).toString('utf8');
  };
  const digest = (purpose, value) => createHmac('sha256', key).update(purpose).update('\0').update(value).digest('hex');
  const clearCandidateCredentials = id => db.prepare("DELETE FROM auth WHERE id LIKE ? ESCAPE '\\'").run(`${candidatePrefix(id)}%`).changes;
  const expireCandidates = now => {
    const expired = db.prepare("SELECT id FROM candidate_sessions WHERE status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready') AND expires_at <= ?").all(now);
    for (const { id } of expired) {
      clearCandidateCredentials(id);
      db.prepare("UPDATE candidate_sessions SET status='expired', updated_at=? WHERE id=?").run(now, id);
    }
    return expired.length;
  };
  const setAuthValues = values => {
    db.exec('BEGIN IMMEDIATE');
    try {
      for (const [id, value] of Object.entries(values)) {
        if (value === null) db.prepare('DELETE FROM auth WHERE id = ?').run(id);
        else db.prepare('INSERT INTO auth (id, value) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value').run(id, seal(value));
      }
      db.exec('COMMIT');
    } catch (error) { db.exec('ROLLBACK'); throw error; }
  };
  return {
    get(id) { const row = db.prepare('SELECT value FROM auth WHERE id = ?').get(id); return row ? open(row.value) : null; },
    // Legacy active credentials have no namespace. Never let an active reset
    // erase a candidate operation that is isolated under candidate:<id>:.
    clearAuth() { db.prepare("DELETE FROM auth WHERE id NOT LIKE 'candidate:%'").run(); },
    createCandidate(id, expiresAt, expectedPhone, now = Date.now()) {
      if (!CANDIDATE_ID.test(id || '') || !Number.isSafeInteger(expiresAt) || expiresAt <= now || !/^55[1-9][0-9][0-9]{8,9}$/.test(expectedPhone || ''))
        throw new Error('Invalid candidate session');
      db.exec('BEGIN IMMEDIATE');
      try {
        expireCandidates(now);
        const active = db.prepare("SELECT id FROM candidate_sessions WHERE status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready') LIMIT 1").get();
        if (active) { db.exec('COMMIT'); return null; }
        db.prepare('INSERT INTO candidate_sessions (id, status, created_at, expires_at, updated_at, expected_phone_hash) VALUES (?, ?, ?, ?, ?, ?)')
          .run(id, 'preparing', now, expiresAt, now, digest('candidate-phone', expectedPhone));
        db.exec('COMMIT');
        return { id, status: 'preparing', expires_at: expiresAt };
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    candidate(id) {
      if (!CANDIDATE_ID.test(id || '')) return null;
      return db.prepare('SELECT id, status, created_at, expires_at, updated_at FROM candidate_sessions WHERE id=?').get(id) || null;
    },
    updateCandidate(id, status, now = Date.now()) {
      if (!CANDIDATE_ID.test(id || '') || !CANDIDATE_STATES.has(status)) throw new Error('Invalid candidate state');
      const changes = db.prepare("UPDATE candidate_sessions SET status=?, updated_at=? WHERE id=? AND status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready')")
        .run(status, now, id).changes;
      return changes === 1;
    },
    finishCandidate(id, status, now = Date.now()) {
      if (!CANDIDATE_ID.test(id || '') || !['failed', 'cancelled', 'expired'].includes(status)) throw new Error('Invalid terminal candidate state');
      db.exec('BEGIN IMMEDIATE');
      try {
        clearCandidateCredentials(id);
        const changes = db.prepare("UPDATE candidate_sessions SET status=?, updated_at=? WHERE id=? AND status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready')")
          .run(status, now, id).changes;
        db.exec('COMMIT');
        return changes === 1;
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    promoteCandidate(id, presentedPhone, now = Date.now(), beforeCommit) {
      if (!CANDIDATE_ID.test(id || '') || !/^55[1-9][0-9][0-9]{8,9}$/.test(presentedPhone || ''))
        throw new Error('Invalid candidate promotion');
      const prefix = candidatePrefix(id);
      db.exec('BEGIN IMMEDIATE');
      try {
        const candidate = db.prepare('SELECT status, expires_at, expected_phone_hash FROM candidate_sessions WHERE id=?').get(id);
        if (!candidate) { db.exec('COMMIT'); return 'missing'; }
        if (candidate.status === PROMOTED_CANDIDATE_STATE) { db.exec('COMMIT'); return 'promoted'; }
        if (candidate.status !== 'ready' || candidate.expires_at <= now || !candidate.expected_phone_hash
            || candidate.expected_phone_hash !== digest('candidate-phone', presentedPhone)) {
          db.exec('COMMIT'); return 'rejected';
        }
        const candidateCreds = db.prepare('SELECT 1 FROM auth WHERE id=?').get(prefix + 'creds');
        if (!candidateCreds) { db.exec('COMMIT'); return 'rejected'; }
        // Stop-and-copy protocol: the caller has already stopped the legacy
        // connection. This transaction replaces every legacy credential with
        // the encrypted candidate values and removes the candidate namespace.
        db.prepare("DELETE FROM auth WHERE id NOT LIKE 'candidate:%'").run();
        db.prepare('INSERT INTO auth (id, value) SELECT substr(id, ?), value FROM auth WHERE id LIKE ?')
          .run(prefix.length + 1, `${prefix}%`);
        clearCandidateCredentials(id);
        db.prepare("UPDATE candidate_sessions SET status=?, updated_at=? WHERE id=? AND status='ready'")
          .run(PROMOTED_CANDIDATE_STATE, now, id);
        // Test seam only: verifies SQLite rolls every credential mutation back
        // when a failure occurs after the copies but before COMMIT.
        beforeCommit?.();
        db.exec('COMMIT');
        return 'promoted';
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    candidateAuth(id) {
      const prefix = candidatePrefix(id);
      return {
        get(name) { const row = db.prepare('SELECT value FROM auth WHERE id = ?').get(prefix + name); return row ? open(row.value) : null; },
        clearAuth() { clearCandidateCredentials(id); },
        setMany(values) {
          const namespaced = {};
          for (const [name, value] of Object.entries(values)) namespaced[prefix + name] = value;
          setAuthValues(namespaced);
        },
      };
    },
    setMany(values) {
      setAuthValues(values);
    },
    reserve(id, payload, recipient) {
      const fingerprint = digest('payload', payload);
      const keyHash = digest('request', id);
      const recipientHash = digest('recipient', recipient);
      db.exec('BEGIN IMMEDIATE');
      try {
        const previous = db.prepare('SELECT fingerprint, status FROM sends WHERE id=?').get(keyHash);
        if (!previous) {
          const count = db.prepare('SELECT COUNT(*) AS n FROM sends WHERE recipient=? AND created_at>?').get(recipientHash, Date.now() - 900000).n;
          if (count >= 5) { db.exec('COMMIT'); return 'limited'; }
          db.prepare('INSERT INTO sends VALUES (?, ?, ?, ?, ?)').run(keyHash, fingerprint, 'pending', Date.now(), recipientHash);
        }
        db.exec('COMMIT');
        if (!previous) return 'new';
        return previous.fingerprint === fingerprint ? previous.status : 'conflict';
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    complete(id, status) {
      const keyHash = digest('request', id);
      db.prepare('UPDATE sends SET status=? WHERE id=?').run(status, keyHash);
    },
    reservePairing(id, phone) {
      const keyHash = digest('pairing-request', id);
      const phoneHash = digest('pairing-phone', phone);
      db.exec('BEGIN IMMEDIATE');
      try {
        if (db.prepare('SELECT id FROM pairing_requests WHERE id=?').get(keyHash)) {
          db.exec('COMMIT'); return 'duplicate';
        }
        const since = Date.now() - 900000;
        const count = db.prepare('SELECT COUNT(*) AS n FROM pairing_requests WHERE phone=? AND created_at>?').get(phoneHash, since).n;
        if (count >= 3) { db.exec('COMMIT'); return 'limited'; }
        db.prepare('INSERT INTO pairing_requests VALUES (?, ?, ?, ?)').run(keyHash, phoneHash, 'pending', Date.now());
        db.exec('COMMIT'); return 'new';
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    completePairing(id, status) {
      db.prepare('UPDATE pairing_requests SET status=? WHERE id=?').run(status, digest('pairing-request', id));
    },
    reserveSwitchRequest(id, now = Date.now()) {
      if (!/^[A-Za-z0-9_-]{16,128}$/.test(id || '')) return false;
      const keyHash = digest('switch-request', id);
      try {
        db.prepare('INSERT INTO switch_requests (id, created_at) VALUES (?, ?)').run(keyHash, now);
        return true;
      } catch { return false; }
    },
    cleanup(now = Date.now()) {
      const sendChanges = db.prepare('DELETE FROM sends WHERE created_at < ?').run(now - 35 * 86400000).changes;
      const pairingChanges = db.prepare('DELETE FROM pairing_requests WHERE created_at < ?').run(now - 900000).changes;
      const switchChanges = db.prepare('DELETE FROM switch_requests WHERE created_at < ?').run(now - 900000).changes;
      db.exec('BEGIN IMMEDIATE');
      try { const candidateChanges = expireCandidates(now); db.exec('COMMIT'); return sendChanges + pairingChanges + switchChanges + candidateChanges; }
      catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    recoverCandidatesAfterRestart(now = Date.now()) {
      db.exec('BEGIN IMMEDIATE');
      try {
        expireCandidates(now);
        const active = db.prepare("SELECT id FROM candidate_sessions WHERE status IN ('preparing', 'awaiting_pairing', 'connecting', 'ready')").all();
        for (const { id } of active) {
          clearCandidateCredentials(id);
          db.prepare("UPDATE candidate_sessions SET status='failed', updated_at=? WHERE id=?").run(now, id);
        }
        db.exec('COMMIT');
        return active.length;
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
    close() { db.close(); },
  };
}

export function baileysState(store, { BufferJSON, initAuthCreds, proto }) {
  const decode = (value) => JSON.parse(value, BufferJSON.reviver);
  const encode = (value) => JSON.stringify(value, BufferJSON.replacer);
  let credentialStore = store;
  const creds = credentialStore.get('creds') ? decode(credentialStore.get('creds')) : initAuthCreds();
  const state = { creds, keys: {
      async get(type, ids) {
        const result = {};
        for (const id of ids) {
          const value = credentialStore.get(`${type}:${id}`);
          if (value !== null) {
            let parsed = decode(value);
            if (type === 'app-state-sync-key') parsed = proto.Message.AppStateSyncKeyData.fromObject(parsed);
            result[id] = parsed;
          }
        }
        return result;
      },
      async set(data) {
        const values = {};
        for (const [type, entries] of Object.entries(data))
          for (const [id, value] of Object.entries(entries)) values[`${type}:${id}`] = value == null ? null : encode(value);
        credentialStore.setMany(values);
      },
    } };
  return {
    state,
    saveCreds() { credentialStore.setMany({ creds: encode(state.creds) }); },
    reset() { credentialStore.clearAuth(); state.creds = initAuthCreds(); },
    // Promotion rebinds an already-open candidate socket after the SQLite
    // transaction commits. Future Baileys updates then use legacy active keys.
    promoteToActive(activeStore) { credentialStore = activeStore; },
  };
}
