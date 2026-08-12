# Pepper Python Portal

This repository provides an easy-to-use web-based interface for controlling animations and audio files on a Pepper robot.

**Prerequisites:**
- [Docker](https://www.docker.com)
- A Pepper robot

## Setting up Pepper
**Network Details:**
- IP Address: `192.168.1.5` (press power button once if different)
- Login credentials, eg user: nao, password: ?

**Web Interface**
Navigate to `192.168.1.5` in your browser and log in.

### Loading Media onto Pepper
Running audio on Pepper requires having the media loaded onto Pepper.
Audio files should be located in `/data/home/nao/.local/share/wav`
This folder may not exist and can be created by first ssh-ing into Pepper:
```bash
ssh nao@192.168.1.5
cd /data/home/nao/.local/share/
mkdir wav
```
Then the media files can be copied into this directory:
```bash
scp <file_name> nao@192.168.1.5:/data/home/nao/.local/share/wav/
```

## Build and Run the Container

> **The one rule:** the NAOqi Python SDK (pynaoqi) ships **x86-64-only** binaries, so this image
> must always be built and run as `linux/amd64` — natively on Intel/AMD, or under emulation
> (QEMU/Rosetta) on ARM hosts. `docker-compose.yaml` pins this for you. If you bypass Compose and
> forget the platform flag, see [Frequent Issues](#frequent-issues).

Before doing so, you will need to copy the pynaoqi python2.7 sdk into the root folder: `pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327.tar.gz`. This can be found online.

### On an x86-64 host (native — no emulation needed)

```bash
docker compose build pepper-portal
docker compose up pepper-portal
```

Web page: `localhost:8080`.

### On an ARM host (Apple Silicon / Raspberry Pi / Jetson)

First enable amd64 emulation, then use the `pepper-portal-arm` service — it depends on
`pepper-portal-arm-setup`, which installs the QEMU binfmt handlers before the portal starts:

```bash
docker compose up pepper-portal-arm-setup   # one-off: installs QEMU binfmt handlers
docker compose build pepper-portal-arm
docker compose up pepper-portal-arm
```

Web page: `localhost:8088`.

**On Apple Silicon**, skip the binfmt step (Docker Desktop already emulates amd64) and turn on
**Settings → General → "Use Rosetta for x86/amd64 emulation"**. Rosetta is dramatically faster
than QEMU for this image.

**Build time warning:** the Dockerfile compiles Python 2.7 from source with
`--enable-optimizations` (profile-guided optimisation). Native that is a few minutes; under QEMU
emulation it can exceed an hour. If you don't need PGO, drop `--enable-optimizations` from the
`./configure` line in the `Dockerfile` — it cuts build time substantially with no effect on this
application.

### Verify it actually worked

Do not trust "the page loaded". Check the import directly:

```bash
docker exec pepper_portal python2 -c "import qi; print(qi.__file__)"
```

Success prints a path. Any traceback here means the container is still the wrong architecture,
and no robot command will work.

### Compose services at a glance

| Service | Container | Port | Use it when |
|---|---|---|---|
| `pepper-portal` | `pepper_portal` | 8080 | Host is x86-64 (native amd64) |
| `pepper-portal-arm-setup` | `pepper_portal_arm_setup` | — | One-off; installs QEMU binfmt on ARM Linux hosts |
| `pepper-portal-arm` | `pepper_portal_arm` | 8088 | Host is ARM (Pi, Jetson, Apple Silicon) |

All three share the `pepper-portal-python:latest` tag and the `platform: linux/amd64` setting from
the `x-pepper-portal` anchor, so they cannot disagree about architecture.

The older `docker build` / `./run_container.sh` path still works, but you must pass the platform
flag yourself, otherwise you get the arm64 image described above:

```bash
docker buildx build --platform linux/amd64 --load -t pepper-portal-python .
```

## Local Llama Conversation

The Conversation workspace can run a private speech loop on the local computer:

1. Pepper records through its front microphone until three seconds of silence.
2. MLX Whisper transcribes the utterance locally and displays what Pepper heard.
3. A local Ollama model generates Pepper's response.
4. Pepper speaks the response through `ALTextToSpeech`, then listens again.

Install the project-local speech environment once:

```bash
./setup_local_speech.sh
```

Start Ollama and the loopback-only MLX Whisper helper:

```bash
./run_local_services.sh
```

The default model is `llama3.1:8b`; download it with `ollama pull llama3.1:8b` if needed. The Whisper model downloads on first use. Open the portal, connect to Pepper, confirm the local services are ready, and select **Start conversation**. The loop continues until **Stop** is selected.

Pepper microphone captures are transferred through NAOqi, overwritten on the robot, and deleted from the computer after transcription. Ask permission before recording other people. Browser microphone recognition remains an optional fallback whose processing depends on the browser.

Use `http://127.0.0.1:8080/?preview=1` to inspect the interface without connecting to a robot.

## Development Workflow

The `./src` directory is mounted in the container and updates in real-time, allowing you to:
1. Develop code on your host machine
2. Run and test code from within the Docker container

## Frequent Issues

### `NAOqi 'qi' module could not be imported` — the container is the wrong architecture

**Symptom.** The image builds fine, Flask starts, the web page loads — and then every robot action
fails with:

```
NAOqi 'qi' module could not be imported. Ensure the SDK is installed,
PYTHONPATH is set, and the container is running as linux/amd64.
ImportError: .../_qi.so: cannot open shared object file: No such file or directory
```

**This is not a `PYTHONPATH` problem**, despite what the message suggests. The file exists and the
path is correct. `cannot open shared object file` is a misleading libc message that means *"cannot
load this object"*, not *"cannot find it"* — here, because it's an x86-64 `.so` being loaded into
an arm64 process.

**Cause.** Docker builds for your host CPU by default. On an Apple Silicon Mac, Raspberry Pi, or
Jetson, a plain `docker build` produces an **arm64** image. Ubuntu, Python and Flask all have arm64
builds so the build succeeds — but pynaoqi is a closed-source 2019 SoftBank release that only ever
shipped x86-64 binaries. There is no ARM build of it.

**Diagnose.** Compare your host arch against the image arch:

```bash
uname -m
# arm64  → you are on an ARM host

docker image inspect pepper-portal-python:latest --format '{{.Architecture}}'
# arm64  → the image is wrong; it must say amd64
```

And confirm what the SDK actually contains:

```bash
file pynaoqi-*/lib/python2.7/site-packages/_qi.so
# _qi.so: ELF 64-bit LSB shared object, x86-64, ...
```

**Fix.** Rebuild as amd64. Via Compose (which pins the platform):

```bash
docker compose down
docker compose build --no-cache pepper-portal      # or pepper-portal-arm on an ARM host
docker compose up pepper-portal
```

Or manually, if you're not using Compose:

```bash
docker buildx build --platform linux/amd64 --load -t pepper-portal-python .
```

**Verify** — do not trust "the page loaded":

```bash
docker exec pepper_portal python2 -c "import qi; print(qi.__file__)"
```

Success prints a path. A traceback means the container is still the wrong architecture and no robot
command will work.

### The rebuild takes forever on ARM

The Dockerfile compiles Python 2.7 from source with `--enable-optimizations` (profile-guided
optimisation). Native that's a few minutes; under QEMU emulation it can exceed an hour.

- On Apple Silicon, enable **Docker Desktop → Settings → General → "Use Rosetta for x86/amd64
  emulation"**. Much faster than QEMU.
- If you don't need PGO, drop `--enable-optimizations` from the `./configure` line in the
  `Dockerfile`. It cuts build time substantially with no effect on this application.

### `exec format error` when starting an amd64 container on ARM Linux

The QEMU binfmt handlers aren't installed on the host. Run the setup service once per boot:

```bash
docker compose up pepper-portal-arm-setup
```

Verify with `ls /proc/sys/fs/binfmt_misc/` (should list `qemu-amd64`) and
`docker run --rm --platform linux/amd64 alpine uname -m` (should print `x86_64`).
Not needed on Docker Desktop for Mac, which emulates amd64 out of the box.

### `import qi` works, but the robot won't connect

That's a separate, network-level problem — the SDK is loading correctly. Check that Pepper is
reachable on port 9559 from *inside* the container:

```bash
docker exec pepper_portal ping -c1 192.168.1.5
docker exec pepper_portal telnet 192.168.1.5 9559
```

## Additional Resources

- [NAOqi Getting Started Guide](http://doc.aldebaran.com/2-5/getting_started/index.html)
- [Python SDK Documentation](http://doc.aldebaran.com/2-5/dev/python/intro_python.html)
- [qicli Command Reference](http://doc.aldebaran.com/2-5/dev/libqi/guide/qicli.html)

# 🐳 Run x86 (NAOqi) Docker Images on Raspberry Pi (ARM)

Raspberry Pi = ARM (`arm64/v8`)  
NAOqi SDK = x86 only (`linux/386` or `linux/amd64`)  

To make this work, enable QEMU + Docker Buildx.

---

## 1. Enable QEMU Emulation

```bash
docker run --rm --privileged tonistiigi/binfmt --install all
```

Verify:

```bash
ls /proc/sys/fs/binfmt_misc/
# should list qemu-amd64, qemu-i386, etc.

docker run --rm --platform linux/amd64 alpine uname -m
# Expected: x86_64

docker run --rm --platform linux/386 alpine uname -m
# Expected: i686
```

---

## 2. Ensure Buildx is Available

```bash
docker buildx version
# should show a version string
```

If needed, create a builder:

```bash
docker buildx create --use --name mybuilder
docker buildx inspect --bootstrap
```

---

## 3. Build Image for amd64 

Preferred: use Compose, which pins the platform for you (see
[Build and Run the Container](#build-and-run-the-container)):

```bash
docker compose up pepper-portal-arm-setup   # installs binfmt handlers
docker compose build pepper-portal-arm
docker compose up pepper-portal-arm
```

Manual equivalent, for 64-bit NAOqi (amd64):

```bash
docker buildx build --platform linux/amd64 --load -t pepper-portal-python .
```
```bash
docker run --rm --privileged tonistiigi/binfmt --install all #make sure this is enabled
chmod +x run_pi.sh #make sure its an executable
./run_pi.sh
```



# How to connect from cluster

``` txt
        [ Your PC on the Internet at home]
                       |
                       |  (you can ssh -L [local_port]:10.100.12.216:8080]
                       v
+-------------------------------------------------------------------+
|               Cluster Gateway (Public IP)                         |
|                   [ 146.141.10.100 ]                              |
|                                                                   |
| [Port Forwarding Rules - Layer 1]                                 | 
|   1. Public Port :3000  --->  [Internal Router IP] :3000          |
|   2. Public Port :8080  --->  [Internal Router IP] :8080          |
+-------------------------------------------------------------------+
                              |                 
                              |   (Router IP:10.100.12.216)
                              V                  
+-------------------------------------------------------------------+
|           Internal Router (Within Cluster Network)                |
|              [ e.g., 10.0.0.1 or 192.168.0.1 ]                    |
|                                                                   |
| [Port Forwarding Rules - Layer 2]                                 | (you have to be in the rail lab)
|   1. Incoming Port :3000  --->  Pi (192.168.1.27) :3000           |
|   2. Incoming Port :8080  --->  Pi (192.168.1.27) :8080           |
+-------------------------------------------------------------------+
                       |                          |
(Path 1: SSH Access)   |                          | (Path 2: Web App Access)
                       |                          |
                       v                          v
+----------------------+--------------------------+-------------------+
|               Raspberry Pi (Internal IP: 192.168.1.27)             |
|                                                                    |
|     :3000 (sshd service)                    :8080 (Docker host port) |
+---------|--------------------------------------|-------------------+
          |                                      | (Docker Port Mapping)
          v                                      v
    [ SSH Service ]                  [ Docker Container ]
                                     [ Web App on Port :5000 ]```
