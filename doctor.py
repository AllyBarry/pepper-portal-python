#!/usr/bin/env python3
"""Pepper portal doctor - progressive health checks with remediation hints.

Runs on the Jetson host. Stdlib only, no pip installs. Meant to answer the
question "why isn't X working right now?" and be safe to run any time.

Usage:
    python3 doctor.py                    # run everything
    python3 doctor.py --only ollama stt  # run one or more groups
    python3 doctor.py --list             # list group names
    python3 doctor.py --json             # machine-readable output

Exit code = number of FAIL results (0 = clean).
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(REPO_ROOT, ".env")


# ---------------- result plumbing ----------------

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"

COLORS = {
    PASS: "\033[32m",   # green
    WARN: "\033[33m",   # yellow
    FAIL: "\033[31m",   # red
    SKIP: "\033[90m",   # grey
    "RESET": "\033[0m",
    "HEADER": "\033[1;36m",  # bold cyan
    "DIM": "\033[2m",
}


class Result:
    __slots__ = ("name", "status", "detail", "fix")

    def __init__(self, name, status, detail="", fix=""):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    def to_dict(self):
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


def use_colors():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text, key):
    if not use_colors():
        return text
    return "%s%s%s" % (COLORS[key], text, COLORS["RESET"])


def render_result(r):
    status = paint("%-4s" % r.status, r.status)
    line = "  [%s] %s" % (status, r.name)
    if r.detail:
        line += " - %s" % r.detail
    print(line)
    if r.fix and r.status in (FAIL, WARN):
        print("        " + paint("fix: " + r.fix, "DIM"))


def render_header(title):
    bar = "=" * max(4, 60 - len(title))
    print()
    print(paint("== %s %s" % (title, bar), "HEADER"))


# ---------------- shared helpers ----------------

def load_env():
    """Parse .env if present. Returns dict of KEY=value (last wins)."""
    env = {}
    try:
        with open(ENV_FILE, "r") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def run(cmd, timeout=10, check=False):
    """Run cmd, return (rc, stdout, stderr). Never raises on timeout/missing."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=check,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, "", "%s not installed" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss" % timeout


def http_json(url, timeout=5, data=None, method="GET"):
    """GET/POST JSON; returns (status, body dict or None, err str)."""
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(data).encode("utf-8")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body), ""
            except ValueError:
                return resp.status, None, "non-JSON body"
    except urllib.error.HTTPError as e:
        return e.code, None, "HTTP %d" % e.code
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        return 0, None, str(e.reason if hasattr(e, "reason") else e)
    except Exception as e:
        return 0, None, str(e)


# ---------------- host ----------------

def check_host():
    out = []
    rc, sysout, _ = run(["uname", "-srmo"])
    out.append(Result("uname", PASS if rc == 0 else FAIL, sysout.strip() or "unknown"))

    # RAM
    try:
        with open("/proc/meminfo") as fh:
            meminfo = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in fh)}
        total_kb = int(meminfo["MemTotal"].split()[0])
        avail_kb = int(meminfo["MemAvailable"].split()[0])
        total_gb = total_kb / 1024 / 1024
        avail_gb = avail_kb / 1024 / 1024
        pct = 100.0 * avail_kb / total_kb
        status = PASS if avail_gb >= 2.0 else (WARN if avail_gb >= 1.0 else FAIL)
        fix = "close other processes or reboot; ollama especially needs contiguous memory" if status != PASS else ""
        out.append(Result(
            "memory",
            status,
            "%.1f / %.1f GiB available (%.0f%%)" % (avail_gb, total_gb, pct),
            fix=fix,
        ))
    except Exception as e:
        out.append(Result("memory", FAIL, str(e)))

    # Swap - roll every entry into totals so a Jetson's zram pool renders as one line.
    try:
        rc, so, _ = run(["swapon", "--show=SIZE,USED", "--bytes", "--noheadings"])
        if rc == 0 and so.strip():
            total = used = 0
            for line in so.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        total += int(parts[0]); used += int(parts[1])
                    except ValueError:
                        pass
            out.append(Result("swap", PASS, "%.1f / %.1f GiB used" % (used / 2**30, total / 2**30)))
        else:
            out.append(Result("swap", WARN, "no swap enabled", fix="sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"))
    except Exception as e:
        out.append(Result("swap", WARN, str(e)))

    # Disk under /var/lib/docker
    for path in ("/var/lib/docker", "/"):
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            pct_free = 100.0 * usage.free / usage.total
            status = PASS if free_gb >= 5 else (WARN if free_gb >= 1 else FAIL)
            out.append(Result(
                "disk %s" % path,
                status,
                "%.1f / %.1f GiB free (%.0f%%)" % (free_gb, total_gb, pct_free),
            ))
            break
        except FileNotFoundError:
            continue

    # Temperature (Jetson uses /sys/class/thermal/thermal_zone*)
    try:
        temps = []
        for i in range(0, 12):
            tz = "/sys/class/thermal/thermal_zone%d" % i
            if not os.path.exists(tz):
                break
            try:
                name = open(os.path.join(tz, "type")).read().strip()
                temp_c = int(open(os.path.join(tz, "temp")).read().strip()) / 1000.0
                if temp_c > 0:
                    temps.append((name, temp_c))
            except Exception:
                pass
        if temps:
            hottest = max(temps, key=lambda t: t[1])
            status = PASS if hottest[1] < 75 else (WARN if hottest[1] < 90 else FAIL)
            out.append(Result("temperature", status, "%s %.1f C (%d zones)" % (hottest[0], hottest[1], len(temps))))
    except Exception:
        pass

    return out


