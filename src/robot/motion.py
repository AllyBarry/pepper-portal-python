# -*- coding: utf-8 -*-
from .base import Capability, call


class Motion(Capability):
    """Animations and motor state (ALAnimationPlayer, ALMotion)."""

    def run_animation(self, name, wait=True):
        return call(self._service("ALAnimationPlayer"), "run", name, wait=wait)

    def stop_animations(self):
        self._service("ALAnimationPlayer").stopAll()

    def wake(self):
        """Motors on / ready."""
        self._service("ALMotion").wakeUp()

    def rest(self):
        """Motors off / relaxed."""
        self._service("ALMotion").rest()

    def is_awake(self):
        motion = self._service("ALMotion")
        try:
            return bool(motion.robotIsWakeUp())
        except Exception:
            # Older images lack robotIsWakeUp(); infer from stiffness.
            try:
                return any(motion.getStiffnesses("Body"))
            except Exception:
                return False
