# -*- coding: utf-8 -*-
from .base import Capability, call, to_str


class Audio(Capability):
    """Plays sound files that already live on Pepper (ALAudioPlayer)."""

    def load(self, path):
        """Preload a file; returns an id for play_loaded(). Avoids a gap on first play."""
        return self._service("ALAudioPlayer").loadFile(to_str(path))

    def play_loaded(self, file_id, wait=True):
        return call(self._service("ALAudioPlayer"), "play", file_id, wait=wait)

    def play_file(self, path, wait=True):
        return call(self._service("ALAudioPlayer"), "playFile", to_str(path), wait=wait)

    def stop_all(self):
        self._service("ALAudioPlayer").stopAll()
