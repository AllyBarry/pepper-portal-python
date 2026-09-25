#!/usr/bin/env python3
"""
Native host-side helper that lets the portal (running inside Docker) drive
the Jetson's wifi over `nmcli`, for the "choose wifi" screen on Pepper's
tablet (see src/app/templates/tablet_wifi.html).

This deliberately does NOT run in a container. Reconfiguring the host's own
wifi radio needs the host's network namespace and NetworkManager's D-Bus
socket -- giving the portal container that access (network_mode: host,
privileged, D-Bus mount) would also break the portal's use of Compose
service-name DNS to reach ollama/speech-to-text. A tiny native process,
started by systemd (see README: "Jetson wifi setup"), keeps that blast radius
out of the container entirely; the portal container reaches it over
host.docker.internal, already wired in docker-compose.yaml's extra_hosts.

Only ever targets one interface -- PEPPER_WIFI_IFACE. Default is wlP1p1s0,
this project's own Jetson's integrated wifi (see README: "Mercusys MA14H
Wi-Fi Adapter Setup on Jetson" / "Pepper Wi-Fi Access Point" for how that was
determined on this hardware -- `iw dev` names it per-machine, so check it
there before assuming the default holds elsewhere). That's the NIC meant for
the Jetson's own internet uplink; the Mercusys MA14H USB dongle
(wlx088af19321e3 on this Jetson) is a *different* interface, already
dedicated as the `pepper-ap` access point Pepper itself connects to at
192.168.50.1/24 -- this helper never touches it, and shouldn't be pointed at
it. If PEPPER_WIFI_ROUTE_METRIC is set, connect() also sets that route metric
on the newly-connected profile; left unset (the default), it leaves routing
alone, since the AP interface runs in NetworkManager "shared" mode and was
never a default-route competitor to begin with.

Binds 0.0.0.0 by default so host.docker.internal can reach it from inside
the container -- loopback-only would not be reachable that way. Since this
endpoint can reconfigure networking (more sensitive than the rest of the
portal, which already runs with no auth on a trusted robot LAN), set
PEPPER_WIFI_HELPER_TOKEN to require a matching X-Wifi-Helper-Token header;
leave it unset for a quick test on a private network.
"""
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("PEPPER_WIFI_HELPER_HOST", "0.0.0.0")
PORT = int(os.environ.get("PEPPER_WIFI_HELPER_PORT", "8766"))
IFACE = os.environ.get("PEPPER_WIFI_IFACE", "wlP1p1s0")
ROUTE_METRIC = os.environ.get("PEPPER_WIFI_ROUTE_METRIC", "").strip() or None
AUTH_TOKEN = os.environ.get("PEPPER_WIFI_HELPER_TOKEN", "").strip() or None
NMCLI_TIMEOUT = int(os.environ.get("PEPPER_WIFI_NMCLI_TIMEOUT", "25"))
MAX_BODY_BYTES = 8 * 1024


def run_nmcli(args, timeout=NMCLI_TIMEOUT):
    proc = subprocess.run(
        ["nmcli"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def unescape_terse(field):
    # nmcli -t escapes ':' (the field delimiter) and '\' as '\:' / '\\'.
    return field.replace("\\:", ":").replace("\\\\", "\\")


def split_terse_line(line):
    return [unescape_terse(f) for f in re.split(r"(?<!\\):", line)]


def scan_networks():
    rc, out, err = run_nmcli([
        "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE",
        "device", "wifi", "list", "ifname", IFACE, "--rescan", "yes",
    ])
    if rc != 0:
        raise RuntimeError(err.strip() or "nmcli scan failed (rc=%d)" % rc)

    best = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = split_terse_line(line)
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts[0], parts[1], parts[2], parts[3]
        if not ssid:
            continue  # hidden network, nothing to show a tap target for
        try:
            signal_num = int(signal)
        except ValueError:
            signal_num = 0
        existing = best.get(ssid)
        if existing is None or signal_num > existing["signal"]:
            best[ssid] = {
                "ssid": ssid,
                "signal": signal_num,
                "secure": bool(security and security != "--"),
                "in_use": in_use == "*",
            }
    networks = sorted(best.values(), key=lambda n: n["signal"], reverse=True)
    return networks


def interface_status():
    rc, out, err = run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if rc != 0:
        raise RuntimeError(err.strip() or "nmcli status failed (rc=%d)" % rc)
    for line in out.splitlines():
        parts = split_terse_line(line)
        if len(parts) >= 4 and parts[0] == IFACE:
            return {"device": parts[0], "type": parts[1], "state": parts[2], "connection": parts[3] or None}
    return {"device": IFACE, "type": None, "state": "unknown", "connection": None}


def connect(ssid, password):
    args = ["device", "wifi", "connect", ssid, "ifname", IFACE]
    if password:
        args += ["password", password]
    rc, out, err = run_nmcli(args, timeout=NMCLI_TIMEOUT)
    if rc != 0:
        raise RuntimeError(err.strip() or out.strip() or "nmcli connect failed (rc=%d)" % rc)

    metric_warning = None
    if ROUTE_METRIC:
        try:
            status = interface_status()
            conn_name = status.get("connection")
            if conn_name:
                run_nmcli(["connection", "modify", conn_name, "ipv4.route-metric", ROUTE_METRIC])
                run_nmcli(["connection", "up", conn_name])
        except Exception as exc:  # connected either way; the metric is a preference, not required
            metric_warning = str(exc)

    return {"ok": True, "output": out.strip(), "route_metric_warning": metric_warning}


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PepperWifiHelper/1.0"

    def log_message(self, message, *args):
        print("%s - %s" % (self.address_string(), message % args), flush=True)

    def respond(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if AUTH_TOKEN is None:
            return True
        return self.headers.get("X-Wifi-Helper-Token") == AUTH_TOKEN

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"ok": True, "interface": IFACE})
            return
        if not self.authorized():
            self.respond(401, {"ok": False, "error": "Missing or invalid X-Wifi-Helper-Token"})
            return
        if self.path == "/status":
            try:
                self.respond(200, {"ok": True, "status": interface_status()})
            except Exception as exc:
                self.respond(500, {"ok": False, "error": str(exc)})
            return
        if self.path == "/networks":
            try:
                self.respond(200, {"ok": True, "networks": scan_networks()})
            except Exception as exc:
                self.respond(500, {"ok": False, "error": str(exc)})
            return
        self.respond(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        if not self.authorized():
            self.respond(401, {"ok": False, "error": "Missing or invalid X-Wifi-Helper-Token"})
            return
        if self.path != "/connect":
            self.respond(404, {"ok": False, "error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY_BYTES:
                raise ValueError("Request body must be between 1 byte and %d bytes" % MAX_BODY_BYTES)
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            ssid = (payload.get("ssid") or "").strip()
            password = payload.get("password") or ""
            if not ssid:
                raise ValueError("'ssid' is required")
        except Exception as exc:
            self.respond(400, {"ok": False, "error": str(exc)})
            return

        try:
            self.respond(200, connect(ssid, password))
        except Exception as exc:
            self.respond(500, {"ok": False, "error": str(exc)})


if __name__ == "__main__":
    print(
        "Pepper wifi helper listening on http://%s:%s (interface %s%s)"
        % (HOST, PORT, IFACE, ", token required" if AUTH_TOKEN else ""),
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
