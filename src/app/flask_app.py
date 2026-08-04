# -*- coding: utf-8 -*-
"""
Pepper Control Web App (Flask)
--------------------------------
Serves a control UI and JSON endpoints to:
- Test connection to Pepper
- Play / stop audio on Pepper
- Run animations (sync or async)
- List / run Python scripts from scripts/
- Save / list / get / run scene JSON files from scenes/

Prereqs:
- Python 2.7 with NAOqi Python SDK available (module `qi`).
- Flask installed (pip install Flask==2.2.* for Py2 compat, or your working version).

Run:
  python flask_app.py
Open:
  http://127.0.0.1:5000
"""

from __future__ import print_function

import itertools
import json
import os
import io
import subprocess
import threading
import traceback

from functools import wraps
from flask import Flask, jsonify, render_template, request

try:
    import qi  # NAOqi Python SDK
    _QI_IMPORT_ERROR = None
except Exception as _e:
    qi = None
    # Keep the real reason: the usual cause is an architecture mismatch (pynaoqi
    # ships x86-64-only .so files), not a missing PYTHONPATH.
    _QI_IMPORT_ERROR = traceback.format_exc()

# Make local modules importable even if CWD differs
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# If you have a pepper_core module with PepperController, you can import it.
# with_services below uses the session directly, so pepper_core is optional for the web API.
from pepper_core import PepperController, PepperScripter  # optional; used by run-scene


app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"), static_folder=os.path.join(BASE_DIR, "static"))

# --------------------------
# Directories (configurable)
# --------------------------
SCENES_DIR = os.environ.get("SCENES_DIR") or os.path.join(os.path.dirname(BASE_DIR), "scenes")
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR") or os.path.join(BASE_DIR, "scripts")

for _d in (SCENES_DIR, SCRIPTS_DIR):
    if not os.path.isdir(_d):
        try:
            os.makedirs(_d)
        except OSError:
            pass

def _json_write_utf8(path, obj):
    """
    Py2-safe JSON writer:
    - Opens as Unicode text
    - Forces unicode string (ensure_ascii=False)
    """
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    try:
        # On Py2, ensure txt is unicode for io.open(..., encoding=...) write()
        unicode  # noqa
        if not isinstance(txt, unicode):
            txt = txt.decode('utf-8')
    except NameError:
        # Py3: already a str
        pass
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(txt)

# --------------------------
# Safe path helpers
# --------------------------
def _safe_name(name):
    """Allow only 'basename' style names (no slashes, traversal, hidden)."""
    name = (name or "").strip()
    if (not name) or ("/" in name) or ("\\" in name) or name.startswith(".") or (".." in name):
        return None
    return name

def _safe_join(base_dir, filename):
    """Join and ensure the result stays inside base_dir."""
    path = os.path.normpath(os.path.join(base_dir, filename))
    base_norm = os.path.normpath(base_dir)
    # Ensure trailing separator to avoid prefix tricks
    if not path.startswith(base_norm + os.sep) and path != base_norm:
        raise ValueError("Unsafe path")
    return path

# --------------------------
# Session cache & services
# --------------------------
_sessions = {}  # key: "ip:port" -> qi.Session()

def get_session(ip, port=9559):
    if qi is None:
        raise RuntimeError(
            "NAOqi 'qi' module could not be imported. Ensure the SDK is installed, "
            "PYTHONPATH is set, and the container is running as linux/amd64.\n%s"
            % (_QI_IMPORT_ERROR or "")
        )
    key = "%s:%s" % (ip, port)
    sess = _sessions.get(key)
    if sess is None:
        sess = qi.Session()
        _sessions[key] = sess

    # Connect only if not already connected
    try:
        if hasattr(sess, "isConnected"):
            if not sess.isConnected():
                sess.connect("tcp://{}:{}".format(ip, port))
        else:
            # Fallback for older bindings: try connect and ignore "already connected"
            sess.connect("tcp://{}:{}".format(ip, port))
    except RuntimeError as e:
        if "already connected" not in str(e).lower():
            raise
    return sess

def clear_session(ip, port):
    """Explicitly close and delete a session for ip:port."""
    key = "%s:%s" % (ip, port)
    sess = _sessions.pop(key, None)
    if sess:
        try:
            sess.close()
        except Exception:
            pass
        print("Session cleared for {}:{}".format(ip, port))
    else:
        print("No session found for {}:{}".format(ip, port))

def with_services(ip, port=9559):
    """Helper to get ALAudioPlayer and ALAnimationPlayer services for an IP:port."""
    sess = get_session(ip, port)
    audio = sess.service("ALAudioPlayer")
    anim = sess.service("ALAnimationPlayer")
    return audio, anim

