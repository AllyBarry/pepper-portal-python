# -*- coding: utf-8 -*-
"""Shared plumbing for the capability classes."""


def call(proxy, method, *args, **kwargs):
    """
    Call a NAOqi method. wait=True blocks until it finishes and returns the
    result; wait=False returns a qi.Future straight away (future.value() to
    join it later).
    """
    wait = kwargs.pop("wait", True)
    func = getattr(proxy, method)
    if wait:
        return func(*args)
    return func(*args, _async=True)


def to_str(text):
    """NAOqi's Python 2 bindings want UTF-8 byte strings, not unicode."""
    try:
        if isinstance(text, unicode):  # noqa: F821 (Py2 only)
            return text.encode("utf-8")
    except NameError:
        pass
    return text


class Capability(object):
    """One NAOqi responsibility, built on a service provider (`.service(name)`)."""

    def __init__(self, services):
        self._services = services

    def _service(self, name):
        return self._services.service(name)
