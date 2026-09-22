# -*- coding: utf-8 -*-
"""
Local catalog for user-uploaded audio/video, and the transfer of audio onto Pepper.

- Audio has to physically live on the robot: ALAudioPlayer.playFile() runs on
  Pepper and reads Pepper's own filesystem. Uploaded audio is scp'd into one
  fixed folder there (PEPPER_AUDIO_UPLOAD_DIR) over an SSH key set up ahead of
  time (see README: "Media uploads (SSH key setup)").
- Video is NOT sent to Pepper. Tablet playback (ALTabletService.showWebview)
  just points the tablet's browser at a URL, so video stays on the portal and
  is served over HTTP.

Either way, everything uploaded is recorded in one manifest.json so the portal
(and the scripting editor) can list what exists without the user tracking
paths themselves. Scene JSON only ever needs a bare stored_filename; the
scripter joins that onto PEPPER_AUDIO_UPLOAD_DIR automatically.
"""
from __future__ import print_function

import io
import json
import os
import re
import subprocess
import threading
import time
import traceback
import uuid


def _log(level, msg, verbose=True):
    if not verbose:
        return
    try:
        if isinstance(msg, unicode):  # noqa: F821 (Py2 only)
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[MEDIA][%s] %s" % (level, msg))


try:
    from werkzeug.utils import secure_filename as _werkzeug_secure_filename
except Exception:
    _werkzeug_secure_filename = None


class MediaError(Exception):
    """Raised for user-facing validation/transfer failures."""
    pass


_APP_DIR = os.path.dirname(os.path.abspath(__file__))          # .../src/app/pepper_core
_SRC_APP_DIR = os.path.dirname(_APP_DIR)                       # .../src/app
_PROJECT_ROOT = os.path.dirname(_SRC_APP_DIR)                  # repo root (or /home/user in the container)

MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or os.path.join(_PROJECT_ROOT, "media")
AUDIO_DIR = os.path.join(MEDIA_ROOT, "audio")
VIDEO_DIR = os.path.join(MEDIA_ROOT, "video")
MANIFEST_PATH = os.path.join(MEDIA_ROOT, "manifest.json")

# The one place on Pepper every uploaded audio file ends up. The scripting
# editor resolves bare filenames against this, so nobody has to type it.
PEPPER_AUDIO_UPLOAD_DIR = (
    os.environ.get("PEPPER_AUDIO_UPLOAD_DIR") or "/data/home/nao/.local/share/wav/uploads"
).rstrip("/") + "/"
PEPPER_SSH_USER = os.environ.get("PEPPER_SSH_USER", "nao")
_SSH_CONNECT_TIMEOUT = int(os.environ.get("PEPPER_SSH_TIMEOUT", "10"))

# The container's key lives in $HOME/.ssh (see docker-compose.yaml's
# pepper-ssh-key volume), so plain ssh/scp find it without -i. Host key
# checking is off deliberately: Pepper is a single robot on a trusted LAN with
# a changing identity (re-imaged, DHCP), same trust model as the manual `scp`
# instructions this replaces.
_SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=%d" % _SSH_CONNECT_TIMEOUT,
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2",
]

AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v")

_lock = threading.Lock()


def _ensure_dirs():
    for d in (MEDIA_ROOT, AUDIO_DIR, VIDEO_DIR):
        if not os.path.isdir(d):
            try:
                os.makedirs(d)
            except OSError:
                pass


_ensure_dirs()


def kind_for_filename(filename):
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def _dir_for(kind):
    return AUDIO_DIR if kind == "audio" else VIDEO_DIR


def _fallback_secure_filename(name):
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name


def _clean_filename(name):
    cleaned = _werkzeug_secure_filename(name) if _werkzeug_secure_filename else ""
    if not cleaned:
        cleaned = _fallback_secure_filename(name)
    return cleaned


def _unique_stored_name(kind, filename):
    directory = _dir_for(kind)
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 1
    while os.path.exists(os.path.join(directory, candidate)):
        n += 1
        candidate = "%s_%d%s" % (base, n, ext)
    return candidate


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_write_utf8(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    try:
        if not isinstance(text, unicode):  # noqa: F821 (Py2 only)
            text = text.decode("utf-8")
    except NameError:
        pass
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        return {"media": []}
    try:
        with io.open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("media"), list):
            return data
    except Exception:
        _log("ERROR", "Failed to read manifest, starting fresh: %s" % traceback.format_exc())
    return {"media": []}


def _save_manifest(data):
    _json_write_utf8(MANIFEST_PATH, data)


def _shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _proc_error(exc):
    output = getattr(exc, "output", None)
    if output:
        try:
            return output.decode("utf-8", "replace").strip()[:400]
        except Exception:
            return str(output)[:400]
    return str(exc)


def _ssh_target(ip, ssh_user=None):
    return "%s@%s" % (ssh_user or PEPPER_SSH_USER, ip)


