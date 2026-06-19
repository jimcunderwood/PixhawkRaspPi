#!/bin/bash

# Install and enable the companion computer as a boot-time systemd service.

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="drone-companion"
APP_DIR="${APP_DIR:-/opt/${SERVICE_NAME}}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_USER="${SERVICE_USER:-drone-companion}"
SERVICE_HOME="${SERVICE_HOME:-/var/lib/drone-companion}"
SERVICE_GROUPS="${SERVICE_GROUPS:-video,dialout,gpio}"
SUDO=(sudo)

if [ "${EUID}" -eq 0 ]; then
    SUDO=()
elif ! sudo -n true 2>/dev/null; then
    echo "This installer needs sudo to write ${SERVICE_FILE} and enable systemd startup."
    echo "Run it from the Pi with:"
    echo "  cd ${SOURCE_DIR}"
    echo "  sudo ./install_service.sh"
    exit 1
fi

if [ ! -f "${SOURCE_DIR}/.env" ]; then
    if [ -f "${SOURCE_DIR}/.env.example" ]; then
        echo "Missing ${SOURCE_DIR}/.env; creating it from .env.example so the service can boot."
        cp "${SOURCE_DIR}/.env.example" "${SOURCE_DIR}/.env"
    else
        echo "Missing ${SOURCE_DIR}/.env and .env.example."
        exit 1
    fi
fi

echo "Installing ${SERVICE_NAME} from ${SOURCE_DIR} to ${APP_DIR}"

if [ "${SOURCE_DIR}" != "${APP_DIR}" ]; then
    "${SUDO[@]}" mkdir -p "${APP_DIR}"
    if command -v rsync >/dev/null 2>&1; then
        "${SUDO[@]}" rsync -a --delete \
            --exclude ".git/" \
            --exclude "__pycache__/" \
            --exclude "*.pyc" \
            --exclude "mav.tlog" \
            --exclude "mav.tlog.raw" \
            "${SOURCE_DIR}/" "${APP_DIR}/"
    else
        echo "rsync not found; using tar to copy application files."
        (cd "${SOURCE_DIR}" && tar \
            --exclude ".git" \
            --exclude "__pycache__" \
            --exclude "*.pyc" \
            --exclude "mav.tlog" \
            --exclude "mav.tlog.raw" \
            -cf - .) | (cd "${APP_DIR}" && "${SUDO[@]}" tar -xf -)
    fi
fi

if [ ! -x "${APP_DIR}/venv/bin/python" ]; then
    echo "Missing virtual environment at ${APP_DIR}/venv"
    echo "Run setup from the installed app directory:"
    echo "  cd ${APP_DIR}"
    echo "  sudo ./setup.sh"
    exit 1
fi

if [ ! -f "${APP_DIR}/.env" ]; then
    if [ -f "${APP_DIR}/.env.example" ]; then
        echo "Missing ${APP_DIR}/.env after install copy; creating it from .env.example."
        "${SUDO[@]}" cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
    else
        echo "Missing ${APP_DIR}/.env and .env.example after install copy."
        exit 1
    fi
fi

if ! getent group "${SERVICE_USER}" >/dev/null; then
    echo "Creating system group ${SERVICE_USER}..."
    "${SUDO[@]}" groupadd --system "${SERVICE_USER}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    echo "Creating system user ${SERVICE_USER}..."
    "${SUDO[@]}" useradd \
        --system \
        --gid "${SERVICE_USER}" \
        --home "${SERVICE_HOME}" \
        --create-home \
        --shell /usr/sbin/nologin \
        "${SERVICE_USER}"
else
    "${SUDO[@]}" usermod --gid "${SERVICE_USER}" "${SERVICE_USER}"
fi

IFS=',' read -r -a REQUESTED_GROUPS <<< "${SERVICE_GROUPS}"
EXISTING_GROUPS=()
for group in "${REQUESTED_GROUPS[@]}"; do
    group="$(echo "${group}" | xargs)"
    if [ -z "${group}" ]; then
        continue
    fi
    if getent group "${group}" >/dev/null; then
        EXISTING_GROUPS+=("${group}")
    else
        echo "Skipping missing group: ${group}"
    fi
