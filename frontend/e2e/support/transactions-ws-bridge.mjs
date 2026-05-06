/**
 * Minimal WS fan-out + HTTP push for the live transaction grid (VITE_TRANSACTIONS_WS_URL).
 * Playwright pushes a row after a real evaluate so the virtualized grid shows an integrated "Block".
 *
 * Usage: node e2e/support/transactions-ws-bridge.mjs <wsPort> <httpPort>
 */
import { createServer } from "node:http";
import { WebSocketServer } from "ws";

const wsPort = Number(process.argv[2] || 47999);
const httpPort = Number(process.argv[3] || 47998);

/** @type {Set<import('ws').WebSocket>} */
const clients = new Set();

const wss = new WebSocketServer({ port: wsPort, host: "127.0.0.1" });
wss.on("connection", (ws) => {
  clients.add(ws);
  ws.on("close", () => clients.delete(ws));
});

const httpServer = createServer((req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, clients: clients.size }));
    return;
  }
  if (req.method === "POST" && req.url === "/push") {
    let body = "";
    req.on("data", (c) => {
      body += c;
    });
    req.on("end", () => {
      let n = 0;
      for (const c of clients) {
        if (c.readyState === 1) {
          c.send(body);
          n += 1;
        }
      }
      res.writeHead(204);
      res.end();
      if (process.env.E2E_WS_BRIDGE_LOG === "1") {
        console.error(`[transactions-ws-bridge] push bytes=${body.length} clients=${n}`);
      }
    });
    return;
  }
  res.writeHead(404);
  res.end();
});

httpServer.listen(httpPort, "127.0.0.1", () => {
  // eslint-disable-next-line no-console
  process.stdout.write(
    JSON.stringify({
      wsPort,
      httpPort,
      wsUrl: `ws://127.0.0.1:${wsPort}`,
      pushUrl: `http://127.0.0.1:${httpPort}/push`,
    }),
  );
});
