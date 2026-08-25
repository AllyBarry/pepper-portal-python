"""
Pepper Control Web App (Flask)
--------------------------------
A tiny Flask app that serves a single web page with buttons to:
- Prompt for Pepper IP and port on first load, auto-connect
- Test connection to Pepper
- Play/stop a WAV file that lives on Pepper
- Run built-in or custom animations (sync or async)
- Stop all animations

Prereqs
- Python (the client machine) with the NAOqi Python SDK available (module `qi`).
  * Ensure your PYTHONPATH points to the NAOqi SDK lib, e.g. (example path):
    export PYTHONPATH="$PYTHONPATH:/path/to/pynaoqi-python2.7-2.5.7.1-linux64/lib/python2.7/site-packages"
- Flask: pip install Flask==3.0.0

Run
  python2 app.py
Then open: http://127.0.0.1:5000

NOTE: This app intentionally has no auth and trusts the provided Pepper IP. If you expose it on a network, add auth and allow-listing.
"""

from __future__ import print_function

import base64
import io
import json
import os
import random
import re
import struct
import sys
import subprocess
import time
import traceback
import urllib2
import zlib
from functools import wraps
import itertools
import threading

from flask import Flask, Response, request, jsonify, render_template

try:
    import qi  # NAOqi Python SDK
    _QI_IMPORT_ERROR = None
except Exception:
    qi = None
    _QI_IMPORT_ERROR = traceback.format_exc()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from pepper_core import PepperController, PepperScripter
except Exception:
    PepperController = None
    PepperScripter = None

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR") or os.path.join(BASE_DIR, "scripts")
SCENES_DIR = os.environ.get("SCENES_DIR") or os.path.join(os.path.dirname(BASE_DIR), "scenes")

for _directory in (SCRIPTS_DIR, SCENES_DIR):
    if not os.path.isdir(_directory):
        try:
            os.makedirs(_directory)
        except OSError:
            pass

# --- Simple in-memory session cache per (ip, port) (optional) ---
_sessions = {}
_sessions_lock = threading.Lock()
_connect_test_lock = threading.Lock()
_jobs = {}
_job_counter = itertools.count(1)
_jobs_lock = threading.Lock()
_camera_counter = itertools.count(1)
_camera_lock = threading.Lock()
_vision_awareness_lock = threading.Lock()
_vision_awareness_states = {}
_ollama_generation_lock = threading.Lock()
_microphone_lock = threading.Lock()
_microphone_state_lock = threading.Lock()
_microphone_cancel_events = {}

CAMERA_IDS = {"top": 0, "bottom": 1}
CAMERA_RESOLUTIONS = {
    "160x120": 0,  # QQVGA
    "320x240": 1,  # QVGA
    "640x480": 2,  # VGA
}
RGB_COLOR_SPACE = 11
CAMERA_TIMEOUT_MS = 5000
OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
).rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava:latest")
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
OLLAMA_VISION_MODEL_URL = "https://ollama.com/library/qwen3-vl"
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120"))
OLLAMA_KEEP_ALIVE_SECONDS = int(os.environ.get("OLLAMA_KEEP_ALIVE_SECONDS", "0"))
OLLAMA_CONTEXT_LENGTH = max(
    1024,
    min(8192, int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "4096"))),
)
LOCAL_STT_BASE_URL = os.environ.get(
    "LOCAL_STT_BASE_URL", "http://host.docker.internal:8765"
).rstrip("/")
LOCAL_STT_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_STT_TIMEOUT_SECONDS", "180"))
LOCAL_STT_SETUP_URL = "https://pypi.org/project/mlx-whisper/"
LOCAL_STT_CONTAINER_SETUP_URL = "https://pypi.org/project/faster-whisper/"
PEPPER_MIC_SAMPLE_RATE = 16000
PEPPER_MIC_MIN_SECONDS = 2
PEPPER_MIC_MAX_SECONDS = 45
PEPPER_MIC_SILENCE_SECONDS = float(os.environ.get("PEPPER_MIC_SILENCE_SECONDS", "3"))
PEPPER_MIC_ENERGY_THRESHOLD = float(os.environ.get("PEPPER_MIC_ENERGY_THRESHOLD", "1200"))
PEPPER_MIC_ENERGY_POLL_SECONDS = 0.17
PEPPER_MIC_ROBOT_PATH = "/data/home/nao/pepper_portal_mic.wav"
PEPPER_MIC_FILE_KEY = "pepper_portal_mic.wav"
PEPPER_CONNECT_TIMEOUT_MS = int(os.environ.get("PEPPER_CONNECT_TIMEOUT_MS", "12000"))
PEPPER_GESTURE_CHANCE = max(
    0.0,
    min(1.0, float(os.environ.get("PEPPER_GESTURE_CHANCE", "0.35"))),
)
PEPPER_GESTURES = {
    "bow": ("animations/Stand/Gestures/BowShort_1", "a short polite bow"),
    "calm": ("animations/Stand/Gestures/CalmDown_1", "a calming motion"),
    "confused": ("animations/Stand/Emotions/Neutral/Confused_1", "a confused motion"),
    "enthusiastic": ("animations/Stand/Gestures/Enthusiastic_4", "an enthusiastic emphasis"),
    "explain": ("animations/Stand/Gestures/Explain_1", "a gentle explanatory gesture"),
    "give": ("animations/Stand/Gestures/Give_3", "a presenting or offering motion"),
    "hello": ("animations/Stand/Gestures/Hey_1", "a friendly greeting"),
    "me": ("animations/Stand/Gestures/Me_1", "a self-reference gesture"),
    "no": ("animations/Stand/Gestures/No_1", "a clear negative gesture"),
    "roar": ("animations/Stand/Waiting/Monster_1", "a playful monster or dinosaur roar"),
    "shrug": ("animations/Stand/Gestures/IDontKnow_1", "an uncertain shrug"),
    "thinking": ("animations/Stand/Gestures/Thinking_1", "a thoughtful motion"),
    "yes": ("animations/Stand/Gestures/Yes_1", "a clear affirmative gesture"),
    "you": ("animations/Stand/Gestures/You_1", "a gentle listener-reference gesture"),
}
PEPPER_SYSTEM_PROMPT = os.environ.get(
    "PEPPER_SYSTEM_PROMPT",
    (
        "You are Pepper, a friendly social robot speaking aloud to a person. "
        "Answer naturally in one to three short sentences. Use plain text only, "
        "with no markdown, lists, stage directions, or emoji."
    ),
)


def pepper_response_schema():
    """Structured Ollama response: speech plus one optional, allowlisted gesture."""
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "gesture": {
                "type": "string",
                "enum": ["none"] + sorted(PEPPER_GESTURES.keys()),
            },
            "gesture_mode": {
                "type": "string",
                "enum": ["none", "optional", "requested"],
            },
        },
        "required": ["reply", "gesture", "gesture_mode"],
        "additionalProperties": False,
    }


