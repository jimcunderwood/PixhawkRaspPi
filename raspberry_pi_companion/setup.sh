#!/bin/bash

# Raspberry Pi 4 Companion Computer Setup Script
# Installs dependencies and configures the system

set -e

echo "=== Agricultural Drone Companion Computer Setup ==="

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and pip
echo "Installing Python development tools..."
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update && sudo apt-get install -y \
  git \
  curl \
  libssl-dev \
  libffi-dev \
  libjpeg-dev \
  zlib1g-dev \
  libopenblas-dev \
  libharfbuzz0b \
  libtiff-dev


# Enable serial interface for Pixhawk communication (Raspberry Pi only)
if command -v raspi-config &> /dev/null; then
    echo "Enabling serial interface..."
    sudo raspi-config nonint do_serial_hw 0
    sudo raspi-config nonint do_serial_console 1
else
    echo "Skipping serial interface setup (not on Raspberry Pi)"
fi

# Create virtual environment
echo "Creating Python virtual environment..."
cd "$(dirname "$0")"
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install Python requirements
echo "Installing Python requirements..."
pip install -r requirements.txt

# Fix dronekit Python 3.10+ compatibility issue
echo "Patching dronekit for Python 3.10+..."
DRONEKIT_PATH=$(python -c "import dronekit; import os; print(os.path.dirname(dronekit.__file__))")
if [ -f "$DRONEKIT_PATH/__init__.py" ]; then
    sed -i 's/collections\.MutableMapping/collections.abc.MutableMapping/g' "$DRONEKIT_PATH/__init__.py"
    echo "dronekit patched successfully"
fi

echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env and configure settings"
echo "2. Run: source venv/bin/activate"
echo "3. Run: python main.py"
echo ""
echo "For systemd service setup, see docs/SETUP.md"
