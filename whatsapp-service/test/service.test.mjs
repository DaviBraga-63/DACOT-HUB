import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { randomBytes, createHash, createHmac } from 'node:crypto';
import { openStore } from '../store.mjs';
import { connectedBrazilianAccountPhone, createGateway } from '../gateway.mjs';
import { createConnection } from '../connection.mjs';

function removeTestDirectory(dir) {
  const root = resolve(tmpdir()) + sep;
  const target = resolve(dir);
  if (!target.startsWith(root) || !target.slice(root.length).startsWith('dacot-wa-'))
    throw new Error('Invalid temporary test directory');
  rmSync(target, { recursive: true, force: true });
}

test('encrypted auth persists and idempotency survives restart', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  try {
    const key = randomBytes(32), path = join(dir, 'state.sqlite');
    let store = openStore(path, key);
    store.setMany({ creds: 'test-sensitive-session-value' });
    assert.equal(store.reserve('request-one', 'payload', '+5511912345678'), 'new');
    store.complete('request-one', 'accepted');
    store.close();
    assert.equal(readFileSync(path).includes(Buffer.from('test-sensitive-session-value')), false);
    store = openStore(path, key);
    assert.equal(store.get('creds'), 'test-sensitive-session-value');
    assert.equal(store.reserve('request-one', 'payload', '+5511912345678'), 'accepted');
    assert.equal(store.reserve('request-one', 'other', '+5511912345678'), 'conflict');
    store.clearAuth();
    assert.equal(store.get('creds'), null);
    assert.equal(store.reserve('request-one', 'payload', '+5511912345678'), 'accepted');
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('connected account identity exposes only a validated Brazilian phone JID', () => {
  assert.equal(connectedBrazilianAccountPhone('5511912345678@s.whatsapp.net'), '+5511912345678');
  assert.equal(connectedBrazilianAccountPhone('5511912345678:23@s.whatsapp.net'), '+5511912345678');
  assert.equal(connectedBrazilianAccountPhone('123456789@lid'), null);
  assert.equal(connectedBrazilianAccountPhone('12025550123@s.whatsapp.net'), null);
  assert.equal(connectedBrazilianAccountPhone('not-a-jid'), null);
  assert.equal(connectedBrazilianAccountPhone(null), null);
});

test('gateway rejects unauthenticated requests and does not resend accepted or indeterminate requests', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    let sends = 0;
    const connection = { state: 'open', send: async () => { sends++; } };
    const secret = 'x'.repeat(32);
    const adminSecret = 'y'.repeat(32);
    const pairingSecret = 'z'.repeat(32);
    const gateway = createGateway({ secret, adminSecret, pairingSecret, frontendOrigin: 'https://hub.example.test', connection, store });
    const token = 'a'.repeat(43);
    const request = { method: 'POST', path: '/internal/auth-messages', authorization: `Bearer ${secret}`, id: createHash('sha256').update(token).digest('hex'),
      body: { destination: '+5511912345678', purpose: 'recovery', link: `https://hub.example.test/reset-password?token=${'a'.repeat(43)}` } };
    request.rawBody = Buffer.from(JSON.stringify(request.body));
    request.timestamp = String(Math.floor(Date.now() / 1000));
    request.signature = createHmac('sha256', secret).update(request.timestamp + '.').update(request.rawBody).digest('hex');
    assert.equal((await gateway.handle({ ...request, authorization: 'Bearer wrong' })).status, 401);
    assert.equal((await gateway.handle({ ...request, timestamp: '1000000000' })).status, 401);
    assert.equal((await gateway.handle({ ...request, signature: '0'.repeat(64) })).status, 401);
    assert.equal((await gateway.handle({ ...request, id: 'another-id' })).status, 400);
    assert.equal((await gateway.handle({ method: 'GET', path: '/internal/pairing', authorization: `Bearer ${secret}` })).status, 401);
    assert.equal((await gateway.handle({ method: 'GET', path: '/internal/status', authorization: `Bearer ${adminSecret}` })).status, 200);
    assert.equal((await gateway.handle(request)).status, 202);
    assert.equal((await gateway.handle(request)).status, 202);
    assert.equal(sends, 1);
    connection.send = async () => { sends++; throw new Error('test'); };
    const secondToken = 'b'.repeat(43);
    const second = { ...request, id: createHash('sha256').update(secondToken).digest('hex'), body: { ...request.body, link: `https://hub.example.test/reset-password?token=${secondToken}` } };
    second.rawBody = Buffer.from(JSON.stringify(second.body));
    second.signature = createHmac('sha256', secret).update(second.timestamp + '.').update(second.rawBody).digest('hex');
    assert.equal((await gateway.handle(second)).status, 503);
    assert.equal((await gateway.handle(second)).status, 409);
    assert.equal(sends, 2);
    connection.state = 'disconnected';
    assert.equal((await gateway.handle({ ...request })).status, 503);
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('integration status is authenticated, replay-safe, and exposes only sanitized state', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const secret = 'x'.repeat(32), adminSecret = 'y'.repeat(32), pairingSecret = 'z'.repeat(32);
    const connection = { state: 'open', accountId: () => '5511912345678:4@s.whatsapp.net' };
    const gateway = createGateway({ secret, adminSecret, pairingSecret, pairingEnabled: false,
      frontendOrigin: 'https://hub.example.test', connection, store });
    const request = (id) => {
      const timestamp = String(Math.floor(Date.now() / 1000));
      const signed = `GET\n/internal/integration-status\n${timestamp}\n${id}`;
      return { method: 'GET', path: '/internal/integration-status', authorization: `Bearer ${secret}`,
        id, rawBody: Buffer.alloc(0), timestamp,
        signature: createHmac('sha256', secret).update(signed).digest('hex') };
    };
    const first = request('integration-status-request-one');
    assert.equal((await gateway.handle({ ...first, authorization: `Bearer ${adminSecret}` })).status, 401);
    assert.equal((await gateway.handle({ ...first, signature: '0'.repeat(64) })).status, 401);
    assert.equal((await gateway.handle({ ...first, method: 'POST' })).status, 400);
    assert.deepEqual(await gateway.handle(first), {
      status: 200,
      body: {
        connection_state: 'open',
        pairing_self_service_enabled: false,
        account_switch_available: false,
        connected_account_phone: '+5511912345678',
      },
    });
    assert.equal((await gateway.handle(first)).status, 409);
    for (const [index, state] of ['connecting', 'pairing', 'disconnected', 'logged_out', 'error', 'stopped', 'disabled'].entries()) {
      connection.state = state;
      const response = await gateway.handle(request(`integration-status-request-${index + 20}`));
      assert.deepEqual(response.body, {
        connection_state: state,
        pairing_self_service_enabled: false,
        account_switch_available: false,
        connected_account_phone: null,
      });
      assert.equal(Object.keys(response.body).length, 4);
    }
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('pairing-code delegation is opt-in, separately signed, replay-safe, and never needs the admin secret', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const secret = 'x'.repeat(32), adminSecret = 'y'.repeat(32), pairingSecret = 'z'.repeat(32);
    let calls = 0;
    const connection = { state: 'pairing', requestPairingCode: async () => { calls++; return 'ABCD1234'; } };
    const gateway = createGateway({ secret, adminSecret, pairingSecret, pairingEnabled: true,
      frontendOrigin: 'https://hub.example.test', connection, store });
    const body = { destination: '5511912345678' };
    const rawBody = Buffer.from(JSON.stringify(body));
    const timestamp = String(Math.floor(Date.now() / 1000));
    const request = { method: 'POST', path: '/internal/pairing/code', authorization: `Bearer ${pairingSecret}`,
      id: 'pairing-request-one', body, rawBody, timestamp,
      signature: createHmac('sha256', pairingSecret).update(timestamp + '.').update(rawBody).digest('hex') };
    assert.equal((await gateway.handle({ ...request, authorization: `Bearer ${adminSecret}` })).status, 401);
    assert.equal((await gateway.handle({ ...request, signature: '0'.repeat(64) })).status, 401);
    const accepted = await gateway.handle(request);
    assert.deepEqual(accepted, { status: 202, body: { code: 'ABCD1234' } });
    assert.equal((await gateway.handle(request)).status, 409);
    assert.equal(calls, 1);
    const disabled = createGateway({ secret, adminSecret, pairingEnabled: false,
      frontendOrigin: 'https://hub.example.test', connection, store });
    assert.equal((await disabled.handle(request)).status, 404);
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('account switch controls require their own HMAC secret, are replay-safe, and expose only candidate state/code', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  try {
    const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
    const secret = 'x'.repeat(32), adminSecret = 'y'.repeat(32), pairingSecret = 'z'.repeat(32), switchSecret = 'w'.repeat(32);
    const calls = [];
    const controller = {
      available: () => true,
      prepare: ({ operationId, requestedPhone }) => { calls.push(['prepare', operationId, requestedPhone]); return { state: 'connecting', expiresAt: 12345 }; },
      status: () => ({ state: 'ready', expiresAt: 12345 }),
      requestPairingCode: async () => 'ABCD1234', cancel: () => true, promote: () => ({ status: 'promoted' }),
    };
    const gateway = createGateway({ secret, adminSecret, pairingSecret, switchSecret, switchController: controller,
      frontendOrigin: 'https://hub.example.test', connection: { state: 'open' }, store });
    const operationId = 'a'.repeat(48);
    const request = (action, id, body = {}) => {
      const path = `/internal/account-switch/${operationId}/${action}`;
      const method = action === 'status' ? 'GET' : 'POST';
      const rawBody = method === 'GET' ? Buffer.alloc(0) : Buffer.from(JSON.stringify(body));
      const timestamp = String(Math.floor(Date.now() / 1000));
      const digest = createHash('sha256').update(rawBody).digest('hex');
      const signed = `${method}\n${path}\n${timestamp}\n${id}\n${digest}`;
      return { method, path, id, body: method === 'GET' ? null : body, rawBody, timestamp,
        authorization: `Bearer ${switchSecret}`, signature: createHmac('sha256', switchSecret).update(signed).digest('hex') };
    };
    const prepared = request('prepare', 'switch-request-one-1234', { phone: '+5511912345678' });
    assert.equal((await gateway.handle({ ...prepared, authorization: `Bearer ${secret}` })).status, 401);
    assert.equal((await gateway.handle({ ...prepared, signature: '0'.repeat(64) })).status, 401);
    assert.deepEqual(await gateway.handle(prepared), { status: 202, body: { state: 'connecting', expires_at: 12345 } });
    assert.equal((await gateway.handle(prepared)).status, 409);
    assert.deepEqual(calls, [['prepare', operationId, '+5511912345678']]);
    const status = await gateway.handle(request('status', 'switch-request-two-1234'));
    assert.deepEqual(status, { status: 200, body: { state: 'ready', expires_at: 12345 } });
    const code = await gateway.handle(request('code', 'switch-request-three-12'));
    assert.deepEqual(code, { status: 202, body: { code: 'ABCD1234', state: 'ready', expires_at: 12345 } });
    const promote = await gateway.handle(request('promote', 'switch-request-four-123', { confirm: true }));
    assert.deepEqual(promote, { status: 200, body: { state: 'promoted' } });
    store.close();
  } finally { removeTestDirectory(dir); }
});

test('storage failure stops the connection without reconnecting', () => {
  const events = new EventEmitter(), scheduled = [];
  const socket = { ev: events, end() { events.emit('connection.update', { connection: 'close' }); } };
  const connection = createConnection({ makeSocket: () => socket,
    auth: { state: {}, saveCreds() { throw new Error('synthetic'); } }, logger: {}, loggedOutCode: 401,
    schedule: fn => scheduled.push(fn) });
  events.emit('creds.update');
  assert.equal(connection.state, 'error');
  assert.equal(scheduled.length, 0);
});

test('retention preserves auth and replay records beyond all valid link lifetimes', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-'));
  const store = openStore(join(dir, 'state.sqlite'), randomBytes(32));
  try {
    store.setMany({ creds: 'synthetic-session' });
    store.reserve('old-request', 'payload', '+5511912345678');
    store.complete('old-request', 'indeterminate');
    assert.equal(store.cleanup(Date.now() + 34 * 86400000), 0);
    assert.equal(store.reserve('old-request', 'payload', '+5511912345678'), 'indeterminate');
    assert.equal(store.cleanup(Date.now() + 36 * 86400000), 1);
    assert.equal(store.get('creds'), 'synthetic-session');
  } finally { store.close(); removeTestDirectory(dir); }
});

test('connection enters pairing, opens, reconnects, and stops on logout', async () => {
  const sockets = [], scheduled = [];
  const makeSocket = () => { const ev = new EventEmitter(); const socket = { ev, end() {}, sendMessage: async () => {} }; sockets.push(socket); return socket; };
  let resets = 0, saves = 0;
  const connection = createConnection({ makeSocket, auth: { state: {}, saveCreds() { saves++; }, reset() { resets++; } }, logger: {}, loggedOutCode: 401,
    schedule: (fn) => scheduled.push(fn) });
  sockets[0].ev.emit('connection.update', { qr: 'synthetic-qr' });
  assert.equal(connection.state, 'pairing');
  sockets[0].ev.emit('connection.update', { connection: 'open' });
  assert.equal(connection.state, 'open');
  assert.equal(connection.qr, null);
  sockets[0].ev.emit('connection.update', { connection: 'close' });
  assert.equal(connection.state, 'disconnected');
  scheduled.shift()();
  assert.equal(sockets.length, 2);
  sockets[1].ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 401 } } } });
  assert.equal(connection.state, 'logged_out');
  assert.equal(scheduled.length, 0);
  assert.equal(connection.resetPairing(), true);
  assert.equal(resets, 1);
  assert.equal(sockets.length, 3);
  assert.equal(connection.resetPairing(), false);
  connection.stop();
  sockets[2].ev.emit('creds.update');
  assert.equal(saves, 0, 'a stopped candidate or active connection cannot rewrite cleared credentials');
});
