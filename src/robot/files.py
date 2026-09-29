# -*- coding: utf-8 -*-
"""Pepper's sound folder, managed over SSH (ALAudioPlayer plays files from here)."""
import os

from .shell import shquote

WAV_ROOT = (
    os.environ.get("PEPPER_WAV_ROOT") or "/data/home/nao/.local/share/wav"
).rstrip("/") + "/"
# Where portal uploads go when no folder is given; scenes resolve a bare
# {"audiofile": "x.wav"} against it.
DEFAULT_FOLDER = "uploads"


def robot_path(rel):
    """Absolute path on Pepper of a file stored under WAV_ROOT."""
    return WAV_ROOT + rel


class RobotFiles(object):
    """List, copy and delete files under WAV_ROOT on Pepper."""

    def __init__(self, shell):
        self._shell = shell

    def list(self):
        """
        {rel: (size, int mtime)} for every non-hidden file under WAV_ROOT.

        Pepper ships BusyBox find, which lacks GNU -printf, so find is paired
        with stat (BusyBox stat does support -c).
        """
        root = shquote(WAV_ROOT)
        out = self._shell.run(
            "mkdir -p %s && cd %s && find . -type f ! -name '.*' "
            "-exec stat -c '%%n\t%%s\t%%Y' {} +" % (root, root)
        )
        files = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            rel, size, mtime = parts
            if rel.startswith("./"):
                rel = rel[2:]
            try:
                files[rel] = (int(size), int(mtime))
            except ValueError:
                continue
        return files

    def make_dirs(self, rels):
        """Create the parent folders on Pepper for these files."""
        dirs = sorted(set(robot_path(rel).rsplit("/", 1)[0] for rel in rels))
        if dirs:
            self._shell.run("mkdir -p " + " ".join(shquote(d) for d in dirs))

    def push(self, local_path, rel, mtime):
        """
        Stream the file into a hidden temp name, stamp it with the local mtime,
        then rename. Pepper never shows a half-written file, and the mtime stamp
        makes (size, mtime) comparisons independent of Pepper's clock (often no
        NTP on the AP). Piping through `cat` sidesteps scp's remote-path quoting,
        which differs between scp protocol versions for names with spaces.
        """
        dest = robot_path(rel)
        directory, name = dest.rsplit("/", 1)
        tmp = "%s/.upload-%s" % (directory, name)
        command = "cat > %s && touch -d @%d %s && mv -f %s %s" % (
            shquote(tmp), mtime, shquote(tmp), shquote(tmp), shquote(dest))
        with open(local_path, "rb") as source:
            self._shell.run_with_stdin(command, source)

    def delete(self, rel):
        self._shell.run("rm -f %s" % shquote(robot_path(rel)))
