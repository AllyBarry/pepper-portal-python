# -*- coding: utf-8 -*-
"""Scenes (JSON choreography in src/scenes/) and scripts (Python in src/app/scripts/)."""
import io
import itertools
import json
import os
import subprocess
import sys
import threading

from flask import Blueprint, jsonify

import robot

from .common import json_body, json_endpoint, robot_from

bp = Blueprint("scene_routes", __name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/app
_SRC_DIR = os.path.dirname(_APP_DIR)                                       # src
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR") or os.path.join(_APP_DIR, "scripts")
SCENES_DIR = os.environ.get("SCENES_DIR") or os.path.join(_SRC_DIR, "scenes")

for _directory in (SCRIPTS_DIR, SCENES_DIR):
    if not os.path.isdir(_directory):
        try:
            os.makedirs(_directory)
        except OSError:
            pass

_jobs = {}
_job_counter = itertools.count(1)
_jobs_lock = threading.Lock()


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
    if not isinstance(text, type(u"")):
        text = text.decode("utf-8")
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# ---------------------------------------------------------------- scripts

def _run_script_job(job_id, script_path, ip, port, language="English", name_param=""):
    env = os.environ.copy()
    env["PEPPER_IP"] = ip
    env["PEPPER_PORT"] = str(port)
    env["SCRIPT_LANG"] = language
    env["BIRTHDAY_NAME"] = name_param
    # Scripts control Pepper through the robot package in src/.
    env["PYTHONPATH"] = os.pathsep.join(p for p in (_SRC_DIR, env.get("PYTHONPATH")) if p)
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


@bp.route("/api/scripts", methods=["GET"])
def api_scripts():
    if not os.path.isdir(SCRIPTS_DIR):
        return jsonify({"ok": True, "scripts": []})
    names = sorted(
        name for name in os.listdir(SCRIPTS_DIR)
        if name.endswith(".py") and not name.startswith("_")
    )
    return jsonify({"ok": True, "scripts": names})


@bp.route("/api/run-script", methods=["POST"])
@json_endpoint
def api_run_script():
    data = json_body()
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
        _jobs[job_id] = {"script": script, "done": False, "rc": None, "output": "", "process": None}
    t = threading.Thread(target=_run_script_job, args=(job_id, spath, ip, port, language, name_param))
    t.daemon = True
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@bp.route("/api/stop-script", methods=["POST"])
@json_endpoint
def api_stop_script():
    job_id = (json_body().get("job_id") or "").strip()
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


@bp.route("/api/script-status", methods=["GET"])
def api_script_status():
    from flask import request
    job_id = request.args.get("job_id", "").strip()
    with _jobs_lock:
        state = _jobs.get(job_id)
        if not state:
            return jsonify({"ok": False, "error": "Unknown job_id"}), 404
        return jsonify({"ok": True, "done": state["done"], "rc": state["rc"], "output": state["output"]})


# ---------------------------------------------------------------- scenes

SCENE_ACTION_VERBS = frozenset([
    "audiofile", "audiofiles", "audio", "audios",
    "say", "text", "texts",
    "animation", "animations", "run", "runs",
    "behavior", "behaviors", "behaviour", "behaviours",
])
SCENE_ACTION_MODIFIERS = frozenset([
    "await", "await_audio", "await_tts", "await_anim", "await_behavior",
    "hold_for",
])
SCENE_BLOCK_KEYS = frozenset(["actions", "wait", "time"])


def validate_scene_steps(steps):
    """Return None if steps is a well-formed scene body, else an error string.

    Mirrors validateSceneSteps() in the UI so a hand-crafted POST or a saved
    file can't smuggle in blocks the scene runner doesn't understand.
    """
    if not isinstance(steps, list):
        return "Top-level scene must be a list of blocks."
    for bi, block in enumerate(steps):
        if not isinstance(block, dict):
            return "Block %d must be an object." % bi
        stray = set(block.keys()) - SCENE_BLOCK_KEYS
        if stray:
            return "Block %d: unknown key(s) %s" % (bi, ", ".join(sorted(stray)))
        actions = block.get("actions")
        if not isinstance(actions, list) or not actions:
            return "Block %d needs a non-empty 'actions' array." % bi
        for ai, action in enumerate(actions):
            if not isinstance(action, dict) or not action:
                return "Block %d action %d must be a non-empty object." % (bi, ai)
            keys = set(action.keys())
            unknown = keys - SCENE_ACTION_VERBS - SCENE_ACTION_MODIFIERS
            if unknown:
                return "Block %d action %d: unknown key(s) %s" % (bi, ai, ", ".join(sorted(unknown)))
            if not (keys & SCENE_ACTION_VERBS):
                return "Block %d action %d has no verb (say/audiofile/animation/behavior)." % (bi, ai)
    return None


@bp.route("/api/list-scenes", methods=["GET"])
def api_list_scenes():
    try:
        items = [
            filename[:-5] for filename in os.listdir(SCENES_DIR)
            if not filename.startswith(".") and filename.lower().endswith(".json")
        ]
        items.sort(key=lambda value: value.lower())
        return jsonify(items)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/get-scene/<name>", methods=["GET"])
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


@bp.route("/api/save-scene", methods=["POST"])
@json_endpoint
def api_save_scene():
    data = json_body()
    name = _safe_name(data.get("name"))
    steps = data.get("steps")
    if not name:
        return jsonify({"ok": False, "error": "Scene name is required"}), 400
    problem = validate_scene_steps(steps)
    if problem:
        return jsonify({"ok": False, "error": problem}), 400
    path = _safe_join(SCENES_DIR, name + ".json")
    _json_write_utf8(path, {"script_name": name, "scene": steps})
    return jsonify({"ok": True, "filename": os.path.basename(path), "script_name": name})


@bp.route("/api/run-scene", methods=["POST"])
@json_endpoint
def api_run_scene():
    data = json_body()
    name = _safe_name(data.get("name"))
    if not name:
        return jsonify({"ok": False, "error": "Missing scene name or IP"}), 400
    pepper = robot_from(data)
    scene_path = _safe_join(SCENES_DIR, name + ".json")
    if not os.path.exists(scene_path):
        return jsonify({"ok": False, "error": "Scene not found"}), 404
    completed = robot.run_scene_file(pepper, scene_path)
    return jsonify({"ok": bool(completed), "status": "completed" if completed else "no_actions"})
