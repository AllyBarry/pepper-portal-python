# -*- coding: utf-8 -*-
"""Pepper's chest tablet: the RAIL Lab landing page and what the portal puts on screen."""
import threading
import time

from flask import Blueprint, jsonify, render_template, request

import portal_address
import tablet_content
from pepper_core import media_store
from robot import RobotUnavailable

from .common import json_body, json_endpoint, robot_address, robot_from

bp = Blueprint("tablet_routes", __name__)

# NAOqi can't report what the tablet is showing, so the portal remembers what
# it last put there, per robot.
_now_showing = {}
_now_showing_lock = threading.Lock()


def _remember(ip, port, item):
    with _now_showing_lock:
        if item is None:
            _now_showing.pop((ip, port), None)
        else:
            _now_showing[(ip, port)] = dict(item, shown_at=time.time())


@bp.route("/tablet", methods=["GET"])
def tablet_landing():
    """The page the tablet shows by default. Static: works with no internet."""
    return render_template("tablet.html")


@bp.route("/api/tablet/catalog", methods=["GET"])
@json_endpoint
def api_tablet_catalog():
    return jsonify({"ok": True, "items": tablet_content.catalog(media_store.status()["files"])})


@bp.route("/api/tablet/status", methods=["GET"])
@json_endpoint
def api_tablet_status():
    ip, port = robot_address(request.args)
    pepper = robot_from(request.args)
    available = pepper.tablet.available()
    with _now_showing_lock:
        showing = _now_showing.get((ip, port))
    return jsonify({
        "ok": True,
        "available": available,
        "now_showing": showing if available else None,
        "base_url": portal_address.tablet_base_url(ip),
    })


@bp.route("/api/tablet/show", methods=["POST"])
@json_endpoint
def api_tablet_show():
    """
    Body: {ip, port, kind, ref} with kind in landing|video|image|web.
    Older callers may send {path} (a page on this portal) or {url}.
    """
    data = json_body()
    ip, port = robot_address(data)
    base_url = portal_address.tablet_base_url(ip)
    kind = (data.get("kind") or "").strip()
    if kind:
        content = tablet_content.from_choice(
            kind, (data.get("ref") or "").strip(),
            lambda rel: media_store.local_file(rel) is not None,
        )
    elif (data.get("url") or "").strip():
        content = tablet_content.WebPage(data["url"])
    else:
        path = (data.get("path") or "/tablet").strip()
        if not path.startswith("/"):
            path = "/" + path
        content = (tablet_content.LandingPage() if path == tablet_content.LandingPage.PATH
                   else tablet_content.WebPage(base_url + path, label=path))
    try:
        url = content.render(robot_from(data).tablet, base_url)
    except RobotUnavailable as exc:
        return jsonify({"ok": False, "error": str(exc), "tablet_offline": True}), 409
    item = dict(content.describe(), url=url)
    _remember(ip, port, item)
    return jsonify(dict(item, ok=True))


@bp.route("/api/tablet/hide", methods=["POST"])
@json_endpoint
def api_tablet_hide():
    data = json_body()
    ip, port = robot_address(data)
    try:
        robot_from(data).tablet.hide()
    except RobotUnavailable as exc:
        return jsonify({"ok": False, "error": str(exc), "tablet_offline": True}), 409
    _remember(ip, port, None)
    return jsonify({"ok": True})
