// Local-only proxy for invitation pages. No administrative or database routes.
const https = require('node:https');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const state = path.join(__dirname, '..', '.local-dev', 'tls');
const allowedGet = new Set(['/reset-password', '/confirm-owner-whatsapp', '/confirm-owner-email', '/favicon.ico', '/manifest.json']);
const allowedApi = new Set(['/api/auth/reset-password/context', '/api/auth/reset-password', '/api/auth/confirm-owner-whatsapp', '/api/auth/confirm-owner-email']);
const server = https.createServer({ key: fs.readFileSync(path.join(state, 'localhost.key')), cert: fs.readFileSync(path.join(state, 'localhost.crt')) }, (req, res) => {
  let url;
  try { url = new URL(req.url, 'https://localhost:8443'); } catch { res.writeHead(400).end(); return; }
  const staticAsset = url.pathname.startsWith('/static/') && req.method === 'GET';
  const page = allowedGet.has(url.pathname) && req.method === 'GET';
  const api = allowedApi.has(url.pathname) && ['GET', 'POST'].includes(req.method);
  if (!staticAsset && !page && !api) { res.writeHead(404).end(); return; }
  const upstream = http.request({ host: '127.0.0.1', port: 8000, path: req.url, method: req.method, headers: req.headers }, response => {
    res.writeHead(response.statusCode, response.headers); response.pipe(res);
  });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(503); res.end(); });
  req.pipe(upstream);
});
server.listen(8443, '127.0.0.1');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close());
