# -*- coding: utf-8 -*-
"""
Dashboard and Pepper discovery: doctor.py, Jetson logs, a Jetson shell, and
Pepper's battery / health / NAOqi logs.

Everything Jetson-side goes through host_services/wifi_helper.py (native, on
the host): the leases file, docker, journalctl and the pty are all outside
this container. Pepper-side calls go through robot/ like every other route.
"""
import json

try:
    import urllib2 as _urlreq            # Py2
    from urllib import urlencode
except ImportError:                      # pragma: no cover
    import urllib.request as _urlreq     # Py3
    import urllib.error
    from urllib.parse import urlencode
    _urlreq.HTTPError = urllib.error.HTTPError

from flask import Blueprint, Response, jsonify, request

from .common import json_body, json_endpoint, robot_from
from .network_routes import WIFI_HELPER_BASE_URL, WIFI_HELPER_INSTALL, WIFI_HELPER_TOKEN

bp = Blueprint("dashboard_routes", __name__)

# Above the helper's 20s terminal long-poll.
TERMINAL_TIMEOUT_SECONDS = 30
DOCTOR_TIMEOUT_SECONDS = 200


def _call(path, args=None, payload=None, timeout=15, headers=None):
    """(status, raw JSON) from the host helper; raises if it can't be reached."""
    url = WIFI_HELPER_BASE_URL + path
    if args:
        url += "?" + urlencode(args)
    hdrs = {"Accept": "application/json"}
    hdrs.update(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if WIFI_HELPER_TOKEN:
        hdrs["X-Wifi-Helper-Token"] = WIFI_HELPER_TOKEN
    try:
        resp = _urlreq.urlopen(_urlreq.Request(url, data=body, headers=hdrs), timeout=timeout)
        return resp.getcode(), resp.read()
    except _urlreq.HTTPError as exc:
        return exc.code, exc.read()


def helper(path, args=None, payload=None, timeout=15, headers=None):
    """Forward to the host helper, passing its status code and JSON straight through."""
    try:
        status, raw = _call(path, args, payload, timeout, headers)
    except Exception as exc:
        return jsonify({
            "ok": False, "helper_missing": True,
            "error": "Host helper unreachable at %s (%s). Install it on the Jetson: %s"
                     % (WIFI_HELPER_BASE_URL, exc, WIFI_HELPER_INSTALL),
        }), 502
    if status == 404:
        # The portal knows this path, so the helper predates it.
        return jsonify({
            "ok": False, "helper_outdated": True,
            "error": "The host helper is running old code. On the Jetson run: "
                     "sudo systemctl restart pepper-wifi-helper",
        }), 502
    return Response(raw, status=status, mimetype="application/json")


# ---------------- Pepper discovery ----------------

def find_pepper_ip():
    """Pepper's current IP on pepper-ap (by PEPPER_MAC), or None."""
    try:
        status, raw = _call("/pepper", timeout=10)
        found = json.loads(raw.decode("utf-8")).get("pepper") if status == 200 else None
    except Exception:
        return None
    return found["ip"] if found and found.get("naoqi") else None


@bp.route("/api/pepper/discover", methods=["GET"])
def api_pepper_discover():
    """Devices on pepper-ap; `pepper` is the one with PEPPER_MAC (or the only NAOqi host)."""
    return helper("/pepper", timeout=10)


@bp.route("/api/pepper/link", methods=["GET"])
@json_endpoint
def api_pepper_link():
    """
    Pepper <-> Jetson Wi-Fi link for the top-bar signal meter. Signal comes from
    Pepper itself (SSH): the AP dongle's driver reports a dummy 0 dBm. Link
    speeds come from the AP (`iw station get`, via the host helper).
    """
    out = {"ok": True, "signal_dbm": None, "quality": None, "ap": None}
    try:
        signal = robot_from(request.args).network.wifi_signal()
        if signal:
            out.update(signal_dbm=signal["signal_dbm"], quality=signal["quality"], interface=signal["interface"])
        else:
            out["wired"] = True
    except Exception as exc:
        out["signal_error"] = str(exc)[-200:]
    try:
        status, raw = _call("/pepper/link", args={"ip": request.args.get("ip", "")}, timeout=5)
        if status == 200:
            out["ap"] = json.loads(raw.decode("utf-8"))
    except Exception:
        pass
    return jsonify(out)


@bp.route("/api/pepper/remember", methods=["POST"])
def api_pepper_remember():
    return helper("/pepper/remember", payload={"mac": json_body().get("mac")})


# ---------------- Jetson ----------------

@bp.route("/api/dashboard/doctor", methods=["GET"])
def api_dashboard_doctor():
    args = {"pepper_ip": request.args["ip"]} if request.args.get("ip") else None
    return helper("/doctor", args=args, timeout=DOCTOR_TIMEOUT_SECONDS)


@bp.route("/api/dashboard/log-sources", methods=["GET"])
def api_dashboard_log_sources():
    return helper("/logs/sources")


@bp.route("/api/dashboard/logs", methods=["GET"])
def api_dashboard_logs():
    return helper("/logs", args={"source": request.args.get("source", ""),
                                 "lines": request.args.get("lines", 300)})


@bp.route("/api/terminal/<action>", methods=["GET", "POST"])
def api_terminal(action):
    if action not in ("login", "open", "read", "write", "resize", "close"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    token = request.headers.get("X-Terminal-Token")
    return helper(
        "/terminal/" + action,
        args=request.args.to_dict(),
        payload=json_body() if request.method == "POST" else None,
        headers={"X-Terminal-Token": token} if token else None,
        timeout=TERMINAL_TIMEOUT_SECONDS,
    )


# ---------------- Pepper ----------------

@bp.route("/api/dashboard/pepper", methods=["GET"])
@json_endpoint
def api_dashboard_pepper():
    """Battery over NAOqi and uptime/memory/disk over SSH; either half may fail alone."""
    pepper = robot_from(request.args)
    out = {"ok": True}
    try:
        out["battery"] = pepper.system.battery()
        out["name"] = pepper.system.name()
        out["version"] = pepper.system.version()
    except Exception as exc:
        out["naoqi_error"] = str(exc)
    try:
        out["health"] = pepper.health.status()
    except Exception as exc:
        out["ssh_error"] = str(exc)
    return jsonify(out)


@bp.route("/api/dashboard/pepper-logs", methods=["GET"])
@json_endpoint
def api_dashboard_pepper_logs():
    """NAOqi log files on Pepper, and the tail of `file` (default: the newest)."""
    health = robot_from(request.args).health
    files = health.log_files()
    path = request.args.get("file") or (files[0]["path"] if files else None)
    lines = health.tail(path, request.args.get("lines", 300)) if path else []
    return jsonify({"ok": True, "files": files, "file": path, "lines": lines})
