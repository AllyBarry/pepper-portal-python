#!/usr/bin/env python3
"""
Host-side tools behind the portal's Dashboard and its Pepper auto-discovery,
served by wifi_helper.py (which already runs natively as root under systemd).

    pepper_link()      Pepper's Wi-Fi signal as the AP sees it
    find_pepper()      who is on pepper-ap: DHCP leases + neighbour table,
                       each probed on NAOqi's port 9559. Pepper is known by
                       its MAC (PEPPER_MAC in .env) since its IP changes
                       whenever the lease does; remember_pepper() saves it.
    run_doctor()       doctor.py --json
    log_sources() /
    read_log()         docker container logs and systemd journals
    Terminals          a password-protected login shell in a pty

The shell is real: anyone with the password can run anything as
PEPPER_TERMINAL_USER (default jetson, never root). The password is
PORTAL_TERMINAL_PASSWORD in the repo's .env, re-read on every login so
changing it doesn't need a restart. With no password set the terminal is off.
"""
import base64
import fcntl
import grp
import hmac
import json
import os
import pty
import pwd
import re
import secrets
import signal
import socket
import struct
import subprocess
import termios
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(REPO_ROOT, ".env")
DOCTOR = os.path.join(REPO_ROOT, "doctor.py")

AP_IFACE = os.environ.get("PEPPER_AP_IFACE", "wlx088af19321e3")
LEASES_FILE = os.environ.get(
    "PEPPER_AP_LEASES", "/var/lib/NetworkManager/dnsmasq-%s.leases" % AP_IFACE)
NAOQI_PORT = 9559
PROBE_TIMEOUT = 1.0

TERMINAL_USER = os.environ.get("PEPPER_TERMINAL_USER", "jetson")
TERMINAL_IDLE_SECONDS = int(os.environ.get("PEPPER_TERMINAL_IDLE_SECONDS", "1800"))
LOGIN_TTL_SECONDS = 12 * 3600
# Output kept per terminal so a reloaded page can replay the screen.
SCROLLBACK_BYTES = 256 * 1024

# Journals offered next to the docker containers.
LOG_UNITS = ("pepper-wifi-helper", "NetworkManager", "docker")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


class LoginRequired(Exception):
    """No valid terminal login; the portal shows its password prompt."""


def read_env():
    """KEY=value pairs from the repo's .env (same rules as doctor.py)."""
    env = {}
    try:
        with open(ENV_FILE) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


# ---------------- Pepper discovery ----------------

def _leases():
    """{ip: {mac, hostname, expires}} from the AP's dnsmasq lease file."""
    out = {}
    try:
        with open(LEASES_FILE) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 4:
                    continue
                expires, mac, ip, hostname = parts[:4]
                out[ip] = {"mac": mac.lower(), "hostname": None if hostname == "*" else hostname,
                           "expires": int(expires) if expires.isdigit() else None}
    except OSError:
        pass  # missing, or not root: the neighbour table still finds a booted Pepper
    return out


def _neighbours():
    """{ip: {mac, state}} for pepper-ap from `ip neigh`."""
    out = {}
    proc = subprocess.run(["ip", "-o", "neigh", "show", "dev", AP_IFACE],
                          capture_output=True, text=True, timeout=5)
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts or ":" in parts[0]:
            continue  # IPv6
        mac = parts[parts.index("lladdr") + 1].lower() if "lladdr" in parts else None
        out[parts[0]] = {"mac": mac, "state": parts[-1]}
    return out


def _naoqi_open(ip):
    try:
        socket.create_connection((ip, NAOQI_PORT), PROBE_TIMEOUT).close()
        return True
    except OSError:
        return False


