# -*- coding: utf-8 -*-
from .base import Capability


class System(Capability):
    """Robot-level queries (ALSystem)."""

    def ping(self):
        return bool(self._service("ALSystem").ping())

    def version(self):
        return self._service("ALSystem").systemVersion()

    def name(self):
        return self._service("ALSystem").robotName()

    def battery(self):
        """{"charge": percent, "charging": bool} -- current flows in while charging."""
        charge = self._service("ALBattery").getBatteryCharge()
        current = self._service("ALMemory").getData("Device/SubDeviceList/Battery/Current/Sensor/Value")
        return {"charge": int(charge), "charging": float(current or 0) > 0}
