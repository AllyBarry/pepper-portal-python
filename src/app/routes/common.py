# -*- coding: utf-8 -*-
"""Helpers shared by every route module."""
from __future__ import print_function

import traceback
from functools import wraps

from flask import jsonify, request

import robot


def json_endpoint(fn):
    """Any exception becomes {"ok": false, "error": ...} with HTTP 400."""
    @wraps(fn)
    def _wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"ok": False, "error": str(e)}), 400
    return _wrap


def json_body():
    return request.get_json(force=True, silent=True) or {}


def robot_address(source):
    """(ip, port) from a JSON body or query args. Raises ValueError if ip is missing."""
    ip = (source.get("ip") or "").strip()
    if not ip:
        raise ValueError("Missing 'ip'")
    return ip, int(source.get("port", 9559) or 9559)


def robot_from(source):
    """A robot.Robot for the ip/port in a JSON body or query args."""
    ip, port = robot_address(source)
    return robot.connect(ip, port)
