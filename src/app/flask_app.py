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

import itertools
import json
import os
import subprocess
import sys
import threading
import traceback
from functools import wraps

from flask import Flask, jsonify, render_template, request

try:
    import qi  # NAOqi Python SDK
except Exception as e:
    qi = None

app = Flask(__name__)

SCRIPTS_DIR = os.environ.get(
    "SCRIPTS_DIR", os.path.join(os.path.dirname(__file__), "scripts")
)

# --- Simple in-memory session cache per (ip, port) (optional) ---
_sessions = {}
_jobs = {}
_job_counter = itertools.count(1)
_jobs_lock = threading.Lock()


def get_session(ip, port=9559):
    if qi is None:
        raise RuntimeError(
            "NAOqi 'qi' module not found. Ensure NAOqi SDK is installed and PYTHONPATH is set."
        )
    key = "%s:%s" % (ip, port)
    sess = _sessions.get(key)
    if sess is None:
        sess = qi.Session()
        _sessions[key] = sess

    # Connect only if not already connected
    try:
        # NAOqi 2.5 provides isConnected()
        if hasattr(sess, "isConnected"):
            if not sess.isConnected():
                sess.connect("tcp://%s:%s" % (ip, port))
        else:
            # Fallback for older bindings: try connect and ignore "already connected"
            sess.connect("tcp://%s:%s" % (ip, port))
    except RuntimeError as e:
        if "already connected" not in str(e).lower():
            raise
    return sess


def with_services(ip, port=9559):
    """Helper to get ALAudioPlayer and ALAnimationPlayer services for an IP:port."""
    sess = get_session(ip, port)
    audio = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")
    return audio, anim


def _run_script_job(job_id, script_path, ip, port):
    env = os.environ.copy()
    env["PEPPER_IP"] = ip
    env["PEPPER_PORT"] = str(port)
    # Prefer the same Python used by Flask app; change to explicit path if needed.
    cmd = [sys.executable, script_path, "--ip", ip, "--port", str(port)]
    try:
        p = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
        )
        out, _ = p.communicate()
        output = out.decode("utf-8", "ignore") if not isinstance(out, str) else out
        rc = p.returncode
    except Exception as e:
        output = "Error: %s" % (str(e),)
        rc = 1
    with _jobs_lock:
        _jobs[job_id]["done"] = True
        _jobs[job_id]["rc"] = rc
        _jobs[job_id]["output"] = output


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
    "animations/Stand/Emotions/Positive/Happy_1",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_2",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_3",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_4",  # Has noise
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
    if not ip or not script:
        return jsonify({"ok": False, "error": "Provide 'ip' and 'script'"}), 400

    spath = os.path.abspath(os.path.join(SCRIPTS_DIR, script))
    if not spath.startswith(
        os.path.abspath(SCRIPTS_DIR) + os.sep
    ) or not os.path.isfile(spath):
        return jsonify({"ok": False, "error": "Invalid script"}), 400

    job_id = str(next(_job_counter))
    with _jobs_lock:
        _jobs[job_id] = {"script": script, "done": False, "rc": None, "output": ""}

    t = threading.Thread(target=_run_script_job, args=(job_id, spath, ip, port))
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/script-status", methods=["GET"])
def api_script_status():
    job_id = request.args.get("job_id", "").strip()
    with _jobs_lock:
        state = _jobs.get(job_id)
        if not state:
            return jsonify({"ok": False, "error": "Unknown job_id"}), 404
        # Return a copy
        return jsonify(
            {
                "ok": True,
                "done": state["done"],
                "rc": state["rc"],
                "output": state["output"],
            }
        )


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
        is_awake = bool(
            motion.robotIsWakeUp()
        )  # True if motors on (wakeUp), False if rest
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

    return jsonify(
        {
            "ok": True,
            "is_awake": is_awake,
            "animation_enabled": animation_enabled,
            "life_state": life_state,
        }
    )


@app.route("/api/sleep", methods=["POST"])
@json_endpoint
def api_sleep():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    action = (data.get("action") or "").strip().lower()
    if not ip or action not in ("rest", "wake"):
        return (
            jsonify(
                {"ok": False, "error": "Provide 'ip' and action in {'rest','wake'}"}
            ),
            400,
        )

    sess = get_session(ip, port)
    motion = sess.service("ALMotion")
    if action == "rest":
        motion.rest()  # motors off / relaxed
    else:
        motion.wakeUp()  # motors on / ready
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


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


@app.route("/api/save-scene", methods=["POST"])
@json_endpoint
def api_save_scene():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    steps = data.get("steps", [])
    if not name or not isinstance(steps, list):
        return jsonify({"ok": False, "error": "Name and steps (array) required"}), 400

    scene = {"script_name": name, "scene": steps}

    scene_dir = os.path.join(SCRIPTS_DIR, "scenes")
    os.makedirs(scene_dir)
    path = os.path.join(scene_dir, "{}.json".format(name))
    with open(path, "w") as f:
        json.dump(scene, f, indent=2)

    return jsonify({"ok": True, "filename": path})


@app.route("/api/run-scene", methods=["POST"])
@json_endpoint
def api_run_scene():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    port = int(data.get("port", 9559))
    name = data.get("name", "").strip()
    if not ip or not name:
        return jsonify({"ok": False, "error": "Missing IP or scene name"}), 400

    scene_path = os.path.abspath(
        os.path.join(SCRIPTS_DIR, "scenes", "{}.json".format(name))
    )
    if not os.path.exists(scene_path):
        return jsonify({"ok": False, "error": "Scene not found"}), 404

    job_id = str(next(_job_counter))
    script_path = os.path.join(SCRIPTS_DIR, "run_scene.py")

    with _jobs_lock:
        _jobs[job_id] = {
            "script": "scene:{}".format(name),
            "done": False,
            "rc": None,
            "output": "",
        }

    t = threading.Thread(target=_run_script_job, args=(job_id, script_path, ip, port))
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=True)
