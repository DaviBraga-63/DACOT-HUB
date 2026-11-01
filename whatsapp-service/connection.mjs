export function createConnection({ makeSocket, auth, logger, loggedOutCode, schedule = setTimeout }) {
  let socket, stopped = false, delay = 1000, reconnectScheduled = false;
  const connection = {
    state: 'connecting', qr: null,
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
    accountId() {
      // The connected identity comes from Baileys credentials/socket state. Keep
      // it internal; the gateway sanitizes it before any status response.
      if (connection.state !== 'open') return null;
      return typeof socket?.user?.id === 'string' ? socket.user.id
        : (typeof auth.state.creds.me?.id === 'string' ? auth.state.creds.me.id : null);
    },
    resetPairing() {
      if (connection.state !== 'logged_out' || stopped) return false;
      auth.reset();
      start();
      return true;
    },
    stop() { stopped = true; connection.state = 'stopped'; connection.qr = null; if (socket) socket.end(); },
  };
  function start() {
    if (stopped) return;
    reconnectScheduled = false;
    connection.state = 'connecting';
    socket = makeSocket({ auth: auth.state, logger, syncFullHistory: false, markOnlineOnConnect: false });
    socket.ev.on('creds.update', () => {
      try { auth.saveCreds(); }
      catch { stopped = true; connection.state = 'error'; connection.qr = null; socket.end(); }
    });
    socket.ev.on('connection.update', ({ connection: status, lastDisconnect, qr }) => {
      if (stopped) return;
      if (qr) { connection.qr = qr; connection.state = 'pairing'; }
      if (status === 'open') { connection.state = 'open'; connection.qr = null; delay = 1000; }
      if (status === 'close') {
        connection.qr = null;
        if (lastDisconnect?.error?.output?.statusCode === loggedOutCode) { connection.state = 'logged_out'; return; }
        connection.state = 'disconnected';
        if (!reconnectScheduled) { reconnectScheduled = true; schedule(start, delay); delay = Math.min(delay * 2, 30000); }
      }
    });
  }
  start();
  return connection;
}