def pepper_gesture_prompt(gestures_enabled):
    if not gestures_enabled:
        return (
            "Return gesture as 'none' and gesture_mode as 'none'. "
            "Gestures are disabled for this turn."
        )
    choices = "; ".join(
        "%s: %s" % (key, PEPPER_GESTURES[key][1])
        for key in sorted(PEPPER_GESTURES)
    )
    return (
        "Return only JSON matching the provided schema. Put the exact words Pepper should "
        "say in 'reply'. Set gesture_mode to 'requested' when the user explicitly asks Pepper "
        "to move, gesture, wave, bow, nod, act something out, or imitate an animal; choose the "
        "closest safe gesture. Such explicit requests should be performed. Use 'roar' for playful "
        "monster, dinosaur, lion, or T-Rex acting requests. For ordinary replies, "
        "set gesture_mode to 'optional' only when one gesture clearly reinforces the meaning, "
        "and otherwise use gesture='none' and gesture_mode='none'. When Pepper genuinely does "
        "not know, is uncertain, or needs clarification, 'confused' or 'shrug' is a natural "
        "optional choice. Never claim to know something just to avoid showing uncertainty. "
        "Never force a movement. "
        "Available gestures: %s." % choices
    )


def requested_gesture_from_prompt(prompt):
    """Recognize direct movement commands so safe explicit requests are reliable."""
    normalized = prompt.lower().replace("-", " ")
    action_request = re.search(
        r"(?:^|\b(?:please|then|and)\b\s*)"
        r"(?:(?:can|could|would|will)\s+you\s+|i\s+want\s+you\s+to\s+)?"
        r"(?:do|perform|show|act|look|pretend|imitate|wave|bow|nod|shake|shrug|"
        r"roar|point|greet|calm|explain)\b",
        normalized,
    )
    if not action_request:
        return None

    keyword_groups = (
        ("roar", (r"\broar\b", r"\bt\s*rex\b", r"\bdinosaur\b", r"\bmonster\b")),
        ("confused", (r"\bconfus", r"\bpuzzl", r"\bdon'?t know\b", r"\bdo not know\b")),
        ("shrug", (r"\bshrug\b", r"\bnot sure\b", r"\buncertain\b")),
        ("hello", (r"\bwave\b", r"\bgreet\b", r"\bhello\b", r"\bhi\b")),
        ("bow", (r"\bbow\b",)),
        ("yes", (r"\bnod\b", r"\byes gesture\b", r"\baffirmative\b")),
        ("no", (r"\bshake (?:your )?head\b", r"\bno gesture\b", r"\bnegative\b")),
        ("thinking", (r"\bthink", r"\bponder", r"\bremember")),
        ("calm", (r"\bcalm", r"\brelax")),
        ("enthusiastic", (r"\benthusias", r"\bexcited", r"\bcelebrat")),
        ("explain", (r"\bexplain", r"\bdemonstrat")),
        ("give", (r"\bgive", r"\bpresent", r"\boffer")),
        ("me", (r"\bpoint to (?:yourself|you)\b", r"\bgesture to yourself\b")),
        ("you", (r"\bpoint to me\b", r"\bgesture to me\b")),
    )
    for gesture, patterns in keyword_groups:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return gesture
    return None


def conversational_gesture_from_reply(reply):
    """Supply restrained body language when the model admits uncertainty."""
    normalized = reply.lower()
    uncertainty_phrases = (
        "i don't know",
        "i do not know",
        "i'm not sure",
        "i am not sure",
        "i can't tell",
        "i cannot tell",
        "i have no idea",
        "not certain",
        "need more information",
    )
    if any(phrase in normalized for phrase in uncertainty_phrases):
        return "confused"
    return None


def get_session(ip, port=9559):
    if qi is None:
        raise RuntimeError(
            "NAOqi 'qi' module could not be imported. Ensure the SDK is installed, "
            "PYTHONPATH is set, and the container is running as linux/amd64.\n%s"
            % (_QI_IMPORT_ERROR or "")
        )
    key = "%s:%s" % (ip, port)
    with _sessions_lock:
        sess = _sessions.get(key)
        if sess is not None:
            try:
                if not hasattr(sess, "isConnected") or sess.isConnected():
                    return sess
            except Exception:
                pass
            try:
                sess.close()
            except Exception:
                pass
            _sessions.pop(key, None)

        # A disconnected qi.Session keeps stale service-directory state, so a
        # reconnect always starts with a fresh object. The future also bounds a
        # dead lab-network connection instead of holding a Flask worker forever.
        sess = qi.Session()
        try:
            future = sess.connect("tcp://%s:%s" % (ip, port), _async=True)
            future.value(PEPPER_CONNECT_TIMEOUT_MS)
        except Exception as exc:
            try:
                future.cancel()
            except Exception:
                pass
            try:
                sess.close()
            except Exception:
                pass
            raise RuntimeError("Could not connect to Pepper at %s: %s" % (key, exc))

        _sessions[key] = sess
        return sess


def discard_session(ip, port=9559):
    """Remove a failed qi session so the next attempt starts cleanly."""
    key = "%s:%s" % (ip, port)
    with _sessions_lock:
        sess = _sessions.pop(key, None)
    if sess is not None and hasattr(sess, "close"):
        try:
            sess.close()
        except Exception:
            pass


def _safe_name(name):
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        return None
    return name


def _safe_join(base_dir, filename):
    path = os.path.normpath(os.path.join(base_dir, filename))
    base = os.path.normpath(base_dir)
    if path != base and not path.startswith(base + os.sep):
        raise ValueError("Unsafe path")
    return path


def _json_write_utf8(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if not isinstance(text, unicode):
        text = text.decode("utf-8")
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def with_services(ip, port=9559):
    """Helper to get ALAudioPlayer and ALAnimationPlayer services for an IP:port."""
    sess = get_session(ip, port)
    audio = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")
    return audio, anim


def _png_chunk(chunk_type, payload):
    checksum = zlib.crc32(chunk_type + payload) & 0xffffffff
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def rgb_to_png(width, height, rgb_bytes):
    """Encode packed 8-bit RGB pixels as PNG using only Python's standard library."""
    row_bytes = width * 3
    expected = row_bytes * height
    if len(rgb_bytes) < expected:
        raise RuntimeError(
            "Camera returned %s bytes; expected at least %s" % (len(rgb_bytes), expected)
        )

    scanlines = []
    for row in range(height):
        start = row * row_bytes
        scanlines.append("\x00" + rgb_bytes[start:start + row_bytes])

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        "\x89PNG\r\n\x1a\n"
        + _png_chunk("IHDR", header)
        + _png_chunk("IDAT", zlib.compress("".join(scanlines), 3))
        + _png_chunk("IEND", "")
    )


def capture_camera_png(ip, port, camera_name, resolution_name, fps):
    camera_id = CAMERA_IDS[camera_name]
    resolution_id = CAMERA_RESOLUTIONS[resolution_name]
    session = get_session(ip, port)
    video = session.service("ALVideoDevice")
    subscriber = None

    # Pepper exposes a limited number of camera subscriptions. Serialize these
    # short-lived captures and always unsubscribe, including on timeouts.
    with _camera_lock:
        client_name = "pepper_portal_%s_%s" % (os.getpid(), next(_camera_counter))
        try:
            subscriber = video.subscribeCamera(
                client_name, camera_id, resolution_id, RGB_COLOR_SPACE, fps
            )
            future = video.getImageRemote(subscriber, _async=True)
            image = future.value(CAMERA_TIMEOUT_MS)
            if not image or len(image) < 7:
                raise RuntimeError("Pepper returned an empty camera frame")

            width = int(image[0])
            height = int(image[1])
            pixels = image[6]
            if isinstance(pixels, bytearray):
                pixels = str(pixels)
            elif not isinstance(pixels, str):
                pixels = bytes(pixels)
            return rgb_to_png(width, height, pixels)
        finally:
            if subscriber:
                try:
                    video.unsubscribe(subscriber)
                except Exception:
                    pass


