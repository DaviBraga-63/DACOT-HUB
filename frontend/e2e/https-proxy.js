// Local-only HTTPS entry point for the isolated E2E runner.
const fs = require("fs");
const http = require("http");
const https = require("https");

const server = https.createServer({
  key: fs.readFileSync(process.env.E2E_TLS_KEY),
  cert: fs.readFileSync(process.env.E2E_TLS_CERT),
}, (req, res) => {
  const pathname = new URL(req.url, "https://localhost").pathname;
  const api = pathname === "/api" || pathname.startsWith("/api/");
  const port = api ? 8443 : 3000;
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

server.listen(9443);