# --------------------------
# Async job infra (scripts)
# --------------------------
_jobs = {}
_job_counter = itertools.count(1)
_jobs_lock = threading.Lock()


def _run_script_job(job_id, script_path, ip, port, language, name_param=""):
    env = os.environ.copy()
    env["PEPPER_IP"] = ip
    env["PEPPER_PORT"] = str(port)
    env["SCRIPT_LANG"] = language  # also available via env
    env["BIRTHDAY_NAME"] = name_param  # consumed by birthday.py; other scripts ignore it

    cmd = [sys.executable, script_path, "--ip", ip, "--port", str(port), "--lang", language]
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

# --------------------------
# JSON error wrapper
# --------------------------
def json_endpoint(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e)}), 400
    return _wrap

# -----------------------------------------
# Animations list (kept from your version)
# -----------------------------------------
ANIMATIONS = [
    "animations/Stand/Emotions/Negative/Bored_1",
    "animations/Stand/Emotions/Neutral/Embarrassed_1",
    "animations/Stand/Emotions/Positive/Happy_1",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_2",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_3",  # Has noise
    "animations/Stand/Emotions/Positive/Happy_4",  # Has noise
    "animations/Stand/Emotions/Positive/Hysterical_1",
    "animations/Stand/Emotions/Positive/Peaceful_1",
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

# --------------------------
# Routes
# --------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", animations=ANIMATIONS)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# ---- Connectivity ----
@app.route("/api/connect-test", methods=["POST"])
@json_endpoint
def api_connect():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    audio, _ = with_services(ip, port)
    _ = audio.getMasterVolume()  # tiny no-op to confirm call works
    return jsonify({"ok": True})

# ---- Audio ----
@app.route("/api/play-audio", methods=["POST"])
@json_endpoint
def api_play_audio():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    path = (data.get("path") or "").strip()
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
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    audio, _ = with_services(ip, port)
    try:
        audio.stopAll()
    except Exception:
        pass
    return jsonify({"ok": True})

# ---- Animations ----
@app.route("/api/run-animation", methods=["POST"])
@json_endpoint
def api_run_animation():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    animation = (data.get("animation") or "").strip()
    mode = (data.get("mode", "sync") or "sync").lower()
    if not ip or not animation:
        return jsonify({"ok": False, "error": "'ip' and 'animation' are required"}), 400
    _, anim = with_services(ip, port)
    if mode == "async":
        _fut = anim.run(animation, _async=True)
        return jsonify({"ok": True, "async": True})
    else:
        anim.run(animation)
        return jsonify({"ok": True, "async": False})

@app.route("/api/stop-animation", methods=["POST"])
@json_endpoint
def api_stop_animation():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    _, anim = with_services(ip, port)
    try:
        anim.stopAll()
    except Exception:
        pass
    return jsonify({"ok": True})

# ---- Behaviors (installed Choregraphe behaviors) ----
@app.route("/api/list-behaviors", methods=["POST"])
@json_endpoint
def api_list_behaviors():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    sess = get_session(ip, port)
    bm = sess.service("ALBehaviorManager")
    installed = list(bm.getInstalledBehaviors())
    running = set(bm.getRunningBehaviors())
    installed.sort(key=lambda s: s.lower())
    return jsonify({"ok": True, "behaviors": installed, "running": list(running)})


@app.route("/api/run-behavior", methods=["POST"])
@json_endpoint
def api_run_behavior():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    behavior = (data.get("behavior") or "").strip()
    if not ip or not behavior:
        return jsonify({"ok": False, "error": "'ip' and 'behavior' are required"}), 400
    sess = get_session(ip, port)
    bm = sess.service("ALBehaviorManager")
    if not bm.isBehaviorInstalled(behavior):
        return jsonify({"ok": False, "error": "Behavior not installed: " + behavior}), 404
    # Fire-and-forget — the portal can poll /api/list-behaviors to see running state.
    bm.runBehavior(behavior, _async=True)
    return jsonify({"ok": True, "behavior": behavior})


@app.route("/api/stop-behavior", methods=["POST"])
@json_endpoint
def api_stop_behavior():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    behavior = (data.get("behavior") or "").strip()
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400
    sess = get_session(ip, port)
    bm = sess.service("ALBehaviorManager")
    try:
        if behavior:
            bm.stopBehavior(behavior)
        else:
            bm.stopAllBehaviors()
    except Exception:
        pass
    return jsonify({"ok": True})


# ---- Scripts listing/running (scripts/) ----

@app.route("/api/scripts", methods=["GET"])
def api_scripts():
    items = []
    try:
        for fn in os.listdir(SCRIPTS_DIR):
            if fn.startswith("."):
                continue
            if fn.lower().endswith(".py"):
                items.append(fn)
        items.sort(key=lambda s: s.lower())
        return jsonify({"ok": True, "scripts": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
    # guard path traversal
    if ("/" in script) or ("\\" in script) or script.startswith(".") or (".." in script):
        return jsonify({"ok": False, "error": "Unsafe script name"}), 400
    spath = _safe_join(SCRIPTS_DIR, script)
    if not os.path.isfile(spath):
        return jsonify({"ok": False, "error": "Script not found"}), 404

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
        target=_run_script_job, args=(job_id, spath, ip, port, language, name_param)
    )
    t.daemon = True
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/stop-script", methods=["POST"])
@json_endpoint
def api_stop_script():
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    job_id = (data.get("job_id") or "").strip()
    audio, anim = with_services(ip, port)
    audio.stopAll()
    anim.stopAll()
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Unknown job_id"}), 404
        p = job.get("process")

    if p and p.poll() is None:
        try:
            # graceful first
            p.terminate()
            try:
                p.wait(timeout=2)
            except Exception:
                pass
            if p.poll() is None:
                p.kill()
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
    job_id = (request.args.get("job_id") or "").strip()
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


# ---- Modes / state ----
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
        try:
            is_awake = any(motion.getStiffnesses("Body"))
        except Exception:
            is_awake = False

    # Autonomous Life state as "animation mode"
    animation_enabled = False
    life_state = "unknown"
    try:
        life = sess.service("ALAutonomousLife")
        life_state = life.getState()
        animation_enabled = life_state != "disabled"
    except Exception:
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
    ip = (data.get("ip") or "").strip()
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
    # TODO - http://doc.aldebaran.com/2-5/naoqi/interaction/autonomouslife-api.html
    data = request.get_json(force=True)
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))
    enabled = bool(data.get("enabled", True))
    if not ip:
        return jsonify({"ok": False, "error": "Missing 'ip'"}), 400

    sess = get_session(ip, port)
    try:
        life = sess.service("ALAutonomousLife")
        life.setState("solitary" if enabled else "disabled")
    except Exception:
        try:
            awareness = sess.service("ALBasicAwareness")
            awareness.setEnabled(enabled)
        except Exception:
            pass
    return jsonify({"ok": True, "enabled": enabled})

