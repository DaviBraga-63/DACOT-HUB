export function createConnection({ makeSocket, auth, logger, loggedOutCode, schedule = setTimeout,
  maxReconnectAttempts = 8, maxReconnectDelayMs = 60000, maxMessageRetries = 3,
  getMessage = async () => undefined, retainMessage = async () => {}, onOutboundEvent = () => {}, onStateChange }) {
  let socket, stopped = false, reconnectScheduled = false, reconnectAttempts = 0;
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
