// Local-only HTTPS entry point for an isolated E2E frontend.
const fs = require("fs");
const http = require("http");
const https = require("https");

const listenPort = Number(process.env.E2E_HTTPS_PROXY_PORT || 9443);
const frontendPort = Number(process.env.E2E_HTTPS_FRONTEND_PORT || 3000);
const apiPort = Number(process.env.E2E_HTTPS_API_PORT || 8443);

if (![listenPort, frontendPort, apiPort].every((port) => Number.isSafeInteger(port) && port > 0 && port <= 65_535)) {
  throw new Error("Invalid isolated E2E HTTPS proxy port");
}

const server = https.createServer({
  key: fs.readFileSync(process.env.E2E_TLS_KEY),
  cert: fs.readFileSync(process.env.E2E_TLS_CERT),
}, (req, res) => {
  const pathname = new URL(req.url, "https://localhost").pathname;
  const api = pathname === "/api" || pathname.startsWith("/api/");
  const port = api ? apiPort : frontendPort;
  const upstream = http.request({
    hostname: "127.0.0.1",
    port,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: `localhost:${port}` },
  }, (response) => {
    res.writeHead(response.statusCode, response.headers);
    response.pipe(res);
  });
  upstream.on("error", () => {
    if (!res.headersSent) res.writeHead(502);
    res.end();
  });
  req.pipe(upstream);
});

server.listen(listenPort, "127.0.0.1");
