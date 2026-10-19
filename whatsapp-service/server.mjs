import { createServer } from 'node:https';
import { readFileSync } from 'node:fs';
import pino from 'pino';
import makeWASocket, { BufferJSON, initAuthCreds, proto, DisconnectReason } from '@whiskeysockets/baileys';
import { baileysState, openStore } from './store.mjs';
import { createConnection } from './connection.mjs';
import { createGateway } from './gateway.mjs';

const env = process.env;
const key = Buffer.from(env.WHATSAPP_STORAGE_KEY || '', 'base64');
if (!env.WHATSAPP_DB_PATH || !env.WHATSAPP_TLS_KEY_FILE || !env.WHATSAPP_TLS_CERT_FILE)
  throw new Error('Missing required service configuration');
const store = openStore(env.WHATSAPP_DB_PATH, key);
const auth = baileysState(store, { BufferJSON, initAuthCreds, proto });
const connection = createConnection({ makeSocket: makeWASocket, auth, logger: pino({ level: 'silent' }),
                                      loggedOutCode: DisconnectReason.loggedOut });
const gateway = createGateway({ secret: env.WHATSAPP_SERVICE_SECRET, adminSecret: env.WHATSAPP_ADMIN_SECRET, frontendOrigin: env.WHATSAPP_FRONTEND_ORIGIN,
                                connection, store });
const server = createServer({ key: readFileSync(env.WHATSAPP_TLS_KEY_FILE), cert: readFileSync(env.WHATSAPP_TLS_CERT_FILE) }, (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Content-Type', 'application/json');
  const chunks = [];
  let length = 0;
  req.on('data', chunk => {
    length += chunk.length;
    if (length > 4096) req.destroy();
    else chunks.push(chunk);
  });
  req.on('end', async () => {
    try {
      const rawBody = Buffer.concat(chunks);
      const body = chunks.length ? JSON.parse(rawBody.toString('utf8')) : null;
      const result = await gateway.handle({ method: req.method, path: req.url, authorization: req.headers.authorization,
                                            id: req.headers['idempotency-key'], body, rawBody,
                                            timestamp: req.headers['x-dacot-timestamp'], signature: req.headers['x-dacot-signature'] });
      res.writeHead(result.status);
      res.end(JSON.stringify(result.body || {}));
    } catch { res.writeHead(400); res.end('{}'); }
  });
});
server.listen(Number(env.PORT || 3002), env.HOST || '127.0.0.1');
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  connection.stop();
  server.close(() => { store.close(); process.exit(0); });
});
