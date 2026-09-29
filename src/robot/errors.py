# -*- coding: utf-8 -*-
"""Exceptions raised by the robot package."""


class RobotError(Exception):
    """A call to Pepper failed."""


class RobotUnavailable(RobotError):
    """A part of the robot is missing or offline (e.g. the tablet)."""
