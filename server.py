import os
import numpy as np
import pvporcupine
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

access_key = os.environ.get("PICOVOICE_ACCESS_KEY")
if not access_key:
    raise ValueError("Porcupine access key not set!")
    
# ---------------------------
# Multi wake-word setup
# ---------------------------
# Built-in keywords (optional)
built_in_keywords = ["jarvis"]

# Custom models
custom_keyword_paths = [
    "porcupine_params/word1.ppn"
]

porcupine = pvporcupine.create(
    access_key=access_key,
    keywords=built_in_keywords,
    keyword_paths=custom_keyword_paths
)

# Combined list of all keywords for index mapping
all_keywords = built_in_keywords + [p.split("/")[-1].split(".")[0] for p in custom_keyword_paths]
FRAME_LENGTH = porcupine.frame_length

# ---------------------------
# Browser UI
# ---------------------------
@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ---------------------------
# WebSocket streaming endpoint (ESP32 & Browser)
# ---------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_bytes()
            pcm = np.frombuffer(data, dtype=np.int16)

            if len(pcm) < FRAME_LENGTH:
                continue

            # Process in frames
            for i in range(0, len(pcm) - FRAME_LENGTH, FRAME_LENGTH):
                frame = pcm[i:i+FRAME_LENGTH]
                result = porcupine.process(frame)
                if result >= 0:
                    detected_word = all_keywords[result]
                    await ws.send_text(f"TRIGGER:{detected_word}")
    except Exception as e:
        print("WebSocket error:", e)
    finally:
        await ws.close()
