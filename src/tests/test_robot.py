# -*- coding: utf-8 -*-
import unittest

from fakes import FakeServices, FakeShell

from robot import Robot, RobotError, RobotUnavailable
from robot.compat import PepperController
from robot.session import SessionPool


def make_robot(**kwargs):
    services = FakeServices(**kwargs)
    return Robot("10.0.0.2", 9559, services=services, shell=FakeShell()), services


class SpeechAudioMotionTest(unittest.TestCase):
    def test_say_blocks_by_default(self):
        pepper, services = make_robot()
        pepper.speech.say(u"h\xe9llo")
        self.assertEqual(services.calls, [("ALTextToSpeech", "say", (u"h\xe9llo".encode("utf-8"),), False)])

    def test_say_async_returns_future(self):
        pepper, services = make_robot()
        future = pepper.speech.say("hi", wait=False)
        self.assertTrue(hasattr(future, "value"))
        self.assertTrue(services.calls[0][3])

    def test_audio_load_then_play(self):
        pepper, services = make_robot(results={"ALAudioPlayer": {"loadFile": 7}})
        file_id = pepper.audio.load("/data/x.wav")
        pepper.audio.play_loaded(file_id, wait=False)
        self.assertEqual(services.methods(), [("ALAudioPlayer", "loadFile"), ("ALAudioPlayer", "play")])
        self.assertEqual(services.calls[1][2], (7,))

    def test_animation_and_motors(self):
        pepper, services = make_robot(results={"ALMotion": {"robotIsWakeUp": True}})
        pepper.motion.run_animation("animations/Stand/Gestures/Hey_1", wait=False)
        pepper.motion.wake()
        pepper.motion.rest()
        self.assertTrue(pepper.motion.is_awake())
        self.assertEqual(services.methods(), [
            ("ALAnimationPlayer", "run"), ("ALMotion", "wakeUp"),
            ("ALMotion", "rest"), ("ALMotion", "robotIsWakeUp"),
        ])

    def test_is_awake_falls_back_to_stiffness(self):
        pepper, _ = make_robot(results={"ALMotion": {
            "robotIsWakeUp": AttributeError("old image"), "getStiffnesses": [0.0, 1.0]}})
        self.assertTrue(pepper.motion.is_awake())


class TabletTest(unittest.TestCase):
    def test_show_video_and_image(self):
        pepper, services = make_robot()
        pepper.tablet.show_url("http://192.168.50.1:8081/tablet")
        pepper.tablet.play_video("http://192.168.50.1:8081/media/video/a.mp4")
        pepper.tablet.show_image("http://192.168.50.1:8081/media/img/b.png")
        self.assertEqual(services.methods(), [
            ("ALTabletService", "showWebview"), ("ALTabletService", "playVideo"),
            ("ALTabletService", "showImage"),
        ])

    def test_hide_clears_everything(self):
        pepper, services = make_robot()
        pepper.tablet.hide()
        self.assertEqual([m for _, m in services.methods()], ["stopVideo", "hideImage", "hideWebview"])

    def test_offline_tablet_raises_unavailable(self):
        pepper, _ = make_robot(missing=["ALTabletService"])
        self.assertFalse(pepper.tablet.available())
        with self.assertRaises(RobotUnavailable):
            pepper.tablet.show_url("http://x/tablet")

    def test_unreachable_robot_is_not_reported_as_offline_tablet(self):
        class Down(object):
            def service(self, name):
                raise RobotError("Could not connect to Pepper")
        pepper = Robot("10.0.0.2", services=Down(), shell=FakeShell())
        with self.assertRaises(RobotError) as ctx:
            pepper.tablet.show_url("http://x/tablet")
        self.assertNotIsInstance(ctx.exception, RobotUnavailable)


class AwarenessTest(unittest.TestCase):
    def test_vision_hold_restores_previous_state(self):
        pepper, services = make_robot(results={
            "ALAutonomousLife": {"getAutonomousAbilityEnabled": True},
            "ALBasicAwareness": {"isEnabled": True},
        })
        previous = pepper.awareness.hold_for_vision(True)
        self.assertEqual(previous, {"life_enabled": True, "awareness_enabled": True})
        services.calls[:] = []
        pepper.awareness.hold_for_vision(False)
        self.assertIn(("ALBasicAwareness", "setEnabled", (True,), False), services.calls)

    def test_life_state(self):
        pepper, _ = make_robot(results={"ALAutonomousLife": {"getState": "solitary"}})
        self.assertEqual(pepper.awareness.life_state(), (True, "solitary"))


class FilesAndNetworkTest(unittest.TestCase):
    def test_list_parses_busybox_stat(self):
        shell = FakeShell({"mkdir -p": "./uploads/a.wav\t10\t100\n./b c.wav\t5\t50\nbad line\n"})
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=shell)
        self.assertEqual(pepper.files.list(), {"uploads/a.wav": (10, 100), "b c.wav": (5, 50)})

    def test_internet_check(self):
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=FakeShell({"python": "ok\n"}))
        self.assertEqual(pepper.network.internet(), {"online": True, "error": None})


class SessionPoolTest(unittest.TestCase):
    def test_reuses_live_session_and_replaces_dead_one(self):
        made = []

        class Sess(object):
            def __init__(self):
                self.live = True
                self.closed = False

            def isConnected(self):
                return self.live

            def close(self):
                self.closed = True

        def connect(ip, port, timeout):
            made.append(Sess())
            return made[-1]

        pool = SessionPool(connect=connect)
        first = pool.get("10.0.0.2")
        self.assertIs(pool.get("10.0.0.2"), first)
        first.live = False
        second = pool.get("10.0.0.2")
        self.assertIsNot(second, first)
        self.assertTrue(first.closed)
        pool.discard("10.0.0.2")
        self.assertTrue(second.closed)


class CompatControllerTest(unittest.TestCase):
    def test_errors_are_swallowed(self):
        pepper, _ = make_robot(results={"ALTextToSpeech": {"say": RuntimeError("boom")}})
        ctrl = PepperController(robot=pepper, verbose=False)
        self.assertIsNone(ctrl.say("hi", async_play=False))

    def test_skips_uninstalled_behavior(self):
        pepper, services = make_robot(results={"ALBehaviorManager": {"isBehaviorInstalled": False}})
        ctrl = PepperController(robot=pepper, verbose=False)
        self.assertIsNone(ctrl.play_behavior("x/behavior_1"))
        self.assertNotIn(("ALBehaviorManager", "runBehavior"), services.methods())


if __name__ == "__main__":
    unittest.main()
