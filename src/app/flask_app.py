"""
Pepper Portal (Flask)
---------------------
App wiring plus the local-intelligence features (Ollama chat and vision,
speech-to-text, conversation turns). Everything else lives in routes/, one
blueprint per area, and every call to Pepper goes through the robot package
(src/robot/) -- this file never touches NAOqi directly.

Run
  python2 src/app/flask_app.py
Then open: http://127.0.0.1:5000

NOTE: This app intentionally has no auth and trusts the provided Pepper IP. If you expose it on a network, add auth and allow-listing.
"""

from __future__ import print_function

import base64
import json
import os
import random
import re
import sys
import time
import threading
import urllib2

from flask import Flask, request, jsonify, render_template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # src/app
SRC_DIR = os.path.dirname(BASE_DIR)                          # src (robot package)
for _path in (SRC_DIR, BASE_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import robot  # noqa: E402
from robot.camera import CAMERA_IDS, CAMERA_RESOLUTIONS  # noqa: E402
from robot.gestures import GESTURES as PEPPER_GESTURES, animation_for  # noqa: E402
from pepper_core import media_store  # noqa: E402
import routes  # noqa: E402
from routes.common import json_endpoint  # noqa: E402

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MEDIA_MAX_MB", "300")) * 1024 * 1024

routes.register(app)
# Start the media sync worker now rather than on the first page load, so audio
# copied into media/ by hand reaches PEPPER_IP with no browser open.
media_store.request_sync()

_ollama_generation_lock = threading.Lock()

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
LOCAL_STT_BASE_URL_FROM_ENV = "LOCAL_STT_BASE_URL" in os.environ
LOCAL_STT_BASE_URL = os.environ.get(
    "LOCAL_STT_BASE_URL", "http://host.docker.internal:8765"
).rstrip("/")
LOCAL_STT_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_STT_TIMEOUT_SECONDS", "180"))
LOCAL_STT_SETUP_URL = "https://pypi.org/project/faster-whisper/"

PEPPER_MIC_MIN_SECONDS = 2
PEPPER_MIC_MAX_SECONDS = 45
PEPPER_GESTURE_CHANCE = max(
    0.0,
    min(1.0, float(os.environ.get("PEPPER_GESTURE_CHANCE", "0.35"))),
)
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
    png = robot.connect(ip, port).camera.capture_png(camera_name, resolution_name, 1)
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
    """What to tell the operator when speech-to-text is unreachable.

    Speech-to-text is a Compose service, so recovery is always a compose command.
    """
    return {
        "provider": "faster-whisper (CPU)",
        "model": "tiny",
        "setup_command": "docker compose build speech-to-text",
        "start_command": "docker compose up -d speech-to-text",
        "setup_url": LOCAL_STT_SETUP_URL,
    }


@app.route("/api/local-speech/status", methods=["GET"])
def api_local_speech_status():
    """Report on the speech-to-text container."""
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


@app.route("/api/local-mic-devices", methods=["GET"])
def api_local_mic_devices():
    """List ALSA capture devices visible to the speech-to-text container."""
    try:
        result = local_stt_request("/devices", timeout=5)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "devices": []})
    return jsonify(result)


@app.route("/api/local-mic-listen", methods=["POST"])
@json_endpoint
def api_local_mic_listen():
    """Record a fixed-length clip from a Jetson-attached mic and transcribe."""
    data = request.get_json(force=True) or {}
    device = (data.get("device") or "default").strip() or "default"
    try:
        duration_seconds = int(data.get("duration_seconds", 5))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "duration_seconds must be an integer"}), 400
    if duration_seconds < 1 or duration_seconds > 60:
        return jsonify({"ok": False, "error": "duration_seconds must be 1..60"}), 400

    result = local_stt_request(
        "/capture",
        {"device": device, "duration_seconds": duration_seconds},
        timeout=duration_seconds + LOCAL_STT_TIMEOUT_SECONDS,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "Local mic capture failed")
    # Strip the raw WAV before echoing back: the browser only wants the transcript
    # and the audio can be tens of KB per second.
    result.pop("audio_wav_base64", None)
    return jsonify(result)


