import http from "node:http";
import { createReadStream, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const host = process.env.TENNIS_TERMINAL_HOST || "127.0.0.1";
const port = Number(process.env.TENNIS_TERMINAL_PORT || 4173);
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json; charset=utf-8",
};

const server = http.createServer((request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url, `http://${host}`).pathname);
    const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const candidate = normalize(join(root, relative));
    if (!candidate.startsWith(root)) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    const file = statSync(candidate).isDirectory() ? join(candidate, "index.html") : candidate;
    response.writeHead(200, {
      "Content-Type": contentTypes[extname(file)] || "application/octet-stream",
      "Cache-Control": "no-cache",
    });
    createReadStream(file).pipe(response);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found");
  }
});

server.listen(port, host, () => {
  console.log(`Tennis Rover terminal: http://${host}:${port}`);
  console.log("Press Ctrl+C to stop.");
});
