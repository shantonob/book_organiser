#!/usr/bin/env bash
# One-shot installer: apt security auto-updates + systemd timer + watchtower + log server.
# Usage: sudo bash pi_maintenance/install_updates.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_DIR="${REPO_ROOT}/pi_maintenance"
LOG=/var/log/book-pi-updates/updates.log
LOG_DIR=/var/log/book-pi-updates

say()  { printf '\033[1;32m[pi-updates]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[pi-updates]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[pi-updates]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# ── 1. OS security patches via unattended-upgrades ──────────────────
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
# enable automatic security-only upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
say "unattended-upgrades enabled (security patches only)"

# ── 2. Nightly script + systemd timer ───────────────────────────────
sed "s|{{BOOK_COMPOSE_DIR}}|$REPO_ROOT|g" "${SERVICE_DIR}/updates.sh" > /usr/local/sbin/book-pi-updates.sh
chmod +x /usr/local/sbin/book-pi-updates.sh

install -m 0644 "${SERVICE_DIR}/book-pi-updates.service" /etc/systemd/system/book-pi-updates.service
install -m 0644 "${SERVICE_DIR}/book-pi-updates.timer"  /etc/systemd/system/book-pi-updates.timer
install -m 0644 "${SERVICE_DIR}/book-pi-log-server.service" /etc/systemd/system/book-pi-log-server.service

# ensure aptitude never asks questions during our nightly run
grep -q '^unattended-upgrades' /etc/apt/apt.conf.d/50unattended-upgrades ||
  sed -i 's|^//Unattended-Upgrade::Automatic-Reboot "false";|Unattended-Upgrade::Automatic-Reboot "false";|' /etc/apt/apt.conf.d/50unattended-upgrades
# sanity: never let unattended-upgrades itself auto-reboot (we gate it)
if grep -q 'Automatic-Reboot "true"' /etc/apt/apt.conf.d/50unattended-upgrades; then
  sed -i 's|Automatic-Reboot "true"|Automatic-Reboot "false"|g' /etc/apt/apt.conf.d/50unattended-upgrades
fi

systemctl daemon-reload
systemctl enable --now book-pi-updates.timer
systemctl enable --now book-pi-log-server.service
say "nightly timer + log server started"

systemctl list-timers book-pi-updates.timer --no-pager || true

# ── 3. Watchtower (auto-update all other containers) ────────────────
if docker compose version >/dev/null 2>&1; then
  ( cd "$REPO_ROOT" && docker compose -f pi_maintenance/watchtower.yml up -d )
  say "watchtower started (runs daily 05:00; skips book-organiser via label)"
else
  warn "docker compose missing — watchtower not started"
fi

# ── 4. Report log location ──────────────────────────────────────────
mkdir -p "$LOG_DIR"
touch "$LOG"
say "updates script installed at /usr/local/sbin/book-pi-updates.sh"
say "log: $LOG  (served at http://<pi-ip>:8088/updates.log for the Homarr tile)"
say "done."