# ---------------- hardware ----------------

def check_hardware():
    out = []

    rc, so, _ = run(["lsusb"])
    if rc != 0:
        out.append(Result("lsusb", SKIP, so.strip()))
    else:
        interesting = [l for l in so.splitlines() if re.search(r"audio|webcam|realtek|logitech|generalplus|wireless|network", l, re.I)]
        detail = "%d USB devices; %d audio/webcam/wifi" % (len(so.strip().splitlines()), len(interesting))
        out.append(Result("USB devices (lsusb)", PASS, detail))

    # Capture (mic) devices
    rc, so, _ = run(["arecord", "-l"])
    if rc == 127:
        out.append(Result("arecord (ALSA capture)", WARN, "alsa-utils not installed on host", fix="sudo apt install alsa-utils"))
    elif rc != 0:
        out.append(Result("arecord -l", FAIL, so.strip() or "arecord failed"))
    else:
        cards = re.findall(r"^card \d+:.*device \d+:", so, re.M)
        usb_cards = [l for l in cards if "USB" in l or "BRIO" in l]
        status = PASS if usb_cards else WARN
        detail = "%d capture devices (%d look like USB mics)" % (len(cards), len(usb_cards))
        out.append(Result("USB microphones", status, detail, fix="plug in a USB mic" if not usb_cards else ""))

    # Webcam presence
    v4l = sorted([n for n in os.listdir("/dev") if n.startswith("video")])
    if v4l:
        out.append(Result("v4l devices", PASS, ", ".join("/dev/" + n for n in v4l)))
    else:
        out.append(Result("v4l devices", WARN, "no /dev/video* found"))

    # WiFi interfaces via ip link
    rc, so, _ = run(["ip", "-brief", "link"])
    if rc == 0:
        wifi = [l for l in so.splitlines() if re.match(r"^(wl|wlan|wlp)", l)]
        eth = [l for l in so.splitlines() if re.match(r"^(en|eth)", l)]
        pepper_dongle = [l for l in wifi if "UP" in l]
        out.append(Result(
            "network links",
            PASS if pepper_dongle or eth else WARN,
            "wifi=%d (up=%d) ethernet=%d" % (len(wifi), len(pepper_dongle), len(eth)),
            fix="check `ip link` output; enable wlan with `nmcli device connect <iface>`" if not pepper_dongle and not eth else "",
        ))
    else:
        out.append(Result("ip link", FAIL, so.strip()))

    return out


# ---------------- network ----------------

