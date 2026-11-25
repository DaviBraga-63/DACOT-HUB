import { AsyncLocalStorage } from 'node:async_hooks';

function addressParts(jid) {
  if (typeof jid !== 'string') return null;
  const match = /^(\d+)(?:_\d+)?(?::(\d+))?@(s\.whatsapp\.net|lid)$/.exec(jid);
  return match && { account: match[1], device: Number(match[2] || 0), kind: match[3] === 'lid' ? 'lid' : 'pn' };
}

function sameAccount(left, right) {
  return Boolean(left && right && left.kind === right.kind && left.account === right.account);
}

function summarizeCopyCandidates(jids) {
  const summary = { total: jids.length, pn: 0, lid: 0, unknown: 0, base: false };
  for (const jid of jids) {
    const address = addressParts(jid);
    summary[address?.kind ?? 'unknown'] += 1;
    if (address?.device === 0) summary.base = true;
  }
  return summary;
}

export function createConnection({ makeSocket, auth, logger, loggedOutCode, schedule = setTimeout,
  maxReconnectAttempts = 8, maxReconnectDelayMs = 60000, maxMessageRetries = 3,
  getMessage = async () => undefined, retainMessage = async () => {}, onOutboundEvent = () => {}, onStateChange }) {
  let socket, stopped = false, reconnectScheduled = false, reconnectAttempts = 0, ownDeviceInspection = null;
  const outgoing = new AsyncLocalStorage();
  const connection = {
    state: 'connecting', qr: null,
    accountId() {
      if (connection.state !== 'open') return null;
      return typeof socket?.user?.id === 'string' ? socket.user.id
        : (typeof auth.state.creds.me?.id === 'string' ? auth.state.creds.me.id : null);
    },
    async send(number, text, expiresAt, purpose) {
      if (connection.state !== 'open' || !socket) throw new Error('Not connected');
      const sessionId = connection.accountId();
      if (!sessionId) throw new Error('Missing active session');
      const destination = `${number.slice(1)}@s.whatsapp.net`;
      const observation = { copies: null };
      const sent = await outgoing.run(observation, () => socket.sendMessage(destination, { text }));
      if (!sent?.key || !sent.message) throw new Error('Missing outbound message');
      await retainMessage(sent.key, sessionId, sent.message, expiresAt);
      const sender = addressParts(sessionId);
      const destinationScope = sameAccount(addressParts(destination), sender) ? 'own_account'
        : sender?.kind === 'pn' ? 'other_account' : 'unknown';
      emitOutboundEvent('submitted', sent.key, undefined, {
        sessionId, purpose, destinationScope, copies: observation.copies,
      });
    },
    async requestPairingCode(number) {
      // Pairing codes are valid only while this instance owns an unregistered
      // connection.  Never expose the socket or QR outside this narrow method.
      if (!socket || !['connecting', 'pairing'].includes(connection.state)) throw new Error('Pairing unavailable');
      return socket.requestPairingCode(number);
    },
    async inspectOwnDevices() {
      // Baileys exposes this helper on the active socket. It performs only a
      // USync device-directory read; it does not call relayMessage,
      // assertSessions, or touch the Signal key store. The forced second read
      // deliberately refreshes the in-memory device cache, so run it at most
      // once per socket and expose aggregates only.
      if (ownDeviceInspection) return ownDeviceInspection;
      if (connection.state !== 'open' || !socket || typeof socket.getUSyncDevices !== 'function')
        return { state: 'unavailable' };
      const sessionId = connection.accountId();
      if (!sessionId) return { state: 'unavailable' };
      ownDeviceInspection = (async () => {
        try {
          const cachedDevices = await socket.getUSyncDevices([sessionId], true, true);
          const refreshedDevices = await socket.getUSyncDevices([sessionId], false, true);
          const summarize = devices => {
            const summary = { total: 0, pn: 0, lid: 0, unknown: 0 };
            for (const device of Array.isArray(devices) ? devices : []) {
              summary.total += 1;
              if (typeof device?.jid === 'string' && device.jid.endsWith('@s.whatsapp.net')) summary.pn += 1;
              else if (typeof device?.jid === 'string' && device.jid.endsWith('@lid')) summary.lid += 1;
              else summary.unknown += 1;
            }
            return summary;
          };
          const cacheProbe = summarize(cachedDevices), refreshedProbe = summarize(refreshedDevices);
          return {
            state: 'collected',
            // For a PN direct message Baileys separately constructs the bare
            // own-account DSM copy before adding USync-discovered companions.
            base_own_copy_for_pn_direct: true,
            cache_probe: cacheProbe,
            refreshed_probe: refreshedProbe,
            aggregate_changed: Object.keys(cacheProbe).some(key => cacheProbe[key] !== refreshedProbe[key]),
            identity_difference: 'not_collected',
          };
        } catch {
          return { state: 'unavailable' };
        }
      })();
      return ownDeviceInspection;
    },
    resetPairing() {
      if (connection.state !== 'logged_out' || stopped) return false;
      auth.reset();
      reconnectAttempts = 0;
      connect();
      return true;
    },
    stop() {
      stopped = true;
      setState('stopped');
      connection.qr = null;
      const current = socket;
      socket = null;
      if (current) {
        try { current.end(); } catch { /* Shutdown must still release the session lease. */ }
      }
    },
  };

  function setState(state) {
    connection.state = state;
    try { onStateChange?.(state); } catch { /* State reporting must not affect the socket. */ }
  }

  function emitOutboundEvent(kind, key, status, details) {
    try { onOutboundEvent({ kind, key, status, details }); }
    catch { /* Observability must never affect delivery or retry. */ }
  }

  function retryScope(key, socketUser) {
    const participant = addressParts(key?.participant);
    const own = [socketUser?.id, socketUser?.lid, auth.state.creds.me?.id, auth.state.creds.me?.lid]
      .map(addressParts);
    if (own.some(account => sameAccount(participant, account))) return 'own_account';
    if (own.some(account => account && account.kind === participant?.kind)
        && sameAccount(participant, addressParts(key?.remoteJid))) return 'destination';
    return 'unknown';
  }

  function scheduleReconnect() {
    if (stopped || reconnectScheduled) return;
    if (reconnectAttempts >= maxReconnectAttempts) {
      setState('error');
      connection.qr = null;
      return;
    }
    reconnectScheduled = true;
    const delay = Math.min(1000 * (2 ** reconnectAttempts), maxReconnectDelayMs);
    reconnectAttempts += 1;
    schedule(() => {
      reconnectScheduled = false;
      connect();
    }, delay);
  }

  function connect() {
    if (stopped) return;
    reconnectScheduled = false;
    setState('connecting');
    let nextSocket;
    try {
      nextSocket = makeSocket({ auth: auth.state, logger, syncFullHistory: false, markOnlineOnConnect: false,
        maxMsgRetryCount: maxMessageRetries,
        // Baileys calls this before encrypting each set of participants. Observe
        // targeted copies only and return exactly the original message.
        patchMessageBeforeSending: (message, jids) => {
          try {
            const observation = outgoing.getStore();
            if (observation && message?.deviceSentMessage && Array.isArray(jids)) {
              observation.copies = summarizeCopyCandidates(jids);
            }
          } catch { /* Diagnostics must not affect encryption. */ }
          return message;
        },
        getMessage: async messageKey => {
          let scope = 'unknown';
          try { scope = retryScope(messageKey, nextSocket?.user); } catch { /* Optional diagnostic. */ }
          const details = { retryScope: scope };
          emitOutboundEvent('retry_requested', messageKey, undefined, details);
          try {
            const message = await getMessage(messageKey);
            emitOutboundEvent(message ? 'retry_served' : 'retry_unavailable', messageKey, undefined, details);
            return message;
          } catch {
            emitOutboundEvent('retry_failed', messageKey, undefined, details);
            return undefined;
          }
        } });
    } catch {
      setState('disconnected');
      scheduleReconnect();
      return;
    }
    socket = nextSocket;
    // A replacement socket owns a different in-memory Baileys device cache.
    ownDeviceInspection = null;
    nextSocket.ev.on('creds.update', () => {
      if (stopped || socket !== nextSocket) return;
      try { auth.saveCreds(); }
      catch {
        stopped = true;
        setState('error');
        connection.qr = null;
        socket = null;
        try { nextSocket.end(); } catch { /* The credential-store failure remains the terminal state. */ }
      }
    });
    nextSocket.ev.on('messages.update', updates => {
      if (stopped || socket !== nextSocket || !Array.isArray(updates)) return;
      for (const { key, update } of updates) {
        if (Number.isInteger(update?.status)) emitOutboundEvent('status', key, update.status);
      }
    });
    nextSocket.ev.on('connection.update', ({ connection: status, lastDisconnect, qr }) => {
      if (stopped || socket !== nextSocket) return;
      if (qr) { connection.qr = qr; setState('pairing'); }
      if (status === 'open') {
        setState('open');
        connection.qr = null;
        reconnectAttempts = 0;
      }
      if (status === 'close') {
        connection.qr = null;
        socket = null;
        if (lastDisconnect?.error?.output?.statusCode === loggedOutCode) {
          setState('logged_out');
          return;
        }
        setState('disconnected');
        scheduleReconnect();
      }
    });
  }
  connect();
  return connection;
}
