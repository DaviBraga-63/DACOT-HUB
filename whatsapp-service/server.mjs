import { baileysState, openStore } from './store.mjs';
import { createConnection } from './connection.mjs';
import { createGateway } from './gateway.mjs';
import { createListener, transportConfiguration } from './http-app.mjs';

const env = process.env;
const config = transportConfiguration(env);
const key = Buffer.from(env.WHATSAPP_STORAGE_KEY || '', 'base64');
const store = openStore(env.WHATSAPP_DB_PATH || '/var/data/whatsapp.sqlite', key);
let connection = { state: 'disabled', qr: null, stop() {}, resetPairing() { return false; }, requestPairingCode() { throw new Error('Pairing unavailable'); } };
const proxyConnection = {
  get state() { return connection.state; }, get qr() { return connection.qr; },
  send(...args) { return connection.send(...args); }, resetPairing() { return connection.resetPairing(); },
  requestPairingCode(...args) { return connection.requestPairingCode(...args); },
};
const gateway = createGateway({ secret: env.WHATSAPP_SERVICE_SECRET, adminSecret: env.WHATSAPP_ADMIN_SECRET,
  pairingSecret: env.WHATSAPP_PAIRING_SERVICE_SECRET,
  pairingEnabled: env.WHATSAPP_PAIRING_SELF_SERVICE_ENABLED === 'true',
  frontendOrigin: env.WHATSAPP_FRONTEND_ORIGIN, connection: proxyConnection, store });
const server = createListener({ gateway, tls: config.tls });
// Administration is loopback-only, reachable through an authorized shell/SSH tunnel.
const admin = createListener({ gateway, administrative: true });
let stopping = false;
async function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  clearInterval(cleanup);
  connection.stop();
  const deadline = setTimeout(() => process.exit(1), 10000);
  deadline.unref();
  await Promise.all([server, admin].map(listener => new Promise(resolve => {
    listener.close(resolve); listener.closeIdleConnections();
  })));
  store.close();
  process.exit(code);
}
store.cleanup();
const cleanup = setInterval(() => {
  try { store.cleanup(); } catch { console.error('whatsapp_storage_failure'); void shutdown(1); }
}, 3600000);
cleanup.unref();
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void shutdown(); });
try {
  await Promise.all([[server, config.port, config.host], [admin, config.adminPort, '127.0.0.1']].map(
    ([listener, port, host]) => new Promise((resolve, reject) => {
      listener.once('error', reject); listener.listen(port, host, resolve);
    })));
  // Credentials and listeners must be valid before connecting to WhatsApp.
  if (config.enabled) {
    const { default: makeWASocket, BufferJSON, initAuthCreds, proto, DisconnectReason } = await import('@whiskeysockets/baileys');
    const { default: pino } = await import('pino');
    const auth = baileysState(store, { BufferJSON, initAuthCreds, proto });
    connection = createConnection({ makeSocket: makeWASocket, auth, logger: pino({ level: 'silent' }),
      loggedOutCode: DisconnectReason.loggedOut });
  }
} catch { console.error('whatsapp_startup_failure'); await shutdown(1); }