def check_network(env):
    out = []
    rc, so, _ = run(["ip", "-brief", "addr"])
    if rc == 0:
        addrs = []
        for line in so.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "UP":
                addrs.extend(a for a in parts[2:] if "." in a)
        out.append(Result(
            "IPv4 addresses",
            PASS if addrs else WARN,
            ", ".join(addrs) if addrs else "no UP interfaces have an IPv4 address",
        ))
    else:
        out.append(Result("ip addr", FAIL, so.strip()))

    # Default route
    rc, so, _ = run(["ip", "route", "show", "default"])
    out.append(Result(
        "default route",
        PASS if so.strip() else WARN,
        so.strip() or "no default route",
    ))

    # Internet reachability
    rc, _, _ = run(["ping", "-c", "1", "-W", "2", "1.1.1.1"])
    out.append(Result("internet (1.1.1.1)", PASS if rc == 0 else WARN, "reachable" if rc == 0 else "no ping response"))

    # Pepper reachability (optional; skip cleanly if not set)
    pepper_ip = env.get("PEPPER_IP") or os.environ.get("PEPPER_IP", "")
    if pepper_ip:
        rc, _, _ = run(["ping", "-c", "1", "-W", "2", pepper_ip])
        out.append(Result("Pepper ping (%s)" % pepper_ip, PASS if rc == 0 else FAIL, "reachable" if rc == 0 else "no response"))
        # NAOqi port
        try:
            with socket.create_connection((pepper_ip, 9559), timeout=2):
                out.append(Result("Pepper NAOqi :9559", PASS, "TCP open"))
        except Exception as e:
            out.append(Result("Pepper NAOqi :9559", FAIL, str(e), fix="verify Pepper is booted and the WiFi dongle bridges into Pepper's network"))
    else:
        out.append(Result("Pepper reachability", SKIP, "PEPPER_IP not set in .env"))

    return out


# ---------------- docker / compose ----------------

def check_docker():
    out = []
    rc, so, _ = run(["docker", "version", "--format", "{{.Server.Version}}"])
    if rc != 0:
        out.append(Result("docker daemon", FAIL, so.strip(), fix="sudo systemctl start docker"))
        return out
    out.append(Result("docker daemon", PASS, "server %s" % so.strip()))

    rc, so, _ = run(["docker", "compose", "config", "--quiet"], timeout=15)
    if rc != 0:
        out.append(Result("compose file parses", FAIL, so.strip()))
        return out
    out.append(Result("compose file parses", PASS))

    # Container status
    rc, so, _ = run([
        "docker", "compose", "ps", "--format",
        "{{.Name}}\t{{.State}}\t{{.Status}}",
    ], timeout=15)
    if rc != 0:
        out.append(Result("docker compose ps", FAIL, so.strip()))
        return out
    rows = [l for l in so.strip().splitlines() if l.strip()]
    if not rows:
        out.append(Result("compose containers", WARN, "none running", fix="docker compose up -d"))
    for row in rows:
        name, state, status_str = (row.split("\t") + ["", "", ""])[:3]
        healthy = "healthy" in status_str
        unhealthy = "unhealthy" in status_str
        starting = "health: starting" in status_str
        if state == "running" and healthy:
            r = Result(name, PASS, status_str)
        elif state == "running" and unhealthy:
            r = Result(name, FAIL, status_str, fix="docker logs %s --tail 50" % name)
        elif state == "running" and starting:
            r = Result(name, WARN, status_str)
        elif state == "running":
            r = Result(name, PASS, status_str)
        elif state == "exited":
            r = Result(name, FAIL, status_str, fix="docker logs %s --tail 50; docker compose up -d %s" % (name, name.replace("pepper_portal_", "").replace("pepper_portal", "pepper-portal") or name))
        elif state == "restarting":
            r = Result(name, FAIL, status_str, fix="docker logs %s --tail 100 (a crash loop is happening)" % name)
        else:
            r = Result(name, WARN, "%s | %s" % (state, status_str))
        out.append(r)

    return out


# ---------------- ollama ----------------

