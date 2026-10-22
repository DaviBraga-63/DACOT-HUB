import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request } from 'node:https';
import { request as upstreamRequest } from 'node:http';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';
import { tmpdir } from 'node:os';
import { once } from 'node:events';
import { createListener } from '../http-app.mjs';

test('real local TLS proxy verifies CA and hostname and preserves public route separation', async t => {
  const openssl = existsSync('C:/Program Files/Git/usr/bin/openssl.exe') ? 'C:/Program Files/Git/usr/bin/openssl.exe' : 'openssl';
  if (spawnSync(openssl, ['version'], { stdio: 'ignore' }).status !== 0) {
    t.skip('OpenSSL is required for disposable certificates; TLS integration not executed'); return;
  }
  const dir = mkdtempSync(join(tmpdir(), 'dacot-wa-tls-'));
  const generate = args => assert.equal(spawnSync(openssl, args, { cwd: dir, stdio: 'ignore' }).status, 0, 'test certificate generation failed');
  let upstream, proxy;
  try {
    generate(['req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout', 'ca.key', '-out', 'ca.crt', '-days', '1', '-subj', '/CN=DACOT disposable test CA', '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign']);
    generate(['req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout', 'server.key', '-out', 'server.csr', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost', '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'extendedKeyUsage=serverAuth']);
    generate(['x509', '-req', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key', '-CAcreateserial', '-days', '1', '-copy_extensions', 'copy', '-out', 'server.crt']);
    upstream = createListener({ gateway: { handle: async () => ({ status: 401 }) } });
    upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
    proxy = createServer({ key: readFileSync(join(dir, 'server.key')), cert: readFileSync(join(dir, 'server.crt')) }, (req, res) => {
      const target = upstreamRequest({ host: '127.0.0.1', port: upstream.address().port, path: req.url, method: req.method, headers: req.headers }, response => {
        res.writeHead(response.statusCode, response.headers); response.pipe(res);
      });
      target.on('error', () => { res.writeHead(502); res.end(); }); req.pipe(target);
    });
    proxy.listen(0, '127.0.0.1'); await once(proxy, 'listening');
    const get = (path, trust = true, servername = 'localhost') => new Promise((resolve, reject) => {
      const req = request({ host: '127.0.0.1', port: proxy.address().port, path, servername,
        ...(trust ? { ca: readFileSync(join(dir, 'ca.crt')) } : {}) }, res => {
        res.resume(); res.on('end', () => resolve(res.statusCode));
      });
      req.on('error', reject); req.end();
    });
    assert.equal(await get('/health'), 200);
    assert.equal(await get('/internal/pairing'), 404);
    await assert.rejects(get('/health', false));
    await assert.rejects(get('/health', true, 'wrong.example.test'), { code: 'ERR_TLS_CERT_ALTNAME_INVALID' });
  } finally {
    for (const server of [proxy, upstream]) if (server) { server.closeAllConnections(); await new Promise(r => server.close(r)); }
    const target = resolve(dir), root = resolve(tmpdir()) + sep;
    assert.ok(target.startsWith(root) && target.slice(root.length).startsWith('dacot-wa-tls-'));
    rmSync(target, { recursive: true, force: true });
  }
});
