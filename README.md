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
After cloning this repository, from the root directory, build the image and run the container.

Before doing so, you will need to copy the pynaoqi python2.7 sdk into the root folder: `pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327.tar.gz`. This can be found online.

```bash
# Build the container
docker build -t pepper-portal-python .

# Run the container (use provided script)
./run_container.sh
```

You should now be able to access the web page on your local PC at: `localhost:8080`.

## Development Workflow

The `./src` directory is mounted in the container and updates in real-time, allowing you to:
1. Develop code on your host machine
2. Run and test code from within the Docker container

## Additional Resources

- [NAOqi Getting Started Guide](http://doc.aldebaran.com/2-5/getting_started/index.html)
- [Python SDK Documentation](http://doc.aldebaran.com/2-5/dev/python/intro_python.html)
- [qicli Command Reference](http://doc.aldebaran.com/2-5/dev/libqi/guide/qicli.html)

## TODO
- Debug scene json
- Make json scene GUI
