# How internet and the tablet work

This page explains how Pepper gets internet, how its tablet gets content, and
how to change the lab Wi-Fi. It assumes no networking background. The
companion page [container-to-pepper-networking.md](container-to-pepper-networking.md)
explains the firewall rule that lets the portal container reach Pepper.

## The picture

```
  Internet
     ^
     |  lab Wi-Fi (e.g. RAIL_002)
     |
  wlP1p1s0  --------------------------  "uplink": the Jetson's internal NIC
     |                                   (changed from the portal's Network page)
  [ Jetson ]  routing + NAT (NetworkManager "shared" mode)
     |
  wlx088af19321e3  192.168.50.1 -------  "pepper-ap": the USB dongle's access point
     |
     |  Wi-Fi: PepperJetson
     v
  Pepper's head  192.168.50.x  ---------  NAOqi on port 9559, SSH on port 22
     |
     |  internal link inside the robot
     v
  Pepper's tablet  -------------------  a separate Android device
```

The Jetson is a **router**:
- Pepper's default route is `192.168.50.1`, the Jetson's address on its hotspot.
- The Jetson rewrites Pepper's packets so they appear to come from the Jetson itself (**NAT**), then sends them out over the lab Wi-Fi. Replies come back the same way.
- **Pepper's internet is whatever the Jetson's uplink is connected to.** Switch the uplink Wi-Fi and Pepper's internet follows. The hotspot itself doesn't change.

## Checking internet: don't use ping

The lab network blocks ping (ICMP) to the internet. `ping 8.8.8.8` fails from both the Jetson and Pepper, even though the internet works fine.

The portal checks with a **TCP connection** to `1.1.1.1:443`, which is how web browsing works. The Network page shows this check for both the Jetson and Pepper.

To test by hand on Pepper:

```bash
ssh nao@192.168.50.226 "python -c \"import socket;socket.create_connection(('1.1.1.1',443),4);print('ok')\""
```

## Changing the lab Wi-Fi (Network page)

Portal → **Network**:
- **Internet**: whether the Jetson and Pepper are online.
- **Lab Wi-Fi**: scan, pick a network, and enter its password. This only changes `wlP1p1s0`, never the Pepper hotspot.
- **Interfaces**: read-only list of every network card and what it's for.

**Warning:** if your laptop reaches the portal *through the lab Wi-Fi* (for example `http://192.168.1.7:8081`), the page drops while the Jetson switches networks. The Jetson gets a new address on the new network, and you reconnect there. A laptop joined to the `PepperJetson` hotspot can always use `http://192.168.50.1:8081`.

The portal container can't change the Jetson's Wi-Fi itself; that needs root access to the host's network. A small helper does it instead. It runs natively on the Jetson as a systemd service. Install it once:

```bash
sudo ./install/setup_wifi_helper.sh      # listens on port 8767
```

## The tablet

Pepper's tablet is a separate small Android device inside the robot. The portal can tell it to:

| Show | NAOqi call | Where it comes from |
|---|---|---|
| RAIL Lab page | `showWebview` | `http://192.168.50.1:8081/tablet` (this portal) |
| A video | `playVideo` (native player) | `http://192.168.50.1:8081/media/<file>` |
| An image | `showImage` | `http://192.168.50.1:8081/media/<file>` |
| A website | `showWebview` | anywhere on the internet (Pepper has internet) |

Choose what to show from portal → **Tablet**, or with **Show on tablet** next to a video or image on the Media page.

### Why `192.168.50.1`?

The tablet loads pages over the network, so it needs an address it can actually reach. The portal runs in Docker, and inside the container its own address is something like `172.19.0.3`. That's a Docker-internal network the tablet can't reach. Pepper *can* reach the Jetson at its hotspot address, `192.168.50.1`, and Docker publishes the portal there on port 8081.

The portal works this out itself (`src/app/portal_address.py`). To override it, set `PORTAL_PUBLIC_BASE_URL` or `PEPPER_AP_ADDRESS` in `.env`.

### Why videos stay on the Jetson

- **Audio has to be on Pepper.** NAOqi's audio player only plays files stored on the robot, so the portal copies audio onto Pepper.
- **Videos and images don't.** The tablet can't read Pepper's disk; it can only load URLs. So they stay in `media/` on the Jetson and are streamed over the hotspot. They're never copied to Pepper, whose disk is small.

### When the tablet shows "offline"

The tablet appears to NAOqi as the service `ALTabletService`. If the tablet has crashed, is still booting, or has lost its internal link to the head, that service disappears. The portal then says **Tablet offline** instead of failing silently.

Fix: restart the tablet (hold its power button), or reboot Pepper. `python3 doctor.py --only portal` checks this.

## Where this lives in the code

| Piece | File |
|---|---|
| All robot control (NAOqi + SSH) | `src/robot/`; the tablet is `src/robot/tablet.py` |
| What the tablet can show | `src/app/tablet_content.py` |
| The address the tablet loads | `src/app/portal_address.py` |
| Tablet / network HTTP routes | `src/app/routes/tablet_routes.py`, `network_routes.py` |
| RAIL Lab page | `src/app/templates/tablet.html` |
| Wi-Fi helper (host side) | `host_services/wifi_helper.py` |