# ---- Scenes (scenes/) ----
@app.route("/api/list-scenes", methods=["GET"])
def api_list_scenes():
    """Return scene base names (without .json) from SCENES_DIR."""
    items = []
    try:
        for fn in os.listdir(SCENES_DIR):
            if fn.startswith("."):
                continue
            if fn.lower().endswith(".json"):
                items.append(fn[:-5])
        items.sort(key=lambda s: s.lower())
        return jsonify(items)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/get-scene/<name>", methods=["GET"])
def api_get_scene(name):
    """Load a scene JSON by name (no extension)."""
    base = _safe_name(name)
    if not base:
        return jsonify({"ok": False, "error": "Invalid scene name"}), 400
    path = _safe_join(SCENES_DIR, base + ".json")
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "Scene not found"}), 404
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/save-scene", methods=["POST"])
@json_endpoint
def api_save_scene():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    steps = data.get("steps", [])
    if not name or not isinstance(steps, list):
        return jsonify({"ok": False, "error": "Name and steps (array) required"}), 400

    scene = {"script_name": name, "scene": steps}
    try:
        if not os.path.isdir(SCENES_DIR):
            os.makedirs(SCENES_DIR)
    except OSError:
        pass

    path = _safe_join(SCENES_DIR, name + ".json")
    _json_write_utf8(path, scene)   # <-- use the helper here
    return jsonify({"ok": True, "filename": os.path.basename(path)})

@app.route("/api/run-scene", methods=["POST"])
@json_endpoint
def api_run_scene():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    ip = (data.get("ip") or "").strip()
    port = int(data.get("port", 9559))

    if not name or not ip:
        return jsonify({"ok": False, "error": "Missing script name or IP"}), 400

    if PepperController is None or PepperScripter is None:
        return jsonify({"ok": False, "error": "PepperController/Scripter not available"}), 500

    scene_path = _safe_join(SCENES_DIR, name + ".json")
    if not os.path.exists(scene_path):
        return jsonify({"ok": False, "error": "Scene not found {}".format(scene_path)}), 404

    try:
        ctrl = PepperController(ip=ip, port=port, verbose=True)
        # Blocking=True ensures each event completes before the next
        scripter = PepperScripter(controller=ctrl, blocking=True, verbose=True)
        ok = scripter.run_scene(scene_path, base=os.path.dirname(scene_path))
        return jsonify({"ok": ok, "status": "completed" if ok else "no_actions"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# --------------------------
# Main
# --------------------------
if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=True)