def find_pepper():
    """
    Every device on pepper-ap (naoqi=True for those answering on 9559), and
    `pepper`: the device with PEPPER_MAC, or -- when no MAC is saved yet --
    the only NAOqi host, if there is exactly one.
    """
    leases = _leases()
    neigh = _neighbours()
    devices = {}
    for ip in set(leases) | set(neigh):
        lease = leases.get(ip, {})
        n = neigh.get(ip, {})
        devices[ip] = {
            "ip": ip,
            "mac": lease.get("mac") or n.get("mac"),
            "hostname": lease.get("hostname"),
            "leased": ip in leases,
            "state": n.get("state"),
        }
    threads = []
    for dev in devices.values():
        t = threading.Thread(target=lambda d=dev: d.update(naoqi=_naoqi_open(d["ip"])))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    found = sorted(devices.values(), key=lambda d: (not d["naoqi"], d["ip"]))
    saved_mac = read_env().get("PEPPER_MAC", "").lower() or None
    if saved_mac:
        pepper = next((d for d in found if d["mac"] == saved_mac), None)
    else:
        naoqi = [d for d in found if d["naoqi"]]
        pepper = naoqi[0] if len(naoqi) == 1 else None
    return {"interface": AP_IFACE, "leases_readable": os.access(LEASES_FILE, os.R_OK),
            "pepper_mac": saved_mac, "pepper": pepper, "devices": found}


def pepper_link(ip=None):
    """
    Pepper's Wi-Fi link as the AP sees it (`iw station dump`): signal dBm,
    bitrates, idle time. Pepper is PEPPER_MAC, else whoever holds `ip`.
    signal is None when the driver doesn't report it.
    """
    mac = read_env().get("PEPPER_MAC", "").lower() or None
    if not mac and ip:
        mac = (_neighbours().get(ip) or {}).get("mac") or (_leases().get(ip) or {}).get("mac")
    if not mac:
        return {"mac": None, "associated": False}
    proc = subprocess.run(["iw", "dev", AP_IFACE, "station", "get", mac],
                          capture_output=True, text=True, timeout=5)
    if proc.returncode != 0:
        return {"mac": mac, "associated": False}  # not on pepper-ap right now
    fields = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep:
            fields[key.strip()] = value.strip()

    def first_number(key):
        match = re.match(r"-?\d+(\.\d+)?", fields.get(key, ""))
        return float(match.group(0)) if match else None

    signal = first_number("signal avg")
    if signal is None:
        signal = first_number("signal")
    if signal == 0:
        signal = None  # out-of-tree drivers (the Mercusys MA14H) report a dummy 0 dBm
    return {
        "mac": mac,
        "associated": True,
        "signal_dbm": int(signal) if signal is not None else None,
        "tx_mbps": first_number("tx bitrate"),
        "rx_mbps": first_number("rx bitrate"),
        "inactive_ms": first_number("inactive time"),
        "connected_s": first_number("connected time"),
    }


def remember_pepper(mac):
    """Save PEPPER_MAC in .env (edited in place so it keeps its owner)."""
    mac = (mac or "").strip().lower()
    if not MAC_RE.match(mac):
        raise ValueError("Not a MAC address: %r" % mac)
    try:
        with open(ENV_FILE) as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        lines = []
    entry = "PEPPER_MAC=" + mac
    for i, line in enumerate(lines):
        if line.strip().startswith("PEPPER_MAC="):
            lines[i] = entry
            break
    else:
        lines.append(entry)
    with open(ENV_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return mac


# ---------------- doctor + logs ----------------

def run_doctor(pepper_ip=None, timeout=180):
    args = ["python3", DOCTOR, "--json"]
    if pepper_ip:
        args += ["--pepper-ip", pepper_ip]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT)
    try:
        report = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-600:] or "doctor.py printed no JSON")
    return report


def log_sources():
    sources = []
    proc = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}"],
                          capture_output=True, text=True, timeout=10)
    rows = [line.partition("\t")[::2] for line in proc.stdout.splitlines() if line.strip()]
    for name, state in sorted(rows, key=lambda r: (r[1] != "running", r[0])):
        sources.append({"id": "docker:" + name, "label": name, "kind": "container", "state": state})
    for unit in LOG_UNITS:
        sources.append({"id": "unit:" + unit, "label": unit, "kind": "journal", "state": None})
    return sources


def read_log(source, lines=300):
    kind, _, name = (source or "").partition(":")
    if not SAFE_NAME.match(name):
        raise ValueError("Bad log source %r" % source)
    lines = max(10, min(2000, int(lines)))
    if kind == "docker":
        cmd = ["docker", "logs", "--timestamps", "--tail", str(lines), name]
    elif kind == "unit":
        cmd = ["journalctl", "-u", name, "-n", str(lines), "-o", "short-iso", "--no-pager"]
    else:
        raise ValueError("Bad log source %r" % source)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    text = proc.stdout.decode("utf-8", "replace")
    return text.splitlines()[-lines:]


