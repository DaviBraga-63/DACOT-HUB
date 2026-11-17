export function createConnection({ makeSocket, auth, logger, loggedOutCode, schedule = setTimeout,
  maxReconnectAttempts = 8, maxReconnectDelayMs = 60000, maxMessageRetries = 3,
  getMessage = async () => undefined, retainMessage = async () => {}, onOutboundEvent = () => {}, onStateChange }) {
  let socket, stopped = false, reconnectScheduled = false, reconnectAttempts = 0, ownDeviceInspection = null;
  const connection = {
    state: 'connecting', qr: null,
    accountId() {
      if (connection.state !== 'open') return null;
      return typeof socket?.user?.id === 'string' ? socket.user.id
        : (typeof auth.state.creds.me?.id === 'string' ? auth.state.creds.me.id : null);
    },
    async send(number, text, expiresAt) {
      if (connection.state !== 'open' || !socket) throw new Error('Not connected');
      const sessionId = connection.accountId();
      if (!sessionId) throw new Error('Missing active session');
      const sent = await socket.sendMessage(`${number.slice(1)}@s.whatsapp.net`, { text });
      if (!sent?.key || !sent.message) throw new Error('Missing outbound message');
      await retainMessage(sent.key, sessionId, sent.message, expiresAt);
      emitOutboundEvent('submitted', sent.key);
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

  function emitOutboundEvent(kind, key, status) {
    try { onOutboundEvent({ kind, key, status }); }
    catch { /* Observability must never affect delivery or retry. */ }
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
        getMessage: async messageKey => {
          emitOutboundEvent('retry_requested', messageKey);
          try {
            const message = await getMessage(messageKey);
            emitOutboundEvent(message ? 'retry_served' : 'retry_unavailable', messageKey);
            return message;
          } catch {
            emitOutboundEvent('retry_failed', messageKey);
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
