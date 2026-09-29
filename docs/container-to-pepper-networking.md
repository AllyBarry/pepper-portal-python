# Why the portal container couldn't reach Pepper (and the fix)

**Symptom:** from the Jetson you can `ping` Pepper (e.g. `192.168.50.226`), but from
inside the `pepper_portal` container the same ping fails with:

```
From 0.0.0.0 icmp_seq=1 Destination Port Unreachable
```

**Fix:** run once per Jetson:

```bash
sudo ./install/setup_ap_docker_forward.sh
docker exec pepper_portal ping -c2 <pepper-ip>
```

The rest of this page explains what's going on, assuming no networking background.

---

## 1. The setup: the Jetson is a router

The Jetson is connected to several separate networks at once, one per network card:

| Card | Network | Jetson's address | What's on it |
|---|---|---|---|
| `wlP1p1s0` (built-in Wi-Fi) | `192.168.1.x` | 192.168.1.7 | Home/lab Wi-Fi and the internet |
| `wlx088af19321e3` (Mercusys USB dongle) | `192.168.50.x` | 192.168.50.1 | **Pepper** |
| Docker bridge (virtual) | `172.19.x.x` | 172.19.0.1 | The containers |

The dongle runs as a **hotspot** (the `pepper-ap` profile, README §9) that Pepper joins.
So the Jetson isn't just a computer. It's a **router** sitting between these networks.

## 2. Containers live on their own private network

Docker doesn't put containers directly on the real networks. It creates a **virtual
network** inside the Jetson (the `172.19.x.x` one) and gives each container an address
there. For the container, the Jetson is its gateway, the way a home router is the
gateway for a laptop.

So a packet from the portal container to Pepper travels:

```
container (172.19.0.x)  →  Jetson  →  dongle  →  Pepper (192.168.50.x)
```

The Jetson has to **pass the packet from one network to another**. That's called
**forwarding**.

When you ping Pepper **from the Jetson itself**, there's no forwarding. The Jetson sends
the packet straight out of its own dongle:

```
Jetson (192.168.50.1)  →  Pepper
```

That's why it worked outside the container and failed inside.

## 3. The firewall treats those two paths differently

Linux has a built-in firewall called **iptables**. It sorts packets into lists of rules
called **chains**. The important ones:

