# -*- coding: utf-8 -*-
"""
Media: drag-and-drop onto the portal. Files land in media/; audio is synced
onto Pepper in the background, everything is served at /media/<rel> (how the
tablet shows videos and images). See pepper_core/media_store.py.
"""
import os

from flask import Blueprint, jsonify, request, send_from_directory

from pepper_core import media_store

from .common import json_body, json_endpoint

bp = Blueprint("media_routes", __name__)


@bp.route("/api/media", methods=["GET"])
@json_endpoint
def api_media():
    media_store.set_robot(request.args.get("ip"))
    return jsonify(dict(media_store.status(), ok=True))


@bp.route("/api/media/upload", methods=["POST"])
@json_endpoint
def api_upload_media():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400
    media_store.set_robot(request.form.get("ip"))
    rel = media_store.save_upload(uploaded, uploaded.filename, request.form.get("folder"))
    # remote_path is what scenes need: the file's absolute location on Pepper
    # once synced. Only audio is synced.
    return jsonify({
        "ok": True,
        "path": rel,
        "kind": media_store.kind(rel),
        "remote_path": media_store.robot_path(rel) if media_store.is_audio(rel) else None,
    })


@bp.route("/api/media/sync", methods=["POST"])
@json_endpoint
def api_media_sync():
    media_store.set_robot(json_body().get("ip"))
    media_store.request_sync()
    return jsonify({"ok": True})


@bp.route("/api/media/delete", methods=["POST"])
@json_endpoint
def api_media_delete():
    data = json_body()
    media_store.set_robot(data.get("ip"))
    remote_error = media_store.delete_file(data.get("path") or "")
    return jsonify({"ok": True, "remote_error": remote_error})


@bp.route("/media/<path:rel>", methods=["GET"])
def media_file(rel):
    path = media_store.local_file(rel)
    if path is None:
        return jsonify({"ok": False, "error": "Not found"}), 404
    # conditional=True lets the tablet's video player seek (HTTP Range).
    return send_from_directory(os.path.dirname(path), os.path.basename(path), conditional=True)
