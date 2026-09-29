# -*- coding: utf-8 -*-
"""
media/ -- the portal's one media folder.

    media/<rel>   (repo root, bind-mounted into the portal container)
      audio (.wav/.mp3/.ogg) -> ssh -> /data/home/nao/.local/share/wav/<rel> on Pepper
      everything else (video, images, ...) stays on the Jetson and is served
      over HTTP at /media/<rel>, which is how the tablet shows it.

Audio has to be on the robot because ALAudioPlayer only plays local files.
The tablet can't read Pepper's disk, so videos and images are streamed from
the Jetson over the AP instead of filling Pepper's small disk.

Anything dropped on the portal (or copied into the folder by hand on the
Jetson) lands here first, then the sync worker pushes whatever audio Pepper
is missing. Uploads never wait on the robot, and a Pepper that is off or out
of range just leaves files queued until the next pass. All robot I/O goes
through robot.files (SSH).

The folder itself is the source of truth -- there is no manifest. Each pass
lists Pepper's wav tree over SSH and compares it by (size, mtime). Each push
stamps the remote copy with the local mtime, so the comparison doesn't depend
on Pepper's clock (which often has no NTP on the AP network).

Any file type is allowed; only AUDIO_EXTENSIONS are synced and offered for
playback. Files that exist on Pepper but not locally are shown read-only --
the portal only deletes files it manages.
"""
from __future__ import print_function

import os
import re
import sys
import threading
import time
import traceback
import uuid

_SRC_DIR_FOR_IMPORT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC_DIR_FOR_IMPORT not in sys.path:
    sys.path.insert(0, _SRC_DIR_FOR_IMPORT)

from robot.files import DEFAULT_FOLDER, WAV_ROOT as PEPPER_WAV_ROOT, robot_path  # noqa: E402,F401
from robot.robot import Robot  # noqa: E402
from robot.shell import error_text as _proc_error  # noqa: E402


def _log(level, msg):
    print("[MEDIA][%s] %s" % (level, msg))


_APP_DIR = os.path.dirname(os.path.abspath(__file__))           # .../src/app/pepper_core
_SRC_DIR = os.path.dirname(os.path.dirname(_APP_DIR))           # .../src (or /home/user/src)
# Sibling of src/: <repo>/media on the host, /home/user/media in the
# container (docker-compose.yaml bind-mounts one onto the other).
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or os.path.join(os.path.dirname(_SRC_DIR), "media")
SYNC_INTERVAL_SECONDS = int(os.environ.get("PEPPER_SYNC_INTERVAL", "60"))

AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg")
VIDEO_EXTENSIONS = (".mp4", ".webm", ".m4v", ".mov", ".ogv")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


class MediaError(Exception):
    """User-facing validation failure."""
    pass


# ---------------------------------------------------------------- paths

_SEGMENT_RE = re.compile(r"[^A-Za-z0-9 ._()+-]+")


def _clean_segment(segment):
    segment = _SEGMENT_RE.sub("_", segment or "").strip(" ")
    # No hidden files: dotfiles are reserved for in-progress uploads.
    segment = segment.lstrip(".")
    return segment


def clean_relpath(path, allow_empty=False):
    """Normalise a user-supplied path under media/. Raises MediaError."""
    raw = (path or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise MediaError("'..' is not allowed in paths")
    cleaned = [_clean_segment(p) for p in parts]
    if any(not c for c in cleaned):
        raise MediaError("Invalid path: %r" % path)
    if not cleaned and not allow_empty:
        raise MediaError("Empty path")
    return "/".join(cleaned)


def _local_path(rel):
    return os.path.join(MEDIA_ROOT, *rel.split("/"))


def _ext(rel):
    return os.path.splitext(rel)[1].lower()


def is_audio(rel):
    return _ext(rel) in AUDIO_EXTENSIONS


def is_video(rel):
    return _ext(rel) in VIDEO_EXTENSIONS


def is_image(rel):
    return _ext(rel) in IMAGE_EXTENSIONS


def kind(rel):
    if is_audio(rel):
        return "audio"
    if is_video(rel):
        return "video"
    if is_image(rel):
        return "image"
    return "other"


def _match_media_owner(path):
    # The container runs as root; hand files back to whoever owns the folder
    # on the host so they can be edited/deleted there without sudo.
    try:
        if os.geteuid() == 0:
            st = os.stat(MEDIA_ROOT)
            os.chown(path, st.st_uid, st.st_gid)
    except Exception:
        pass


def _makedirs(directory):
    """makedirs, chowning every directory it creates."""
    missing = []
    d = directory
    while not os.path.isdir(d):
        missing.append(d)
        d = os.path.dirname(d)
    for d in reversed(missing):
        try:
            os.mkdir(d)
        except OSError:
            if not os.path.isdir(d):
                raise
        _match_media_owner(d)


def _scan_local():
    """{rel: (size, int mtime)} for every regular, non-hidden file."""
    files = {}
    if not os.path.isdir(MEDIA_ROOT):
        return files
    for dirpath, dirnames, filenames in os.walk(MEDIA_ROOT):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, MEDIA_ROOT).replace(os.sep, "/")
            files[rel] = (st.st_size, int(st.st_mtime))
    return files


