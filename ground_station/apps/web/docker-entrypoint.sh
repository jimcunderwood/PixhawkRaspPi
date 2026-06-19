#!/bin/sh
set -eu

cat > /usr/share/nginx/html/runtime-config.json <<EOF
{"companionBaseUrl":"${COMPANION_BASE_URL:-}"}
EOF
