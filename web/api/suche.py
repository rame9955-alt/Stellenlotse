"""Suche bei der Arbeitsagentur (alles auf einmal) oder bei StepStone (eine Seite je Aufruf, die Seite fragt weiter).
GET /api/suche?quelle=ba|st&begriff=...&plz=12345&umkreis=10&seite=1"""
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from _lib import antwort, arbeitsagentur, arbeitsagentur_remote, stepstone_seite  # noqa: E402

UMKREISE = {"", "5", "10", "20", "30", "50", "100", "remote"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        quelle, begriff, plz, umkreis = q.get("quelle", ""), q.get("begriff", "").strip(), q.get("plz", ""), q.get("umkreis", "")
        # nur harmlose Eingaben: sonst wäre das ein offener Abruf-Dienst
        if quelle not in ("ba", "st") or not re.fullmatch(r"[\w\s.+#&/-]{2,60}", begriff) or umkreis not in UMKREISE:
            return antwort(self, 400, {"fehler": "Ungültige Eingabe."})
        bundesweit = umkreis == "remote"
        if bundesweit and quelle != "ba":
            return antwort(self, 400, {"fehler": "Bundesweit nur Remote geht nur bei der Arbeitsagentur."})
        if not bundesweit and not re.fullmatch(r"\d{5}", plz):
            return antwort(self, 400, {"fehler": "Bitte eine fünfstellige PLZ angeben."})
        try:
            if quelle == "ba":
                return antwort(self, 200, {"anzeigen": arbeitsagentur_remote(begriff) if bundesweit else arbeitsagentur(begriff, plz, umkreis)})
            seite = int(q.get("seite", "1"))
            if not 1 <= seite <= 8:
                return antwort(self, 400, {"fehler": "Ungültige Seite."})
            return antwort(self, 200, {"anzeigen": stepstone_seite(begriff, plz, umkreis, seite)})
        except Exception as e:
            return antwort(self, 502, {"fehler": f"Die Jobbörse antwortet nicht ({type(e).__name__}). Bitte später noch einmal versuchen."})
