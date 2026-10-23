import { createServer as httpServer } from 'node:http';
import { createServer as httpsServer } from 'node:https';
import { readFileSync } from 'node:fs';

const adminPaths = new Set(['/internal/status', '/internal/pairing', '/internal/pairing/reset']);

export function createListener({ gateway, administrative = false, tls, now = Date.now }) {
  let windowStart = now(), attempts = 0;
  const handler = (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Content-Type', 'application/json');
    const reply = (status, body = {}) => { res.writeHead(status); res.end(JSON.stringify(body)); };
    if (!administrative && req.url === '/health' && req.method === 'GET') return reply(200, { ok: true });
    if (now() - windowStart >= 60000) { windowStart = now(); attempts = 0; }
    // Global, bounded admission independent of forgeable proxy headers.
    if (++attempts > (administrative ? 30 : 120)) return reply(429);
    if (administrative) {
      if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress)) return reply(404);
      if (!adminPaths.has(req.url)) return reply(404);
      if ((req.url === '/internal/pairing/reset' ? 'POST' : 'GET') !== req.method) return reply(405);
    } else if (!['/internal/auth-messages', '/internal/pairing/code'].includes(req.url) || req.method !== 'POST') return reply(404);
    const chunks = [];
    let length = 0, oversized = false;
    req.on('data', chunk => {
      length += chunk.length;
      if (length > 4096) { if (!oversized) reply(413); oversized = true; }
      else chunks.push(chunk);
    });
    req.on('error', () => { if (!res.headersSent) reply(400); });
    req.on('end', async () => {
      if (oversized) return;
      try {
        const rawBody = Buffer.concat(chunks);
        const body = rawBody.length ? JSON.parse(rawBody.toString('utf8')) : null;
        const result = await gateway.handle({ method: req.method, path: req.url,
          authorization: req.headers.authorization, id: req.headers['idempotency-key'], body, rawBody,
          timestamp: req.headers['x-dacot-timestamp'], signature: req.headers['x-dacot-signature'] });
        reply(result.status, result.body);
      } catch { if (!res.headersSent) reply(400); }
    });
  };
  const server = tls ? httpsServer(tls, handler) : httpServer(handler);
  server.headersTimeout = 10000;
  server.requestTimeout = 15000;
  server.setTimeout(15000, socket => socket.destroy());
  return server;
}

export function transportConfiguration(env) {
  const mode = env.WHATSAPP_TRANSPORT || 'https';
  if (!['https', 'proxy-http'].includes(mode)) throw new Error('Invalid transport mode');
  if (env.WHATSAPP_ENABLED && !['true', 'false'].includes(env.WHATSAPP_ENABLED)) throw new Error('Invalid activation setting');
  const port = Number(env.PORT || 3002), adminPort = Number(env.WHATSAPP_ADMIN_PORT || 3003);
  if (![port, adminPort].every(p => Number.isInteger(p) && p > 0 && p < 65536) || port === adminPort)
    throw new Error('Invalid listener ports');
  const tls = mode === 'https' ? {
    key: readFileSync(env.WHATSAPP_TLS_KEY_FILE), cert: readFileSync(env.WHATSAPP_TLS_CERT_FILE),
  } : undefined;
  return { tls, port, adminPort, host: env.HOST || '0.0.0.0', enabled: env.WHATSAPP_ENABLED === 'true' };
}
