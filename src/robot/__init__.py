# -*- coding: utf-8 -*-
"""
robot -- the only package that talks to Pepper.

    import robot
    pepper = robot.connect("192.168.50.226")
    pepper.speech.say("Hello")
    pepper.motion.run_animation("animations/Stand/Gestures/Hey_1")
    pepper.tablet.show_url("http://192.168.50.1:8081/tablet")

Nothing outside this package imports `qi` or opens SSH to the robot.
"""
from .errors import RobotError, RobotUnavailable
from .robot import Robot
from .scenes import SceneRunner, run_scene_file


def connect(ip, port=9559):
    """A Robot for this address. Connects lazily, on the first call that needs it."""
    return Robot(ip, port)
