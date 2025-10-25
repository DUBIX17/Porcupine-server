// ====== Secure Porcupine WebSocket Server (HTTPS + WSS) ======
const fs = require("fs");
const path = require("path");
const express = require("express");
const https = require("https");
const WebSocket = require("ws");
const porcupine = require("@picovoice/porcupine-node");

// ====== SSL Certificates ======
// ⚠️ Use your own paths or generated self-signed certs for local testing:
// openssl req -nodes -new -x509 -keyout key.pem -out cert.pem
const options = {
  key: fs.readFileSync(path.join(__dirname, "key.pem")),
  cert: fs.readFileSync(path.join(__dirname, "cert.pem")),
};

// ====== Express + HTTPS ======
const app = express();
const server = https.createServer(options, app);
const wss = new WebSocket.Server({ server, path: "/ws-audio" });

const PORT = process.env.PORT || 3000;
const ACCESS_KEY = process.env.PORCUPINE_ACCESS_KEY || "";
const KEYWORD_PATHS = (process.env.KEYWORD_PATHS || "porcupine.ppn")
  .split(",")
  .map((s) => s.trim());
const sensitivities = [1, 1];

if (!ACCESS_KEY) {
  console.error("ERROR: PORCUPINE_ACCESS_KEY environment variable is required.");
  process.exit(1);
}

app.use(express.static(path.join(__dirname, "public")));

const SAMPLE_RATE = porcupine.SAMPLE_RATE || 16000;
const FRAME_LENGTH = porcupine.FRAME_LENGTH || 512;

console.log(`Porcupine sampleRate=${SAMPLE_RATE} frameLength=${FRAME_LENGTH}`);
console.log("Keyword paths:", KEYWORD_PATHS);

let porcupineHandle;
try {
  porcupineHandle = new porcupine.Porcupine(ACCESS_KEY, KEYWORD_PATHS, sensitivities);
  console.log("Porcupine initialized.");
} catch (err) {
  console.error("Failed to initialize Porcupine:", err);
  process.exit(1);
}

wss.on("connection", (ws, req) => {
  console.log("🔗 Client connected:", req.socket.remoteAddress);
  let sampleBuffer = new Int16Array(0);

  ws.on("message", (msg) => {
    if (typeof msg === "string") {
      try {
        const obj = JSON.parse(msg);
        if (obj?.type === "info") console.log("Client info:", obj);
      } catch {
        console.log("Received text:", msg);
      }
      return;
    }

    let buf = Buffer.from(msg);
    if (buf.length % 2 !== 0) buf = buf.slice(0, buf.length - 1);

    const incomingSamples = new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2);
    const combined = new Int16Array(sampleBuffer.length + incomingSamples.length);
    combined.set(sampleBuffer, 0);
    combined.set(incomingSamples, sampleBuffer.length);
    sampleBuffer = combined;

    while (sampleBuffer.length >= FRAME_LENGTH) {
      const frame = sampleBuffer.slice(0, FRAME_LENGTH);
      try {
        const keywordIndex = porcupineHandle.process(frame);
        if (keywordIndex >= 0) {
          ws.send(JSON.stringify({ event: "wake", keywordIndex }));
          console.log("🟢 Wake detected -> sent to client");
        }
      } catch (err) {
        console.error("Error while running porcupine.process:", err);
        ws.send(JSON.stringify({ event: "error", message: err.toString() }));
      }
      sampleBuffer =
        sampleBuffer.length === FRAME_LENGTH
          ? new Int16Array(0)
          : sampleBuffer.slice(FRAME_LENGTH);
    }
  });

  ws.on("close", () => console.log("🔴 Client disconnected"));
});

process.on("SIGINT", () => {
  console.log("Shutting down...");
  if (porcupineHandle) porcupineHandle.delete();
  process.exit(0);
});

server.listen(PORT, () => {
  console.log(`🚀 HTTPS + WSS server running on port ${PORT}`);
  console.log(`Open https://localhost:${PORT} to test`);
});
