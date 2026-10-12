# -*- coding: utf-8 -*-
"""
Teleop: driving the base, step moves, head, joints, hands, posture and
collision protection. Each route is one robot.motion call.

/api/motion/drive is the joystick: the page re-sends it every ~150 ms while a
control is held, and robot.motion stops the base if it stops arriving.
"""
from flask import Blueprint, jsonify

from .common import json_body, json_endpoint, robot_from

bp = Blueprint("motion_routes", __name__)


def _num(data, key, default=0.0):
    return float(data.get(key, default) or 0.0)


@bp.route("/api/motion/drive", methods=["POST"])
@json_endpoint
def api_motion_drive():
    data = json_body()
    robot_from(data).motion.drive(_num(data, "x"), _num(data, "y"), _num(data, "theta"))
    return jsonify({"ok": True})


@bp.route("/api/motion/stop", methods=["POST"])
@json_endpoint
def api_motion_stop():
    robot_from(json_body()).motion.stop_move()
    return jsonify({"ok": True})


@bp.route("/api/motion/move-to", methods=["POST"])
@json_endpoint
def api_motion_move_to():
    """Step move, relative: x/y metres, theta radians. Returns at once; /stop cancels it."""
    data = json_body()
    x, y, theta = _num(data, "x"), _num(data, "y"), _num(data, "theta")
    if abs(x) > 3 or abs(y) > 3:
        return jsonify({"ok": False, "error": "Step moves are limited to 3 m"}), 400
    robot_from(data).motion.move_to(x, y, theta, wait=False)
    return jsonify({"ok": True})


@bp.route("/api/motion/head", methods=["POST"])
@json_endpoint
def api_motion_head():
    data = json_body()
    robot_from(data).motion.look(_num(data, "yaw"), _num(data, "pitch"), _num(data, "speed", 0.2) or 0.2)
    return jsonify({"ok": True})


@bp.route("/api/motion/joints", methods=["POST"])
@json_endpoint
def api_motion_joints():
    """{"names": ["RShoulderPitch", ...], "angles": [radians, ...], "speed": 0..1}"""
    data = json_body()
    names, angles = data.get("names") or [], data.get("angles") or []
    if not names or len(names) != len(angles):
        return jsonify({"ok": False, "error": "'names' and 'angles' must be equal-length lists"}), 400
    robot_from(data).motion.set_angles(names, angles, _num(data, "speed", 0.2) or 0.2)
    return jsonify({"ok": True})


@bp.route("/api/motion/hand", methods=["POST"])
@json_endpoint
def api_motion_hand():
    data = json_body()
    robot_from(data).motion.hand((data.get("hand") or "").lower(), bool(data.get("open")))
    return jsonify({"ok": True})


@bp.route("/api/motion/posture", methods=["POST"])
@json_endpoint
def api_motion_posture():
    data = json_body()
    reached = robot_from(data).motion.go_to_posture(data.get("name") or "", _num(data, "speed", 0.5) or 0.5)
    return jsonify({"ok": True, "reached": reached})


@bp.route("/api/motion/collision", methods=["POST"])
@json_endpoint
def api_motion_collision():
    data = json_body()
    robot_from(data).motion.set_collision_protection(bool(data.get("enabled", True)))
    return jsonify({"ok": True, "enabled": bool(data.get("enabled", True))})


@bp.route("/api/motion/state", methods=["POST"])
@json_endpoint
def api_motion_state():
    """Awake, moving, odometry, head angles, posture, collision protection; each part may fail alone."""
    motion = robot_from(json_body()).motion
    out = {"ok": True}
    for key, read in (
        ("awake", motion.is_awake),
        ("moving", motion.is_moving),
        ("position", motion.position),
        ("head", lambda: motion.angles(["HeadYaw", "HeadPitch"])),
        ("posture", motion.posture),
        ("collision_protection", motion.collision_protection),
    ):
        try:
            out[key] = read()
        except Exception as exc:
            out.setdefault("errors", {})[key] = str(exc)
    return jsonify(out)