@app.route("/api/local-transcribe", methods=["POST"])
@json_endpoint
def api_local_transcribe():
    """Transcribe a WAV recorded in the browser - no Pepper needed.

    Lets the operator smoke-test the mic and STT container from any device
    that reaches the portal, using getUserMedia in the browser.
    """
    data = request.get_json(force=True) or {}
    audio_b64 = (data.get("audio_wav_base64") or "").strip()
    if not audio_b64:
        return jsonify({"ok": False, "error": "Missing 'audio_wav_base64'"}), 400

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

    result = local_stt_request(
        "/transcribe",
        {"audio_wav_base64": audio_b64},
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

    wav_data, pcm_bytes, capture_info = robot.connect(ip, port).microphone.record_utterance(
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

    pepper = robot.connect(ip, port)
    listening_stopped = pepper.microphone.cancel()
    for stop in (pepper.speech.stop_all, pepper.motion.stop_animations):
        try:
            stop()
        except Exception:
            pass
    return jsonify({"ok": True, "listening_stopped": listening_stopped})


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

    pepper = robot.connect(ip, port)
    gesture_performed = False
    gesture_error = None
    if gesture != "none":
        try:
            pepper.motion.run_animation(animation_for(gesture), wait=False)
            gesture_performed = True
        except Exception as exc:
            # Speech remains useful if a Pepper image lacks one animation.
            gesture_error = str(exc)
    pepper.speech.say(text, wait=True)
    return jsonify({
        "ok": True,
        "gesture": gesture,
        "gesture_performed": gesture_performed,
        "gesture_error": gesture_error,
    })


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


# --- Dependency monitoring -------------------------------------------------
# Deliberately minimal: no background threads, no metrics stack. Services are
# probed on demand and the result printed to stdout, so `docker compose logs -f`
# is the whole monitoring story.

def log_event(message):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    sys.stdout.flush()


def service_registry():
    """The sibling containers this portal depends on, and a cheap probe for each."""
    return [
        ("ollama", OLLAMA_BASE_URL + "/api/tags"),
        ("speech-to-text", LOCAL_STT_BASE_URL + "/health"),
    ]


def probe_service(url, timeout=2):
    """Returns (ok, error, latency_ms). Kept self-contained so concurrent
    requests cannot clobber each other's timings."""
    started = time.time()
    try:
        urllib2.urlopen(
            urllib2.Request(url, headers={"Accept": "application/json"}),
            timeout=timeout,
        ).read()
        ok, error = True, ""
    except Exception as exc:
        # Some urllib2 failures stringify to "", which says nothing in a log.
        ok, error = False, ("%s: %s" % (type(exc).__name__, exc)).rstrip(": ")
    return ok, error, int((time.time() - started) * 1000)


def probe_all_services():
    report = []
    for name, url in service_registry():
        ok, error, latency_ms = probe_service(url)
        report.append({
            "name": name,
            "url": url,
            "ok": ok,
            "latency_ms": latency_ms,
            "error": error,
        })
    return report


def log_service_report(report):
    for entry in report:
        log_event("  %-15s %-5s %4sms  %s%s" % (
            entry["name"],
            "up" if entry["ok"] else "DOWN",
            entry["latency_ms"],
            entry["url"],
            "" if entry["ok"] else "  <- " + entry["error"],
        ))


@app.route("/api/services", methods=["GET"])
def api_services():
    """On-demand health of every dependency, mirrored into the container log."""
    report = probe_all_services()
    log_event("service check requested")
    log_service_report(report)
    return jsonify({
        "ok": True,
        "services": report,
        "all_up": all(entry["ok"] for entry in report),
    })


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")

    log_event("pepper portal listening on http://%s:%s" % (host, port))
    log_event("configuration:")
    log_event("  %-15s %s" % ("ollama", OLLAMA_BASE_URL))
    log_event("  %-15s %s" % ("chat model", OLLAMA_MODEL))
    log_event("  %-15s %s" % ("vision model", OLLAMA_VISION_MODEL))
    log_event("  %-15s %s%s" % (
        "speech-to-text",
        LOCAL_STT_BASE_URL,
        "" if LOCAL_STT_BASE_URL_FROM_ENV else
        "   <- WARNING: built-in default, LOCAL_STT_BASE_URL is unset. If speech-to-text "
        "runs as a container, recreate this one: docker compose up -d --force-recreate",
    ))
    log_event("dependency check (GET /api/services to repeat):")
    log_service_report(probe_all_services())

    # Keep local Llama requests responsive even while a robot call is waiting
    # on the lab network or Pepper is speaking a longer reply.
    app.run(host=host, port=port, debug=debug, threaded=True)