def set_vision_awareness_hold(ip, port, active):
    """Suspend face-oriented awareness for Vision, restoring prior state later."""
    session = get_session(ip, port)
    life = session.service("ALAutonomousLife")
    awareness = session.service("ALBasicAwareness")
    session_key = "%s:%s" % (ip, port)

    with _vision_awareness_lock:
        if active:
            if session_key not in _vision_awareness_states:
                _vision_awareness_states[session_key] = {
                    "life_enabled": bool(
                        life.getAutonomousAbilityEnabled("BasicAwareness")
                    ),
                    "awareness_enabled": bool(awareness.isEnabled()),
                }
            life.setAutonomousAbilityEnabled("BasicAwareness", False)
            awareness.setEnabled(False)
            return _vision_awareness_states[session_key]

        previous = _vision_awareness_states.pop(session_key, None)
        if previous is not None:
            awareness.setEnabled(previous["awareness_enabled"])
            life.setAutonomousAbilityEnabled(
                "BasicAwareness", previous["life_enabled"]
            )
        return previous

def ollama_request(path, payload=None, timeout=10):
    """Call the Ollama HTTP API running on the Docker host."""
    url = OLLAMA_BASE_URL + path
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib2.Request(url, data=body, headers=headers)
    response = urllib2.urlopen(req, timeout=timeout)
    raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def ollama_models():
    data = ollama_request("/api/tags", timeout=5)
    names = []
    for model in data.get("models", []):
        name = model.get("name") or model.get("model")
        if name:
            names.append(name)
    return names


def ollama_loaded_models():
    data = ollama_request("/api/ps", timeout=5)
    names = []
    for model in data.get("models", []):
        name = model.get("name") or model.get("model")
        if name:
            names.append(name)
    return names


def unload_ollama_model(model, timeout_seconds=8):
    """Request unload and wait until Ollama confirms the model left memory."""
    ollama_request(
        "/api/generate",
        {"model": model, "keep_alive": 0},
        timeout=min(10, timeout_seconds),
    )
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if model not in ollama_loaded_models():
            return True
        time.sleep(0.2)
    return model not in ollama_loaded_models()


def preferred_ollama_model(names):
    if OLLAMA_MODEL in names:
        return OLLAMA_MODEL
    llama_names = [name for name in names if name.lower().startswith("llama")]
    return llama_names[0] if llama_names else (names[0] if names else OLLAMA_MODEL)


VISION_MODEL_PREFIXES = (
    "llava",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen2.5vl",
    "qwen3-vl",
    "minicpm-v",
    "moondream",
    "gemma3",
    "llama3.2-vision",
    "granite3.2-vision",
    "mistral-small3.1",
    "mistral-small3.2",
)


def ollama_model_supports_vision(name):
    """Use Ollama capabilities when available, with an older-version fallback."""
    try:
        details = ollama_request("/api/show", {"model": name}, timeout=10)
        capabilities = [
            str(value).strip().lower() for value in details.get("capabilities", [])
        ]
        if capabilities:
            return "vision" in capabilities
    except Exception:
        pass
    normalized = name.strip().lower()
    return any(normalized.startswith(prefix) for prefix in VISION_MODEL_PREFIXES)


def vision_ollama_models(names):
    return [name for name in names if ollama_model_supports_vision(name)]


def preferred_ollama_vision_model(names):
    if OLLAMA_VISION_MODEL in names:
        return OLLAMA_VISION_MODEL
    preferences = ("qwen3-vl:4b", "qwen3-vl:8b", "qwen3-vl", "llava")
    for prefix in preferences:
        matches = [name for name in names if name.lower().startswith(prefix)]
        if matches:
            return matches[0]
    return names[0] if names else OLLAMA_VISION_MODEL


def local_stt_request(path, payload=None, timeout=10):
    url = LOCAL_STT_BASE_URL + path
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib2.Request(url, data=body, headers=headers)
    response = urllib2.urlopen(req, timeout=timeout)
    raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def capture_pepper_microphone_wav(
    ip,
    port,
    max_duration_seconds,
    silence_seconds=PEPPER_MIC_SILENCE_SECONDS,
    wait_for_speech=False,
):
    """Record until Pepper hears three seconds of continuous silence."""
    session = get_session(ip, port)
    recorder = session.service("ALAudioRecorder")
    file_manager = session.service("ALFileManager")
    audio_device = session.service("ALAudioDevice")
    recording = False
    wav_data = None
    started_at = None
    last_voice_at = None
    speech_detected = False
    max_energy = 0.0
    canceled = False
    session_key = "%s:%s" % (ip, port)
    cancel_event = threading.Event()

    with _microphone_state_lock:
        previous_event = _microphone_cancel_events.get(session_key)
        if previous_event is not None:
            previous_event.set()
        _microphone_cancel_events[session_key] = cancel_event

    # ALAudioDevice callbacks require a robot-visible NAOqi module and do not
    # work reliably through Docker NAT. Pepper's built-in recorder keeps the
    # callback on the robot; ALFileManager then returns the completed WAV over
    # the existing client connection without SSH credentials.
    with _microphone_lock:
        try:
            recorder.startMicrophonesRecording(
                PEPPER_MIC_ROBOT_PATH,
                "wav",
                PEPPER_MIC_SAMPLE_RATE,
                [0, 0, 1, 0],  # left, right, front, rear
            )
            recording = True
            audio_device.enableEnergyComputation()
            started_at = time.time()
            last_voice_at = started_at

            while True:
                if cancel_event.is_set():
                    canceled = True
                    break
                now = time.time()
                elapsed = now - started_at
                energy = float(audio_device.getFrontMicEnergy())
                max_energy = max(max_energy, energy)
                if energy >= PEPPER_MIC_ENERGY_THRESHOLD:
                    speech_detected = True
                    last_voice_at = now

                if (speech_detected or not wait_for_speech) and now - last_voice_at >= silence_seconds:
                    break
                if elapsed >= max_duration_seconds:
                    break
                time.sleep(PEPPER_MIC_ENERGY_POLL_SECONDS)

            recorder.stopMicrophonesRecording()
            recording = False
            wav_data = file_manager.getFileContents(PEPPER_MIC_FILE_KEY)
            if isinstance(wav_data, bytearray):
                wav_data = str(wav_data)
            elif not isinstance(wav_data, str):
                wav_data = bytes(wav_data)
        finally:
            if recording:
                try:
                    recorder.stopMicrophonesRecording()
                except Exception:
                    pass
            # Overwrite the captured speech immediately after transfer. NAOqi
            # 2.5 ALFileManager can read files but provides no delete method.
            try:
                recorder.startMicrophonesRecording(
                    PEPPER_MIC_ROBOT_PATH,
                    "wav",
                    PEPPER_MIC_SAMPLE_RATE,
                    [0, 0, 1, 0],
                )
                time.sleep(0.05)
                recorder.stopMicrophonesRecording()
            except Exception:
                try:
                    recorder.stopMicrophonesRecording()
                except Exception:
                    pass
            with _microphone_state_lock:
                if _microphone_cancel_events.get(session_key) is cancel_event:
                    _microphone_cancel_events.pop(session_key, None)

    actual_seconds = round(time.time() - started_at, 2) if started_at else 0
    capture_info = {
        "actual_seconds": actual_seconds,
        "speech_detected": speech_detected,
        "max_energy": round(max_energy, 1),
        "energy_threshold": PEPPER_MIC_ENERGY_THRESHOLD,
        "silence_seconds": silence_seconds,
        "canceled": canceled,
    }
    if not wav_data or len(wav_data) <= 44 or not wav_data.startswith("RIFF"):
        if canceled:
            return "", 0, capture_info
        raise RuntimeError(
            "Pepper microphone returned no WAV audio. Check ALAudioRecorder access."
        )
    return (
        wav_data,
        max(0, len(wav_data) - 44),
        capture_info,
    )


