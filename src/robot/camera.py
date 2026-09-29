# -*- coding: utf-8 -*-
import itertools
import os
import struct
import threading
import zlib

from .base import Capability
from .errors import RobotError

CAMERA_IDS = {"top": 0, "bottom": 1}
CAMERA_RESOLUTIONS = {
    "160x120": 0,  # QQVGA
    "320x240": 1,  # QVGA
    "640x480": 2,  # VGA
}
RGB_COLOR_SPACE = 11
CAMERA_TIMEOUT_MS = 5000

# Pepper allows only a few camera subscriptions at once. Captures are
# serialised and always unsubscribe, including on timeouts.
_camera_lock = threading.Lock()
_camera_counter = itertools.count(1)


def _png_chunk(chunk_type, payload):
    checksum = zlib.crc32(chunk_type + payload) & 0xffffffff
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def rgb_to_png(width, height, rgb_bytes):
    """Encode packed 8-bit RGB pixels as PNG using only Python's standard library."""
    row_bytes = width * 3
    expected = row_bytes * height
    if len(rgb_bytes) < expected:
        raise RobotError(
            "Camera returned %s bytes; expected at least %s" % (len(rgb_bytes), expected)
        )
    scanlines = []
    for row in range(height):
        start = row * row_bytes
        scanlines.append(b"\x00" + rgb_bytes[start:start + row_bytes])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(scanlines), 3))
        + _png_chunk(b"IEND", b"")
    )


class Camera(Capability):
    """Single frames from Pepper's head cameras (ALVideoDevice)."""

    def capture_png(self, camera="top", resolution="320x240", fps=2):
        if camera not in CAMERA_IDS:
            raise ValueError("Camera must be 'top' or 'bottom'")
        if resolution not in CAMERA_RESOLUTIONS:
            raise ValueError("Resolution must be one of: %s" % ", ".join(sorted(CAMERA_RESOLUTIONS)))
        video = self._service("ALVideoDevice")
        subscriber = None
        with _camera_lock:
            client_name = "pepper_portal_%s_%s" % (os.getpid(), next(_camera_counter))
            try:
                subscriber = video.subscribeCamera(
                    client_name, CAMERA_IDS[camera], CAMERA_RESOLUTIONS[resolution],
                    RGB_COLOR_SPACE, fps,
                )
                image = video.getImageRemote(subscriber, _async=True).value(CAMERA_TIMEOUT_MS)
                if not image or len(image) < 7:
                    raise RobotError("Pepper returned an empty camera frame")
                pixels = image[6]
                if isinstance(pixels, bytearray):
                    pixels = bytes(pixels)
                elif not isinstance(pixels, bytes):
                    pixels = bytes(pixels)
                return rgb_to_png(int(image[0]), int(image[1]), pixels)
            finally:
                if subscriber:
                    try:
                        video.unsubscribe(subscriber)
                    except Exception:
                        pass
