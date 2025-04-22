FROM nvcr.io/hpc/relion:5.0.0

LABEL maintainer="walid"

# Point to existing CUDA
ENV CUDA_HOME=/usr/local/cuda
ENV CUDAHOME=/usr/local/cuda
ENV PATH=/usr/local/cuda/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
ENV CPATH=/usr/local/cuda/include:$CPATH

ENV PATH=/usr/local/relion/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/relion/lib:$LD_LIBRARY_PATH

# Add NVIDIA CUDA repo for Ubuntu 22.04 (CUDA 12.3)
#RUN apt-get update && apt-get install -y wget gnupg ca-certificates && \
#    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb && \
#    dpkg -i cuda-keyring_1.1-1_all.deb && \
#    apt-get update

# Install system + EMHub dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    #cuda-toolkit-12-3 \
    #libcufft-dev-12-3 \
    #libcurand-dev-12-3 \
    software-properties-common \
    git \
    curl \
    wget \
    unzip \
    #python3-pip \
    libxml2-dev \
    libxslt1-dev \
    libfftw3-dev \
    libpng-dev \
    libjpeg-dev \
    libtiff5-dev \
    redis \
    redis-server \
    libopenblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    gfortran \
    build-essential \
    #python3-redis \
    #python3-hiredis \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y \
    python3.8 \
    python3.8-dev \
    python3.8-distutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# Install PIP
RUN curl -O https://bootstrap.pypa.io/get-pip.py \
    && python3.8 get-pip.py \
    && rm get-pip.py

RUN pip3 install --upgrade pip setuptools wheel

RUN apt-get update && apt-get install -y \
    libgtk-3-dev \
    libglib2.0-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

#RUN pip3 install --use-pep517 nvidia-pyindex
RUN pip3.8 install --use-pep517 "cryolo[cu11]"

# Install MotionCor3
RUN wget https://github.com/czimaginginstitute/MotionCor3/releases/download/v1.0.1/MotionCor3_1.0.1_10-26-2023.zip && \
    unzip /opt/MotionCor3_1.0.1_10-26-2023.zip && \
    cp /opt/MotionCor3_1.0.1_Cuda122_10-26-2023 /usr/bin/MotionCor3 && rm /opt/MotionCor3*

# Install cisTEM (includes ctffind5)
WORKDIR /opt
RUN curl -L -o cistem.tar.gz https://grigoriefflab.umassmed.edu/sites/default/files/cistem-1.0.0-beta-intel-linux.tar.gz && \
    tar -xzf cistem.tar.gz && \
    rm cistem.tar.gz && \
    cp /opt/cistem-1.0.0-beta/ctffind* /usr/local/bin/ && \
    rm -r /opt/cistem-1.0.0-beta

# Build MotionCor3
#RUN git clone https://github.com/czimaginginstitute/MotionCor3.git /opt/motioncor3
#WORKDIR /opt/motioncor3
# Testing
#ENV CXXFLAGS="-no-pie"
#ENV LDFLAGS="-no-pie"
#RUN make -j 8 exe -f makefile11 CUDAHOME=$CUDA_HOME

#RUN apt-get update && apt-get install -y --no-install-recommends \
#    python3 \
#    python3-dev \
#    python3-distutils \
#    && rm -rf /var/lib/apt/lists/*

# Install PIP 3.10
#RUN curl -O https://bootstrap.pypa.io/get-pip.py \
#    && python3.10 get-pip.py \
#    && rm get-pip.py

RUN pip3 install "redis[hiredis]"

RUN pip3 install "setuptools<65"

# In Dev Mode
#
# Install EMTools
RUN git clone https://github.com/3dem/emtools.git /opt/emtools && \
    pip3 install -e /opt/emtools/

# Clone the EMHub repository
RUN git clone https://github.com/3dem/emhub.git /opt/emhub && \
    pip3 install --ignore-installed -e /opt/emhub/

# Install crYOLO cli
#RUN apt-get update && apt-get install -y \
#    && rm -rf /var/lib/apt/lists/*

#RUN pip3 install 'cryolo[c11]'

# fake libtiff.so.6 for relion
RUN cp /lib/x86_64-linux-gnu/libtiff.so.5 /lib/x86_64-linux-gnu/libtiff.so.6

# Copy the Relion binaries
RUN cp /usr/local/relion/sm80/bin/* /usr/local/bin && \
    cp /usr/local/relion/sm80/lib/* /usr/local/lib

WORKDIR /root

# Set working directory for EMHub
#ENV EMHUB_INSTANCE=/instance

#CMD ["bash", "/instance/run_emhub.sh"]

## Build the AreTomo3 executable
#RUN make exe -f makefile11 CUDAHOME=$CUDA_HOME
#
## Add AreTomo3 to path
#ENV PATH=/opt/AreTomo3:$PATH
#
## Reset the working directory to default
#WORKDIR /
#
## Set entrypoint
#ENTRYPOINT ["AreTomo3"]
#
## CMD to provide a default action
#CMD ["--help"]