def _run_script_job(job_id, script_path, ip, port, language="English", name_param=""):
    env = os.environ.copy()
    env["PEPPER_IP"] = ip
    env["PEPPER_PORT"] = str(port)
    env["SCRIPT_LANG"] = language
    env["BIRTHDAY_NAME"] = name_param
    cmd = [
        sys.executable,
        script_path,
        "--ip",
        ip,
        "--port",
        str(port),
        "--lang",
        language,
    ]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        with _jobs_lock:
            _jobs[job_id]["process"] = p
        out, _ = p.communicate()
        output = out.decode("utf-8", "ignore") if not isinstance(out, str) else out
        rc = p.returncode
    except Exception as e:
        output = "Error: %s" % (str(e),)
        rc = 1
    finally:
        with _jobs_lock:
            _jobs[job_id]["done"] = True
            _jobs[job_id]["rc"] = rc
            _jobs[job_id]["output"] = output
            _jobs[job_id]["process"] = None



# --- Error handling decorator for JSON endpoints ---


def json_endpoint(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e)}), 400

    return _wrap


# A small curated list of animations from Aldebaran docs (NAOqi 2.5)
# You can extend this as needed.
ANIMATIONS = [
    # BodyTalk
    # "animations/Stand/BodyTalk/BodyTalk_1", # These don't seem to work
    # "animations/Stand/BodyTalk/BodyTalk_2",
    # "animations/Stand/BodyTalk/BodyTalk_3",
    # "animations/Stand/BodyTalk/BodyTalk_4",
    # "animations/Stand/BodyTalk/BodyTalk_5",
    # "animations/Stand/BodyTalk/BodyTalk_6",
    # "animations/Stand/BodyTalk/BodyTalk_7",
    # "animations/Stand/BodyTalk/BodyTalk_8",
    # "animations/Stand/BodyTalk/BodyTalk_9",
    # "animations/Stand/BodyTalk/BodyTalk_10",
    # "animations/Stand/BodyTalk/BodyTalk_11",
    # "animations/Stand/BodyTalk/BodyTalk_12",
    # "animations/Stand/BodyTalk/BodyTalk_13",
    # "animations/Stand/BodyTalk/BodyTalk_14",
    # "animations/Stand/BodyTalk/BodyTalk_15",
    # "animations/Stand/BodyTalk/BodyTalk_16",
    #  Emotions
    "animations/Stand/Emotions/Negative/Bored_1",
    "animations/Stand/Emotions/Neutral/Embarrassed_1",
    "animations/Stand/Emotions/Positive/Happy_1", # Has noise
    "animations/Stand/Emotions/Positive/Happy_2", # Has noise
    "animations/Stand/Emotions/Positive/Happy_3", # Has noise
    "animations/Stand/Emotions/Positive/Happy_4", # Has noise
    "animations/Stand/Emotions/Positive/Hysterical_1",
    "animations/Stand/Emotions/Positive/Peaceful_1",
    #   Gestures
    "animations/Stand/Gestures/BowShort_1",
    "animations/Stand/Gestures/But_1",
    "animations/Stand/Gestures/CalmDown_1",
    "animations/Stand/Gestures/CalmDown_5",
    "animations/Stand/Gestures/CalmDown_6",
    "animations/Stand/Gestures/Choice_1",
    "animations/Stand/Gestures/Desperate_1",
    "animations/Stand/Gestures/Desperate_2",
    "animations/Stand/Gestures/Desperate_4",
    "animations/Stand/Gestures/Desperate_5",
    "animations/Stand/Gestures/Enthusiastic_4",
    "animations/Stand/Gestures/Enthusiastic_5",
    "animations/Stand/Gestures/Everything_1",
    "animations/Stand/Gestures/Everything_2",
    "animations/Stand/Gestures/Everything_3",
    "animations/Stand/Gestures/Everything_4",
    "animations/Stand/Gestures/Excited_1",
    "animations/Stand/Gestures/Explain_1",
    "animations/Stand/Gestures/Explain_2",
    "animations/Stand/Gestures/Explain_3",
    "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Explain_5",
    "animations/Stand/Gestures/Explain_6",
    "animations/Stand/Gestures/Explain_7",
    "animations/Stand/Gestures/Explain_8",
    "animations/Stand/Gestures/Explain_9",
    "animations/Stand/Gestures/Explain_10",
    "animations/Stand/Gestures/Explain_11",
    "animations/Stand/Gestures/Far_1",
    "animations/Stand/Gestures/Far_2",
    "animations/Stand/Gestures/Far_3",
    "animations/Stand/Gestures/Give_3",
    "animations/Stand/Gestures/Give_4",
    "animations/Stand/Gestures/Give_5",
    "animations/Stand/Gestures/Give_6",
    "animations/Stand/Gestures/Hey_1",
    "animations/Stand/Gestures/Hey_3",
    "animations/Stand/Gestures/Hey_4",
    "animations/Stand/Gestures/Hey_6",
    "animations/Stand/Gestures/IDontKnow_1",
    "animations/Stand/Gestures/IDontKnow_2",
    "animations/Stand/Gestures/IDontKnow_3",
    "animations/Stand/Gestures/Me_1",
    "animations/Stand/Gestures/Me_2",
    "animations/Stand/Gestures/Me_4",
    "animations/Stand/Gestures/Me_7",
    "animations/Stand/Gestures/No_1",
    "animations/Stand/Gestures/No_2",
    "animations/Stand/Gestures/No_3",
    "animations/Stand/Gestures/No_8",
    "animations/Stand/Gestures/No_9",
    "animations/Stand/Gestures/Nothing_2",
    "animations/Stand/Gestures/Please_1",
    "animations/Stand/Gestures/ShowFloor_1",
    "animations/Stand/Gestures/ShowFloor_3",
    "animations/Stand/Gestures/ShowFloor_4",
    "animations/Stand/Gestures/ShowSky_1",
    "animations/Stand/Gestures/ShowSky_11",
    "animations/Stand/Gestures/ShowSky_2",
    "animations/Stand/Gestures/ShowSky_4",
    "animations/Stand/Gestures/ShowSky_5",
    "animations/Stand/Gestures/ShowSky_6",
    "animations/Stand/Gestures/ShowSky_7",
    "animations/Stand/Gestures/ShowSky_8",
    "animations/Stand/Gestures/ShowSky_9",
    "animations/Stand/Gestures/ShowTablet_2",
    "animations/Stand/Gestures/ShowTablet_3",
    "animations/Stand/Gestures/Thinking_1",
    "animations/Stand/Gestures/Thinking_3",
    "animations/Stand/Gestures/Thinking_4",
    "animations/Stand/Gestures/Thinking_6",
    "animations/Stand/Gestures/Thinking_8",
    "animations/Stand/Gestures/Yes_1",
    "animations/Stand/Gestures/Yes_2",
    "animations/Stand/Gestures/Yes_3",
    "animations/Stand/Gestures/YouKnowWhat_1",
    "animations/Stand/Gestures/YouKnowWhat_2",
    "animations/Stand/Gestures/YouKnowWhat_3",
    "animations/Stand/Gestures/YouKnowWhat_5",
    "animations/Stand/Gestures/YouKnowWhat_6",
    "animations/Stand/Gestures/You_1",
    "animations/Stand/Gestures/You_4",
    "animations/Stand/Waiting/ShowSky_1",
    "animations/Stand/Waiting/ShowSky_2",
    "animations/Stand/Waiting/Think_1",
    "animations/Stand/Waiting/Think_2",
    "animations/Stand/Waiting/Think_3",
]


