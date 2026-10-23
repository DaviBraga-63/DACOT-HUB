import { createHash, createHmac, timingSafeEqual } from 'node:crypto';

function sameSecret(candidate, expected) {
  const a = Buffer.from(candidate || ''), b = Buffer.from(expected || '');
  return a.length === b.length && a.length >= 32 && timingSafeEqual(a, b);
}

export function createGateway({ secret, adminSecret, pairingSecret, pairingEnabled = false,
  frontendOrigin, connection, store, now = Date.now }) {
  const origin = new URL(frontendOrigin);
  if (origin.protocol !== 'https:' || origin.origin !== frontendOrigin.replace(/\/$/, '') || origin.username || origin.password)
    throw new Error('Invalid frontend origin');
  if (Buffer.byteLength(secret || '') < 32) throw new Error('Invalid service secret');
  if (Buffer.byteLength(adminSecret || '') < 32 || sameSecret(secret, adminSecret)) throw new Error('Invalid administrative secret');
  if (pairingEnabled && (Buffer.byteLength(pairingSecret || '') < 32 || sameSecret(secret, pairingSecret) || sameSecret(adminSecret, pairingSecret)))
    throw new Error('Invalid pairing secret');
  const recentStatusRequests = new Map();

  function reserveStatusRequest(id, timestamp) {
    const nowSeconds = Math.floor(now() / 1000);
    for (const [key, seenAt] of recentStatusRequests) {
      if (seenAt < nowSeconds - 125) recentStatusRequests.delete(key);
    }
    const key = createHash('sha256').update(id).digest('hex');
    if (recentStatusRequests.has(key)) return false;
    recentStatusRequests.set(key, timestamp);
    return true;
  }

  return {
    async handle({ method, path, authorization, id, body, rawBody, timestamp, signature }) {
      const administrative = ['/internal/status', '/internal/pairing', '/internal/pairing/reset'].includes(path);
      const pairing = path === '/internal/pairing/code';
      const integrationStatus = path === '/internal/integration-status';
      if (pairing && !pairingEnabled) return { status: 404 };
      const expected = administrative ? adminSecret : (pairing ? pairingSecret : secret);
      if (!authorization?.startsWith('Bearer ') || !sameSecret(authorization.slice(7), expected)) return { status: 401 };
      if (method === 'GET' && path === '/internal/status') return { status: 200, body: { state: connection.state } };
      if (integrationStatus) {
        if (method !== 'GET' || !/^[A-Za-z0-9_-]{16,128}$/.test(id || '') || !/^[a-f0-9]{64}$/.test(signature || '')
            || !Buffer.isBuffer(rawBody) || rawBody.length !== 0 || !/^\d{10}$/.test(timestamp || '')
            || Math.abs(Math.floor(now() / 1000) - Number(timestamp)) > 120) return { status: 400 };
        const signed = `GET\n/internal/integration-status\n${timestamp}\n${id}`;
        const expectedSignature = createHmac('sha256', secret).update(signed).digest('hex');
        if (!sameSecret(signature, expectedSignature)) return { status: 401 };
        if (!reserveStatusRequest(id, Number(timestamp))) return { status: 409 };
        return { status: 200, body: {
          connection_state: connection.state,
          pairing_self_service_enabled: pairingEnabled,
        } };
      }
      if (method === 'GET' && path === '/internal/pairing') {
        return connection.qr ? { status: 200, body: { qr: connection.qr } } : { status: 404 };
      }
      if (method === 'POST' && path === '/internal/pairing/reset') {
        return connection.resetPairing() ? { status: 202, body: { state: 'connecting' } } : { status: 409 };
      }
      if (pairing) {
        if (method !== 'POST' || !/^[A-Za-z0-9_-]{1,128}$/.test(id || '') || !body ||
            !/^55[1-9][0-9]{9,10}$/.test(body.destination || '') || !/^[a-f0-9]{64}$/.test(signature || '') ||
            !Buffer.isBuffer(rawBody) || !/^\d{10}$/.test(timestamp || '') ||
            Math.abs(Math.floor(now() / 1000) - Number(timestamp)) > 120) return { status: 400 };
        const expectedSignature = createHmac('sha256', pairingSecret).update(timestamp + '.').update(rawBody).digest('hex');
        if (!sameSecret(signature, expectedSignature)) return { status: 401 };
        const reservation = store.reservePairing(id, body.destination);
        if (reservation === 'limited') return { status: 429 };
        if (reservation !== 'new') return { status: 409 };
        try {
          const code = await connection.requestPairingCode(body.destination);
          if (typeof code !== 'string' || !/^[A-Z0-9]{4}-?[A-Z0-9]{4}$/.test(code)) throw new Error('Invalid pairing code');
          store.completePairing(id, 'accepted');
          return { status: 202, body: { code } };
        } catch {
          store.completePairing(id, 'unavailable');
          return { status: 503 };
        }
      }
      if (method !== 'POST' || path !== '/internal/auth-messages') return { status: 404 };
      if (!/^\d{10}$/.test(timestamp || '') || Math.abs(Math.floor(now() / 1000) - Number(timestamp)) > 120 ||
          !/^[a-f0-9]{64}$/.test(signature || '') || !Buffer.isBuffer(rawBody)) return { status: 401 };
      const expectedSignature = createHmac('sha256', secret).update(timestamp + '.').update(rawBody).digest('hex');
      if (!sameSecret(signature, expectedSignature)) return { status: 401 };
      if (!id || !/^[A-Za-z0-9_-]{1,128}$/.test(id) || !body ||
          !/^\+55[1-9][0-9][0-9]{8,9}$/.test(body.destination || '') ||
          !['first_access', 'recovery'].includes(body.purpose)) return { status: 400 };
      let link;
      try { link = new URL(body.link); } catch { return { status: 400 }; }
      if (link.origin !== origin.origin || link.pathname !== '/reset-password' || link.hash ||
          [...link.searchParams.keys()].length !== 1 || !/^[A-Za-z0-9_-]{32,128}$/.test(link.searchParams.get('token') || ''))
        return { status: 400 };
      if (id !== createHash('sha256').update(link.searchParams.get('token')).digest('hex')) return { status: 400 };
      if (connection.state !== 'open') return { status: 503 };
      const payload = JSON.stringify([body.destination, body.purpose, body.link]);
      const previous = store.reserve(id, payload, body.destination);
      if (previous === 'accepted') return { status: 202, body: { state: 'accepted' } };
      if (previous === 'limited') return { status: 429 };
      if (previous !== 'new') return { status: 409, body: { state: 'indeterminate' } };
      const text = body.purpose === 'first_access'
        ? `Olá! Seu acesso ao DACOT foi criado.\n\nPara definir sua senha e começar a utilizar o sistema, acesse:\n\n${body.link}\n\nEste link é individual, pode ser utilizado uma única vez e possui validade de 30 dias.\n\nSe o prazo terminar, você poderá solicitar um novo link.`
        : `Olá! Recebemos uma solicitação de recuperação de senha da sua conta DACOT.\n\nPara definir uma nova senha, acesse:\n\n${body.link}\n\nEste link pode ser utilizado uma única vez e possui validade de 24 horas.\n\nSe você não solicitou a recuperação, ignore esta mensagem.`;
      try {
        await connection.send(body.destination, text);
        store.complete(id, 'accepted');
        return { status: 202, body: { state: 'accepted' } };
      } catch {
        // A network error after send may mean the message was accepted remotely.
        // Never automatically repeat an indeterminate request.
        store.complete(id, 'indeterminate');
        return { status: 503, body: { state: 'indeterminate' } };
      }
    },
  };
}
