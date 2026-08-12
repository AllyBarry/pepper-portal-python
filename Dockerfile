FROM ubuntu:16.04

ARG PYTHON_VERSION=2.7
ENV HOME=/home/user

# Install dependencies
RUN apt-get update && apt-get install -y iproute2 telnet iputils-ping \
    wget gcc make openssl libffi-dev libgdbm-dev libsqlite3-dev libssl-dev zlib1g-dev \
    libbz2-dev \
    liblzma-dev pkg-config \
    && apt-get clean

#Build Python from source
WORKDIR /tmp
RUN wget https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tgz \
    && tar --extract -f Python-$PYTHON_VERSION.tgz \
    && cd ./Python-$PYTHON_VERSION/ \
    && ./configure --with-ensurepip=install --enable-optimizations --prefix=/usr/local \
    && make && make install \
    && cd ../ \
    && rm -r ./Python-$PYTHON_VERSION*

ENV PYTHONPATH=/usr/local/bin/python

#Set the working directory to /naoqi
WORKDIR /naoqi

#--- Added: NAOqi SDK version variable ---
ENV sdk_version=pynaoqi-python2.7-2.8.6.23-linux64-20191127_152327
#ENV sdk_version=pynaoqi-python2.7-2.1.4.13-linux32

#Copy the NAOqi for Python SDK
ADD ${sdk_version}.tar.gz /naoqi/

#Copy the boost fix
# See https://community.ald.softbankrobotics.com/en/forum/import-issue-pynaoqi-214-ubuntu-7956
COPY boost/ /naoqi/${sdk_version}/

#Add the path to the SDK
ENV PYTHONPATH=$PYTHONPATH:/naoqi/${sdk_version}/lib/python2.7/site-packages/
ENV PYTHONPATH=$PYTHONPATH:/naoqi/${sdk_version}/
ENV LD_LIBRARY_PATH=/naoqi/${sdk_version}

# Install required packages
RUN apt-get update && apt-get install -y python-pip \
    && apt-get clean

RUN wget -O /tmp/get-pip.py https://bootstrap.pypa.io/pip/2.7/get-pip.py \
    && python2 /tmp/get-pip.py "pip<21" "setuptools<45" "wheel<0.35" \
    && python2 -m pip install \
        "Flask==1.1.4" \
        "Jinja2==2.11.3" \
        "MarkupSafe==1.1.1" \
        "Werkzeug==1.0.1" \
        "itsdangerous==1.1.0" \
        "click==7.1.2" \
    && rm /tmp/get-pip.py

WORKDIR /home/user

ENV HOST=0.0.0.0
ENV PORT=5000
EXPOSE 5000

ENV SCENES_DIR=src/scenes/

CMD ["python2", "src/app/flask_app.py"]
