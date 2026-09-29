# -*- coding: utf-8 -*-
from .base import Capability, call
from .errors import RobotUnavailable


class Behaviors(Capability):
    """Choregraphe behaviors installed on Pepper (ALBehaviorManager)."""

    def _manager(self):
        try:
            return self._service("ALBehaviorManager")
        except Exception as exc:
            raise RobotUnavailable("ALBehaviorManager is not available: %s" % exc)

    def list_installed(self):
        return list(self._manager().getInstalledBehaviors())

    def running(self):
        return list(self._manager().getRunningBehaviors())

    def is_installed(self, name):
        return bool(self._manager().isBehaviorInstalled(name))

    def start(self, name):
        """Fire and forget."""
        self._manager().startBehavior(name)

    def run(self, name, wait=True):
        """Run to completion (or return a future with wait=False)."""
        return call(self._manager(), "runBehavior", name, wait=wait)

    def stop_all(self):
        self._manager().stopAllBehaviors()