def check_ollama(env):
    out = []
    base = "http://127.0.0.1:11434"

    # Native ollama running alongside the container is a common source of
    # port-conflict / model-confusion problems.
    rc, so, _ = run(["pgrep", "-af", "ollama"])
    if rc == 0 and so.strip():
        # Filter out the container's process; those run under containerd-shim.
        native_lines = [l for l in so.splitlines() if "containerd" not in l and "ollama serve" in l]
        # We can't attribute PIDs to containers without a mount ns check; instead,
        # check systemd:
        rc2, syso, _ = run(["systemctl", "is-active", "ollama"])
        if rc2 == 0 and syso.strip() == "active":
            out.append(Result(
                "native ollama service",
                WARN,
                "systemd `ollama` unit is active - competes for port 11434 and VRAM",
                fix="sudo systemctl stop ollama && sudo systemctl disable ollama",
            ))
        else:
            out.append(Result("native ollama service", PASS, "not running as systemd unit"))

    # API reachability
    status, body, err = http_json(base + "/api/version", timeout=3)
    if status != 200:
        out.append(Result("ollama /api/version", FAIL, err or "HTTP %d" % status, fix="docker compose up -d ollama"))
        return out
    out.append(Result("ollama /api/version", PASS, "v%s" % (body or {}).get("version", "?")))

    # Models present
    status, body, err = http_json(base + "/api/tags", timeout=5)
    models = [m.get("name") for m in (body or {}).get("models", [])] if body else []
    out.append(Result(
        "ollama models",
        PASS if models else WARN,
        (", ".join(models) if models else "none pulled"),
        fix="docker compose run --rm ollama-pull" if not models else "",
    ))

    # OLLAMA_MODEL matches something we have
    target = env.get("OLLAMA_MODEL", "llama3.1:8b")
    if target not in models:
        out.append(Result(
            "OLLAMA_MODEL present",
            FAIL,
            "%s not pulled" % target,
            fix="docker exec pepper_portal_ollama ollama pull %s" % target,
        ))
    else:
        out.append(Result("OLLAMA_MODEL present", PASS, target))

    # Loaded models (memory pressure hint)
    status, body, err = http_json(base + "/api/ps", timeout=5)
    if status == 200 and body:
        loaded = body.get("models", [])
        out.append(Result(
            "ollama loaded",
            PASS,
            "%d in memory: %s" % (len(loaded), ", ".join(m.get("name", "?") for m in loaded)) if loaded else "none loaded (cold start on first request)",
        ))

    # Real load test: try a tiny generate on OLLAMA_MODEL. This is the one that
    # would have caught the NvMap OOM you kept hitting.
    if target in models:
        started = time.time()
        status, body, err = http_json(
            base + "/api/generate",
            timeout=90,
            method="POST",
            data={"model": target, "prompt": "hi", "stream": False, "options": {"num_predict": 1}},
        )
        elapsed = time.time() - started
        if status == 200 and body and body.get("response"):
            out.append(Result(
                "ollama load+infer",
                PASS,
                "'%s' -> %d chars in %.1fs" % (target, len(body["response"]), elapsed),
            ))
        else:
            # Give the crashed runner a beat to flush stderr before we read.
            time.sleep(1.5)
            hint = ""
            # `docker logs` sends container stderr to our stderr, so concat both.
            _, log_out, log_err = run(["docker", "logs", "pepper_portal_ollama", "--tail", "80"], timeout=5)
            logs = log_out + "\n" + log_err
            if "cudaMalloc failed: out of memory" in logs or "NvMap" in logs:
                hint = "GPU VRAM exhausted (Jetson NvMap). Try a smaller model (llama3.2:1b), lower OLLAMA_CONTEXT_LENGTH, or set OLLAMA_RUNTIME=runc in .env for CPU inference."
            elif "no such file" in logs.lower():
                hint = "model file missing on disk"
            elif "connection refused" in (err or "").lower():
                hint = "ollama not reachable; docker compose up -d ollama"
            fix = hint or "docker logs pepper_portal_ollama --tail 80"
            out.append(Result("ollama load+infer", FAIL, err or "HTTP %d" % status, fix=fix))

    # Show which runtime is configured
    runtime = env.get("OLLAMA_RUNTIME", "runc")
    out.append(Result(
        "OLLAMA_RUNTIME",
        PASS if runtime in ("nvidia", "runc") else WARN,
        runtime + (" (GPU)" if runtime == "nvidia" else " (CPU)"),
    ))

    return out


# ---------------- stt ----------------

def check_stt(env):
    out = []
    host_port = env.get("PEPPER_STT_HOST_PORT", "8765")
    base = "http://127.0.0.1:%s" % host_port

    status, body, err = http_json(base + "/status", timeout=3)
    if status != 200:
        out.append(Result("stt /status", FAIL, err or "HTTP %d" % status, fix="docker compose up -d speech-to-text"))
        return out
    engine = (body or {}).get("engine", "?")
    model = (body or {}).get("model", "?")
    ok = (body or {}).get("available")
    out.append(Result(
        "stt /status",
        PASS if ok else FAIL,
        "%s / %s / %s" % (engine, model, "available" if ok else "not available"),
        fix=(body or {}).get("error", "") if not ok else "",
    ))

    # Devices
    status, body, err = http_json(base + "/devices", timeout=5)
    if status != 200:
        out.append(Result("stt /devices", WARN, err or "HTTP %d" % status))
    else:
        arecord_ok = (body or {}).get("arecord_available")
        devices = (body or {}).get("devices", [])
        if not arecord_ok:
            out.append(Result("stt arecord", FAIL, "arecord missing", fix="docker compose build speech-to-text"))
        else:
            usb = [d for d in devices if "USB" in d.get("card_name", "") or "BRIO" in d.get("card_name", "")]
            out.append(Result(
                "stt capture devices",
                PASS if usb else WARN,
                "%d total, %d USB mics" % (len(devices), len(usb)),
                fix="check /dev/snd mount and audio group in compose; plug USB mic in" if not usb else "",
            ))

    # Round-trip: 1s capture from the first USB device (best-effort, warn only)
    status, body, err = http_json(base + "/devices", timeout=5)
    if status == 200 and body:
        devs = body.get("devices", [])
        usb = [d for d in devs if "USB" in d.get("card_name", "") or "BRIO" in d.get("card_name", "")]
        if usb:
            hw = usb[0]["hw"]
            started = time.time()
            status2, body2, err2 = http_json(
                base + "/capture",
                timeout=20,
                method="POST",
                data={"device": hw, "duration_seconds": 1},
            )
            elapsed = time.time() - started
            if status2 == 200 and (body2 or {}).get("ok"):
                out.append(Result(
                    "stt round-trip (%s)" % hw,
                    PASS,
                    "1s capture + transcribe in %.1fs" % elapsed,
                ))
            else:
                msg = (body2 or {}).get("error") if body2 else err2
                out.append(Result("stt round-trip (%s)" % hw, FAIL, msg or "unknown", fix="docker logs pepper_portal_stt --tail 40"))

    return out


