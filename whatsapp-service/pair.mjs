// Run in a private interactive terminal; do not redirect output to logs/files.
import { request } from 'node:https';
import qrcode from 'qrcode-terminal';

const base = process.env.WHATSAPP_SERVICE_URL;
const secret = process.env.WHATSAPP_ADMIN_SECRET;
if (!base || !secret || secret.length < 32) throw new Error('Service URL and secret are required');
const reset = process.argv.includes('--reset');
const endpoint = new URL(reset ? '/internal/pairing/reset' : '/internal/pairing', base);
if (endpoint.protocol !== 'https:') throw new Error('HTTPS is required');
const req = request(endpoint, { method: reset ? 'POST' : 'GET', headers: { Authorization: `Bearer ${secret}` }, timeout: 10000 }, res => {
  let text = '';
  res.setEncoding('utf8');
  res.on('data', chunk => { text += chunk; if (text.length > 8192) req.destroy(); });
  res.on('end', () => {
    try {
      const data = JSON.parse(text);
      if (reset && res.statusCode === 202) { console.log('Novo pareamento iniciado; execute novamente sem --reset para obter o QR.'); return; }
      if (res.statusCode !== 200 || !data.qr) throw new Error('QR unavailable');
      qrcode.generate(data.qr, { small: true });
    } catch { console.error('Pareamento indisponível; verifique o estado do serviço.'); process.exitCode = 1; }
  });
});
req.on('timeout', () => req.destroy());
req.on('error', () => { console.error('Não foi possível conectar ao serviço.'); process.exitCode = 1; });
req.end();
