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


class MotionTest(unittest.TestCase):
    def tearDown(self):
        from robot import motion
        motion._drive_deadlines.clear()

    def test_drive_clamps_and_watchdog_stops(self):
        import time
        from robot import motion
        pepper, services = make_robot()
        pepper.motion.drive(2.0, -0.5, 0.1)
        self.assertEqual(services.calls[0], ("ALMotion", "moveToward", (1.0, -0.5, 0.1), False))
        time.sleep(motion.DRIVE_TIMEOUT_SECONDS + 0.3)
        self.assertEqual(services.methods()[-1], ("ALMotion", "stopMove"))

    def test_drive_zero_and_stop_cancel_watchdog(self):
        pepper, services = make_robot()
        pepper.motion.drive(0.5, 0, 0)
        pepper.motion.drive(0, 0, 0)
        from robot import motion
        self.assertNotIn("10.0.0.2:9559", motion._drive_deadlines)
        self.assertEqual(services.methods(), [("ALMotion", "moveToward"), ("ALMotion", "stopMove")])

    def test_look_clamps_to_joint_limits(self):
        pepper, services = make_robot()
        pepper.motion.look(5, -5, speed=3)
        names, angles, speed = services.calls[0][2]
        self.assertEqual(names, ["HeadYaw", "HeadPitch"])
        self.assertEqual(angles, [2.0857, -0.7068])
        self.assertEqual(speed, 1.0)

    def test_hands_postures_and_validation(self):
        pepper, services = make_robot(results={"ALRobotPosture": {"goToPosture": True}})
        pepper.motion.hand("left", True)
        pepper.motion.hand("right", False)
        self.assertTrue(pepper.motion.go_to_posture("StandInit"))
        self.assertEqual(services.methods(), [
            ("ALMotion", "openHand"), ("ALMotion", "closeHand"), ("ALRobotPosture", "goToPosture")])
        self.assertRaises(ValueError, pepper.motion.hand, "middle", True)
        self.assertRaises(ValueError, pepper.motion.go_to_posture, "Handstand")

    def test_move_to_is_async_by_default(self):
        pepper, services = make_robot()
        future = pepper.motion.move_to(0.5, 0, 1.57)
        self.assertTrue(hasattr(future, "value"))
        self.assertEqual(services.calls[0], ("ALMotion", "moveTo", (0.5, 0.0, 1.57), True))


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


class HealthTest(unittest.TestCase):
    def test_status_parses_one_round_trip(self):
        out = ("@uptime\n3725.4 100.0\n@load\n0.52 0.40 0.31 1/200 999\n"
               "@mem\nMem: 3842 2100 1742 0 0 0\n@disk\n/dev/sda4 1000 400 600 40% /home\n@host\nPepper\n")
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=FakeShell({"echo @uptime": out}))
        self.assertEqual(pepper.health.status(), {
            "hostname": "Pepper", "uptime_s": 3725, "load": ["0.52", "0.40", "0.31"],
            "mem_total_mb": 3842, "mem_used_mb": 2100, "disk_used_pct": 40})

    def test_log_files_and_tail(self):
        shell = FakeShell({"find": "20 5 /var/log/naoqi/servicemanager/a b.log\n10 7 /var/log/naoqi/x.log\n",
                           "tail": "one\ntwo\n"})
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=shell)
        self.assertEqual(pepper.health.log_files()[0], {"path": "/var/log/naoqi/servicemanager/a b.log", "size": 5})
        self.assertEqual(pepper.health.tail("/var/log/naoqi/x.log", 50), ["one", "two"])
        self.assertEqual(shell.commands[-1], "tail -n 50 '/var/log/naoqi/x.log'")

    def test_tail_refuses_other_files(self):
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=FakeShell())
        for path in ("/etc/shadow", "/var/log/naoqi/../../etc/shadow", "/var/log/naoqi-evil/x.log"):
            self.assertRaises(ValueError, pepper.health.tail, path)

    def test_battery(self):
        pepper, _ = make_robot(results={"ALBattery": {"getBatteryCharge": 87},
                                        "ALMemory": {"getData": 0.4}})
        self.assertEqual(pepper.system.battery(), {"charge": 87, "charging": True})


class WifiSignalTest(unittest.TestCase):
    def test_parses_proc_net_wireless(self):
        out = ("Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
               " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
               " wlan0: 0000   62.  -48.  -256        0      0      0      0      0        0\n")
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=FakeShell({"cat /proc/net/wireless": out}))
        self.assertEqual(pepper.network.wifi_signal(), {"interface": "wlan0", "quality": 62, "signal_dbm": -48})

    def test_wired_only_is_none(self):
        out = "Inter-| sta-|   Quality\n face | tus | link level noise\n"
        pepper = Robot("10.0.0.2", services=FakeServices(), shell=FakeShell({"cat": out}))
        self.assertIsNone(pepper.network.wifi_signal())


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
