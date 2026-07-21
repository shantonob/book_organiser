# Cloudflare Tunnel Setup

Once Book Organiser is running in CasaOS on the Pi, expose it securely via Cloudflare Tunnel.

## Option A: cloudflared Docker sidecar (recommended)

Add to `docker-compose.yml`:

```yaml
services:
  book-organiser:
    # ... existing config ...

  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CF_TUNNEL_TOKEN}
```

Then set `CF_TUNNEL_TOKEN` in your `.env` file.

## Option B: Install cloudflared on the Pi directly

```bash
# Install cloudflared on Raspberry Pi (ARM64)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb

# Authenticate
cloudflared tunnel login

# Create a tunnel (one time)
cloudflared tunnel create book-organiser

# Create DNS config
cloudflared tunnel route dns book-organiser books.yourdomain.com

# Create config file: ~/.cloudflared/config.yml
cat << 'EOF' > ~/.cloudflared/config.yml
tunnel: book-organiser
credentials-file: /home/pi/.cloudflared/book-organiser.json

ingress:
  - hostname: books.yourdomain.com
    service: http://localhost:5000
  - service: http_status:404
EOF

# Install as a service
sudo cloudflared service install

# Start
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

## Option C: CasaOS Cloudflared app

Install the Cloudflared app from the CasaOS App Store, then configure it to point to `http://book-organiser:5000` (Docker internal DNS).

## Your domain

Set your domain's DNS in Cloudflare:

```
Type: CNAME
Name: books
Target: <your-tunnel-id>.cfargotunnel.com
Proxy: ✅ (orange cloud)
```

## Verify

```bash
curl https://books.yourdomain.com/api/auth/check
# Should return {"authenticated":false,"enabled":true} if auth is on
```

Then set `BOOK_AUTH_PASSWORD` in the CasaOS app config to protect admin pages.
