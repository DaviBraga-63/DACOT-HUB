import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { tmpdir } from 'node:os';
import { randomBytes, createHash, createHmac } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createListener, transportConfiguration } from '../http-app.mjs';
import { openStore } from '../store.mjs';

async function serve(options, run) {
  const server = createListener(options);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try { await run(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test('proxy HTTP configuration requires explicit choice and activation remains opt-in', () => {
  const config = transportConfiguration({ WHATSAPP_TRANSPORT: 'proxy-http' });
  assert.equal(config.tls, undefined);
  assert.equal(config.port, 3002);
  assert.equal(config.host, '0.0.0.0');
  assert.equal(config.enabled, false);
  assert.throws(() => transportConfiguration({ WHATSAPP_TRANSPORT: 'http' }));
  assert.throws(() => transportConfiguration({ WHATSAPP_TRANSPORT: 'proxy-http', WHATSAPP_ENABLED: 'yes' }));
  assert.throws(() => transportConfiguration({ WHATSAPP_TRANSPORT: 'proxy-http', WHATSAPP_ADMIN_PORT: '3002' }));
  assert.throws(() => transportConfiguration({})); // HTTPS never silently becomes HTTP.
});

test('public listener health contains no private state and all administrative routes are inaccessible', async () => {
  let calls = 0;
  await serve({ gateway: { handle: async () => { calls++; return { status: 401 }; } } }, async base => {
    const health = await fetch(`${base}/health`);
    assert.equal(health.status, 200);
    assert.deepEqual(await health.json(), { ok: true });
    assert.equal(health.headers.get('cache-control'), 'no-store');
    for (const path of ['/internal/status', '/internal/pairing', '/internal/pairing/reset']) {
      const r = await fetch(base + path, { headers: { 'X-Forwarded-For': '127.0.0.1', Authorization: 'Bearer synthetic' } });
      assert.equal(r.status, 404);
    }
    assert.equal(calls, 0);
    assert.equal((await fetch(`${base}/internal/auth-messages`, { method: 'POST', body: '{}' })).status, 401);
    assert.equal(calls, 1);
    assert.equal((await fetch(`${base}/internal/auth-messages`, { method: 'POST', body: 'x'.repeat(4097) })).status, 413);
    assert.equal(calls, 1);
  });
});

test('administrative listener enforces methods and bounded rate limiting without trusting forwarding headers', async () => {
  let now = 0;
  await serve({ administrative: true, now: () => now, gateway: { handle: async () => ({ status: 401 }) } }, async base => {
    assert.equal((await fetch(`${base}/internal/auth-messages`, { method: 'POST' })).status, 404);
    assert.equal((await fetch(`${base}/internal/pairing/reset`)).status, 405);
    for (let i = 0; i < 28; i++)
      assert.equal((await fetch(`${base}/internal/status`, { headers: { 'X-Forwarded-For': `192.0.2.${i}` } })).status, 401);
    assert.equal((await fetch(`${base}/internal/status`)).status, 429);
    now = 60001;
    assert.equal((await fetch(`${base}/internal/status`)).status, 401);
  });
});

test('real entrypoint starts in maintenance without importing Baileys or touching an existing session', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-start-'));
  const publicProbe = createListener({ gateway: {} }), adminProbe = createListener({ gateway: {} });
  publicProbe.listen(0, '127.0.0.1'); adminProbe.listen(0, '127.0.0.1');
  await Promise.all([once(publicProbe, 'listening'), once(adminProbe, 'listening')]);
  const port = publicProbe.address().port, adminPort = adminProbe.address().port;
  await Promise.all([publicProbe, adminProbe].map(s => new Promise(r => s.close(r))));
  const secret = randomBytes(32).toString('hex'), adminSecret = randomBytes(32).toString('hex');
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'].includes(k.toUpperCase())));
  Object.assign(env, { WHATSAPP_TRANSPORT: 'proxy-http', WHATSAPP_ENABLED: 'false', HOST: '127.0.0.1',
    PORT: String(port), WHATSAPP_ADMIN_PORT: String(adminPort), WHATSAPP_DB_PATH: join(dir, 'test.sqlite'),
    WHATSAPP_STORAGE_KEY: randomBytes(32).toString('base64'), WHATSAPP_SERVICE_SECRET: secret,
    WHATSAPP_ADMIN_SECRET: adminSecret, WHATSAPP_FRONTEND_ORIGIN: 'https://hub.example.test' });
  const before = openStore(env.WHATSAPP_DB_PATH, Buffer.from(env.WHATSAPP_STORAGE_KEY, 'base64'));
  before.setMany({ creds: 'synthetic-session-preserved-in-maintenance' }); before.close();
  const child = spawn(process.execPath, [fileURLToPath(new URL('../server.mjs', import.meta.url))], { env, stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });
  let errors = ''; child.stderr.on('data', chunk => { errors += chunk.toString(); });
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      assert.equal(child.exitCode, null, 'maintenance entrypoint exited');
      try { ready = (await fetch(`http://127.0.0.1:${port}/health`)).status === 200; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(ready, true);
    const result = await fetch(`http://127.0.0.1:${adminPort}/internal/status`, { headers: { Authorization: `Bearer ${adminSecret}` } });
    assert.deepEqual(await result.json(), { state: 'disabled' });
    const token = 'z'.repeat(43), timestamp = String(Math.floor(Date.now() / 1000));
    const body = JSON.stringify({ destination: '+5511912345678', purpose: 'recovery', link: `https://hub.example.test/reset-password?token=${token}` });
    const signed = createHmac('sha256', secret).update(timestamp + '.').update(body).digest('hex');
    const unavailable = await fetch(`http://127.0.0.1:${port}/internal/auth-messages`, {
      method: 'POST', body, headers: { Authorization: `Bearer ${secret}`, 'X-DACOT-Timestamp': timestamp,
        'X-DACOT-Signature': signed, 'Idempotency-Key': createHash('sha256').update(token).digest('hex') } });
    assert.equal(unavailable.status, 503);
    assert.equal((await fetch(`http://127.0.0.1:${port}/internal/pairing`, { headers: { Authorization: `Bearer ${adminSecret}` } })).status, 404);
    assert.equal(errors.includes(secret) || errors.includes(adminSecret), false);
  } finally {
    const exited = once(child, 'exit'); child.kill(); await exited;
    const after = openStore(env.WHATSAPP_DB_PATH, Buffer.from(env.WHATSAPP_STORAGE_KEY, 'base64'));
    assert.equal(after.get('creds'), 'synthetic-session-preserved-in-maintenance'); after.close();
    const target = resolve(dir), root = resolve(tmpdir()) + sep;
    assert.ok(target.startsWith(root) && target.slice(root.length).startsWith('dacot-wa-start-'));
    rmSync(target, { recursive: true, force: true });
  }
});