- **OUTPUT**: packets the Jetson itself sends (the host ping)
- **FORWARD**: packets passing *through* the Jetson from one network to another (the
  container's ping)

Each chain is checked top to bottom, and the first rule that matches decides:
**ACCEPT** (let it through), **DROP** (silently discard it), or **REJECT** (discard it
and send back an error).

## 4. Who put the blocking rule there?

The hotspot is configured with `ipv4.method shared`. That tells NetworkManager (the
program that manages Wi-Fi on the Jetson): "share this connection, act as a router for
the devices that join." To do that, NetworkManager automatically adds FORWARD rules
that roughly say:

1. Traffic **from** the hotspot network going anywhere: **ACCEPT** (Pepper can reach out)
2. Traffic **into** the hotspot that's a **reply** to something Pepper started: **ACCEPT**
3. **Anything else going into the hotspot: REJECT**

Rule 3 is a sensible safety default: nobody outside can start a connection to devices
on the hotspot. But the container is "outside" by that definition. It's on the
`172.19` network, trying to **start** a new connection to Pepper, so rule 3 rejects it.

## 5. How we knew it was the firewall

If the packet had simply been lost (bad route, Pepper switched off), ping would show
**no reply at all**, just a timeout. Getting `Destination Port Unreachable` back means
something actively refused the packet, and "port unreachable" is exactly the error an
iptables **REJECT** rule sends by default. Combined with "works from the host, fails
when forwarded," that points straight at NetworkManager's rule 3.

Forwarding itself was switched on (`sysctl net.ipv4.ip_forward` → `1`), which ruled
out the Jetson refusing to route at all.

## 6. The fix: one extra rule, placed first

The fix adds one rule to the **top** of the FORWARD chain:

```bash
iptables -I FORWARD 1 -s 172.16.0.0/12 -o wlx088af19321e3 -j ACCEPT
```

| Part | Meaning |
|---|---|
| `-I FORWARD 1` | **I**nsert into the FORWARD chain at position **1** (the top) |
| `-s 172.16.0.0/12` | where the **s**ource address is any Docker network (172.16.0.0 to 172.31.255.255, which includes 172.19) |
| `-o wlx088af19321e3` | going **o**ut through the Pepper dongle |
| `-j ACCEPT` | **j**ump to ACCEPT: let it through |

Because rules are checked top to bottom and the first match wins, this rule is hit
**before** NetworkManager's REJECT. Container traffic to Pepper gets through, and
everything else is still blocked as before.

**Why don't Pepper's replies need a rule?** Two things already handle them:

- **NAT (masquerading):** Docker rewrites the container's packets so they appear to
  come from the Jetson's own hotspot address, `192.168.50.1`. Pepper replies to the
  Jetson, and the Jetson, which remembers the conversation, hands the reply back to the
  container. A home router does the same for all its devices.
- **NetworkManager's rule 2** already accepts replies.

## 7. Why a script instead of running that command once

iptables rules live **in memory only**. They disappear when the Jetson reboots, and
NetworkManager also rebuilds its hotspot rules whenever the hotspot restarts. A
command typed once would stop working the next day.

NetworkManager has a feature for this: **dispatcher scripts**. Any script in
`/etc/NetworkManager/dispatcher.d/` runs automatically when a network connection
changes state. `install/setup_ap_docker_forward.sh` does two things:

1. **Writes a small hook script** to
   `/etc/NetworkManager/dispatcher.d/90-pepper-ap-docker-forward`. It checks "is this
   the Pepper dongle, and did it just come **up**?" If so, it removes any old copy of
   the rule and inserts a fresh one at the top. Removing first matters: NetworkManager
   re-adds its REJECT rules on every restart, so ours has to be re-inserted above them
   each time, and deleting the old copy stops duplicates piling up.
2. **Runs that hook once immediately**, so there's no need to restart the hotspot to
   get the fix.

If the hotspot uses a different interface on other hardware, pass its name:
`sudo ./install/setup_ap_docker_forward.sh <interface>` (see `nmcli device status`).

### Why not `network_mode: host`?

Putting the portal container on the host network would also avoid the problem, but
then it can no longer reach its sibling containers by service name
(`http://ollama:11434`, `http://speech-to-text:8765`). The firewall rule keeps the
Compose setup unchanged.

## 8. Troubleshooting

```bash
# Is the rule there, and above NetworkManager's REJECT?
sudo iptables -S FORWARD

# Is the hook installed?
ls -l /etc/NetworkManager/dispatcher.d/90-pepper-ap-docker-forward

# Re-apply by hand without restarting the hotspot
sudo /etc/NetworkManager/dispatcher.d/90-pepper-ap-docker-forward wlx088af19321e3 up
```

If the container gets **no reply at all** (a timeout rather than "Port Unreachable"),
the firewall isn't the problem. Check that Pepper is on the hotspot and that its IP
hasn't changed (`ip neigh show dev wlx088af19321e3`).

---

## Glossary

- **IP address / subnet**: a device's address. `192.168.50.0/24` means "every address
  starting with 192.168.50."
- **Router / gateway**: a device that passes packets between networks.
- **Forwarding**: a machine passing packets between two of its networks, instead of
  sending or receiving them itself.
- **Firewall (iptables)**: ordered lists of rules deciding which packets are allowed.
- **NAT / masquerade**: rewriting a packet's sender address so replies come back to the
  router, which then passes them on.
- **Bridge network**: the virtual network Docker makes for containers.
