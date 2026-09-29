# -*- coding: utf-8 -*-
import unittest

from fakes import FakeServices, FakeShell  # noqa: F401 (sets sys.path)

import portal_address
import tablet_content
from robot import Robot

BASE = "http://192.168.50.1:8081"


class RecordingTablet(object):
    def __init__(self):
        self.calls = []

    def show_url(self, url):
        self.calls.append(("show_url", url))

    def play_video(self, url):
        self.calls.append(("play_video", url))

    def show_image(self, url):
        self.calls.append(("show_image", url))


class TabletContentTest(unittest.TestCase):
    def test_landing_page(self):
        tablet = RecordingTablet()
        url = tablet_content.from_choice("landing", "", lambda rel: False).render(tablet, BASE)
        self.assertEqual(url, BASE + "/tablet")
        self.assertEqual(tablet.calls, [("show_url", BASE + "/tablet")])

    def test_video_url_is_quoted(self):
        tablet = RecordingTablet()
        content = tablet_content.from_choice("video", "video/lab tour.mp4", lambda rel: True)
        content.render(tablet, BASE)
        self.assertEqual(tablet.calls, [("play_video", BASE + "/media/video/lab%20tour.mp4")])

    def test_media_must_exist(self):
        with self.assertRaises(ValueError):
            tablet_content.from_choice("image", "nope.png", lambda rel: False)

    def test_website_must_be_http(self):
        with self.assertRaises(ValueError):
            tablet_content.from_choice("web", "javascript:alert(1)", lambda rel: False)
        tablet = RecordingTablet()
        tablet_content.from_choice("web", "https://example.com", lambda rel: False).render(tablet, BASE)
        self.assertEqual(tablet.calls, [("show_url", "https://example.com")])

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            tablet_content.from_choice("hologram", "x", lambda rel: True)

    def test_catalog_lists_landing_videos_and_images_only(self):
        files = [
            {"path": "video/a.mp4", "kind": "video", "managed": True},
            {"path": "img/b.png", "kind": "image", "managed": True},
            {"path": "uploads/c.wav", "kind": "audio", "managed": True},
            {"path": "old/d.mp4", "kind": "video", "managed": False},  # Pepper-only
        ]
        kinds = [(i["kind"], i["ref"]) for i in tablet_content.catalog(files)]
        self.assertEqual(kinds, [("landing", "rail-lab"), ("video", "video/a.mp4"), ("image", "img/b.png")])

    def test_renders_on_real_tablet_display(self):
        services = FakeServices()
        pepper = Robot("10.0.0.2", services=services, shell=FakeShell())
        tablet_content.LandingPage().render(pepper.tablet, BASE)
        self.assertEqual(services.calls[0][:3], ("ALTabletService", "showWebview", (BASE + "/tablet",)))


class PortalAddressTest(unittest.TestCase):
    def setUp(self):
        self._saved = portal_address.PORTAL_PUBLIC_BASE_URL
        portal_address.PORTAL_PUBLIC_BASE_URL = None

    def tearDown(self):
        portal_address.PORTAL_PUBLIC_BASE_URL = self._saved

    def test_docker_bridge_falls_back_to_ap(self):
        url = portal_address.tablet_base_url("192.168.50.226", local_ip=lambda ip: "172.19.0.3")
        self.assertEqual(url, "http://%s:%s" % (portal_address.PEPPER_AP_ADDRESS, portal_address.PORTAL_HOST_PORT))

    def test_host_network_uses_routed_ip(self):
        url = portal_address.tablet_base_url("192.168.1.20", local_ip=lambda ip: "192.168.1.7")
        self.assertEqual(url, "http://192.168.1.7:%s" % portal_address.PORTAL_HOST_PORT)

    def test_explicit_override_wins(self):
        portal_address.PORTAL_PUBLIC_BASE_URL = "http://pepper-jetson.local:8081"
        self.assertEqual(portal_address.tablet_base_url("1.2.3.4"), "http://pepper-jetson.local:8081")

    def test_is_docker_bridge(self):
        self.assertTrue(portal_address.is_docker_bridge("172.31.255.1"))
        self.assertFalse(portal_address.is_docker_bridge("172.32.0.1"))
        self.assertFalse(portal_address.is_docker_bridge("192.168.50.1"))


if __name__ == "__main__":
    unittest.main()
