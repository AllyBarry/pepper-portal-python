# -*- coding: utf-8 -*-
"""Direct robot controls: connection, sound, animation, behaviors, modes, camera."""
import threading

from flask import Blueprint, Response, jsonify, request

from robot.camera import CAMERA_IDS, CAMERA_RESOLUTIONS

from .common import json_body, json_endpoint, robot_from

bp = Blueprint("robot_routes", __name__)

# Only one service-discovery handshake at a time, even if several browser tabs
# click Connect together.
_connect_test_lock = threading.Lock()


@bp.route("/api/connect-test", methods=["POST"])
@json_endpoint
def api_connect():
    pepper = robot_from(json_body())
    with _connect_test_lock:
        try:
            if not pepper.system.ping():
                raise RuntimeError("Pepper's ALSystem service did not respond")
        except Exception:
            # A failed session is discarded so later requests can't reuse
            # its cancelled futures.
            pepper.disconnect()
            raise
    return jsonify({"ok": True})


@bp.route("/api/camera-frame", methods=["GET"])
@json_endpoint
def api_camera_frame():
    args = request.args
    camera = (args.get("camera") or "top").strip().lower()
    resolution = (args.get("resolution") or "320x240").strip().lower()
    fps = max(1, min(5, int(args.get("fps", 2))))
    if camera not in CAMERA_IDS:
        return jsonify({"ok": False, "error": "Camera must be 'top' or 'bottom'"}), 400
    if resolution not in CAMERA_RESOLUTIONS:
        return jsonify({
            "ok": False,
            "error": "Resolution must be one of: %s" % ", ".join(sorted(CAMERA_RESOLUTIONS)),
        }), 400
    png = robot_from(args).camera.capture_png(camera, resolution, fps)
    return Response(png, mimetype="image/png", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    })


@bp.route("/api/vision-attention", methods=["POST"])
@json_endpoint
def api_vision_attention():
    """Keep Pepper's head steady while the portal Vision workspace is active."""
    data = json_body()
    pepper = robot_from(data)
    active = bool(data.get("active", False))
    previous = pepper.awareness.hold_for_vision(active)
    result = {"ok": True, "active": active, "previous": previous}
    result.update(pepper.awareness.tracking_state())
    return jsonify(result)


@bp.route("/api/play-audio", methods=["POST"])
@json_endpoint
def api_play_audio():
    data = json_body()
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "error": "'ip' and 'path' are required"}), 400
    audio = robot_from(data).audio
    file_id = audio.load(path)
    audio.play_loaded(file_id, wait=True)
    return jsonify({"ok": True, "fileId": int(file_id)})


@bp.route("/api/stop-audio", methods=["POST"])
@json_endpoint
def api_stop_audio():
    try:
        robot_from(json_body()).audio.stop_all()
    except ValueError:
        raise
    except Exception:
        pass
    return jsonify({"ok": True})


@bp.route("/api/run-animation", methods=["POST"])
@json_endpoint
def api_run_animation():
    data = json_body()
    animation = (data.get("animation") or "").strip()
    if not animation:
        return jsonify({"ok": False, "error": "'ip' and 'animation' are required"}), 400
    run_async = (data.get("mode") or "sync").lower() == "async"
    robot_from(data).motion.run_animation(animation, wait=not run_async)
    return jsonify({"ok": True, "async": run_async})


@bp.route("/api/stop-animation", methods=["POST"])
@json_endpoint
def api_stop_animations():
    try:
        robot_from(json_body()).motion.stop_animations()
    except ValueError:
        raise
    except Exception:
        pass
    return jsonify({"ok": True})


@bp.route("/api/list-behaviors", methods=["POST"])
@json_endpoint
def api_list_behaviors():
    behaviors = robot_from(json_body()).behaviors
    return jsonify({"ok": True, "behaviors": behaviors.list_installed(), "running": behaviors.running()})


@bp.route("/api/run-behavior", methods=["POST"])
@json_endpoint
def api_run_behavior():
    data = json_body()
    name = (data.get("behavior") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "'ip' and 'behavior' are required"}), 400
    robot_from(data).behaviors.start(name)
    return jsonify({"ok": True})


@bp.route("/api/stop-behavior", methods=["POST"])
@json_endpoint
def api_stop_behavior():
    try:
        robot_from(json_body()).behaviors.stop_all()
    except ValueError:
        raise
    except Exception:
        pass
    return jsonify({"ok": True})


@bp.route("/api/mode-status", methods=["POST"])
@json_endpoint
def api_mode_status():
    pepper = robot_from(json_body())
    animation_enabled, life_state = pepper.awareness.life_state()
    return jsonify({
        "ok": True,
        "is_awake": pepper.motion.is_awake(),
        "animation_enabled": animation_enabled,
        "life_state": life_state,
    })


@bp.route("/api/sleep", methods=["POST"])
@json_endpoint
def api_sleep():
    data = json_body()
    action = (data.get("action") or "").strip().lower()
    if action not in ("rest", "wake"):
        return jsonify({"ok": False, "error": "Provide 'ip' and action in {'rest','wake'}"}), 400
    motion = robot_from(data).motion
    if action == "rest":
        motion.rest()
    else:
        motion.wake()
    return jsonify({"ok": True, "action": action})


@bp.route("/api/animation-mode", methods=["POST"])
@json_endpoint
def api_animation_mode():
    data = json_body()
    enabled = bool(data.get("enabled", True))
    robot_from(data).awareness.set_animation_mode(enabled)
    return jsonify({"ok": True, "enabled": enabled})