def _files(ip):
    return Robot(ip).files


# ---------------------------------------------------------------- sync worker

class _SyncState(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.ip = os.environ.get("PEPPER_IP", "").strip() or None
        self.remote = None            # {rel: (size, mtime)} from the last listing
        self.remote_ip = None         # which robot that listing came from
        self.remote_listed_at = None
        self.remote_error = None      # why the last listing failed
        self.errors = {}              # rel -> last push error
        self.queue = []               # rels still to push in the current pass
        self.current = None           # rel being pushed right now
        self.pass_total = 0
        self.pass_done = 0
        self.last_sync_at = None
        self.thread = None


_state = _SyncState()


def set_robot(ip):
    """Remember which Pepper to sync to. Called from any media API request."""
    ip = (ip or "").strip() or None
    if not ip:
        return
    with _state.lock:
        changed = ip != _state.ip
        _state.ip = ip
    if changed:
        request_sync()


def request_sync():
    _ensure_worker()
    _state.wake.set()


def _ensure_worker():
    with _state.lock:
        if _state.thread is not None and _state.thread.is_alive():
            return
        t = threading.Thread(target=_worker_loop, name="media-sync")
        t.daemon = True
        _state.thread = t
    t.start()


def _worker_loop():
    while True:
        _state.wake.wait(SYNC_INTERVAL_SECONDS)
        _state.wake.clear()
        try:
            _sync_pass()
        except Exception:
            _log("ERROR", "Sync pass crashed: %s" % traceback.format_exc())


def _needs_push(local_meta, remote_meta):
    return remote_meta is None or tuple(local_meta) != tuple(remote_meta)


def _sync_pass():
    with _state.lock:
        ip = _state.ip
    if not ip:
        return

    try:
        remote = _files(ip).list()
    except Exception as e:
        with _state.lock:
            _state.remote_error = _proc_error(e)
            if _state.remote_ip != ip:
                _state.remote = None
        _log("WARN", "Could not list Pepper (%s): %s" % (ip, _proc_error(e)))
        return

    local = _scan_local()
    todo = sorted(
        rel for rel, meta in local.items()
        if is_audio(rel) and _needs_push(meta, remote.get(rel))
    )
    with _state.lock:
        _state.remote = remote
        _state.remote_ip = ip
        _state.remote_listed_at = time.time()
        _state.remote_error = None
        # Errors for files that are gone or already fine are stale.
        _state.errors = dict((k, v) for k, v in _state.errors.items() if k in todo)
        _state.queue = list(todo)
        _state.pass_total = len(todo)
        _state.pass_done = 0

    if not todo:
        with _state.lock:
            _state.last_sync_at = time.time()
        return

    files = _files(ip)
    try:
        files.make_dirs(todo)
    except Exception as e:
        with _state.lock:
            for rel in todo:
                _state.errors[rel] = "mkdir on Pepper failed: %s" % _proc_error(e)
            _state.queue = []
        return

    for rel in todo:
        with _state.lock:
            if _state.ip != ip:
                break  # robot changed mid-pass; the next pass starts over
            _state.current = rel
        meta = None
        try:
            # Re-stat right before pushing: the file may have been replaced
            # or deleted since the scan.
            st = os.stat(_local_path(rel))
            meta = (st.st_size, int(st.st_mtime))
            files.push(_local_path(rel), rel, meta[1])
            err = None
            _log("INFO", "Pushed %s -> %s" % (rel, robot_path(rel)))
        except OSError:
            err = None  # deleted locally meanwhile; nothing to push
        except Exception as e:
            err = _proc_error(e)
            _log("ERROR", "Push failed for %s: %s" % (rel, err))
        with _state.lock:
            _state.current = None
            _state.pass_done += 1
            if rel in _state.queue:
                _state.queue.remove(rel)
            if err:
                _state.errors[rel] = err
            else:
                _state.errors.pop(rel, None)
                if meta is not None and _state.remote is not None:
                    _state.remote[rel] = meta

    with _state.lock:
        _state.queue = []
        _state.last_sync_at = time.time()


# ---------------------------------------------------------------- public API

def save_upload(file_storage, filename, folder=None):
    """
    Store an uploaded file under media/<folder>/<filename> and queue it
    for Pepper. Re-uploading the same name replaces the file (and re-syncs it).
    Returns the file's relative path.
    """
    name = _clean_segment(os.path.basename((filename or "").replace("\\", "/")))
    if not name:
        raise MediaError("Invalid filename")
    folder = clean_relpath(folder if folder is not None else DEFAULT_FOLDER, allow_empty=True)
    rel = (folder + "/" + name) if folder else name

    dest = _local_path(rel)
    _makedirs(os.path.dirname(dest))
    # Write to a hidden temp file, then rename: the sync worker skips
    # dotfiles, so it never pushes a half-written upload.
    tmp = os.path.join(os.path.dirname(dest), ".upload-%s" % uuid.uuid4().hex)
    try:
        file_storage.save(tmp)
        os.rename(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _match_media_owner(dest)
    with _state.lock:
        _state.errors.pop(rel, None)
    request_sync()
    return rel


def delete_file(rel):
    """Delete a managed file locally and on Pepper. Pepper-only files are refused."""
    rel = clean_relpath(rel)
    path = _local_path(rel)
    if not os.path.isfile(path):
        raise MediaError(
            "%s is not in media/ -- the portal only deletes files it manages" % rel
        )
    os.remove(path)
    with _state.lock:
        ip = _state.ip
        _state.errors.pop(rel, None)
    remote_error = None
    if not is_audio(rel):
        pass  # never copied to Pepper
    elif ip:
        try:
            _files(ip).delete(rel)
            with _state.lock:
                if _state.remote is not None:
                    _state.remote.pop(rel, None)
        except Exception as e:
            remote_error = _proc_error(e)
    else:
        remote_error = "No Pepper IP known; the copy on Pepper (if any) was left in place."
    return remote_error


def local_file(rel):
    """Absolute path of a file in media/ for HTTP serving, or None if unknown/unsafe."""
    try:
        rel = clean_relpath(rel)
    except MediaError:
        return None
    path = _local_path(rel)
    return path if os.path.isfile(path) else None


def status():
    """Everything the Media page needs: per-file state plus the worker's progress."""
    _ensure_worker()
    local = _scan_local()
    with _state.lock:
        remote = dict(_state.remote) if _state.remote is not None else None
        errors = dict(_state.errors)
        queue = set(_state.queue)
        current = _state.current
        info = {
            "ip": _state.ip,
            "media_root": MEDIA_ROOT,
            "pepper_root": PEPPER_WAV_ROOT,
            "default_folder": DEFAULT_FOLDER,
            "remote_listed_at": _state.remote_listed_at,
            "remote_error": _state.remote_error,
            "last_sync_at": _state.last_sync_at,
            "current": current,
            "pass_total": _state.pass_total,
            "pass_done": _state.pass_done,
        }

    files = []
    for rel in sorted(set(local) | set(remote or {})):
        l = local.get(rel)
        r = (remote or {}).get(rel)
        if l is None:
            state = "pepper_only"
        elif not is_audio(rel):
            state = "jetson_only"  # served to the tablet from the Jetson
        elif rel == current:
            state = "uploading"
        elif rel in errors:
            state = "failed"
        elif remote is None:
            state = "unknown"      # never managed to list Pepper
        elif not _needs_push(l, r):
            state = "synced"
        else:
            state = "queued"
        files.append({
            "path": rel,
            "folder": rel.rsplit("/", 1)[0] if "/" in rel else "",
            "name": rel.rsplit("/", 1)[-1],
            "size": (l or r)[0],
            "state": state,
            "error": errors.get(rel),
            "managed": l is not None,
            "audio": is_audio(rel),
            "kind": kind(rel),
            "robot_path": robot_path(rel) if is_audio(rel) or l is None else None,
        })
    info["busy"] = bool(current or queue) or any(f["state"] == "queued" for f in files)
    info["files"] = files
    info["folders"] = sorted(set(f["folder"] for f in files if f["folder"]) | {DEFAULT_FOLDER})
    return info
