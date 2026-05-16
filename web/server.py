#!/usr/bin/env python3
"""Servidor de preview local. Sirve la raiz del proyecto para que
web/index.html pueda leer data/cartelera.json.

  python3 web/server.py            # http://localhost:8777/web/
  python3 web/server.py 9000       # otro puerto
"""
import http.server
import os
import socketserver
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


with socketserver.TCPServer(("", PORT), H) as httpd:
    url = f"http://localhost:{PORT}/web/"
    print(f"Cartelera CABA -> {url}  (Ctrl+C para salir)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nchau")
