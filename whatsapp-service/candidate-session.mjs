import { randomBytes } from 'node:crypto';

const CANDIDATE_TTL_MS = 10 * 60 * 1000;

function candidateState(connectionState) {
  if (connectionState === 'pairing') return 'awaiting_pairing';
  if (connectionState === 'connecting' || connectionState === 'disconnected') return 'connecting';
  if (connectionState === 'open') return 'ready';
  return 'failed';
}

function normalizeRequestedPhone(value) {
  const digits = String(value || '').replace(/^\+/, '');
  return /^55[1-9][0-9][0-9]{8,9}$/.test(digits) ? digits : null;
}

function connectedAccountPhone(accountId) {
  const match = /^(\d+)(?::\d+)?@s\.whatsapp\.net$/.exec(accountId || '');
  return match ? normalizeRequestedPhone(match[1]) : null;
}

function snapshot(candidate) {
  return candidate ? {
    id: candidate.id,
    state: candidate.state,
    expiresAt: candidate.expiresAt,
  } : null;
}

// Candidate sessions are intentionally not exposed by the gateway yet. This
// manager provides the isolated lifecycle used by the future authorized swap
// operation, while keeping the active Baileys connection untouched.
export function createCandidateSessionManager({ store, createAuth, createConnection,
  now = Date.now, randomId = () => randomBytes(24).toString('hex'),
  schedule = setTimeout, cancelSchedule = clearTimeout, ttlMs = CANDIDATE_TTL_MS }) {
  let current = null;
  let expiryTimer = null;
  let promotionInProgress = false;

  const clearExpiryTimer = () => {
    if (expiryTimer !== null) cancelSchedule(expiryTimer);
    expiryTimer = null;
  };

  const finish = (candidate, state) => {
    if (!candidate || current?.id !== candidate.id) return false;
    current = null;
    clearExpiryTimer();
    try { candidate.connection?.stop(); } catch { /* Cleanup continues in storage. */ }
    return store.finishCandidate(candidate.id, state, now());
  };

  const observe = (candidate, connectionState) => {
    if (current?.id !== candidate.id) return;
    const state = candidateState(connectionState);
    if (state === 'failed') { finish(candidate, 'failed'); return; }
    if (store.updateCandidate(candidate.id, state, now())) candidate.state = state;
  };

  const expire = id => {
    if (current?.id !== id) return false;
    return finish(current, 'expired');
  };

  return {
    prepare({ requestedPhone, operationId } = {}) {
      const createdAt = now();
      const id = operationId || randomId();
      const expiresAt = createdAt + ttlMs;
      const expectedPhone = normalizeRequestedPhone(requestedPhone);
      if (!expectedPhone) return null;
      const record = store.createCandidate(id, expiresAt, expectedPhone, createdAt);
      if (!record) return null;
      const candidate = { id, state: 'preparing', expiresAt, expectedPhone, connection: null, auth: null };
      current = candidate;
      try {
        candidate.auth = createAuth(store.candidateAuth(id));
        candidate.connection = createConnection({ auth: candidate.auth, onStateChange: state => observe(candidate, state) });
        observe(candidate, candidate.connection.state);
        if (current?.id !== id) return null;
        expiryTimer = schedule(() => { expire(id); }, ttlMs);
        return snapshot(candidate);
      } catch {
        finish(candidate, 'failed');
        return null;
      }
    },
    cancel(id) {
      return current?.id === id ? finish(current, 'cancelled') : false;
    },
    expire(id) { return expire(id); },
    active() { return snapshot(current); },
    status(id) {
      if (current?.id === id) return snapshot(current);
      const record = store.candidate(id);
      return record ? { id: record.id, state: record.status, expiresAt: record.expires_at } : null;
    },
    async requestPairingCode(id) {
      if (current?.id !== id || !['connecting', 'awaiting_pairing'].includes(current.state)
          || typeof current.connection?.requestPairingCode !== 'function') return null;
      try {
        const code = await current.connection.requestPairingCode(current.expectedPhone);
        return typeof code === 'string' && /^[A-Z0-9]{4}-?[A-Z0-9]{4}$/.test(code) ? code : null;
      } catch { return null; }
    },
    promote(id, { suspendActive, restoreActive, activateCandidate } = {}) {
      const persisted = store.candidate(id);
      if (persisted?.status === 'promoted') return { status: 'promoted', idempotent: true };
      if (promotionInProgress) return { status: 'busy' };
      const candidate = current?.id === id ? current : null;
      if (!candidate || candidate.state !== 'ready' || candidate.connection?.state !== 'open'
          || typeof candidate.connection.accountId !== 'function'
          || typeof candidate.auth?.promoteToActive !== 'function'
          || typeof suspendActive !== 'function' || typeof restoreActive !== 'function'
          || typeof activateCandidate !== 'function') return { status: 'rejected' };
      const actualPhone = connectedAccountPhone(candidate.connection.accountId());
      if (!actualPhone || actualPhone !== candidate.expectedPhone) return { status: 'rejected' };

      promotionInProgress = true;
      let legacySuspended = false;
      let committed = false;
      try {
        // The old connection must be stopped before the SQLite commit, or a
        // delayed creds.update could overwrite the newly promoted credentials.
        if (suspendActive() === false) return { status: 'rejected' };
        legacySuspended = true;
        const result = store.promoteCandidate(id, actualPhone, now());
        if (result !== 'promoted') {
          restoreActive();
          return { status: result === 'missing' ? 'rejected' : result };
        }
        committed = true;
        // From this point rollback to the previous account is intentionally
        // forbidden: the prior credentials have been removed durably. Rebind
        // before exposing the candidate so all later updates target active keys.
        candidate.auth.promoteToActive(store);
        current = null;
        clearExpiryTimer();
        activateCandidate(candidate.connection);
        return { status: 'promoted', idempotent: false };
      } catch {
        if (!committed) {
          if (legacySuspended) {
            try { restoreActive(); } catch { /* Caller performs fail-closed recovery. */ }
          }
          return { status: 'failed_before_commit' };
        }
        // The durable state is already the new account. Do not resurrect old
        // credentials; stop this socket and let the normal active startup path
        // recover it from the promoted legacy storage after a restart.
        current = null;
        clearExpiryTimer();
        try { candidate.connection.stop(); } catch { /* Durable recovery remains available. */ }
        return { status: 'recovery_required' };
      } finally { promotionInProgress = false; }
    },
    shutdown() {
      if (!current) return;
      // A process stop is not a promotion. Credentials are removed so a restart
      // cannot resume or accidentally replace the active account.
      finish(current, 'failed');
    },
  };
}