# ---------------- portal ----------------

def check_portal(env):
    out = []
    port = env.get("PORTAL_HOST_PORT", "8081")
    base = "http://127.0.0.1:%s" % port

    status, _, err = http_json(base + "/", timeout=5)
    if status not in (200, 302):
        out.append(Result("portal /", FAIL, err or "HTTP %d" % status, fix="docker compose up -d pepper-portal"))
        return out
    out.append(Result("portal /", PASS, "HTTP %d" % status))

    status, body, err = http_json(base + "/api/services", timeout=15)
    if status != 200 or not body:
        out.append(Result("portal /api/services", WARN, err or "HTTP %d" % status))
    else:
        services = body.get("services", []) if isinstance(body, dict) else body
        if isinstance(services, dict):
            services = [dict(name=k, **(v if isinstance(v, dict) else {"detail": v})) for k, v in services.items()]
        for svc in services if isinstance(services, list) else []:
            name = svc.get("name", "?")
            ok = svc.get("ok", svc.get("available", False))
            detail = svc.get("detail") or svc.get("url", "")
            out.append(Result("portal svc: %s" % name, PASS if ok else FAIL, str(detail)))

    return out


# ---------------- driver ----------------

GROUPS = [
    ("host", check_host, "OS, memory, disk, thermals"),
    ("hardware", check_hardware, "USB, mics, webcam, network links"),
    ("network", lambda: check_network(load_env()), "interfaces, routes, Pepper reachability"),
    ("docker", check_docker, "daemon, compose, container health"),
    ("ollama", lambda: check_ollama(load_env()), "reachability, models, real load test"),
    ("stt", lambda: check_stt(load_env()), "engine, ALSA devices, 1s round-trip"),
    ("portal", lambda: check_portal(load_env()), "Flask reachability and internal services"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", metavar="GROUP", help="Run only these groups")
    parser.add_argument("--list", action="store_true", help="List group names")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of colored text")
    args = parser.parse_args()

    if args.list:
        for name, _, desc in GROUPS:
            print("%-10s %s" % (name, desc))
        return 0

    selected = [g for g in GROUPS if not args.only or g[0] in args.only]
    if not selected:
        print("No matching groups. Use --list to see options.", file=sys.stderr)
        return 2

    all_results = []
    for name, fn, desc in selected:
        if not args.json:
            render_header("%s - %s" % (name, desc))
        try:
            results = fn() or []
        except Exception as e:
            results = [Result(name, FAIL, "check raised: %s" % e)]
        for r in results:
            if not args.json:
                render_result(r)
        all_results.append({"group": name, "results": [r.to_dict() for r in results]})

    if args.json:
        json.dump({"groups": all_results}, sys.stdout, indent=2)
        sys.stdout.write("\n")

    fails = sum(1 for g in all_results for r in g["results"] if r["status"] == FAIL)
    warns = sum(1 for g in all_results for r in g["results"] if r["status"] == WARN)
    passes = sum(1 for g in all_results for r in g["results"] if r["status"] == PASS)
    if not args.json:
        print()
        print("Summary: %s %s %s" % (
            paint("%d pass" % passes, PASS),
            paint("%d warn" % warns, WARN),
            paint("%d fail" % fails, FAIL),
        ))
    return fails


if __name__ == "__main__":
    sys.exit(main())
