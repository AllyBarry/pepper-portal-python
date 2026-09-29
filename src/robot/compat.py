# -*- coding: utf-8 -*-
"""
PepperController: the older call style (async_play=..., errors logged and
swallowed, returns a future or None), kept as a thin layer over Robot. It is
the performer the scene runner drives, and what old scripts import.
"""
from __future__ import print_function

import traceback

from .robot import Robot


def _log(msg, level="INFO", verbose=True):
    if not verbose:
        return
    try:
        if isinstance(msg, unicode):  # noqa: F821 (Py2 only)
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[CONTROLLER][%s] %s" % (level, msg))


class PepperController(object):
    def __init__(self, ip=None, port=9559, verbose=True, reset=False, robot=None):
        self.robot = robot or Robot(ip, port)
        self.ip = self.robot.ip
        self.port = self.robot.port
        self.verbose = verbose
        if reset:
            self.robot.disconnect()
        # Connect now so a bad IP fails here, as it always has.
        self.robot.system.ping()
        _log("Connected to Pepper at %s:%s" % (self.ip, self.port), "INFO", verbose)

    def _do(self, label, func, *args, **kwargs):
        async_play = kwargs.pop("async_play", False)
        _log("%s%r%s" % (label, args, " (async)" if async_play else ""), "INFO", self.verbose)
        try:
            return func(*args, wait=not async_play)
        except Exception as e:
            _log("%s failed: %s | %s" % (label, e.__class__.__name__, e), "ERROR", self.verbose)
            if self.verbose:
                print(traceback.format_exc())
            return None

    def say(self, text, async_play=True):
        return self._do("SAY", self.robot.speech.say, text, async_play=async_play)

    def play_animation(self, name, async_play=True):
        return self._do("ANIMATION", self.robot.motion.run_animation, name, async_play=async_play)

    def play_behavior(self, name, async_play=True):
        try:
            if not self.robot.behaviors.is_installed(name):
                _log("Behavior not installed: %s" % (name,), "WARN", self.verbose)
                return None
        except Exception as e:
            _log("Behavior lookup failed: %s | %s" % (e.__class__.__name__, e), "ERROR", self.verbose)
            return None
        return self._do("BEHAVIOR", self.robot.behaviors.run, name, async_play=async_play)

    def play_audio(self, path, async_play=True):
        norm = path.replace("\\", "/")
        if not norm.startswith("/"):
            _log("Audio path is not absolute on robot: %s (expected /home/nao/...)" % norm,
                 "WARN", self.verbose)
        return self._do("AUDIO", self.robot.audio.play_file, norm, async_play=async_play)

    def show_tablet(self, url):
        try:
            return self.robot.tablet.show_url(url)
        except Exception as e:
            _log("Tablet show failed: %s" % e, "WARN", self.verbose)
            return None

    def hide_tablet(self):
        try:
            return self.robot.tablet.hide()
        except Exception as e:
            _log("Tablet hide failed: %s" % e, "WARN", self.verbose)
            return None


def get_session(ip, port=9559):
    from .session import pool
    return pool.get(ip, port)


def reset_session(ip=None, port=9559, verbose=True):
    from .session import pool
    pool.discard(ip, port)
