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

import os
import traceback
from functools import wraps

from flask import Flask, request, jsonify, render_template

try:
    import qi  # NAOqi Python SDK
except Exception as e:
    qi = None

app = Flask(__name__)

# --- Simple in-memory session cache per (ip, port) (optional) ---
_sessions = {}


def get_session(ip, port=9559):
    if qi is None:
        raise RuntimeError("NAOqi 'qi' module not found. Ensure NAOqi SDK is installed and PYTHONPATH is set.")
    key = "%s:%s" % (ip, port)
    sess = _sessions.get(key)
    if sess is None:
        sess = qi.Session()
        _sessions[key] = sess

    # Connect only if not already connected
    try:
        # NAOqi 2.5 provides isConnected()
        if hasattr(sess, 'isConnected'):
            if not sess.isConnected():
                sess.connect("tcp://%s:%s" % (ip, port))
        else:
            # Fallback for older bindings: try connect and ignore "already connected"
            sess.connect("tcp://%s:%s" % (ip, port))
    except RuntimeError as e:
        if 'already connected' not in str(e).lower():
            raise
    return sess


def with_services(ip, port=9559):
    """Helper to get ALAudioPlayer and ALAnimationPlayer services for an IP:port."""
    sess = get_session(ip, port)
    audio = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")
    return audio, anim


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
    "animations/Stand/Gestures/Hey_1",
    "animations/Stand/Gestures/Hello_3",
    "animations/Stand/Gestures/Enthusiastic_4",
    "animations/Stand/Gestures/CalmDown_2",
    "animations/Stand/Gestures/Explain_2",
    "animations/Stand/BodyTalk/Pepper/BodyTalk_1",
    "animations/Stand/BodyTalk/Pepper/BodyTalk_3",
    "animations/Stand/BodyTalk/Pepper/BodyTalk_4",
]


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
    # Attempt to fetch one service to confirm connectivity
    audio, anim = with_services(ip, port)
    # A tiny no-op to confirm we can call a method (get volume)
    _ = audio.getMasterVolume()
    return jsonify({"ok": True})


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


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=True)
