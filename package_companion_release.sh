#!/usr/bin/env bash

# Create a small release archive that contains only the companion app files
# needed for end-user installation on a Raspberry Pi.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
COMPANION_DIR="${REPO_ROOT}/raspberry_pi_companion"
DIST_DIR="${REPO_ROOT}/dist"
VERSION="${1:-$(git -C "${REPO_ROOT}" describe --tags --always --dirty 2>/dev/null || date -u +%Y%m%d%H%M%S)}"
ARCHIVE_NAME="drone-companion-${VERSION}.tar.gz"
ARCHIVE_PATH="${DIST_DIR}/${ARCHIVE_NAME}"

mkdir -p "${DIST_DIR}"
rm -f "${ARCHIVE_PATH}"

tar -czf "${ARCHIVE_PATH}" -C "${COMPANION_DIR}" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    main.py \
    requirements.txt \
    setup.sh \
    install_service.sh \
    .env.example \
    README.md \
    QUICKSTART.md \
    PROJECT_STRUCTURE.md \
    docs \
    src

sha256sum "${ARCHIVE_PATH}" > "${ARCHIVE_PATH}.sha256"

echo "Created ${ARCHIVE_PATH}"
echo "SHA256 checksum written to ${ARCHIVE_PATH}.sha256"
echo "Upload ${ARCHIVE_NAME} to your GitHub release assets."