# ---------------- terminal ----------------

class Terminal(object):
    """One login shell in a pty, running as TERMINAL_USER."""

    def __init__(self, cols=100, rows=30):
        user = pwd.getpwnam(TERMINAL_USER)
        # Resolved before fork: the child of a threaded process should only exec.
        groups = os.getgrouplist(user.pw_name, user.pw_gid)
        env = {
            "HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name,
            "SHELL": user.pw_shell or "/bin/bash", "TERM": "xterm-256color",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        shell = env["SHELL"]
        pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                if os.getuid() != user.pw_uid:
                    os.setgroups(groups)
                    os.setgid(user.pw_gid)
                    os.setuid(user.pw_uid)
                os.chdir(REPO_ROOT if os.access(REPO_ROOT, os.X_OK) else user.pw_dir)
                os.execve(shell, [shell, "-l"], env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.buf = bytearray()
        self.base = 0          # stream offset of buf[0]
        self.alive = True
        self.last_used = time.time()
        self.cond = threading.Condition()
        self.resize(cols, rows)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                chunk = b""
            with self.cond:
                if not chunk:
                    self.alive = False
                    self.cond.notify_all()
                    break
                self.buf += chunk
                if len(self.buf) > SCROLLBACK_BYTES:
                    drop = len(self.buf) - SCROLLBACK_BYTES
                    del self.buf[:drop]
                    self.base += drop
                self.cond.notify_all()
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass

    def read(self, offset, wait):
        """(bytes from offset, next offset, alive); waits up to `wait`s for new output."""
        self.last_used = time.time()
        with self.cond:
            end = self.base + len(self.buf)
            if offset >= end and self.alive and wait > 0:
                self.cond.wait(wait)
                end = self.base + len(self.buf)
            start = max(offset, self.base)
            data = bytes(self.buf[start - self.base:]) if start < end else b""
            return data, end, self.alive

    def write(self, data):
        self.last_used = time.time()
        os.write(self.fd, data)

    def resize(self, cols, rows):
        cols, rows = max(20, min(500, int(cols))), max(5, min(200, int(rows)))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self):
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


class Terminals(object):
    """Login tokens and open terminals. All state is in memory: a restart logs everyone out."""

    def __init__(self):
        self.lock = threading.Lock()
        self.logins = {}     # token -> expiry
        self.sessions = {}   # sid -> Terminal
        threading.Thread(target=self._reap, daemon=True).start()

    @staticmethod
    def enabled():
        return bool(os.environ.get("PORTAL_TERMINAL_PASSWORD") or read_env().get("PORTAL_TERMINAL_PASSWORD"))

    def login(self, password):
        expected = os.environ.get("PORTAL_TERMINAL_PASSWORD") or read_env().get("PORTAL_TERMINAL_PASSWORD")
        if not expected:
            raise LoginRequired("Terminal disabled: set PORTAL_TERMINAL_PASSWORD in .env")
        if not hmac.compare_digest((password or "").encode("utf-8"), expected.encode("utf-8")):
            time.sleep(1)  # slow down guessing
            raise LoginRequired("Wrong password")
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.logins[token] = time.time() + LOGIN_TTL_SECONDS
        return token

    def check(self, token):
        with self.lock:
            expiry = self.logins.get(token or "")
        if not expiry or expiry < time.time():
            raise LoginRequired("Terminal login required")

    def open(self, cols, rows):
        term = Terminal(cols, rows)
        sid = secrets.token_urlsafe(12)
        with self.lock:
            self.sessions[sid] = term
        return sid

    def get(self, sid):
        with self.lock:
            term = self.sessions.get(sid or "")
        if term is None:
            raise KeyError("Terminal session ended")
        return term

    def close(self, sid):
        with self.lock:
            term = self.sessions.pop(sid or "", None)
        if term:
            term.close()

    def _reap(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self.lock:
                stale = [sid for sid, t in self.sessions.items()
                         if now - t.last_used > TERMINAL_IDLE_SECONDS
                         or (not t.alive and now - t.last_used > 60)]
                self.logins = {k: v for k, v in self.logins.items() if v > now}
            for sid in stale:
                self.close(sid)


def b64(data):
    return base64.b64encode(data).decode("ascii")
