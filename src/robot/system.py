# -*- coding: utf-8 -*-
from .base import Capability


class System(Capability):
    """Robot-level queries (ALSystem)."""

    def ping(self):
        return bool(self._service("ALSystem").ping())

    def version(self):
        return self._service("ALSystem").systemVersion()
