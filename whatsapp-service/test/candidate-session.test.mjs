import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { randomBytes } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { createCandidateSessionManager } from '../candidate-session.mjs';
import { openStore } from '../store.mjs';

function removeTestDirectory(dir) {
  const root = resolve(tmpdir()) + sep;
  const target = resolve(dir);
  if (!target.startsWith(root) || !target.slice(root.length).startsWith('dacot-wa-candidate-'))
    throw new Error('Invalid temporary test directory');
  rmSync(target, { recursive: true, force: true });
}

function candidateId(value) { return value.toString(16).padStart(32, '0'); }

const TEST_PHONE = '5511912345678';

function candidateHarness(store, { now = () => 1000, id = candidateId(1), ttlMs = 10000,
  accountId = `${TEST_PHONE}@s.whatsapp.net` } = {}) {
  const sockets = [];
  const timers = [];
  const manager = createCandidateSessionManager({
    store,
    now,
    randomId: () => id,
    ttlMs,
    schedule: callback => { timers.push(callback); return timers.length - 1; },
    cancelSchedule: () => {},
    createAuth: authStore => ({
      authStore,
      promoteToActive(activeStore) { this.authStore = activeStore; },
    }),
    createConnection: ({ auth, onStateChange }) => {
      auth.authStore.setMany({ creds: 'candidate-sensitive-session' });
      const socket = {
        state: 'connecting',
        auth,
        sends: 0,
        accountId() { return accountId; },
        async send() { this.sends++; },
        stop() { this.state = 'stopped'; onStateChange('stopped'); },
        emit(state) { this.state = state; onStateChange(state); },
      };
      sockets.push(socket);
      return socket;
    },
  });
  return { manager, sockets, timers };
}

test('candidate credentials are isolated from the legacy active namespace', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const id = candidateId(1);
    store.setMany({ creds: 'active-session-preserved' });
    store.candidateAuth(id).setMany({ creds: 'candidate-session-isolated', 'pre-key:key': 'candidate-key' });
    assert.equal(store.get('creds'), 'active-session-preserved');
    assert.equal(store.candidateAuth(id).get('creds'), 'candidate-session-isolated');
    store.clearAuth();
    assert.equal(store.get('creds'), null);
    assert.equal(store.candidateAuth(id).get('creds'), 'candidate-session-isolated');
    store.setMany({ creds: 'active-session-preserved' });
    store.candidateAuth(id).clearAuth();
    assert.equal(store.get('creds'), 'active-session-preserved');
    assert.equal(store.candidateAuth(id).get('creds'), null);
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('opening an existing SQLite file adds only the candidate binding column without rewriting active credentials', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const path = join(dir, 'state.sqlite');
    const legacy = new DatabaseSync(path);
    legacy.exec('CREATE TABLE auth (id TEXT PRIMARY KEY, value BLOB NOT NULL); CREATE TABLE candidate_sessions (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);');
    legacy.close();
    const store = openStore(path, randomBytes(32));
    store.setMany({ creds: 'legacy-active-session-preserved' });
    assert.equal(store.get('creds'), 'legacy-active-session-preserved');
    const id = candidateId(10);
    assert.deepEqual(store.createCandidate(id, 11000, TEST_PHONE, 1000), { id, status: 'preparing', expires_at: 11000 });
    assert.equal(store.get('creds'), 'legacy-active-session-preserved');
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('a candidate starts in preparing state without changing legacy credentials', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const id = candidateId(11);
    store.setMany({ creds: 'active-session-preserved' });
    assert.deepEqual(store.createCandidate(id, 11000, TEST_PHONE, 1000), { id, status: 'preparing', expires_at: 11000 });
    assert.equal(store.candidate(id).status, 'preparing');
    assert.equal(store.get('creds'), 'active-session-preserved');
    assert.equal(store.finishCandidate(id, 'cancelled', 1001), true);
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('candidate lifecycle is exclusive, cancellable, and never touches active credentials', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'active-session-preserved' });
    const id = candidateId(2);
    const { manager, sockets } = candidateHarness(store, { id });
    assert.deepEqual(manager.prepare({ requestedPhone: '+' + TEST_PHONE }), { id, state: 'connecting', expiresAt: 11000 });
    assert.equal(manager.prepare({ requestedPhone: '+' + TEST_PHONE }), null, 'only one active candidate is allowed');
    sockets[0].emit('pairing');
    assert.equal(store.candidate(id).status, 'awaiting_pairing');
    sockets[0].emit('open');
    assert.equal(manager.active().state, 'ready');
    assert.equal(manager.cancel(id), true);
    assert.equal(store.candidate(id).status, 'cancelled');
    assert.equal(store.candidateAuth(id).get('creds'), null);
    assert.equal(store.get('creds'), 'active-session-preserved');
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('candidate expiry and connection failures clear only candidate credentials', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'active-session-preserved' });
    const id = candidateId(3);
    const { manager, timers } = candidateHarness(store, { id });
    manager.prepare({ requestedPhone: TEST_PHONE });
    timers[0]();
    assert.equal(store.candidate(id).status, 'expired');
    assert.equal(store.candidateAuth(id).get('creds'), null);
    assert.equal(store.get('creds'), 'active-session-preserved');

    const failedId = candidateId(4);
    const failed = createCandidateSessionManager({
      store,
      now: () => 2000,
      randomId: () => failedId,
      createAuth: authStore => ({ authStore, promoteToActive() {} }),
      createConnection: ({ auth }) => { auth.authStore.setMany({ creds: 'temporary' }); throw new Error('synthetic failure'); },
    });
    assert.equal(failed.prepare({ requestedPhone: TEST_PHONE }), null);
    assert.equal(store.candidate(failedId).status, 'failed');
    assert.equal(store.candidateAuth(failedId).get('creds'), null);
    assert.equal(store.get('creds'), 'active-session-preserved');
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('restart recovery fails candidate operations without promoting or changing the active session', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const id = candidateId(5);
    store.setMany({ creds: 'active-session-preserved' });
    store.createCandidate(id, 10000, TEST_PHONE, 1000);
    store.candidateAuth(id).setMany({ creds: 'candidate-will-not-resume' });
    assert.equal(store.recoverCandidatesAfterRestart(2000), 1);
    assert.equal(store.candidate(id).status, 'failed');
    assert.equal(store.candidateAuth(id).get('creds'), null);
    assert.equal(store.get('creds'), 'active-session-preserved');
    store.close();
  } finally { removeTestDirectory(dir); }
});

