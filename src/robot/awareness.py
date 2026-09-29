# -*- coding: utf-8 -*-
import threading

from .base import Capability

# Awareness state saved by hold_for_vision(True), per robot, so release restores
# exactly what was on before. Module-level: Robot objects are cheap and
# short-lived, the hold outlives any one of them.
_vision_holds = {}
_vision_lock = threading.Lock()


class Awareness(Capability):
    """Autonomous Life and head tracking (ALAutonomousLife, ALBasicAwareness)."""

    def __init__(self, services, robot_key):
        super(Awareness, self).__init__(services)
        self._key = robot_key

    def life_state(self):
        """(animation_enabled, state_name). State is disabled/solitary/interactive/safeguard."""
        try:
            state = self._service("ALAutonomousLife").getState()
            return state != "disabled", state
        except Exception:
            try:
                enabled = bool(self._service("ALBasicAwareness").isEnabled())
                return enabled, "basic_awareness_%s" % ("on" if enabled else "off")
            except Exception:
                return False, "unknown"

    def set_animation_mode(self, enabled):
        """'solitary' Autonomous Life gives idle animations; 'disabled' stops them."""
        try:
            self._service("ALAutonomousLife").setState("solitary" if enabled else "disabled")
        except Exception:
            # Some images prefer the BasicAwareness toggle.
            try:
                self._service("ALBasicAwareness").setEnabled(bool(enabled))
            except Exception:
                pass

    def hold_for_vision(self, active):
        """Suspend face tracking so the camera holds still; restore prior state on release."""
        life = self._service("ALAutonomousLife")
        awareness = self._service("ALBasicAwareness")
        with _vision_lock:
            if active:
                if self._key not in _vision_holds:
                    _vision_holds[self._key] = {
                        "life_enabled": bool(life.getAutonomousAbilityEnabled("BasicAwareness")),
                        "awareness_enabled": bool(awareness.isEnabled()),
                    }
                life.setAutonomousAbilityEnabled("BasicAwareness", False)
                awareness.setEnabled(False)
                return _vision_holds[self._key]

            previous = _vision_holds.pop(self._key, None)
            if previous is not None:
                awareness.setEnabled(previous["awareness_enabled"])
                life.setAutonomousAbilityEnabled("BasicAwareness", previous["life_enabled"])
            return previous

    def tracking_state(self):
        return {
            "basic_awareness_enabled": bool(self._service("ALBasicAwareness").isEnabled()),
            "autonomous_ability_enabled": bool(
                self._service("ALAutonomousLife").getAutonomousAbilityEnabled("BasicAwareness")
            ),
        }
