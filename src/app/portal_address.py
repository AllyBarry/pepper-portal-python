# -*- coding: utf-8 -*-
"""
The portal's address as seen *from Pepper* -- what the tablet must load.

The portal runs in a container, so the local IP it sees on the route to
Pepper is a Docker bridge address (172.16.0.0/12) the tablet can't reach.
Pepper reaches the Jetson at the AP address (192.168.50.1 on pepper-ap), and
Docker publishes the portal there on PORTAL_HOST_PORT.
"""
import os
import socket

PORTAL_HOST_PORT = os.environ.get("PORTAL_HOST_PORT", "8081")
PORTAL_PUBLIC_BASE_URL = (os.environ.get("PORTAL_PUBLIC_BASE_URL") or "").rstrip("/") or None
PEPPER_AP_ADDRESS = os.environ.get("PEPPER_AP_ADDRESS", "192.168.50.1")


def local_ip_for(remote_ip, remote_port=9559):
    """Local IP of the interface that routes to remote_ip. Sends no packets."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((remote_ip, remote_port))
        return sock.getsockname()[0]
    except Exception:
        return None
    finally:
        if sock is not None:
            sock.close()


def is_docker_bridge(ip):
    """True for 172.16.0.0/12, where Docker puts container networks."""
    try:
        a, b = [int(x) for x in ip.split(".")[:2]]
    except Exception:
        return False
    return a == 172 and 16 <= b <= 31


def tablet_base_url(pepper_ip=None, local_ip=local_ip_for):
    """
    Base URL for pages shown on Pepper's tablet, in order of preference:
      1. PORTAL_PUBLIC_BASE_URL, if set
      2. the local IP routing to Pepper, when the portal runs on the host
      3. the AP address, when running in Docker (the usual case)
    """
    if PORTAL_PUBLIC_BASE_URL:
        return PORTAL_PUBLIC_BASE_URL
    host = local_ip(pepper_ip) if pepper_ip else None
    if not host or is_docker_bridge(host) or host.startswith("127."):
        host = PEPPER_AP_ADDRESS
    return "http://%s:%s" % (host, PORTAL_HOST_PORT)
