#!/usr/bin/env bash
# Book Organiser — Raspberry Pi / CasaOS one-command installer.
# Idempotent: safe to re-run; it only creates missing dirs / files.
#
#   curl -fsSL <this-repo>/install_pi.sh | bash
#   (or copy the repo to the Pi and run:  bash install_pi.sh)

set -euo pipefail

cd "$(dirname "$0")"

say()  { printf '\033[1;32m[book-organiser]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[book-organiser]\033[0m %s\n' "$*" >&2; }

say "Installing Book Organiser on $(uname -m) ($(uname -s))"

# ── 1. Check Docker + Compose ────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker not found. Install CasaOS (ships Docker) or:"
  warn "  curl -fsSL https://get.docker.com | sh"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  warn "docker compose plugin not found. Run: sudo apt install docker-compose-plugin"
  exit 1
fi

# ── 2. Storage layout ─────────────────────────────────────────
# Sensible defaults for a Pi: SSD data, SD config, media/NAS books.
DATA_HOST_PATH="${DATA_HOST_PATH:-/mnt/ssd/book-organiser/data}"
CONFIG_HOST_PATH="${CONFIG_HOST_PATH:-/mnt/sd/book-organiser/config}"
BOOKS_HOST_PATH="${BOOKS_HOST_PATH:-/mnt/media_ssd/books}"

for d in "$DATA_HOST_PATH" "$CONFIG_HOST_PATH"; do
  if [ -d "$d" ]; then
    say "mount ok: $d"
  else
    warn "$d does not exist yet"
    if sudo -n true 2>/dev/null; then
      sudo mkdir -p "$d" && say "created $d"
    else
      warn "please create it (or point to your media share) and re-run:"
      warn "  sudo mkdir -p $d"
      warn "or set DATA_HOST_PATH/CONFIG_HOST_PATH before running."
    fi
  fi
done
if [ ! -d "$BOOKS_HOST_PATH" ]; then
  warn "Source books dir not found: $BOOKS_HOST_PATH"
  warn "Point BOOKS_HOST_PATH at your books/NAS mount and re-run."
fi

# ── 3. .env scaffold (never overwrite) ───────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s|DATA_HOST_PATH=.*|DATA_HOST_PATH=$DATA_HOST_PATH|" .env
  sed -i "s|CONFIG_HOST_PATH=.*|CONFIG_HOST_PATH=$CONFIG_HOST_PATH|" .env
  sed -i "s|BOOKS_HOST_PATH=.*|BOOKS_HOST_PATH=$BOOKS_HOST_PATH|" .env
  say "wrote .env from .env.example"
else
  say ".env exists — leaving as-is (edit it to change mounts/password)"
fi

# ── 4. Image: pull prebuilt (A) or build locally (B) ──────────
BUILD_OR_PULL="${BUILD_OR_PULL:-pull}"
if [ "$BUILD_OR_PULL" = "pull" ] && [ -n "${BOOK_ORGANISER_IMAGE:-}" ]; then
  say "Pulling image: $BOOK_ORGANISER_IMAGE"
  docker compose pull
elif [ "$BUILD_OR_PULL" = "build" ] || [ -z "${BOOK_ORGANISER_IMAGE:-}" ]; then
  say "Building image locally (needs build-essential; may take a while)"
  docker compose build
fi

# ── 5. Start + health probe ────────────────────────────────────
say "Starting container ..."
docker compose up -d

say "Waiting for /api/health ..."
PORT=$(grep -E '^BOOK_PORT=' .env | cut -d= -f2)
PORT="${PORT:-5000}"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" = "1" ]; then
  say "Up and healthy on http://<pi-ip>:$PORT"
else
  warn "Health check did not pass yet. Inspect logs: docker compose logs -f book-organiser"
fi

say "Done. Next step — expose securely:"
say "  see casaos/cloudflare-tunnel.md (cloudflared sidecar / bare-metal / CasaOS app)"