# -*- coding: utf-8 -*-
"""
SSH into Pepper -- for what NAOqi can't do: copying files onto the robot and
running shell checks there.

The container's key lives in /home/user/.ssh (pepper-ssh-key volume; README:
"Media uploads (SSH key setup)"). -i is passed explicitly because ssh looks
for default identities under the effective user's real home (/root/.ssh for
root), not $HOME. Host key checking is off: one robot on a private AP whose
host key changes when it is re-imaged.
"""
import os
import subprocess

SSH_USER = os.environ.get("PEPPER_SSH_USER", "nao")
SSH_KEY_PATH = os.environ.get("PEPPER_SSH_KEY", "/home/user/.ssh/id_ed25519")
SSH_CONNECT_TIMEOUT = int(os.environ.get("PEPPER_SSH_TIMEOUT", "10"))
SSH_OPTS = [
    "-i", SSH_KEY_PATH,
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=%d" % SSH_CONNECT_TIMEOUT,
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2",
]


def shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def error_text(exc):
    """Readable tail of a failed ssh call's output."""
    output = getattr(exc, "output", None)
    if output:
        try:
            return output.decode("utf-8", "replace").strip()[-400:]
        except Exception:
            return str(output)[-400:]
    return str(exc)


class RobotShell(object):
    """Runs commands on Pepper over SSH."""

    def __init__(self, ip):
        self.ip = ip

    def _argv(self, command):
        return ["ssh"] + SSH_OPTS + ["%s@%s" % (SSH_USER, self.ip), command]

    def run(self, command):
        """Run a command; returns its output as text. Raises CalledProcessError."""
        out = subprocess.check_output(self._argv(command), stderr=subprocess.STDOUT)
        if not isinstance(out, str):
            out = out.decode("utf-8", "replace")
        return out

    def run_with_stdin(self, command, stdin):
        """Run a command fed from an open file; raises CalledProcessError on failure."""
        proc = subprocess.Popen(
            self._argv(command), stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = proc.communicate()[0]
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "ssh", output)
        return output