ANIMATIONS_GROUPED = {
    "Gestures": [
        "animations/Stand/Gestures/Hey_1",
        "animations/Stand/Gestures/Hello_1",
        "animations/Stand/Gestures/CalmDown_1",
        "animations/Stand/Gestures/Enthusiastic_1",
        "animations/Stand/Gestures/Explain_1",
        "animations/Stand/Gestures/No_1",
        "animations/Stand/Gestures/Yes_1",
        "animations/Stand/Gestures/YouKnowWhat_1",
        "animations/Stand/Gestures/ShowSky_1",
        "animations/Stand/Gestures/ShowFloor_1",
        "animations/Stand/Gestures/Me_1",
        "animations/Stand/Gestures/Think_1",
        "animations/Stand/Gestures/Surprised_1",
        "animations/Stand/Gestures/Clap_1",
    ],
    "BodyTalk": [
        "animations/Stand/BodyTalk/BodyTalk_1",
        "animations/Stand/BodyTalk/BodyTalk_2",
        "animations/Stand/BodyTalk/BodyTalk_3",
        "animations/Stand/BodyTalk/BodyTalk_4",
    ],
    "Emotions": [
        "animations/Stand/Emotions/Positive_1",
        "animations/Stand/Emotions/Negative_1",
        "animations/Stand/Emotions/Surprise_1",
        "animations/Stand/Emotions/Excited_1",
        "animations/Stand/Emotions/Frustrated_1",
    ],
    "Reactions": [
        "animations/Stand/Reactions/Applause_1",
        "animations/Stand/Reactions/Joy_1",
        "animations/Stand/Reactions/Sad_1",
        "animations/Stand/Reactions/Startled_1",
    ],
    "Waiting": [
        "animations/Stand/Waiting/LookHand_1",
        "animations/Stand/Waiting/Idle_1",
        "animations/Stand/Waiting/LookFar_1",
        "animations/Stand/Waiting/Stretch_1",
    ],
}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", animations=ANIMATIONS)


@app.route("/api/connect-test", methods=["POST"])
@json_endpoint
def api_connect():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    # Only one service-discovery handshake may run at a time, even if several
    # browser tabs click Connect together. A failed qi session is discarded so
    # later requests cannot reuse its canceled futures.
    with _connect_test_lock:
        try:
            session = get_session(ip, port)
            system = session.service("ALSystem")
            if not system.ping():
                raise RuntimeError("Pepper's ALSystem service did not respond")
        except Exception:
            discard_session(ip, port)
            raise
    return jsonify({"ok": True})


@app.route("/api/camera-frame", methods=["GET"])
@json_endpoint
def api_camera_frame():
    ip = (request.args.get("ip") or "").strip()
    port = int(request.args.get("port", 9559))
    camera_name = (request.args.get("camera") or "top").strip().lower()
    resolution_name = (request.args.get("resolution") or "320x240").strip().lower()
    fps = max(1, min(5, int(request.args.get("fps", 2))))

    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    if camera_name not in CAMERA_IDS:
        return jsonify({"ok": False, "error": "Camera must be 'top' or 'bottom'"}), 400
    if resolution_name not in CAMERA_RESOLUTIONS:
        return jsonify({
            "ok": False,
            "error": "Resolution must be one of: %s" % ", ".join(sorted(CAMERA_RESOLUTIONS)),
        }), 400

    png = capture_camera_png(ip, port, camera_name, resolution_name, fps)
    return Response(
        png,
        mimetype="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.route("/api/vision-attention", methods=["POST"])
@json_endpoint
def api_vision_attention():
    """Keep Pepper's head steady while the portal Vision workspace is active."""
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    active = bool(data.get("active", False))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    previous = set_vision_awareness_hold(ip, port, active)
    session = get_session(ip, port)
    life = session.service("ALAutonomousLife")
    awareness = session.service("ALBasicAwareness")
    return jsonify({
        "ok": True,
        "active": active,
        "basic_awareness_enabled": bool(awareness.isEnabled()),
        "autonomous_ability_enabled": bool(
            life.getAutonomousAbilityEnabled("BasicAwareness")
        ),
        "previous": previous,
    })


@app.route("/api/local-ai/status", methods=["GET"])
def api_local_ai_status():
    """Detect a running local Ollama service and list its downloaded models."""
    try:
        version_data = ollama_request("/api/version", timeout=3)
        names = ollama_models()
        return jsonify({
            "ok": True,
            "available": True,
            "provider": "Ollama",
            "version": version_data.get("version", "unknown"),
            "models": names,
            "preferred_model": preferred_ollama_model(names),
            "download_url": OLLAMA_DOWNLOAD_URL,
            "start_command": "ollama serve",
        })
    except Exception as exc:
        return jsonify({
            "ok": True,
            "available": False,
            "provider": "Ollama",
            "models": [],
            "preferred_model": OLLAMA_MODEL,
            "download_url": OLLAMA_DOWNLOAD_URL,
            "start_command": "ollama serve",
            "error": str(exc),
        })


@app.route("/api/local-ai/chat", methods=["POST"])
@json_endpoint
def api_local_ai_chat():
    data = request.get_json(force=True)
    prompt = (data.get("prompt") or "").strip()
    model = (data.get("model") or OLLAMA_MODEL).strip()
    history = data.get("messages") or []
    gestures_enabled = bool(data.get("gestures_enabled", True))

    if not prompt:
        return jsonify({"ok": False, "error": "Say or type something first"}), 400
    if len(prompt) > 4000:
        return jsonify({"ok": False, "error": "Message is too long"}), 400
    if not model or len(model) > 100:
        return jsonify({"ok": False, "error": "Invalid model name"}), 400

    installed_models = ollama_models()
    if model not in installed_models:
        return jsonify({
            "ok": False,
            "error": "Model '%s' is not downloaded in Ollama" % model,
            "models": installed_models,
        }), 400

    messages = [{
        "role": "system",
        "content": PEPPER_SYSTEM_PROMPT + " " + pepper_gesture_prompt(gestures_enabled),
    }]
    for item in history[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, basestring):
            continue
        content = content.strip()
        if content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt})

    # The Mac has unified memory, so text and vision generations must never
    # load in parallel. keep_alive=0 releases model memory after every reply.
    with _ollama_generation_lock:
        try:
            result = ollama_request(
                "/api/chat",
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE_SECONDS,
                    "format": pepper_response_schema(),
                    "options": {
                        "temperature": 0.4,
                        "num_predict": 220,
                        "num_ctx": OLLAMA_CONTEXT_LENGTH,
                    },
                },
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
        finally:
            if OLLAMA_KEEP_ALIVE_SECONDS == 0 and not unload_ollama_model(model):
                raise RuntimeError(
                    "Ollama did not release model '%s' from memory" % model
                )
    content = ((result.get("message") or {}).get("content") or "").strip()
    try:
        structured = json.loads(content)
    except (TypeError, ValueError):
        # Keep conversation usable with older models that ignore structured output.
        structured = {"reply": content, "gesture": "none", "gesture_mode": "none"}

    reply = structured.get("reply") if isinstance(structured, dict) else ""
    reply = reply.strip() if isinstance(reply, basestring) else ""
    if not reply:
        raise RuntimeError("Ollama returned an empty reply")

    suggested_gesture = structured.get("gesture", "none")
    gesture_mode = structured.get("gesture_mode", "none")
    explicit_gesture = (
        requested_gesture_from_prompt(prompt) if gestures_enabled else None
    )
    if explicit_gesture:
        suggested_gesture = explicit_gesture
        gesture_mode = "requested"
    if suggested_gesture not in PEPPER_GESTURES:
        suggested_gesture = "none"
        gesture_mode = "none"
    if gesture_mode not in ("optional", "requested"):
        suggested_gesture = "none"
        gesture_mode = "none"
    if gestures_enabled and suggested_gesture == "none":
        conversational_gesture = conversational_gesture_from_reply(reply)
        if conversational_gesture:
            suggested_gesture = conversational_gesture
            gesture_mode = "optional"

    # Explicit movement requests always run. Model-suggested body language is
    # deliberately occasional so Pepper does not move on every conversational turn.
    gesture_suggestion = suggested_gesture
    gesture_suggestion_mode = gesture_mode
    gesture = suggested_gesture
    if (
        not gestures_enabled
        or (gesture_mode == "optional" and random.random() > PEPPER_GESTURE_CHANCE)
    ):
        gesture = "none"
        gesture_mode = "none"

    gesture_label = PEPPER_GESTURES.get(gesture, (None, "no gesture"))[1]
    return jsonify({
        "ok": True,
        "model": model,
        "reply": reply,
        "gesture": gesture,
        "gesture_mode": gesture_mode,
        "gesture_label": gesture_label,
        "suggested_gesture": gesture_suggestion,
        "suggested_gesture_mode": gesture_suggestion_mode,
    })


