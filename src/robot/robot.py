# -*- coding: utf-8 -*-
from .audio import Audio
from .awareness import Awareness
from .behaviors import Behaviors
from .camera import Camera
from .files import RobotFiles
from .microphone import Microphone
from .motion import Motion
from .network import RobotNetwork
from .session import pool as default_pool
from .shell import RobotShell
from .speech import Speech
from .system import System
from .tablet import TabletDisplay


class _PooledServices(object):
    """Service provider that connects on first use, through the shared pool."""

    def __init__(self, pool, ip, port):
        self._pool = pool
        self._ip = ip
        self._port = port

    def service(self, name):
        return self._pool.get(self._ip, self._port).service(name)


class Robot(object):
    """
    The one way to control Pepper. Each attribute is a single responsibility:

        robot.speech      say / stop
        robot.audio       play sound files stored on Pepper
        robot.motion      animations, wake / rest
        robot.behaviors   installed Choregraphe behaviors
        robot.awareness   Autonomous Life, head tracking
        robot.camera      head-camera snapshots
        robot.microphone  record one utterance
        robot.tablet      chest tablet: web page / video / image
        robot.system      ping, version
        robot.files       Pepper's sound folder (SSH)
        robot.network     checks run on Pepper (SSH)

    Cheap to create: nothing connects until a capability is used, and qi
    sessions are shared per ip:port.
    """

    def __init__(self, ip, port=9559, services=None, shell=None, pool=None):
        self.ip = ip
        self.port = int(port)
        self._pool = pool or default_pool
        services = services or _PooledServices(self._pool, ip, self.port)
        shell = shell or RobotShell(ip)
        key = "%s:%s" % (ip, self.port)

        self.speech = Speech(services)
        self.audio = Audio(services)
        self.motion = Motion(services)
        self.behaviors = Behaviors(services)
        self.awareness = Awareness(services, key)
        self.camera = Camera(services)
        self.microphone = Microphone(services, key)
        self.tablet = TabletDisplay(services)
        self.system = System(services)
        self.files = RobotFiles(shell)
        self.network = RobotNetwork(shell)

    def disconnect(self):
        """Forget the cached session so the next call starts a fresh connection."""
        self._pool.discard(self.ip, self.port)

    def stop_everything(self):
        """Best-effort stop of speech, sound and animations."""
        for stop in (self.speech.stop_all, self.audio.stop_all, self.motion.stop_animations):
            try:
                stop()
            except Exception:
                pass
