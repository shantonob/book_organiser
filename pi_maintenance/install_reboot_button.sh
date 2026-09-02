#!/usr/bin/env bash
# Installer for the Homarr restart-Pi button service.
# Usage: sudo bash pi_maintenance/install_reboot_button.sh [TOKEN]
#   TOKEN (optional): secret used to protect the endpoint. If omitted, a random
#   one is generated and printed. Put this same value in the Homarr tile URL.

set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN="${1:-}"
ENV_DIR=/etc/book-pi

say()  { printf '\033[1;32m[pi-reboot]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[pi-reboot]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# 1. Generate token if not provided
if [ -z "$TOKEN" ]; then
  TOKEN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' )"
  TOKEN="${TOKEN:0:24}"
fi

# 2. Install the script + env + unit
install -m 0755 "${SERVICE_DIR}/reboot_server.py" /usr/local/sbin/book-pi-reboot.py
mkdir -p "$ENV_DIR"
umask 077
printf 'REBOOT_TOKEN=%s\n' "$TOKEN" > "$ENV_DIR/reboot.env"
chmod 600 "$ENV_DIR/reboot.env"
install -m 0644 "${SERVICE_DIR}/book-pi-reboot.service" /etc/systemd/system/book-pi-reboot.service

systemctl daemon-reload
systemctl enable --now book-pi-reboot.service
say "restart service installed & started (port 8900)"

# 3. Report the URL to put in the Homarr tile
URL="http://192.168.68.110:8900/?key=${TOKEN}"
say "Homarr tile URL:  ${URL}"
say "WARNING: keep this URL private — anyone on your LAN with it can restart the Pi."
