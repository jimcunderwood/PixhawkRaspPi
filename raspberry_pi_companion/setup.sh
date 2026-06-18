#!/bin/bash

# Raspberry Pi 4 Companion Computer Setup Script
# Installs dependencies and configures the system

set -euo pipefail

SUDO=(sudo)
if [ "${EUID}" -eq 0 ]; then
    SUDO=()
elif ! sudo -n true 2>/dev/null; then
    echo "This setup script needs sudo to install system packages and configure serial access."
    echo "Run it from the Pi with:"
    echo "  cd $(cd "$(dirname "$0")" && pwd)"
    echo "  sudo ./setup.sh"
    exit 1
fi

echo "=== Agricultural Drone Companion Computer Setup ==="

# Update system
echo "Updating system packages..."
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get upgrade -y

# Install Python and pip
echo "Installing Python development tools..."
"${SUDO[@]}" apt-get install -y \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential

# Install system dependencies
echo "Installing system dependencies..."
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y \
  git \
  curl \
  ripgrep \
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
    "${SUDO[@]}" raspi-config nonint do_serial_hw 0
    "${SUDO[@]}" raspi-config nonint do_serial_console 1
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
echo "4. Install to /opt and enable boot startup: sudo ./install_service.sh"
echo ""
echo "For more systemd service details, see docs/SETUP.md"
