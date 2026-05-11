# -*- coding: utf-8 -*-
import os
import traceback
try:
    import qi
except ImportError:
    qi = None

_sessions = {}

def _log(msg, level="INFO", verbose=True):
    if not verbose:
        return
    # ASCII-safe: avoid non-ascii symbols, encode defensively on Py2
    try:
        # Py2: ensure str for stdout
        if isinstance(msg, unicode):  # noqa
            msg = msg.encode("utf-8")
    except NameError:
        pass
    print("[CONTROLLER][%s] %s" % (level, msg))

def get_session(ip, port=9559):
    if qi is None:
        raise RuntimeError("NAOqi 'qi' module not found. Set PYTHONPATH to SDK.")
    key = "%s:%s" % (ip, port)
    sess = _sessions.get(key)
    if sess is None:
        sess = qi.Session()
        _sessions[key] = sess
    try:
        if hasattr(sess, "isConnected") and not sess.isConnected():
            sess.connect("tcp://{}:{}".format(ip, port))
        else:
            sess.connect("tcp://{}:{}".format(ip, port))
    except RuntimeError as e:
        if "already connected" not in str(e).lower():
            raise
    return sess

def reset_session(ip=None, port=9559, verbose=True):
    if ip is None:
        _sessions.clear()
        _log("All cached sessions reset", "INFO", verbose)
        return
    key = "%s:%s" % (ip, port)
    sess = _sessions.pop(key, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    _log("Session reset for %s" % key, "INFO", verbose)

class PepperController(object):
    def __init__(self, ip, port=9559, verbose=True, reset=False):
        self.ip = ip
        self.port = port
        self.verbose = verbose
        if reset:
            reset_session(ip, port, verbose=verbose)
        self.session = get_session(ip, port)
        # Fetch NAOqi services ONCE
        self.tts   = self.session.service("ALTextToSpeech")
        self.audio = self.session.service("ALAudioPlayer")
        self.anim  = self.session.service("ALAnimationPlayer")
        try:
            self.behavior = self.session.service("ALBehaviorManager")
        except Exception:
            self.behavior = None
        _log("Connected to Pepper at %s:%s" % (ip, port), "INFO", self.verbose)

    def _call(self, proxy, method, *args, **kwargs):
        async_play = kwargs.pop("async_play", False)
        try:
            func = getattr(proxy, method)
            if async_play:
                _log("Calling %s.%s%r with _async=True" %
                     (proxy.__class__.__name__, method, args), "INFO", self.verbose)
                result = func(*args, _async=True)
            else:
                _log("Calling %s.%s%r" %
                     (proxy.__class__.__name__, method, args), "INFO", self.verbose)
                result = func(*args)
            _log("%s.%s executed OK" % (proxy.__class__.__name__, method), "INFO", self.verbose)
            return result
        except Exception as e:
            _log("%s.%s failed: %s | %s" %
                 (proxy.__class__.__name__, method, e.__class__.__name__, e), "ERROR", self.verbose)
            if self.verbose:
                print(traceback.format_exc())
            return None

    # --- Public API ---
    def say(self, text, async_play=True):
        _log('Request SAY: "%s"' % (text,), "INFO", self.verbose)
        return self._call(self.tts, "say", text, async_play=async_play)

    def play_animation(self, name, async_play=True):
        _log("Request ANIMATION: %s" % (name,), "INFO", self.verbose)
        return self._call(self.anim, "run", name, async_play=async_play)

    def play_behavior(self, name, async_play=True):
        if self.behavior is None:
            _log("ALBehaviorManager not available", "WARN", self.verbose)
            return None
        try:
            if not self.behavior.isBehaviorInstalled(name):
                _log("Behavior not installed: %s" % (name,), "WARN", self.verbose)
                return None
        except Exception as e:
            _log("Behavior lookup failed: %s | %s" %
                 (e.__class__.__name__, e), "ERROR", self.verbose)
            if self.verbose:
                print(traceback.format_exc())
            return None
        _log("Request BEHAVIOR: %s" % (name,), "INFO", self.verbose)
        return self._call(self.behavior, "runBehavior", name, async_play=async_play)

    def play_audio(self, path, async_play=True):
        # Normalize to robot Linux-style path and warn if it looks local
        norm = path.replace("\\", "/")
        if not norm.startswith("/"):
            _log("Audio path is not absolute on robot: %s (expected /home/nao/...)" %
                 norm, "WARN", self.verbose)
        _log("Request AUDIO: %s" % norm, "INFO", self.verbose)
        return self._call(self.audio, "playFile", norm, async_play=async_play)
