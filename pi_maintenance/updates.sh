#!/usr/bin/env bash
# Nightly Pi maintenance: security patches + container updates + reboot-if-needed.
# Runs as root via systemd timer (pi-updates.timer).

set -uo pipefail

LOG=/var/log/book-pi-updates/updates.log
BOOK_COMPOSE_DIR="{{BOOK_COMPOSE_DIR}}"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
announce() { echo; echo "================================================================" | tee -a "$LOG"; log "$*"; }

announce "Pi updates: starting"

# 1. OS security patches (unattended-upgrades)
announce "1/4 apt-get update + unattended-upgrades"
export DEBIAN_FRONTEND=noninteractive
apt-get update >>"$LOG" 2>&1
unattended-upgrade >>"$LOG" 2>&1 && log "unattended-upgrade OK" || log "unattended-upgrade FAILED"

# 2. Containers: book-organiser (built from Pi source of truth)
if [ -d "$BOOK_COMPOSE_DIR" ] && [ -f "$BOOK_COMPOSE_DIR/docker-compose.yml" ]; then
  announce "2/4 rebuild book-organiser via compose"
  ( cd "$BOOK_COMPOSE_DIR" && docker compose up -d --build --pull always ) >>"$LOG" 2>&1 \
    && log "book-organiser recompose OK" || log "book-organiser recompose FAILED"
else
  log "skip book-organiser recompose (compose dir not found: $BOOK_COMPOSE_DIR)"
fi

# 3. Clean up dangling images
announce "3/4 docker system prune"
docker image prune -f >>"$LOG" 2>&1 && log "prune OK" || log "prune FAILED"

# 4. Reboot ONLY if kernel/docker upgrade requires it
announce "4/4 reboot check"
if [ -f /var/run/reboot-required ] || [ -f /var/lib/update-notifier/reboot-required ]; then
  log "reboot required (kernel/docker/pkg) -> shutting down at 04:00+2min"
  shutdown -r +2 "Pi auto-update requires reboot" >>"$LOG" 2>&1
else
  log "no reboot required"
fi

announce "Pi updates: done"