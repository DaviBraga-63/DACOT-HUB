// Local-only proxy for invitation pages. No administrative or database routes.
const https = require('node:https');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const state = path.join(__dirname, '..', '.local-dev');
const tlsDir = process.env.LOCAL_TLS_DIR || path.join(state, 'tls');
const stopFile = path.join(process.env.LOCAL_STATE_DIR || state, 'https.stop');
const allowedGet = new Set(['/reset-password', '/confirm-owner-whatsapp', '/confirm-owner-email', '/favicon.ico', '/manifest.json']);
const allowedApi = new Set(['/api/auth/reset-password/context', '/api/auth/reset-password', '/api/auth/confirm-owner-whatsapp', '/api/auth/confirm-owner-email']);
const server = https.createServer({ key: fs.readFileSync(path.join(tlsDir, 'server-dev.key')), cert: fs.readFileSync(path.join(tlsDir, 'server-dev.crt')) }, (req, res) => {
  const pathname = req.url.split('?')[0];
  const staticAsset = /^\/static\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+$/.test(pathname)
    && !pathname.split('/').some(segment => segment === '.' || segment === '..') && req.method === 'GET';
  const page = allowedGet.has(pathname) && req.method === 'GET';
  const api = allowedApi.has(pathname) && req.method === 'POST';
  if (!staticAsset && !page && !api) { res.writeHead(404).end(); return; }
  const { 'content-type': contentType, 'content-length': contentLength } = req.headers;
  const headers = {};
  if (contentType) headers['content-type'] = contentType;
  if (contentLength) headers['content-length'] = contentLength;
  const upstream = http.request({ host: '127.0.0.1', port: Number(process.env.LOCAL_HUB_PORT || 8000), path: req.url, method: req.method, headers }, response => {
    res.writeHead(response.statusCode, response.headers); response.pipe(res);
  });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(503); res.end(); });
  req.pipe(upstream);
});
server.listen(Number(process.env.LOCAL_HTTPS_PORT || 8444), '127.0.0.1');
const checkStop = setInterval(() => {
  if (fs.existsSync(stopFile)) stop();
}, 250);
function stop() {
  clearInterval(checkStop);
  server.close();
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, stop);
