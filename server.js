const express = require("express");
const http = require("http");
const WebSocket = require("ws");
const path = require("path");

// Porcupine Node SDK
const porcupine = require("@picovoice/porcupine-node");

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: "/ws-audio" });

const PORT = process.env.PORT || 3000;
const ACCESS_KEY = process.env.PORCUPINE_ACCESS_KEY || "";
const KEYWORD_PATHS = (process.env.KEYWORD_PATHS || "porcupine.ppn").split(",").map(s => s.trim());
const sensitivities = [1, 1];  // ✅ two values, one for each keyword

if (!ACCESS_KEY) {
  console.error("ERROR: PORCUPINE_ACCESS_KEY environment variable is required.");
  process.exit(1);
}

// Serve static client files
app.use(express.static(path.join(__dirname, "public")));

// Porcupine parameters
const SAMPLE_RATE = porcupine.SAMPLE_RATE || 16000; // usually 16000
const FRAME_LENGTH = porcupine.FRAME_LENGTH || 512; // usually 512

console.log(`Porcupine sampleRate=${SAMPLE_RATE} frameLength=${FRAME_LENGTH}`);
console.log("Keyword paths:", KEYWORD_PATHS);

// Create Porcupine instance (one global instance shared by all clients is simplest)
// If you need per-client models or instances, create per-WS-client instances instead.
let porcupineHandle;
try {
  porcupineHandle = new porcupine.Porcupine(ACCESS_KEY, KEYWORD_PATHS, sensitivities);
  console.log("Porcupine initialized.");
} catch (err) {
  console.error("Failed to initialize Porcupine:", err);
  process.exit(1);
}

// Helper: convert ArrayBuffer (16-bit PCM little-endian) to Int16Array
function abToInt16(ab) {
  return new Int16Array(ab);
}

// For incoming audio we will collect samples into a buffer of Int16,
// then each time we have FRAME_LENGTH samples we call porcupineHandle.process(frame)
wss.on("connection", (ws, req) => {
  console.log("Client connected:", req.socket.remoteAddress);

  // per-connection buffer for samples
  let sampleBuffer = new Int16Array(0);

  ws.on("message", (msg) => {
    // Expect binary messages (ArrayBuffer) containing 16-bit PCM little-endian samples (Int16)
    if (typeof msg === "string") {
      // protocol messages
      try {
        const obj = JSON.parse(msg);
        if (obj && obj.type === "info") {
          console.log("Client info:", obj);
        }
      } catch (e) {
        console.log("Received text message:", msg);
      }
      return;
    }

    // msg is Buffer (Node.js Buffer). We need to view as Int16Array.
    // Ensure even length
    const buf = Buffer.from(msg);
    if (buf.length % 2 !== 0) {
      // drop last byte if odd (shouldn't usually happen)
      console.warn("Received audio buffer with odd length, dropping last byte.");
      buf = buf.slice(0, buf.length - 1);
    }

    // Create Int16Array view (little-endian)
    const incomingSamples = new Int16Array(buf.buffer, buf.byteOffset, buf.length / 2);

    // Append to sampleBuffer
    const combined = new Int16Array(sampleBuffer.length + incomingSamples.length);
    combined.set(sampleBuffer, 0);
    combined.set(incomingSamples, sampleBuffer.length);
    sampleBuffer = combined;

    // Process in FRAME_LENGTH chunks
    while (sampleBuffer.length >= FRAME_LENGTH) {
      const frame = sampleBuffer.slice(0, FRAME_LENGTH); // new Int16Array
      // Call porcupine process
      try {
        const keywordIndex = porcupineHandle.process(frame);
        if (keywordIndex >= 0) {
          const resp = JSON.stringify({ event: "wake", keywordIndex });
          ws.send(resp);
          console.log("Wake detected -> sent to client");
        }
      } catch (err) {
        console.error("Error while running porcupine.process:", err);
        // Optionally notify client of error
        ws.send(JSON.stringify({ event: "error", message: err.toString() }));
      }

      // Remove processed samples from buffer
      if (sampleBuffer.length === FRAME_LENGTH) {
        sampleBuffer = new Int16Array(0);
      } else {
        sampleBuffer = sampleBuffer.slice(FRAME_LENGTH);
      }
    }
  });

  ws.on("close", () => {
    console.log("Client disconnected.");
  });
});

process.on("SIGINT", () => {
  console.log("Shutting down...");
  if (porcupineHandle) porcupineHandle.delete();
  process.exit(0);
});

server.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
  console.log(`Open http://localhost:${PORT} (or your Render URL) to test the client.`);
});
