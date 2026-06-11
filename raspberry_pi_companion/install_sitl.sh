#!/bin/bash

# PX4 SITL install helper for Raspberry Pi
# This script installs the minimum packages required to run PX4 SITL on the Pi.
# If the px4-sitl package is available in apt, it will install that first.
# Otherwise it installs build dependencies and leaves the source checkout for manual build.

set -e

echo "=== PX4 SITL install helper ==="

echo "Updating package lists..."
sudo apt-get update

echo "Installing SITL dependencies..."
sudo apt-get install -y \
    git \
    python3-pip \
    python3-venv \
    build-essential \
    cmake \
    ninja-build \
    genromfs \
    pkg-config \
    python3-jinja2 \
    python3-numpy \
    python3-empy \
    python3-dev \
    python3-yaml \
    libxml2-utils \
    libtool \
    libeigen3-dev \
    libopencv-dev \
    libopencv-core-dev \
    libopencv-imgproc-dev \
    libasio-dev \
    libtinyxml2-dev \
    libgeographic-dev

echo "Checking for px4-sitl package..."
if apt-cache show px4-sitl >/dev/null 2>&1; then
    echo "Installing px4-sitl from apt..."
    sudo apt-get install -y px4-sitl
    echo "PX4 SITL package installed."
    exit 0
fi

echo "px4-sitl package not available via apt."

echo "If you need a PX4 source build, clone the firmware repository and build manually:"
echo "  git clone https://github.com/PX4/PX4-Autopilot.git"
echo "  cd PX4-Autopilot"
echo "  git submodule update --init --recursive"
echo "  make px4_sitl_default none_iris"

echo "For local SITL, set .env to use UDP inbound mode and start SITL so it sends packets to the Pi."

echo "Installation helper complete."