function readyPromotion(store, options = {}) {
  const harness = candidateHarness(store, options);
  const prepared = harness.manager.prepare({ requestedPhone: '+' + TEST_PHONE });
  assert.ok(prepared);
  harness.sockets[0].emit('open');
  assert.equal(harness.manager.active().state, 'ready');
  return harness;
}

function activeController() {
  const old = { stopped: false, sends: 0, stop() { this.stopped = true; }, async send() { this.sends++; } };
  let current = old;
  let restores = 0;
  return {
    old,
    get current() { return current; },
    get restores() { return restores; },
    suspendActive() { old.stop(); return true; },
    restoreActive() { restores++; old.stopped = false; current = old; },
    activateCandidate(connection) { current = connection; },
  };
}

test('a validated candidate promotion atomically replaces legacy credentials and moves sends to the new connection', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'old-active-session', 'pre-key:old': 'old-key' });
    const id = candidateId(20);
    const { manager, sockets } = readyPromotion(store, { id });
    const active = activeController();
    assert.deepEqual(manager.promote(id, active), { status: 'promoted', idempotent: false });
    assert.equal(active.old.stopped, true);
    assert.equal(active.current, sockets[0]);
    assert.equal(store.get('creds'), 'candidate-sensitive-session');
    assert.equal(store.get('pre-key:old'), null);
    assert.equal(store.candidateAuth(id).get('creds'), null);
    assert.equal(store.candidate(id).status, 'promoted');
    await active.current.send('+5511912345678', 'synthetic');
    assert.equal(sockets[0].sends, 1);
    assert.equal(active.old.sends, 0);
    sockets[0].auth.authStore.setMany({ creds: 'new-active-update' });
    assert.equal(store.get('creds'), 'new-active-update');
    assert.deepEqual(manager.promote(id, active), { status: 'promoted', idempotent: true });
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('promotion rejects a candidate that is not open or whose connected identity differs from the requested phone', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'old-active-session' });
    const inactiveId = candidateId(21);
    const inactive = candidateHarness(store, { id: inactiveId });
    inactive.manager.prepare({ requestedPhone: TEST_PHONE });
    const active = activeController();
    assert.deepEqual(inactive.manager.promote(inactiveId, active), { status: 'rejected' });
    assert.equal(store.get('creds'), 'old-active-session');
    assert.equal(active.old.stopped, false);
    inactive.manager.cancel(inactiveId);

    const mismatchId = candidateId(22);
    const mismatch = readyPromotion(store, { id: mismatchId, accountId: '5521991234567@s.whatsapp.net' });
    assert.deepEqual(mismatch.manager.promote(mismatchId, active), { status: 'rejected' });
    assert.equal(store.get('creds'), 'old-active-session');
    assert.equal(active.old.stopped, false);
    mismatch.manager.cancel(mismatchId);
    assert.deepEqual(mismatch.manager.promote(mismatchId, active), { status: 'rejected' });
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('promotion serializes concurrent attempts and rejects an expired candidate', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'old-active-session' });
    const id = candidateId(26);
    const { manager } = readyPromotion(store, { id });
    const active = activeController();
    let nested;
    active.suspendActive = () => {
      nested = manager.promote(id, active);
      active.old.stop();
      return true;
    };
    assert.deepEqual(manager.promote(id, active), { status: 'promoted', idempotent: false });
    assert.deepEqual(nested, { status: 'busy' });

    const expiredId = candidateId(27);
    const expired = readyPromotion(store, { id: expiredId });
    expired.timers[0]();
    assert.deepEqual(expired.manager.promote(expiredId, activeController()), { status: 'rejected' });
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('promotion failure before commit restores the legacy connection and leaves both credential sets intact', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    store.setMany({ creds: 'old-active-session' });
    const id = candidateId(23);
    const { manager } = readyPromotion(store, { id });
    const active = activeController();
    const originalPromote = store.promoteCandidate;
    store.promoteCandidate = () => { throw new Error('synthetic pre-commit failure'); };
    assert.deepEqual(manager.promote(id, active), { status: 'failed_before_commit' });
    store.promoteCandidate = originalPromote;
    assert.equal(active.restores, 1);
    assert.equal(active.old.stopped, false);
    assert.equal(store.get('creds'), 'old-active-session');
    assert.equal(store.candidateAuth(id).get('creds'), 'candidate-sensitive-session');
    assert.equal(store.candidate(id).status, 'ready');
    manager.cancel(id);
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('SQLite rollback preserves active and candidate credentials when promotion fails during its transaction', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const id = candidateId(24);
    store.setMany({ creds: 'old-active-session' });
    store.createCandidate(id, 11000, TEST_PHONE, 1000);
    store.candidateAuth(id).setMany({ creds: 'candidate-sensitive-session' });
    store.updateCandidate(id, 'ready', 1001);
    assert.throws(() => store.promoteCandidate(id, TEST_PHONE, 1002, () => { throw new Error('synthetic transaction failure'); }));
    assert.equal(store.get('creds'), 'old-active-session');
    assert.equal(store.candidateAuth(id).get('creds'), 'candidate-sensitive-session');
    assert.equal(store.candidate(id).status, 'ready');
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('a failure after the SQLite commit never restores old credentials and restart retains the promoted session', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-candidate-'));
  const key = randomBytes(32), path = join(dir, 'state.sqlite');
  try {
    let store = openStore(path, key);
    store.setMany({ creds: 'old-active-session' });
    const id = candidateId(25);
    const { manager, sockets } = readyPromotion(store, { id });
    const active = activeController();
    active.activateCandidate = () => { throw new Error('synthetic post-commit failure'); };
    assert.deepEqual(manager.promote(id, active), { status: 'recovery_required' });
    assert.equal(active.old.stopped, true);
    assert.equal(store.get('creds'), 'candidate-sensitive-session');
    assert.equal(store.candidate(id).status, 'promoted');
    assert.equal(sockets[0].state, 'stopped');
    store.close();

    store = openStore(path, key);
    assert.equal(store.recoverCandidatesAfterRestart(2000), 0);
    assert.equal(store.get('creds'), 'candidate-sensitive-session');
    assert.equal(store.candidate(id).status, 'promoted');
    store.close();
  } finally { removeTestDirectory(dir); }
});
