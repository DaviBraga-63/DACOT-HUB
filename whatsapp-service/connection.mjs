export function createConnection({ makeSocket, auth, logger, loggedOutCode, schedule = setTimeout,
  maxReconnectAttempts = 8, maxReconnectDelayMs = 60000, onStateChange }) {
  let socket, stopped = false, reconnectScheduled = false, reconnectAttempts = 0;
  const connection = {
    state: 'connecting', qr: null,
    accountId() {
      if (connection.state !== 'open') return null;
      return typeof socket?.user?.id === 'string' ? socket.user.id
        : (typeof auth.state.creds.me?.id === 'string' ? auth.state.creds.me.id : null);
    },
    async send(number, text) {
      if (connection.state !== 'open' || !socket) throw new Error('Not connected');
      await socket.sendMessage(`${number.slice(1)}@s.whatsapp.net`, { text });
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
      nextSocket = makeSocket({ auth: auth.state, logger, syncFullHistory: false, markOnlineOnConnect: false });
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
