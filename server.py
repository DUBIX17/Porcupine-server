#!/usr/bin/env python3
"""
Porcupine Flask server: accepts raw PCM frames and runs pvporcupine (server-side).
Endpoints:
- POST /session/start    -> create session, returns sessionId, sampleRate, frameLength
- POST /audio?sessionId= -> post raw PCM16LE bytes; returns {"detected": bool, "keyword_index": int?}
- POST /session/end      -> close session
- GET  /health           -> basic health
Serves static files from ./public for browser UI.
"""
import os
import uuid
import struct
from flask import Flask, request, jsonify, send_from_directory, abort
from dotenv import load_dotenv

load_dotenv()

# pvporcupine (Porcupine Python)
try:
    import pvporcupine
except Exception as e:
    # Helpful error: pvporcupine may fail to import if native libs/wheels missing.
    raise RuntimeError("Failed to import pvporcupine. Install pvporcupine and ensure native libs are available. Original error: " + str(e))

app = Flask(__name__, static_folder="public", static_url_path="/")

ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY")
if not ACCESS_KEY:
    raise RuntimeError("Set PICOVOICE_ACCESS_KEY environment variable (get one from Picovoice Console)")

KEYWORD_PATHS = os.getenv("KEYWORD_PATHS", "").strip()
KEYWORDS = os.getenv("KEYWORDS", "").strip()
SENSITIVITIES = os.getenv("SENSITIVITIES", "").strip()

def parse_keyword_inputs():
    # returns (use_paths: bool, values:list, sensitivities:list)
    sens = []
    if SENSITIVITIES:
        sens = [max(0.0, min(1.0, float(x.strip()))) for x in SENSITIVITIES.split(",") if x.strip() != ""]
    if KEYWORD_PATHS:
        parts = [p.strip() for p in KEYWORD_PATHS.split(",") if p.strip() != ""]
        return True, parts, sens
    if KEYWORDS:
        parts = [p.strip() for p in KEYWORDS.split(",") if p.strip() != ""]
        return False, parts, sens
    # default built-in
    return False, ["bumblebee"], sens

USE_PATHS, KEY_VALUES, SENS = parse_keyword_inputs()

# session store: session_id -> detector dict
# detector dict: { 'porcupine': porcupine_handle, 'frame_length': int, 'sample_rate': int, 'remainder': bytes }
SESSIONS = {}

def create_porcupine_detector():
    if SENS:
        sens = list(SENS)
        while len(sens) < len(KEY_VALUES):
            sens.append(0.6)
        sensitivities = sens[:len(KEY_VALUES)]
    else:
        sensitivities = [0.6] * len(KEY_VALUES)

    if USE_PATHS:
        # KEY_VALUES are file paths to .ppn
        porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_paths=KEY_VALUES, sensitivities=sensitivities)
    else:
        # KEY_VALUES are built-in names like 'bumblebee' (pvporcupine expects lower-case)
        names = [k.lower() for k in KEY_VALUES]
        porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_names=names, sensitivities=sensitivities)

    return {
        "porcupine": porcupine,
        "frame_length": porcupine.frame_length,
        "sample_rate": porcupine.sample_rate,
        "remainder": b"",
    }

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "sample_rate": 16000})

@app.route("/session/start", methods=["POST"])
def session_start():
    det = create_porcupine_detector()
    sid = str(uuid.uuid4())
    SESSIONS[sid] = det
    return jsonify({
        "sessionId": sid,
        "sampleRate": det["sample_rate"],
        "frameLength": det["frame_length"],
        "note": "Send 16 kHz, 16-bit PCM (LE), mono frames to /audio?sessionId=<id>"
    })

@app.route("/session/end", methods=["POST"])
def session_end():
    data = request.get_json(force=True, silent=True) or {}
    sid = data.get("sessionId") or request.args.get("sessionId")
    if not sid:
        return jsonify({"error": "sessionId required"}), 400
    det = SESSIONS.pop(sid, None)
    if det:
        try:
            det["porcupine"].delete()
        except Exception:
            pass
    return jsonify({"ended": bool(det)})

@app.route("/audio", methods=["POST"])
def audio():
    sid = request.args.get("sessionId")
    if not sid:
        return jsonify({"error": "sessionId query param required"}), 400
    det = SESSIONS.get(sid)
    if not det:
        return jsonify({"error": "invalid sessionId"}), 400

    chunk = request.get_data()
    if not chunk:
        return jsonify({"detected": False})

    buf = det["remainder"] + chunk
    frame_byte_len = det["frame_length"] * 2  # 16-bit = 2 bytes
    detected = False
    keyword_index = None

    offset = 0
    while (offset + frame_byte_len) <= len(buf):
        frame_bytes = buf[offset: offset + frame_byte_len]
        fmt = "<{}h".format(det["frame_length"])
        frame = struct.unpack(fmt, frame_bytes)
        try:
            r = det["porcupine"].process(frame)
        except Exception as e:
            # in rare cases process can fail if input malformed
            return jsonify({"error": "porcupine process error", "detail": str(e)}), 500
        if r >= 0:
            detected = True
            keyword_index = int(r)
            offset += frame_byte_len
            break
        offset += frame_byte_len

    det["remainder"] = buf[offset:]
    return jsonify({"detected": detected, "keyword_index": keyword_index})

# Serve static UI
@app.route("/", methods=["GET"])
def index():
    if os.path.exists(os.path.join(app.static_folder, "index.html")):
        return send_from_directory(app.static_folder, "index.html")
    return "<h3>Porcupine server running.</h3><p>Use POST /session/start then POST raw PCM16LE to /audio?sessionId=...</p>"

# teardown
@app.teardown_appcontext
def teardown(exception):
    for det in list(SESSIONS.values()):
        try:
            det["porcupine"].delete()
        except Exception:
            pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
