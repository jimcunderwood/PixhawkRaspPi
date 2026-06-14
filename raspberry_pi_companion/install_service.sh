#!/bin/bash

# Install and enable the companion computer as a boot-time systemd service.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="drone-companion"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="${SUDO_USER:-$USER}"
SUDO=(sudo)

if [ "${EUID}" -eq 0 ]; then
    SUDO=()
elif ! sudo -n true 2>/dev/null; then
    echo "This installer needs sudo to write ${SERVICE_FILE} and enable systemd startup."
    echo "Run it from the Pi with:"
    echo "  cd ${APP_DIR}"
    echo "  sudo ./install_service.sh"
    exit 1
fi

if [ ! -x "${APP_DIR}/venv/bin/python" ]; then
    echo "Missing virtual environment at ${APP_DIR}/venv"
    echo "Run ./setup.sh first."
    exit 1
fi

if [ ! -f "${APP_DIR}/.env" ]; then
    echo "Missing ${APP_DIR}/.env"
    echo "Copy .env.example to .env and configure it before enabling the service."
    exit 1
fi

echo "Installing ${SERVICE_NAME}.service for ${APP_DIR}"

"${SUDO[@]}" tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Agricultural Drone Companion Computer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable "${SERVICE_NAME}"
"${SUDO[@]}" systemctl restart "${SERVICE_NAME}"

echo "${SERVICE_NAME} is enabled and running."
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   sudo journalctl -u ${SERVICE_NAME} -f"
