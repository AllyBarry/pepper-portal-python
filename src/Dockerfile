FROM ubuntu:16.04

ARG PYTHON_VERSION=2.7
ENV HOME=/home/user

# Install dependencies
RUN apt-get update && apt-get install -y iproute2 telnet iputils-ping \
    wget gcc make openssl libffi-dev libgdbm-dev libsqlite3-dev libssl-dev zlib1g-dev \
    libsdl2-dev \
    && apt-get clean

# Build Python from source
WORKDIR /tmp/
RUN wget https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tgz \
  && tar --extract -f Python-$PYTHON_VERSION.tgz \
  && cd ./Python-$PYTHON_VERSION/ \
  && ./configure --with-ensurepip=install --enable-optimizations --prefix=/usr/local \
  && make && make install \
  && cd ../ \
  && rm -r ./Python-$PYTHON_VERSION*

ENV PYTHONPATH=/usr/local/bin/python

# Set the working directory to /naoqi
WORKDIR /naoqi

# Copy the NAOqi for Python SDK
ADD pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327.tar.gz /naoqi/

# Copy the boost fix
# See https://community.ald.softbankrobotics.com/en/forum/import-issue-pynaoqi-214-ubuntu-7956
COPY boost/* /naoqi/pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327/

# Set the path to the SDK
ENV PYTHONPATH=${PYTHONPATH}:/naoqi/pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327/lib/python2.7/site-packages/
ENV LD_LIBRARY_PATH="/naoqi/pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327"

# Install required packages
RUN apt-get update && apt-get install -y python-pip \
    && apt-get clean

RUN python2 -m pip install --upgrade "pip<21" "setuptools<45" "wheel<0.35" \
    && pip install "Flask==1.1.4"

WORKDIR /home/user

ENV HOST=0.0.0.0
ENV PORT=5000
EXPOSE 5000 9559
CMD ["python2", "src/app/flask_app.py"]