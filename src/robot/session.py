# -*- coding: utf-8 -*-
"""
qi session cache -- the only module in the project that imports `qi`.

Every other module in robot/ talks to a *service provider*: any object with
`.service(name)`. A real qi.Session is one; tests pass a fake.
"""
from __future__ import print_function

import os
import threading
import traceback

try:
    import qi  # NAOqi Python SDK
    QI_IMPORT_ERROR = None
except Exception:
    qi = None
    QI_IMPORT_ERROR = traceback.format_exc()

from .errors import RobotError

CONNECT_TIMEOUT_MS = int(os.environ.get("PEPPER_CONNECT_TIMEOUT_MS", "12000"))


def _is_live(sess):
    """True if sess is connected. Older bindings lack isConnected(); assume live."""
    if not hasattr(sess, "isConnected"):
        return True
    try:
        return bool(sess.isConnected())
    except Exception:
        return False


def _close_quietly(sess):
    try:
        sess.close()
    except Exception:
        pass


def _qi_connect(ip, port, timeout_ms):
    if qi is None:
        raise RobotError(
            "NAOqi 'qi' module could not be imported. Ensure the SDK is installed, "
            "PYTHONPATH is set, and the container is running as linux/amd64.\n%s"
            % (QI_IMPORT_ERROR or "")
        )
    # A disconnected qi.Session keeps stale service-directory state ("Service
    # already in cache" on reconnect), so every connect starts with a fresh
    # object. The future bounds a dead network instead of hanging forever.
    sess = qi.Session()
    future = None
    try:
        future = sess.connect("tcp://%s:%s" % (ip, port), _async=True)
        future.value(timeout_ms)
    except Exception as exc:
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        _close_quietly(sess)
        raise RobotError("Could not connect to Pepper at %s:%s: %s" % (ip, port, exc))
    return sess


class SessionPool(object):
    """Thread-safe cache of one live session per ip:port."""

    def __init__(self, connect=_qi_connect, timeout_ms=CONNECT_TIMEOUT_MS):
        self._connect = connect
        self._timeout_ms = timeout_ms
        self._sessions = {}
        self._lock = threading.Lock()

    def get(self, ip, port=9559):
        key = "%s:%s" % (ip, port)
        # connect() is serialised: concurrent handshakes against one robot
        # race inside libqi.
        with self._lock:
            sess = self._sessions.get(key)
            if sess is not None and _is_live(sess):
                return sess
            if sess is not None:
                _close_quietly(sess)
                self._sessions.pop(key, None)
            sess = self._connect(ip, port, self._timeout_ms)
            self._sessions[key] = sess
            return sess

    def discard(self, ip=None, port=9559):
        """Drop one cached session (or all, with ip=None) so the next call reconnects."""
        with self._lock:
            if ip is None:
                stale = list(self._sessions.values())
                self._sessions.clear()
            else:
                stale = [self._sessions.pop("%s:%s" % (ip, port), None)]
        for sess in stale:
            if sess is not None:
                _close_quietly(sess)


pool = SessionPool()
