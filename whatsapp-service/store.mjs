import { DatabaseSync } from 'node:sqlite';
import { createCipheriv, createDecipheriv, createHmac, randomBytes } from 'node:crypto';
import { chmodSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

// A single sender instance owns this local persistent database. Values are
// encrypted independently; key material is supplied out of band, never in Git.
export function openStore(path, key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) throw new Error('Invalid storage key');
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const db = new DatabaseSync(path);
  try { chmodSync(path, 0o600); } catch { /* Windows ACLs are managed externally. */ }
  db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS auth (id TEXT PRIMARY KEY, value BLOB NOT NULL); CREATE TABLE IF NOT EXISTS sends (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, recipient TEXT NOT NULL);');
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
  return {
    get(id) { const row = db.prepare('SELECT value FROM auth WHERE id = ?').get(id); return row ? open(row.value) : null; },
    clearAuth() { db.prepare('DELETE FROM auth').run(); },
    setMany(values) {
      db.exec('BEGIN IMMEDIATE');
      try {
        for (const [id, value] of Object.entries(values)) {
          if (value === null) db.prepare('DELETE FROM auth WHERE id = ?').run(id);
          else db.prepare('INSERT INTO auth (id, value) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value=excluded.value').run(id, seal(value));
        }
        db.exec('COMMIT');
      } catch (error) { db.exec('ROLLBACK'); throw error; }
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
    close() { db.close(); },
  };
}

export function baileysState(store, { BufferJSON, initAuthCreds, proto }) {
  const decode = (value) => JSON.parse(value, BufferJSON.reviver);
  const encode = (value) => JSON.stringify(value, BufferJSON.replacer);
  const creds = store.get('creds') ? decode(store.get('creds')) : initAuthCreds();
  const state = { creds, keys: {
      async get(type, ids) {
        const result = {};
        for (const id of ids) {
          const value = store.get(`${type}:${id}`);
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
        store.setMany(values);
      },
    } };
  return {
    state,
    saveCreds() { store.setMany({ creds: encode(state.creds) }); },
    reset() { store.clearAuth(); state.creds = initAuthCreds(); },
  };
}