done

if [ "${#EXISTING_GROUPS[@]}" -gt 0 ]; then
    joined_groups="$(IFS=,; echo "${EXISTING_GROUPS[*]}")"
    echo "Adding ${SERVICE_USER} to groups: ${joined_groups}"
    "${SUDO[@]}" usermod -aG "${joined_groups}" "${SERVICE_USER}"
fi

echo "Preparing runtime data directory ${SERVICE_HOME}..."
"${SUDO[@]}" mkdir -p "${SERVICE_HOME}/photos" "${SERVICE_HOME}/spray-sessions" "${SERVICE_HOME}/missions" "${SERVICE_HOME}/audit" "${SERVICE_HOME}/ppk" "${SERVICE_HOME}/application-records"
"${SUDO[@]}" chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SERVICE_HOME}"
"${SUDO[@]}" chmod 750 "${SERVICE_HOME}"
"${SUDO[@]}" chown -R "root:${SERVICE_USER}" "${APP_DIR}"
"${SUDO[@]}" find "${APP_DIR}" -type d -exec chmod 750 {} \;
"${SUDO[@]}" chmod 640 "${APP_DIR}/.env"
if [ -x "${APP_DIR}/setup.sh" ]; then
    "${SUDO[@]}" chmod 750 "${APP_DIR}/setup.sh"
fi
if [ -x "${APP_DIR}/install_service.sh" ]; then
    "${SUDO[@]}" chmod 750 "${APP_DIR}/install_service.sh"
fi

grant_app_access() {
    if ! command -v setfacl >/dev/null 2>&1; then
        return 1
    fi

    echo "Granting ${SERVICE_USER} read/execute access to ${APP_DIR} with ACLs..."
    local dir="${APP_DIR}"
    while [ "${dir}" != "/" ]; do
        "${SUDO[@]}" setfacl -m "u:${SERVICE_USER}:--x" "${dir}"
        dir="$(dirname "${dir}")"
    done
    "${SUDO[@]}" setfacl -R -m "u:${SERVICE_USER}:rX" "${APP_DIR}"
    "${SUDO[@]}" setfacl -R -d -m "u:${SERVICE_USER}:rX" "${APP_DIR}"
}

if ! "${SUDO[@]}" -u "${SERVICE_USER}" test -r "${APP_DIR}/main.py"; then
    if ! grant_app_access; then
        echo "Service user ${SERVICE_USER} cannot read ${APP_DIR}/main.py."
        echo "Install the acl package, move the app to /opt/${SERVICE_NAME}, or grant an ACL manually."
        exit 1
    fi
fi

if ! "${SUDO[@]}" -u "${SERVICE_USER}" test -x "${APP_DIR}/venv/bin/python"; then
    if ! grant_app_access; then
        echo "Service user ${SERVICE_USER} cannot execute ${APP_DIR}/venv/bin/python."
        echo "Install the acl package, move the app to /opt/${SERVICE_NAME}, or grant an ACL manually."
        exit 1
    fi
fi

supplementary_groups=""
if [ "${#EXISTING_GROUPS[@]}" -gt 0 ]; then
    supplementary_groups="SupplementaryGroups=$(IFS=' '; echo "${EXISTING_GROUPS[*]}")"
fi

"${SUDO[@]}" tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Agricultural Drone Companion Computer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
${supplementary_groups}
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=APP_DATA_DIRECTORY=${SERVICE_HOME}
Environment=PHOTO_DIRECTORY=${SERVICE_HOME}/photos
Environment=SPRAY_SESSION_DIRECTORY=${SERVICE_HOME}/spray-sessions
Environment=MISSION_FILE=${SERVICE_HOME}/missions/mission.json
Environment=AUDIT_LOG_FILE=${SERVICE_HOME}/audit/events.jsonl
Environment=PPK_LOG_DIRECTORY=${SERVICE_HOME}/ppk
Environment=SPRAY_APPLICATION_RECORD_DIRECTORY=${SERVICE_HOME}/application-records
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
