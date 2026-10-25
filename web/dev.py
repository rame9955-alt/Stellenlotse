"""Lokaler Testserver für die Web-Version: liefert web/ aus und führt api/*.py aus wie Vercel. Aufruf: python dev.py [Port]"""
import importlib.util
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ORDNER = Path(__file__).parent
sys.path.insert(0, str(ORDNER / "api"))


def funktion(name):
    pfad = ORDNER / "api" / f"{name}.py"
    if name.startswith("_") or not pfad.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"api_{name}", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.handler


class Dev(BaseHTTPRequestHandler):
    def _api(self, methode):
        klasse = funktion(urlparse(self.path).path[len("/api/"):])
        if not klasse or not hasattr(klasse, methode):
            return self.send_error(404)
        getattr(klasse, methode)(self)  # die Funktionen benutzen nur self.path, self.headers, self.rfile und self.send_*

    def do_GET(self):
        pfad = urlparse(self.path).path
        if pfad.startswith("/api/"):
            return self._api("do_GET")
        datei = (ORDNER / (pfad.lstrip("/") or "index.html")).resolve()
        if ORDNER not in datei.parents or not datei.is_file():
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(datei.name)[0] or "application/octet-stream")
        self.end_headers()
        self.wfile.write(datei.read_bytes())

    def do_POST(self):
        self._api("do_POST")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4920
    print(f"Stellenlotse Web läuft auf http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