def _scp_to_pepper(local_path, stored_name, ip, ssh_user=None, verbose=True):
    """Push one file onto Pepper into PEPPER_AUDIO_UPLOAD_DIR. Returns (ok, error)."""
    target = _ssh_target(ip, ssh_user)
    mkdir_cmd = ["ssh"] + _SSH_OPTS + [target, "mkdir -p %s" % _shquote(PEPPER_AUDIO_UPLOAD_DIR)]
    try:
        subprocess.check_output(mkdir_cmd, stderr=subprocess.STDOUT)
    except Exception as e:
        msg = _proc_error(e)
        _log("ERROR", "Could not create upload dir on Pepper: %s" % msg, verbose)
        return False, msg

    remote = "%s:%s%s" % (target, PEPPER_AUDIO_UPLOAD_DIR, stored_name)
    scp_cmd = ["scp"] + _SSH_OPTS + [local_path, remote]
    try:
        subprocess.check_output(scp_cmd, stderr=subprocess.STDOUT)
        _log("INFO", "Uploaded %s to Pepper:%s" % (stored_name, PEPPER_AUDIO_UPLOAD_DIR), verbose)
        return True, None
    except Exception as e:
        msg = _proc_error(e)
        _log("ERROR", "scp to Pepper failed: %s" % msg, verbose)
        return False, msg


def _ssh_remove(ip, ssh_user, remote_path, verbose=True):
    target = _ssh_target(ip, ssh_user)
    cmd = ["ssh"] + _SSH_OPTS + [target, "rm -f %s" % _shquote(remote_path)]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except Exception as e:
        _log("WARN", "Could not remove file on Pepper: %s" % _proc_error(e), verbose)


def list_media(kind=None):
    with _lock:
        items = list(_load_manifest()["media"])
    if kind:
        items = [m for m in items if m.get("kind") == kind]
    items.sort(key=lambda m: m.get("uploaded_at", ""), reverse=True)
    result = []
    for m in items:
        entry = dict(m)
        if entry.get("kind") == "audio":
            # Computed, not stored, so it always reflects the current
            # PEPPER_AUDIO_UPLOAD_DIR rather than whatever it was at upload time.
            entry["robot_path"] = PEPPER_AUDIO_UPLOAD_DIR + entry.get("stored_filename", "")
        result.append(entry)
    return result


def save_upload(file_storage, original_filename, ip=None, ssh_user=None, verbose=True):
    """
    file_storage: Werkzeug FileStorage (has .save(path)).
    ip: currently-connected Pepper IP, used to scp audio over. Video never
        needs it. If audio is uploaded with no ip, it's staged locally and
        marked unsynced -- the UI can retry via resync_media() once connected.
    Returns the manifest entry dict. Raises MediaError on validation failure.
    """
    kind = kind_for_filename(original_filename)
    if kind is None:
        raise MediaError(
            "Unsupported file type. Audio: %s. Video: %s."
            % (", ".join(AUDIO_EXTENSIONS), ", ".join(VIDEO_EXTENSIONS))
        )

    cleaned = _clean_filename(original_filename)
    if not cleaned or cleaned in (".", ".."):
        raise MediaError("Invalid filename")

    with _lock:
        stored_name = _unique_stored_name(kind, cleaned)
        local_path = os.path.join(_dir_for(kind), stored_name)
        file_storage.save(local_path)
        size = os.path.getsize(local_path)

        entry = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "original_filename": original_filename,
            "stored_filename": stored_name,
            "size": size,
            "uploaded_at": _now_iso(),
            "synced_to_pepper": False,
            "sync_error": None,
        }

        if kind == "audio":
            if ip:
                ok, err = _scp_to_pepper(local_path, stored_name, ip, ssh_user, verbose)
            else:
                ok, err = False, "Not connected to Pepper -- staged locally, use Resync once connected."
            entry["synced_to_pepper"] = ok
            entry["sync_error"] = err
        else:
            entry["synced_to_pepper"] = True  # served locally, nothing to sync

        data = _load_manifest()
        data["media"].append(entry)
        _save_manifest(data)

    return entry


def resync_media(media_id, ip, ssh_user=None, verbose=True):
    """Retry pushing an audio entry onto Pepper (e.g. after the earlier scp failed)."""
    with _lock:
        data = _load_manifest()
        entry = next((m for m in data["media"] if m.get("id") == media_id), None)
        if entry is None:
            raise MediaError("Unknown media id")
        if entry["kind"] != "audio":
            raise MediaError("Only audio is synced to Pepper")
        local_path = os.path.join(AUDIO_DIR, entry["stored_filename"])
        if not os.path.exists(local_path):
            raise MediaError("Local copy missing: %s" % entry["stored_filename"])
        ok, err = _scp_to_pepper(local_path, entry["stored_filename"], ip, ssh_user, verbose)
        entry["synced_to_pepper"] = ok
        entry["sync_error"] = err
        _save_manifest(data)
        return entry


def delete_media(media_id, ip=None, ssh_user=None, verbose=True):
    with _lock:
        data = _load_manifest()
        entry = next((m for m in data["media"] if m.get("id") == media_id), None)
        if entry is None:
            raise MediaError("Unknown media id")
        local_path = os.path.join(_dir_for(entry["kind"]), entry["stored_filename"])
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
        except OSError:
            _log("WARN", "Could not remove local file: %s" % local_path, verbose)
        if entry["kind"] == "audio" and ip:
            _ssh_remove(ip, ssh_user, PEPPER_AUDIO_UPLOAD_DIR + entry["stored_filename"], verbose)
        data["media"] = [m for m in data["media"] if m.get("id") != media_id]
        _save_manifest(data)
        return entry


def video_path(stored_filename):
    """Absolute local path for serving an uploaded video, or None if unknown/unsafe."""
    safe = os.path.basename(stored_filename or "")
    if not safe or safe != stored_filename:
        return None
    path = os.path.join(VIDEO_DIR, safe)
    return path if os.path.exists(path) else None