@app.route("/api/local-vision/status", methods=["GET"])
def api_local_vision_status():
    """List only downloaded Ollama models that can inspect images."""
    try:
        version_data = ollama_request("/api/version", timeout=3)
        installed_models = ollama_models()
        models = vision_ollama_models(installed_models)
        return jsonify({
            "ok": True,
            "available": True,
            "provider": "Ollama",
            "version": version_data.get("version", "unknown"),
            "models": models,
            "preferred_model": preferred_ollama_vision_model(models),
            "download_url": OLLAMA_DOWNLOAD_URL,
            "model_url": OLLAMA_VISION_MODEL_URL,
            "pull_command": "ollama pull qwen3-vl:4b",
        })
    except Exception as exc:
        return jsonify({
            "ok": True,
            "available": False,
            "provider": "Ollama",
            "models": [],
            "preferred_model": OLLAMA_VISION_MODEL,
            "download_url": OLLAMA_DOWNLOAD_URL,
            "model_url": OLLAMA_VISION_MODEL_URL,
            "pull_command": "ollama pull qwen3-vl:4b",
            "error": str(exc),
        })


@app.route("/api/local-vision/ask", methods=["POST"])
@json_endpoint
def api_local_vision_ask():
    """Capture one fresh Pepper frame and ask a local Ollama VLM about it."""
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    camera_name = (data.get("camera") or "top").strip().lower()
    resolution_name = (data.get("resolution") or "640x480").strip().lower()
    question = (data.get("question") or "").strip()
    model = (data.get("model") or OLLAMA_VISION_MODEL).strip()

    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    if not question:
        return jsonify({"ok": False, "error": "Enter a question about Pepper's view"}), 400
    if len(question) > 1000:
        return jsonify({"ok": False, "error": "Vision question is limited to 1000 characters"}), 400
    if camera_name not in CAMERA_IDS:
        return jsonify({"ok": False, "error": "Camera must be 'top' or 'bottom'"}), 400
    if resolution_name not in CAMERA_RESOLUTIONS:
        return jsonify({
            "ok": False,
            "error": "Resolution must be one of: %s" % ", ".join(sorted(CAMERA_RESOLUTIONS)),
        }), 400
    if not model or len(model) > 100:
        return jsonify({"ok": False, "error": "Invalid model name"}), 400

    installed_models = ollama_models()
    if model not in installed_models:
        return jsonify({
            "ok": False,
            "error": "Vision model '%s' is not downloaded in Ollama" % model,
            "models": vision_ollama_models(installed_models),
        }), 400
    if not ollama_model_supports_vision(model):
        return jsonify({
            "ok": False,
            "error": "Model '%s' does not report vision support" % model,
        }), 400

    # One deliberate high-resolution snapshot is considerably lighter than
    # continuously sending the live camera stream to the VLM.
    png = capture_camera_png(ip, port, camera_name, resolution_name, 1)
    encoded_image = base64.b64encode(png)
    with _ollama_generation_lock:
        try:
            result = ollama_request(
                "/api/chat",
                {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are Pepper's visual assistant. Answer the person's question "
                                "about this single camera frame in one or two short, natural sentences. "
                                "Describe only what is visibly supported. If the object or detail is "
                                "unclear, say that you are unsure and suggest moving it closer or improving "
                                "the light. Do not use markdown."
                            ),
                        },
                        {
                            "role": "user",
                            "content": question,
                            "images": [encoded_image],
                        },
                    ],
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE_SECONDS,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 180,
                        "num_ctx": OLLAMA_CONTEXT_LENGTH,
                    },
                },
                timeout=OLLAMA_TIMEOUT_SECONDS,
            )
        finally:
            if OLLAMA_KEEP_ALIVE_SECONDS == 0 and not unload_ollama_model(model):
                raise RuntimeError(
                    "Ollama did not release model '%s' from memory" % model
                )
    answer = ((result.get("message") or {}).get("content") or "").strip()
    if not answer:
        raise RuntimeError("The local vision model returned an empty answer")

    return jsonify({
        "ok": True,
        "model": model,
        "answer": answer,
        "camera": camera_name,
        "resolution": resolution_name,
    })


def local_stt_guidance():
    """Setup/start commands for whichever speech backend LOCAL_STT_BASE_URL targets.

    The two backends are started in completely different ways, so guidance shown
    when the service is unreachable has to follow the configured URL: a host name
    means the MLX helper on the Mac, anything else means the Compose service.
    """
    host_backed = any(
        name in LOCAL_STT_BASE_URL
        for name in ("host.docker.internal", "127.0.0.1", "localhost")
    )
    if host_backed:
        return {
            "provider": "MLX Whisper",
            "model": "mlx-community/whisper-tiny",
            "setup_command": "./setup_local_speech.sh",
            "start_command": "./run_local_services.sh",
            "setup_url": LOCAL_STT_SETUP_URL,
        }
    return {
        "provider": "faster-whisper (CPU)",
        "model": "tiny",
        "setup_command": "docker compose build speech-to-text",
        "start_command": "docker compose up -d speech-to-text",
        "setup_url": LOCAL_STT_CONTAINER_SETUP_URL,
    }


