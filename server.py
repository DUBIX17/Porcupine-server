import numpy as np
import pvporcupine
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------------------------
# Porcupine setup
# ---------------------------
porcupine = pvporcupine.create(keywords=["picovoice"])  # Replace with your wake word
FRAME_LENGTH = porcupine.frame_length

# ---------------------------
# Browser test page
# ---------------------------
@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ---------------------------
# WebSocket streaming (ESP32 + Browser)
# ---------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            # Receive raw PCM16 audio
            data = await ws.receive_bytes()
            pcm = np.frombuffer(data, dtype=np.int16)

            if len(pcm) < FRAME_LENGTH:
                continue

            # Process in frames
            for i in range(0, len(pcm) - FRAME_LENGTH, FRAME_LENGTH):
                frame = pcm[i:i+FRAME_LENGTH]
                if porcupine.process(frame) >= 0:
                    await ws.send_text("TRIGGER")
    except Exception as e:
        print("WebSocket error:", e)
    finally:
        await ws.close()
