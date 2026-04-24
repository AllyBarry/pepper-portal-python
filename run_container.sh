#!/bin/bash

# Before running, run this to allow connections to X server
# xhost +local:docker
# When complete, run:
# xhost -local:docker

# Change to 'run -d' to run in detached mode.
echo $(pwd)/src
echo $DISPLAY 

docker rm pepper_portal
docker run -it \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/src:/home/user/src \
  --name pepper_portal \
  -w /home/user \
  -p 8080:5000 \
  pepper-portal-python:latest
