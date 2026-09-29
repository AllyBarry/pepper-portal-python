# -*- coding: utf-8 -*-
"""Test doubles for NAOqi: no robot, no qi module needed."""
import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(SRC_DIR, "app")
for _p in (SRC_DIR, APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakeFuture(object):
    def __init__(self, result=None):
        self.result = result
        self.waited = False

    def value(self, timeout=None):
        self.waited = True
        return self.result


class FakeProxy(object):
    """Records every call as (service, method, args, async)."""

    def __init__(self, name, log, results=None):
        self._name = name
        self._log = log
        self._results = results or {}

    def __getattr__(self, method):
        def call(*args, **kwargs):
            is_async = bool(kwargs.get("_async"))
            self._log.append((self._name, method, args, is_async))
            result = self._results.get(method)
            if isinstance(result, Exception):
                raise result
            if callable(result):
                result = result(*args)
            return FakeFuture(result) if is_async else result
        return call


class FakeServices(object):
    """Service provider. `missing` names services that don't exist (e.g. offline tablet)."""

    def __init__(self, missing=(), results=None):
        self.calls = []
        self.missing = set(missing)
        self.results = results or {}

    def service(self, name):
        if name in self.missing:
            raise RuntimeError("Cannot find service '%s' in index" % name)
        return FakeProxy(name, self.calls, self.results.get(name))

    def methods(self):
        return [(s, m) for s, m, _, _ in self.calls]


class FakeShell(object):
    def __init__(self, outputs=None):
        self.commands = []
        self.outputs = outputs or {}

    def run(self, command):
        self.commands.append(command)
        for prefix, out in self.outputs.items():
            if command.startswith(prefix):
                if isinstance(out, Exception):
                    raise out
                return out
        return ""

    def run_with_stdin(self, command, stdin):
        self.commands.append(command)
        return ""
