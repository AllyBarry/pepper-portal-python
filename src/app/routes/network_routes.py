# -*- coding: utf-8 -*-
"""
The lab network: the Jetson's internal NIC (its internet uplink), the Pepper
AP, and whether each side can reach the internet.

    internet <- uplink NIC (wlP1p1s0) <- Jetson NAT <- pepper-ap (192.168.50.1) <- Pepper

Wi-Fi changes go through host_services/wifi_helper.py, a native systemd
service on the Jetson: nmcli needs the host's network namespace and
NetworkManager's D-Bus socket, which this container deliberately doesn't have.
"""
import json
import os
import socket
import time

try:
    import urllib2 as _urlreq            # Py2
except ImportError:                      # pragma: no cover
    import urllib.request as _urlreq     # Py3

from flask import Blueprint, jsonify, request

import portal_address

from .common import json_body, json_endpoint, robot_from

bp = Blueprint("network_routes", __name__)

WIFI_HELPER_BASE_URL = os.environ.get(
    "WIFI_HELPER_BASE_URL", "http://host.docker.internal:8767"
).rstrip("/")
WIFI_HELPER_TIMEOUT_SECONDS = int(os.environ.get("WIFI_HELPER_TIMEOUT_SECONDS", "20"))
WIFI_HELPER_TOKEN = os.environ.get("WIFI_HELPER_TOKEN", "").strip() or None
WIFI_HELPER_INSTALL = "sudo ./install/setup_wifi_helper.sh"
# ICMP is blocked upstream of the lab network, so "online" means a TCP
# connection to a public server succeeds.
INTERNET_PROBE = ("1.1.1.1", 443)


def wifi_helper_request(path, payload=None, timeout=None):
    """Call the native host-side wifi helper."""
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if WIFI_HELPER_TOKEN:
        headers["X-Wifi-Helper-Token"] = WIFI_HELPER_TOKEN
    req = _urlreq.Request(WIFI_HELPER_BASE_URL + path, data=body, headers=headers)
    raw = _urlreq.urlopen(req, timeout=timeout or WIFI_HELPER_TIMEOUT_SECONDS).read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def _helper_unreachable(exc):
    return jsonify({
        "ok": False,
        "helper_missing": True,
        "error": "Wi-Fi helper unreachable at %s (%s). Install it on the Jetson: %s"
                 % (WIFI_HELPER_BASE_URL, exc, WIFI_HELPER_INSTALL),
    }), 502


def jetson_internet():
    host, port = INTERNET_PROBE
    started = time.time()
    try:
        socket.create_connection((host, port), 4).close()
        return {"online": True, "error": None, "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"online": False, "error": str(exc), "latency_ms": None}


@bp.route("/api/wifi/status", methods=["GET"])
@json_endpoint
def api_wifi_status():
    try:
        return jsonify(wifi_helper_request("/status", timeout=8))
    except Exception as exc:
        return _helper_unreachable(exc)


@bp.route("/api/wifi/networks", methods=["GET"])
@json_endpoint
def api_wifi_networks():
    try:
        return jsonify(wifi_helper_request("/networks"))
    except Exception as exc:
        return _helper_unreachable(exc)


@bp.route("/api/wifi/connect", methods=["POST"])
@json_endpoint
def api_wifi_connect():
    data = json_body()
    ssid = (data.get("ssid") or "").strip()
    if not ssid:
        return jsonify({"ok": False, "error": "'ssid' is required"}), 400
    try:
        return jsonify(wifi_helper_request(
            "/connect", payload={"ssid": ssid, "password": data.get("password") or ""},
        ))
    except Exception as exc:
        return _helper_unreachable(exc)


@bp.route("/api/network/overview", methods=["GET"])
@json_endpoint
def api_network_overview():
    """Uplink + AP interface state, and internet reachability for the Jetson and Pepper."""
    try:
        helper = wifi_helper_request("/overview", timeout=8)
        helper_error = None if helper.get("ok") else helper.get("error")
    except Exception as exc:
        helper = {}
        helper_error = "Wi-Fi helper unreachable at %s (%s). Install it on the Jetson: %s" % (
            WIFI_HELPER_BASE_URL, exc, WIFI_HELPER_INSTALL)

    pepper = None
    ip = (request.args.get("ip") or "").strip()
    if ip:
        pepper = {"ip": ip, "internet": robot_from(request.args).network.internet()}

    return jsonify({
        "ok": True,
        "helper_error": helper_error,
        "uplink_interface": helper.get("uplink_interface"),
        "devices": helper.get("devices", []),
        "jetson_internet": jetson_internet(),
        "pepper": pepper,
        "tablet_base_url": portal_address.tablet_base_url(ip or None),
    })
