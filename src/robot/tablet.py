# -*- coding: utf-8 -*-
from .base import Capability, to_str
from .errors import RobotError, RobotUnavailable

TABLET_OFFLINE = (
    "Pepper's tablet is offline (ALTabletService is not running). "
    "Restart the tablet or reboot Pepper."
)


class TabletDisplay(Capability):
    """
    Pepper's chest tablet (ALTabletService). The tablet is its own device,
    linked to the head; when that link is down the service vanishes, so
    every call raises RobotUnavailable rather than silently doing nothing.

    URLs must be reachable *from the tablet*, i.e. from Pepper's network --
    never localhost or a Docker-internal address.
    """

    def _tablet(self):
        try:
            return self._service("ALTabletService")
        except RobotError:
            raise  # Pepper itself unreachable -- not a tablet problem
        except Exception:
            raise RobotUnavailable(TABLET_OFFLINE)

    def available(self):
        try:
            self._tablet()
            return True
        except RobotUnavailable:
            return False

    def show_url(self, url):
        """Open a web page (portal page or any website Pepper can reach)."""
        self._tablet().showWebview(to_str(url))

    def play_video(self, url):
        """Full-screen native video player."""
        self._tablet().playVideo(to_str(url))

    def show_image(self, url):
        self._tablet().showImage(to_str(url))

    def hide(self):
        """Clear whatever is showing: web page, video or image."""
        tablet = self._tablet()
        for method in ("stopVideo", "hideImage", "hideWebview"):
            try:
                getattr(tablet, method)()
            except Exception:
                pass
