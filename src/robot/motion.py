# -*- coding: utf-8 -*-
import threading
import time

from .base import Capability, call

# Pepper's joint limits (radians), from the NAOqi 2.5 joint documentation.
HEAD_YAW_LIMIT = 2.0857
HEAD_PITCH_MIN, HEAD_PITCH_MAX = -0.7068, 0.6371
HANDS = {"left": "LHand", "right": "RHand"}
POSTURES = ("Stand", "StandInit", "StandZero", "Crouch")

# Teleop dead-man switch: drive() must be called again within this many seconds
# or the base stops. Covers a dropped phone, a closed tab, a crashed page.
DRIVE_TIMEOUT_SECONDS = 0.6

# Per-robot drive deadlines, module-level for the same reason as awareness's
# vision holds: Robot objects are short-lived, the watchdog outlives them.
_drive_deadlines = {}
_drive_lock = threading.Lock()


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


class Motion(Capability):
    """
    Everything that moves (ALMotion, ALAnimationPlayer, ALRobotPosture):

        animations     run_animation, stop_animations
        motors         wake, rest, is_awake
        base           drive (joystick), move_to (step), stop_move, is_moving, position
        head / joints  look, set_angles, angles
        hands          hand(side, open)
        posture        go_to_posture, posture
        safety         collision_protection, set_collision_protection
        idle motion    set_breathing

    Base moves are refused while the charging flap is open or an obstacle is
    too close, and NAOqi does not report that as an error: nothing happens.
    """

    def __init__(self, services, robot_key="local"):
        super(Motion, self).__init__(services)
        self._key = robot_key

    # ---- animations / motors ----

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

    # ---- base ----

    def drive(self, x, y, theta):
        """
        Joystick-style velocity, each -1..1 as a fraction of Pepper's top speed:
        x forward, y left, theta counter-clockwise. Stops by itself unless
        called again within DRIVE_TIMEOUT_SECONDS.
        """
        x, y, theta = (_clamp(v, -1.0, 1.0) for v in (x, y, theta))
        if x == 0 and y == 0 and theta == 0:
            self.stop_move()
            return
        self._service("ALMotion").moveToward(x, y, theta)
        self._arm_watchdog()

    def move_to(self, x, y, theta, wait=False):
        """Relative move: x/y metres (forward/left), theta radians (counter-clockwise)."""
        with _drive_lock:
            _drive_deadlines.pop(self._key, None)  # a step move isn't a joystick drive
        return call(self._service("ALMotion"), "moveTo", float(x), float(y), float(theta), wait=wait)

    def stop_move(self):
        with _drive_lock:
            _drive_deadlines.pop(self._key, None)
        self._service("ALMotion").stopMove()

    def is_moving(self):
        return bool(self._service("ALMotion").moveIsActive())

    def position(self):
        """[x, y, theta] in the odometry frame (metres, radians since boot)."""
        return [float(v) for v in self._service("ALMotion").getRobotPosition(False)]

    def _arm_watchdog(self):
        with _drive_lock:
            running = self._key in _drive_deadlines
            _drive_deadlines[self._key] = time.time() + DRIVE_TIMEOUT_SECONDS
        if not running:
            t = threading.Thread(target=self._watchdog, name="drive-watchdog-%s" % self._key)
            t.daemon = True
            t.start()

    def _watchdog(self):
        while True:
            time.sleep(0.1)
            with _drive_lock:
                deadline = _drive_deadlines.get(self._key)
                if deadline is None:
                    return  # stopped explicitly
                if time.time() < deadline:
                    continue
                _drive_deadlines.pop(self._key, None)
            try:
                self._service("ALMotion").stopMove()
            except Exception:
                pass
            return

    # ---- head / joints ----

    def look(self, yaw, pitch, speed=0.2):
        """Point the head: yaw left+, pitch down+ (radians, clamped to the joint limits)."""
        self.set_angles(
            ["HeadYaw", "HeadPitch"],
            [_clamp(yaw, -HEAD_YAW_LIMIT, HEAD_YAW_LIMIT), _clamp(pitch, HEAD_PITCH_MIN, HEAD_PITCH_MAX)],
            speed,
        )

    def set_angles(self, names, angles, speed=0.2):
        """Non-blocking joint move; speed is a 0..1 fraction of each joint's max."""
        self._service("ALMotion").setAngles(list(names), [float(a) for a in angles], _clamp(speed, 0.01, 1.0))

    def angles(self, names, use_sensors=True):
        return [float(a) for a in self._service("ALMotion").getAngles(list(names), use_sensors)]

    # ---- hands ----

    def hand(self, side, open_hand):
        name = HANDS.get(side)
        if name is None:
            raise ValueError("hand must be 'left' or 'right'")
        motion = self._service("ALMotion")
        motion.openHand(name) if open_hand else motion.closeHand(name)

    # ---- posture ----

    def go_to_posture(self, name, speed=0.5):
        if name not in POSTURES:
            raise ValueError("posture must be one of %s" % ", ".join(POSTURES))
        return bool(self._service("ALRobotPosture").goToPosture(name, _clamp(speed, 0.1, 1.0)))

    def posture(self):
        return self._service("ALRobotPosture").getPosture()

    # ---- safety / idle ----

    def collision_protection(self):
        """True when external collision protection is on for the base ("Move")."""
        return bool(self._service("ALMotion").getExternalCollisionProtectionEnabled("Move"))

    def set_collision_protection(self, enabled):
        """Turning this off lets Pepper drive into things. Off only while supervised."""
        self._service("ALMotion").setExternalCollisionProtectionEnabled("All", bool(enabled))

    def set_breathing(self, enabled):
        """Idle 'breathing' sway; off holds the body still while driving the head or arms."""
        self._service("ALMotion").setBreathEnabled("Body", bool(enabled))
