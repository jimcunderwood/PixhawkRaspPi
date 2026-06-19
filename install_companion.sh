#!/usr/bin/env bash

# Bootstrap installer for the Raspberry Pi companion package.
# It downloads the latest GitHub release asset by default, extracts it,
# and runs the companion setup script from the release bundle.

set -euo pipefail

REPO="${COMPANION_REPO:-jimcunderwood/PixhawkRaspPi}"
ARCHIVE_PREFIX="${COMPANION_ARCHIVE_PREFIX:-drone-companion}"
ARCHIVE_URL="${COMPANION_ARCHIVE_URL:-}"
TMP_ROOT=""

usage() {
    cat <<'EOF'
Usage:
  ./install_companion.sh [local-archive.tar.gz|https://...tar.gz]

Environment overrides:
  COMPANION_REPO=jimcunderwood/PixhawkRaspPi
  COMPANION_ARCHIVE_URL=https://...
  COMPANION_ARCHIVE_PREFIX=drone-companion

Examples:
  curl -fsSL https://raw.githubusercontent.com/jimcunderwood/PixhawkRaspPi/main/install_companion.sh | bash
  ./install_companion.sh ./dist/drone-companion-1.0.0.tar.gz
EOF
}

cleanup() {
    if [ -n "${TMP_ROOT}" ] && [ -d "${TMP_ROOT}" ]; then
        rm -rf "${TMP_ROOT}"
    fi
}

fail() {
    echo "Error: $*" >&2
    exit 1
}

download_file() {
    local url="$1"
    local output="$2"

    command -v curl >/dev/null 2>&1 || fail "curl is required to download the release archive."
    curl -fL --retry 3 --connect-timeout 15 -o "${output}" "${url}"
}

resolve_latest_asset_url() {
    local api_url="https://api.github.com/repos/${REPO}/releases/latest"

    command -v curl >/dev/null 2>&1 || fail "curl is required to query GitHub releases."
    command -v python3 >/dev/null 2>&1 || fail "python3 is required to parse the GitHub release metadata."

    curl -fsSL -H "Accept: application/vnd.github+json" "${api_url}" | \
        python3 -c '
import json
import sys

prefix = sys.argv[1]
release = json.load(sys.stdin)
assets = release.get("assets", [])

matches = [
    asset.get("browser_download_url", "")
    for asset in assets
    if asset.get("name", "").startswith(prefix) and asset.get("name", "").endswith(".tar.gz")
]

if not matches:
    matches = [
        asset.get("browser_download_url", "")
        for asset in assets
        if asset.get("name", "").endswith(".tar.gz")
    ]

if not matches:
    raise SystemExit("No .tar.gz asset found in the latest release.")

print(matches[0])
' "${ARCHIVE_PREFIX}"
}

find_setup_dir() {
    local root_dir="$1"
    local setup_path

    if [ -f "${root_dir}/setup.sh" ]; then
        echo "${root_dir}"
        return
    fi

    setup_path="$(find "${root_dir}" -maxdepth 2 -type f -name setup.sh | head -n 1)"
    if [ -z "${setup_path}" ]; then
        fail "Could not find setup.sh inside the extracted archive."
    fi

    dirname "${setup_path}"
}

trap cleanup EXIT

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

TMP_ROOT="$(mktemp -d)"
ARCHIVE_PATH="${TMP_ROOT}/drone-companion.tar.gz"
EXTRACT_ROOT="${TMP_ROOT}/extract"
mkdir -p "${EXTRACT_ROOT}"

SOURCE_SPEC="${1:-}"

if [ -n "${SOURCE_SPEC}" ] && [ -f "${SOURCE_SPEC}" ]; then
    cp "${SOURCE_SPEC}" "${ARCHIVE_PATH}"
elif [ -n "${SOURCE_SPEC}" ] && [[ "${SOURCE_SPEC}" =~ ^https?:// ]]; then
    download_file "${SOURCE_SPEC}" "${ARCHIVE_PATH}"
elif [ -n "${ARCHIVE_URL}" ]; then
    download_file "${ARCHIVE_URL}" "${ARCHIVE_PATH}"
else
    download_file "$(resolve_latest_asset_url)" "${ARCHIVE_PATH}"
fi

tar -xzf "${ARCHIVE_PATH}" -C "${EXTRACT_ROOT}"

SETUP_DIR="$(find_setup_dir "${EXTRACT_ROOT}")"
cd "${SETUP_DIR}"

if [ ! -x ./setup.sh ]; then
    chmod +x ./setup.sh ./install_service.sh 2>/dev/null || true
fi

if [ -f .env.example ] && [ ! -f .env ]; then
    cp .env.example .env
fi

echo "Installing companion from ${SETUP_DIR}"
echo "Release repo: ${REPO}"

INSTALL_SYSTEMD_SERVICE="${INSTALL_SYSTEMD_SERVICE:-1}" ./setup.sh

echo "Installation complete."
echo "If the service was enabled, check it with: sudo systemctl status drone-companion"
