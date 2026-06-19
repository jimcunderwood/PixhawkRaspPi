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
    if ! "${SUDO[@]}" raspi-config nonint do_serial_hw 0; then
        echo "Warning: could not enable UART hardware through raspi-config."
    fi
    if ! "${SUDO[@]}" raspi-config nonint do_serial_cons 1; then
        echo "Warning: could not disable serial console through raspi-config."
        echo "Continuing setup; you may need to disable the console manually if the Pixhawk uses serial0."
    fi
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
DRONEKIT_PATH=$(
    python - <<'PY'
import glob
import os
import sysconfig

candidates = []
for key in ("purelib", "platlib"):
    base = sysconfig.get_paths().get(key)
    if base:
        candidates.extend(glob.glob(os.path.join(base, "dronekit", "__init__.py")))

for candidate in candidates:
    if os.path.isfile(candidate):
        print(candidate)
        break
PY
)
if [ -n "$DRONEKIT_PATH" ] && [ -f "$DRONEKIT_PATH" ]; then
    sed -i \
        -e 's/collections\.MutableMapping/collections.abc.MutableMapping/g' \
        -e 's/collections\.Mapping/collections.abc.Mapping/g' \
        -e 's/collections\.Iterable/collections.abc.Iterable/g' \
        -e 's/collections\.Sequence/collections.abc.Sequence/g' \
        "$DRONEKIT_PATH"
    echo "dronekit patched successfully at $DRONEKIT_PATH"
else
    echo "Warning: could not locate dronekit for compatibility patching."
fi

if [ "${INSTALL_SYSTEMD_SERVICE:-1}" != "0" ] && [ -x "./install_service.sh" ]; then
    echo "Installing and enabling the drone-companion systemd service..."
    sudo ./install_service.sh
fi

echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env and configure settings if needed"
echo "2. Run: source venv/bin/activate"
echo "3. Run: python main.py"
echo "4. Re-run ./setup.sh with INSTALL_SYSTEMD_SERVICE=1 to install boot startup"
echo ""
echo "For more systemd service details, see docs/SETUP.md"
