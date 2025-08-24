import os
import io
import struct
import time
import uuid
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

# pvporcupine (Porcupine Python)
import pvporcupine

app = Flask(__name__, static_folder="public", static_url_path="/")

# Configuration from env
ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY")
KEYWORD_PATHS = os.getenv("KEYWORD_PATHS", "").strip()
KEYWORDS = os.getenv("KEYWORDS", "").strip()
SENSITIVITIES = os.getenv("SENSITIVITIES", "").strip()

if not ACCESS_KEY:
    raise RuntimeError("Set PICOVOICE_ACCESS_KEY environment variable (from Picovoice Console)")

def parse_keyword_inputs():
    """
    Return tuple (use_paths: bool, values: list_of_paths_or_names, sensitivities_list)
    """
    sens = []
    if SENSITIVITIES:
        sens = [max(0.0, min(1.0, float(x.strip()))) for x in SENSITIVITIES.split(",") if x.strip() != ""]
    # Prefer explicit .ppn paths if provided
    if KEYWORD_PATHS:
        parts = [p.strip() for p in KEYWORD_PATHS.split(",") if p.strip() != ""]
        return True, parts, sens
    # Otherwise try built-in keywords
    if KEYWORDS:
        parts = [p.strip() for p in KEYWORDS.split(",") if p.strip() != ""]
        return False, parts, sens
    # Default to example built-in keyword
    return False, ["bumblebee"], sens

USE_PATHS, KEY_VALUES, SENS = parse_keyword_inputs()

# session store: session_id -> detector dict
# detector dict: { 'porcupine': porcupine_handle, 'frame_length': int, 'sample_rate': int, 'remainder': bytes }
SESSIONS = {}

def create_porcupine_detector():
    """
    Create a new pvporcupine instance using the configured keywords.
    Returns a dict with the instance and metadata.
    """
    # sensitivities: if not enough, pvporcupine will require equal length; we expand if needed
    if SENS:
        # ensure list length matches keywords
        while len(SENS) < len(KEY_VALUES):
            SENS.append(0.6)
        sensitivities = SENS[: len(KEY_VALUES)]
    else:
        sensitivities = [0.6] * len(KEY_VALUES)

    if USE_PATHS:
        # KEY_VALUES are file paths to .ppn
        porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_paths=KEY_VALUES, sensitivities=sensitivities)
    else:
        # KEY_VALUES are built-in keyword names (case-insensitive)
        # pvporcupine expects keyword_names in lower-case as strings like 'bumblebee'
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

    # Expect raw PCM16LE in request.data
    chunk = request.get_data()
    if not chunk or len(chunk) == 0:
        return jsonify({"detected": False})

    # prepend remainder from previous call
    buf = det["remainder"] + chunk

    frame_byte_len = det["frame_length"] * 2  # 16-bit = 2 bytes
    detected = False
    keyword_index = None

    # process as many full frames as we have
    offset = 0
    while (offset + frame_byte_len) <= len(buf):
        frame_bytes = buf[offset: offset + frame_byte_len]
        # unpack little-endian signed 16-bit integers
        # struct format: '<{n}h'
        fmt = "<{}h".format(det["frame_length"])
        frame = struct.unpack(fmt, frame_bytes)
        r = det["porcupine"].process(frame)
        if r >= 0:
            detected = True
            keyword_index = int(r)
            # stop processing further frames this request (optional: you could continue)
            offset += frame_byte_len
            break
        offset += frame_byte_len

    # Save leftover bytes for next chunk
    det["remainder"] = buf[offset:]

    return jsonify({"detected": detected, "keyword_index": keyword_index})

# Serve a minimal static page if you want (optional)
@app.route("/", methods=["GET"])
def index():
    # If you include a public/index.html, Flask will serve it automatically.
    if os.path.exists(os.path.join(app.static_folder, "index.html")):
        return send_from_directory(app.static_folder, "index.html")
    return (
        "<h3>Porcupine server running.</h3>"
        "<p>Use POST /session/start then POST raw PCM16LE to /audio?sessionId=...</p>"
    )

# Clean-up on shutdown (best-effort)
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
