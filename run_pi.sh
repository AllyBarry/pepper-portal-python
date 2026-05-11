#!/bin/bash

# Before running, run this to allow connections to X server
# xhost +local:docker
# When complete, run:
# xhost -local:docker
# table, complex, fetch robot. Finite table of results for fetch robot. First redo that main table which env does better
# 1. Show the indepdent for training and 
# 2. Infrustructure

# Change to 'run -d' to run in detached mode.
echo $(pwd)/src
echo $DISPLAY 

docker rm pepper_portal
docker run -it \
  --platform linux/amd64 \
  -v "$(pwd)/src:/home/user/src" \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  --name pepper_portal \
  -w /home/user \
  -p 8088:5000 \
  pepper-portal-python
