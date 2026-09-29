# -*- coding: utf-8 -*-
"""Network checks run *on* Pepper."""
from .shell import error_text

# ICMP is blocked upstream of the lab network, so "online" means a TCP
# connection to a public DNS server succeeds -- ping would say offline.
INTERNET_PROBE = ("1.1.1.1", 443)


class RobotNetwork(object):
    def __init__(self, shell):
        self._shell = shell

    def internet(self):
        """{"online": bool, "error": str|None} -- can Pepper reach the internet?"""
        host, port = INTERNET_PROBE
        try:
            out = self._shell.run(
                "python -c \"import socket;socket.create_connection(('%s',%d),4);print('ok')\""
                % (host, port)
            )
            online = out.strip().endswith("ok")
            return {"online": online, "error": None if online else out.strip()[-200:]}
        except Exception as exc:
            return {"online": False, "error": error_text(exc)}
