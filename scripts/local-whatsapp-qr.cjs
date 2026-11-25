// Local operator display for the existing loopback-only administrative API.
// Never print the administrative secret or the raw QR payload.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
const requireGateway = createRequire(path.join(root, 'whatsapp-service', 'package.json'));
const qrTerminal = requireGateway('qrcode-terminal');
const config = fs.readFileSync(path.join(root, '.local-dev', 'gateway-v2.env'), 'utf8');
const registry = path.join(root, '.local-dev', 'processes.json');
const secret = /^WHATSAPP_ADMIN_SECRET=(.+)$/m.exec(config)?.[1]?.trim();
if (!secret || secret.length < 32) throw new Error('Chave administrativa local ausente');
let lastQr = '';
async function poll() {
  if (!fs.existsSync(registry)) {
    console.clear();
    console.log('O ambiente local foi encerrado.');
    return;
  }
  try {
    const headers = { Authorization: `Bearer ${secret}` };
    const status = await fetch('http://127.0.0.1:3015/internal/status', { headers, signal: AbortSignal.timeout(3000) });
    if (!status.ok) throw new Error('Status indisponível');
    const state = (await status.json()).state;
    if (state === 'open') { console.log('WhatsApp de teste conectado. Pode fechar esta janela.'); process.exit(0); }
    const response = await fetch('http://127.0.0.1:3015/internal/pairing', { headers, signal: AbortSignal.timeout(3000) });
    if (response.ok) {
      const qr = (await response.json()).qr;
      if (qr && qr !== lastQr) {
        lastQr = qr;
        console.clear();
        console.log('Sessão LOCAL de teste: escaneie em WhatsApp > Dispositivos conectados.');
        qrTerminal.generate(qr, { small: true });
      }
    } else if (lastQr) {
      console.clear();
      lastQr = '';
    }
  } catch { console.error('Gateway local indisponível; tentando novamente.'); }
  setTimeout(poll, 5000);
}
void poll();
