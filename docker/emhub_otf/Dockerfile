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
    cuda-toolkit-12-3 \
    libcufft-dev-12-3 \
    libcurand-dev-12-3 \
    software-properties-common \
    git \
    curl \
    wget \
    unzip \
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
    #python3-pip \
    #python3-redis \
    #python3-hiredis \
    && rm -rf /var/lib/apt/lists/*

# crYOLO Dependencies
RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.8 \
    python3.8-dev \
    python3.8-distutils \
    libgtk-3-dev \
    libglib2.0-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Switch to a clean working dir
WORKDIR /opt

# Install PIP 3.8
RUN curl -O https://bootstrap.pypa.io/pip/3.8/get-pip.py \
    && python3.8 get-pip.py \
    && rm get-pip.py

# Install crYOLO
RUN pip3 install --upgrade pip setuptools wheel \
    && pip3 install --use-pep517 "cryolo[cu11]"

# Install MotionCor3
RUN wget https://github.com/czimaginginstitute/MotionCor3/releases/download/v1.0.1/MotionCor3_1.0.1_10-26-2023.zip \
    && unzip /opt/MotionCor3_1.0.1_10-26-2023.zip \
    && cp /opt/MotionCor3_1.0.1_Cuda122_10-26-2023 /usr/bin/MotionCor3 \
    && rm /opt/MotionCor3*

# Install ctffind5
RUN curl -L -o ctffind-5.0.2.tar.gz "https://grigoriefflab.umassmed.edu/system/tdf?path=ctffind-5.0.2.tar.gz&file=1" \
    && tar -xzf ctffind-5.0.2.tar.gz \
    && cp /opt/cisTEM/bin/* /usr/local/bin \
    && rm -r /opt/cisTEM ctffind-5.0.2.tar.gz

# Install Redis & friends
RUN apt -y remove python3-blinker
RUN pip3 install "redis[hiredis]" \
    && pip3 install "setuptools<65" \
    && pip3 install blinker

# Install EMTools
RUN git clone https://github.com/3dem/emtools.git /opt/emtools \
    && pip3 install /opt/emtools/ \
    && rm -r /opt/emtools

# Clone the EMHub repository
RUN git clone https://github.com/3dem/emhub.git /opt/emhub \
    && pip3 install /opt/emhub/ \
    && rm -r /opt/emhub

# Clone the EMWrap respository
RUN git clone https://github.com/3dem/emwrap.git /opt/emwrap \
    && pip3 install /opt/emwrap/ \
    && rm -r /opt/emwrap

# Copy the Relion binaries and fake libtiff.so.6 for relion
RUN cp /lib/x86_64-linux-gnu/libtiff.so.5 /lib/x86_64-linux-gnu/libtiff.so.6 \
    && cp /usr/local/relion/sm80/bin/* /usr/local/bin \
    && cp /usr/local/relion/sm80/lib/* /usr/local/lib

RUN ln -s /usr/bin/python3.8 /usr/bin/python

WORKDIR /root

# Set entrypoint (interactive shell)
ENTRYPOINT ["/bin/bash"]
#
## CMD to provide a default action
#CMD ["--help"]
