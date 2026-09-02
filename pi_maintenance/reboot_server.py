#!/usr/bin/env python3
"""Book Pi: tiny web service that allows restarting this Raspberry Pi.

Safety: the reboot endpoint requires a secret key, and shows a confirmation
page before actually rebooting. Runs as root via systemd so it can call
`systemctl reboot` directly.

Usage to trigger a restart (from Homarr tile):
    GET /?key=<TOKEN>      -> confirmation page with a Restart button
    GET /go?key=<TOKEN>     -> schedules `systemctl reboot +2` and returns a page

Hardcode the TOKEN below (see /etc/systemd/system/book-pi-reboot.service).
"""

import html
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("REBOOT_TOKEN", "")

PORT = 8900
HOST = "0.0.0.0"


class Handler(BaseHTTPRequestHandler):
    def _key_ok(self, query):
        return parse_qs(query).get("key", [""])[0] == TOKEN

    def _send(self, body, status=200, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if not self._key_ok(url.query):
            self._send("<h1>403 Forbidden</h1><p>Invalid or missing key.</p>", status=403)
            return
        if url.path == "/go":
            # schedule reboot shortly after responding
            self._send(
                "<html><head><meta charset='utf-8'><title>Restarting…</title>"
                "<style>body{font-family:sans-serif;background:#111;color:#eee;"
                "text-align:center;padding-top:15vh}code{background:#333;padding:2px 6px}"
                "</style></head><body><h1>Pi is restarting…</h1>"
                "<p>This page will go unreachable for a minute or two.</p></body></html>"
            )
            threading = __import__("threading")
            threading.Timer(
                2.0,
                lambda: subprocess.run(["systemctl", "reboot"], check=False),
            ).start()
            return
        # confirmation page
        self._send(
            "<html><head><meta charset='utf-8'><title>Restart Pi</title>"
            "<style>body{font-family:sans-serif;background:#111;color:#eee;"
            "text-align:center;padding-top:12vh}.warn{background:#3a1d1d;border:1px solid #e05555;"
            "display:inline-block;padding:24px 32px;border-radius:10px}code{background:#333;"
            "padding:2px 6px}a.btn{display:inline-block;margin-top:14px;padding:10px 22px;"
            "background:#d33;color:#fff;text-decoration:none;border-radius:6px}"
            "a.btn:hover{background:#f44;background:#0000}</style>"
            "</head><body><div class='warn'><h1>Restart Raspberry Pi?</h1>"
            "<p>This will reboot <b>192.168.68.110</b> and briefly take every"
            " self-hosted service offline.</p>"
            f"<a class='btn' href='/go?key={html.escape(TOKEN)}'>Yes, restart now</a>"
            "</div></body></html>"
        )

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%F %T"), fmt % args), flush=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("REBOOT_TOKEN env var must be set")
    print(f"book-pi-reboot listening on {HOST}:{PORT}", flush=True)
    HTTPServer((HOST, PORT), Handler).serve_forever()
