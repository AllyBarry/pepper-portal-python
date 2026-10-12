# -*- coding: utf-8 -*-
"""Pepper's own health and logs, for the portal's Dashboard (SSH)."""
from .shell import shquote

# Where NAOqi 2.x writes its logs; only files under these can be read.
LOG_DIRS = ("/var/log/naoqi", "/home/nao/.local/share/naoqi/log")

# One round trip; each section starts with a marker line.
STATUS_COMMAND = (
    "echo @uptime; cat /proc/uptime; "
    "echo @load; cat /proc/loadavg; "
    "echo @mem; free -m | grep -i '^mem'; "
    "echo @disk; df -P /home/nao | tail -1; "
    "echo @host; hostname"
)


def _sections(text):
    out, key = {}, None
    for line in text.splitlines():
        if line.startswith("@"):
            key = line[1:].strip()
            out[key] = []
        elif key:
            out[key].append(line.strip())
    return dict((k, " ".join(v).split()) for k, v in out.items())


class RobotHealth(object):
    def __init__(self, shell):
        self._shell = shell

    def status(self):
        """{"hostname", "uptime_s", "load", "mem_used_mb", "mem_total_mb", "disk_used_pct"}."""
        s = _sections(self._shell.run(STATUS_COMMAND))
        mem = s.get("mem", [])
        disk = s.get("disk", [])
        return {
            "hostname": (s.get("host") or [None])[0],
            "uptime_s": int(float(s["uptime"][0])) if s.get("uptime") else None,
            "load": s.get("load", [])[:3],
            "mem_total_mb": int(mem[1]) if len(mem) > 2 else None,
            "mem_used_mb": int(mem[2]) if len(mem) > 2 else None,
            "disk_used_pct": int(disk[4].rstrip("%")) if len(disk) > 4 else None,
        }

    def log_files(self):
        """[{"path", "size"}], most recently written first."""
        out = self._shell.run(
            "find %s -maxdepth 3 -type f -name '*.log' -exec stat -c '%%Y %%s %%n' {} + 2>/dev/null"
            " | sort -rn | head -40" % " ".join(LOG_DIRS))
        files = []
        for line in out.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3:
                files.append({"path": parts[2], "size": int(parts[1])})
        return files

    def tail(self, path, lines=300):
        if ".." in path or not any(path.startswith(d + "/") for d in LOG_DIRS):
            raise ValueError("Not a NAOqi log: %s" % path)
        lines = max(10, min(2000, int(lines)))
        return self._shell.run("tail -n %d %s" % (lines, shquote(path))).splitlines()
