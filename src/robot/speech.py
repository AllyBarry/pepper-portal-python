# -*- coding: utf-8 -*-
from .base import Capability, call, to_str


class Speech(Capability):
    """Text-to-speech (ALTextToSpeech)."""

    def say(self, text, wait=True):
        return call(self._service("ALTextToSpeech"), "say", to_str(text), wait=wait)

    def stop_all(self):
        self._service("ALTextToSpeech").stopAll()