@app.route("/api/local-speech/status", methods=["GET"])
def api_local_speech_status():
    """Report on the speech backend, host MLX helper or speech-to-text container."""
    guidance = local_stt_guidance()
    try:
        status = local_stt_request("/status", timeout=3)
        return jsonify({
            "ok": True,
            "available": bool(status.get("ok") and status.get("available")),
            # Prefer what the service reports about itself; guidance is the fallback.
            "provider": status.get("engine") or guidance["provider"],
            "model": status.get("model") or guidance["model"],
            "language": status.get("language", "auto"),
            "setup_url": guidance["setup_url"],
            "setup_command": guidance["setup_command"],
            "start_command": guidance["start_command"],
        })
    except Exception as exc:
        return jsonify({
            "ok": True,
            "available": False,
            "provider": guidance["provider"],
            "model": guidance["model"],
            "setup_url": guidance["setup_url"],
            "setup_command": guidance["setup_command"],
            "start_command": guidance["start_command"],
            "error": str(exc),
        })


@app.route("/api/pepper-listen", methods=["POST"])
@json_endpoint
def api_pepper_listen():
    """Capture one utterance from Pepper and transcribe it on the local Mac."""
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    try:
        duration_seconds = int(data.get("duration", 30))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Duration must be a number"}), 400
    duration_seconds = max(
        PEPPER_MIC_MIN_SECONDS,
        min(PEPPER_MIC_MAX_SECONDS, duration_seconds),
    )
    continuous = bool(data.get("continuous", False))

    try:
        stt_status = local_stt_request("/status", timeout=3)
    except Exception:
        return jsonify({
            "ok": False,
            "error": (
                "Speech recognition is not running. Start it with: %s"
                % local_stt_guidance()["start_command"]
            ),
        }), 400
    if not stt_status.get("ok") or not stt_status.get("available"):
        return jsonify({"ok": False, "error": "Local speech recognition is not ready"}), 400

    wav_data, pcm_bytes, capture_info = capture_pepper_microphone_wav(
        ip,
        port,
        duration_seconds,
        wait_for_speech=continuous,
    )
    if capture_info.get("canceled"):
        return jsonify({
            "ok": True,
            "canceled": True,
            "transcript": "",
            "capture_seconds": capture_info.get("actual_seconds"),
        })
    result = local_stt_request(
        "/transcribe",
        {"audio_wav_base64": base64.b64encode(wav_data)},
        timeout=LOCAL_STT_TIMEOUT_SECONDS,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "Speech recognition failed")

    return jsonify({
        "ok": True,
        "transcript": (result.get("transcript") or "").strip(),
        "language": result.get("language"),
        "model": result.get("model"),
        "transcription_seconds": result.get("elapsed_seconds"),
        "capture_seconds": capture_info.get("actual_seconds"),
        "silence_seconds": capture_info.get("silence_seconds"),
        "speech_detected": capture_info.get("speech_detected"),
        "max_energy": capture_info.get("max_energy"),
        "energy_threshold": capture_info.get("energy_threshold"),
        "canceled": False,
        "pcm_bytes": pcm_bytes,
    })


@app.route("/api/conversation-stop", methods=["POST"])
@json_endpoint
def api_conversation_stop():
    """Cancel the active microphone turn and stop Pepper's current speech."""
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    session_key = "%s:%s" % (ip, port)
    with _microphone_state_lock:
        cancel_event = _microphone_cancel_events.get(session_key)
        if cancel_event is not None:
            cancel_event.set()

    try:
        session = get_session(ip, port)
        session.service("ALTextToSpeech").stopAll()
        session.service("ALAnimationPlayer").stopAll()
    except Exception:
        pass
    return jsonify({"ok": True, "listening_stopped": cancel_event is not None})


@app.route("/api/pepper-speak", methods=["POST"])
@json_endpoint
def api_pepper_speak():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    text = (data.get("text") or "").strip()
    gesture = (data.get("gesture") or "none").strip().lower()
    if not ip or not text:
        return jsonify({"ok": False, "error": "'ip' and 'text' are required"}), 400
    if len(text) > 1200:
        return jsonify({"ok": False, "error": "Speech is limited to 1200 characters"}), 400

    if gesture != "none" and gesture not in PEPPER_GESTURES:
        return jsonify({"ok": False, "error": "Unknown or unsafe gesture"}), 400

    session = get_session(ip, port)
    gesture_performed = False
    gesture_error = None
    if gesture != "none":
        try:
            animation_path = PEPPER_GESTURES[gesture][0]
            session.service("ALAnimationPlayer").run(animation_path, _async=True)
            gesture_performed = True
        except Exception as exc:
            # Speech remains useful if a Pepper image lacks one animation.
            gesture_error = str(exc)
    speech = session.service("ALTextToSpeech")
    speech.say(text.encode("utf-8") if isinstance(text, unicode) else text)
    return jsonify({
        "ok": True,
        "gesture": gesture,
        "gesture_performed": gesture_performed,
        "gesture_error": gesture_error,
    })


@app.route("/api/play-audio", methods=["POST"])
@json_endpoint
def api_play_audio():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    path = data.get("path", "").strip()
    if not ip or not path:
        return jsonify({"ok": False, "error": "'ip' and 'path' are required"}), 400

    audio, _ = with_services(ip, port)
    file_id = audio.loadFile(path)
    audio.play(file_id)
    return jsonify({"ok": True, "fileId": int(file_id)})


@app.route("/api/stop-audio", methods=["POST"])
@json_endpoint
def api_stop_audio():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    audio, _ = with_services(ip, port)
    try:
        audio.stopAll()
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/run-animation", methods=["POST"])
@json_endpoint
def api_run_animation():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    animation = data.get("animation", "").strip()
    mode = (data.get("mode", "sync") or "sync").lower()
    if not ip or not animation:
        return jsonify({"ok": False, "error": "'ip' and 'animation' are required"}), 400

    _, anim = with_services(ip, port)
    if mode == "async":
        _future = anim.run(animation, _async=True)
        return jsonify({"ok": True, "async": True})
    else:
        anim.run(animation)
        return jsonify({"ok": True, "async": False})


@app.route("/api/stop-animation", methods=["POST"])
@json_endpoint
def api_stop_animations():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    _, anim = with_services(ip, port)
    try:
        anim.stopAll()
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/list-behaviors", methods=["POST"])
@json_endpoint
def api_list_behaviors():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    manager = get_session(ip, port).service("ALBehaviorManager")
    return jsonify({
        "ok": True,
        "behaviors": manager.getInstalledBehaviors(),
        "running": manager.getRunningBehaviors(),
    })


@app.route("/api/run-behavior", methods=["POST"])
@json_endpoint
def api_run_behavior():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    behavior = (data.get("behavior") or "").strip()
    if not ip or not behavior:
        return jsonify({"ok": False, "error": "'ip' and 'behavior' are required"}), 400
    manager = get_session(ip, port).service("ALBehaviorManager")
    manager.startBehavior(behavior)
    return jsonify({"ok": True})


