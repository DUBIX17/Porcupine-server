    import express from "express";
import https from "https";
import http from "http";
import WebSocket from "ws";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import porcupine from "@picovoice/porcupine-node";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const app = express();
const PORT = process.env.PORT || 3000;
const ACCESS_KEY = process.env.PORCUPINE_ACCESS_KEY || "";
const KEYWORD_PATHS = (process.env.KEYWORD_PATHS || "porcupine.ppn").split(",").map(s => s.trim());
const sensitivities = [1, 1];

if (!ACCESS_KEY) {
  console.error("ERROR: PORCUPINE_ACCESS_KEY is required.");
  process.exit(1);
}

// Serve static files
app.use(express.static(path.join(__dirname, "public")));

// ===== Porcupine Setup =====
const SAMPLE_RATE = porcupine.SAMPLE_RATE || 16000;
const FRAME_LENGTH = porcupine.FRAME_LENGTH || 512;

console.log(`Porcupine sampleRate=${SAMPLE_RATE}, frameLength=${FRAME_LENGTH}`);
console.log("Keyword paths:", KEYWORD_PATHS);

let porcupineHandle;
try {
  porcupineHandle = new porcupine.Porcupine(ACCESS_KEY, KEYWORD_PATHS, sensitivities);
  console.log("✅ Porcupine initialized");
} catch (err) {
  console.error("❌ Failed to initialize Porcupine:", err);
  process.exit(1);
}

// ===== WebSocket Setup =====
// On Render, HTTPS/WSS is managed automatically
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: "/ws-audio" });

wss.on("connection", (ws, req) => {
  console.log("Client connected:", req.socket.remoteAddress);
  let sampleBuffer = new Int16Array(0);

  ws.on("message", (msg) => {
    if (typeof msg === "string") {
      try {
        const obj = JSON.parse(msg);
        if (obj.type === "info") console.log("Client info:", obj);
      } catch {
        console.log("Received text:", msg);
      }
      return;
    }

    const buf = Buffer.from(msg);
    if (buf.length % 2 !== 0) buf = buf.slice(0, buf.length - 1);
    const incoming = new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2);

    const combined = new Int16Array(sampleBuffer.length + incoming.length);
    combined.set(sampleBuffer, 0);
    combined.set(incoming, sampleBuffer.length);
    sampleBuffer = combined;

    while (sampleBuffer.length >= FRAME_LENGTH) {
      const frame = sampleBuffer.slice(0, FRAME_LENGTH);
      try {
        const keywordIndex = porcupineHandle.process(frame);
        if (keywordIndex >= 0) {
          const resp = JSON.stringify({ event: "wake", keywordIndex });
          ws.send(resp);
          console.log("Wake detected -> sent to client");
        }
      } catch (err) {
        console.error("Porcupine error:", err);
        ws.send(JSON.stringify({ event: "error", message: err.toString() }));
      }
      sampleBuffer = sampleBuffer.slice(FRAME_LENGTH);
    }
  });

  ws.on("close", () => console.log("Client disconnected."));
});

process.on("SIGINT", () => {
  console.log("Shutting down...");
  if (porcupineHandle) porcupineHandle.delete();
  process.exit(0);
});

server.listen(PORT, () => {
  console.log(`🌐 Listening on port ${PORT}`);
  console.log(`WSS URL: wss://your-app-name.onrender.com/ws-audio`);
});