@app.route("/api/stop-behavior", methods=["POST"])
@json_endpoint
def api_stop_behavior():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    manager = get_session(ip, port).service("ALBehaviorManager")
    try:
        manager.stopAllBehaviors()
    except Exception:
        pass
    return jsonify({"ok": True})

@app.route("/api/scripts", methods=["GET"])
def api_scripts():
    if not os.path.isdir(SCRIPTS_DIR):
        return jsonify({"ok": True, "scripts": []})
    names = []
    for name in os.listdir(SCRIPTS_DIR):
        if name.endswith(".py") and not name.startswith("_"):
            names.append(name)
    names.sort()
    return jsonify({"ok": True, "scripts": names})

@app.route("/api/run-script", methods=["POST"])
@json_endpoint
def api_run_script():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    script = (data.get("script") or "").strip()
    language = (data.get("language") or "English").strip()
    name_param = (data.get("name_param") or "").strip()
    if not ip or not script:
        return jsonify({"ok": False, "error": "Provide 'ip' and 'script'"}), 400

    if not _safe_name(script):
        return jsonify({"ok": False, "error": "Unsafe script name"}), 400
    spath = _safe_join(SCRIPTS_DIR, script)
    if not os.path.isfile(spath):
        return jsonify({"ok": False, "error": "Invalid script"}), 400

    job_id = str(next(_job_counter))
    with _jobs_lock:
        _jobs[job_id] = {
            "script": script,
            "done": False,
            "rc": None,
            "output": "",
            "process": None,
        }

    t = threading.Thread(
        target=_run_script_job,
        args=(job_id, spath, ip, port, language, name_param),
    )
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/stop-script", methods=["POST"])
@json_endpoint
def api_stop_script():
    data = request.get_json(force=True)
    job_id = (data.get("job_id") or "").strip()
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Unknown job_id"}), 404
        process = job.get("process")
    if process and process.poll() is None:
        try:
            process.terminate()
            process.wait()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        with _jobs_lock:
            job["done"] = True
            job["rc"] = -9
            job["output"] = (job.get("output") or "") + "\n[stopped by user]"
            job["process"] = None
        return jsonify({"ok": True, "stopped": True})
    return jsonify({"ok": True, "stopped": False})

@app.route("/api/script-status", methods=["GET"])
def api_script_status():
    job_id = request.args.get("job_id", "").strip()
    with _jobs_lock:
        state = _jobs.get(job_id)
        if not state:
            return jsonify({"ok": False, "error": "Unknown job_id"}), 404
        # Return a copy
        return jsonify({"ok": True, "done": state["done"], "rc": state["rc"], "output": state["output"]})

@app.route("/api/mode-status", methods=["POST"])
@json_endpoint
def api_mode_status():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    sess = get_session(ip, port)
    # Awake / sleep (motors)
    motion = sess.service("ALMotion")
    try:
        is_awake = bool(motion.robotIsWakeUp())  # True if motors on (wakeUp), False if rest
    except Exception:
        # Fallback: if robotIsWakeUp missing, infer from stiffness
        try:
            is_awake = any(motion.getStiffnesses("Body"))
        except Exception:
            is_awake = False

    # Autonomous Life state -> use as our "animation mode"
    animation_enabled = False
    life_state = "unknown"
    try:
        life = sess.service("ALAutonomousLife")
        life_state = life.getState()  # "disabled","solitary","interactive","safeguard"
        animation_enabled = life_state != "disabled"
    except Exception:
        # Fallback: BasicAwareness
        try:
            awareness = sess.service("ALBasicAwareness")
            animation_enabled = bool(awareness.isEnabled())
            life_state = "basic_awareness_%s" % ("on" if animation_enabled else "off")
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "is_awake": is_awake,
        "animation_enabled": animation_enabled,
        "life_state": life_state,
    })

@app.route("/api/sleep", methods=["POST"])
@json_endpoint
def api_sleep():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    action = (data.get("action") or "").strip().lower()
    if not ip or action not in ("rest", "wake"):
        return jsonify({"ok": False, "error": "Provide 'ip' and action in {'rest','wake'}"}), 400

    sess = get_session(ip, port)
    motion = sess.service("ALMotion")
    if action == "rest":
        motion.rest()     # motors off / relaxed
    else:
        motion.wakeUp()   # motors on / ready
    return jsonify({"ok": True, "action": action})


@app.route("/api/animation-mode", methods=["POST"])
@json_endpoint
def api_animation_mode():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    enabled = bool(data.get("enabled", True))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    sess = get_session(ip, port)
    # Use Autonomous Life to toggle idle/animation-like behaviors.
    life = sess.service("ALAutonomousLife")
    try:
        if enabled:
            # 'solitary' is a safe default that enables idle animations/awareness
            life.setState("solitary")
        else:
            life.setState("disabled")
    except Exception:
        # Some images prefer BasicAwareness toggle as fallback
        try:
            awareness = sess.service("ALBasicAwareness")
            awareness.setEnabled(enabled)
        except Exception:
            pass
    return jsonify({"ok": True, "enabled": enabled})


@app.route("/api/list-scenes", methods=["GET"])
def api_list_scenes():
    items = []
    try:
        for filename in os.listdir(SCENES_DIR):
            if not filename.startswith(".") and filename.lower().endswith(".json"):
                items.append(filename[:-5])
        items.sort(key=lambda value: value.lower())
        return jsonify(items)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/get-scene/<name>", methods=["GET"])
def api_get_scene(name):
    safe_name = _safe_name(name)
    if not safe_name:
        return jsonify({"ok": False, "error": "Invalid scene name"}), 400
    path = _safe_join(SCENES_DIR, safe_name + ".json")
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "Scene not found"}), 404
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            return jsonify(json.load(handle))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/save-scene", methods=["POST"])
@json_endpoint
def api_save_scene():
    data = request.get_json(force=True)
    name = _safe_name(data.get("name"))
    steps = data.get("steps")
    if not name or not isinstance(steps, list):
        return jsonify({"ok": False, "error": "Name and steps (array) required"}), 400
    path = _safe_join(SCENES_DIR, name + ".json")
    _json_write_utf8(path, {"script_name": name, "scene": steps})
    return jsonify({"ok": True, "filename": os.path.basename(path)})


@app.route("/api/run-scene", methods=["POST"])
@json_endpoint
def api_run_scene():
    data = request.get_json(force=True)
    name = _safe_name(data.get("name"))
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not name or not ip:
        return jsonify({"ok": False, "error": "Missing scene name or IP"}), 400
    if PepperController is None or PepperScripter is None:
        return jsonify({"ok": False, "error": "Pepper scene controller is unavailable"}), 500
    scene_path = _safe_join(SCENES_DIR, name + ".json")
    if not os.path.exists(scene_path):
        return jsonify({"ok": False, "error": "Scene not found"}), 404
    controller = PepperController(ip=ip, port=port, verbose=True)
    scripter = PepperScripter(controller=controller, blocking=True, verbose=True)
    completed = scripter.run_scene(scene_path, base=os.path.dirname(scene_path))
    return jsonify({
        "ok": bool(completed),
        "status": "completed" if completed else "no_actions",
    })



@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    # Keep local Llama requests responsive even while a robot call is waiting
    # on the lab network or Pepper is speaking a longer reply.
    app.run(host=host, port=port, debug=debug, threaded=True)
