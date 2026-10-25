"""Liest den Anzeigentext und sucht die Bewerbungsadresse. POST /api/vorbereiten mit {"anzeigen": [{id, quelle, refnr oder link}]} (höchstens 12)."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _lib import BA_REFNR, ST_ANZEIGE, antwort, ba_text, mail_finden, mail_unsicher, st_text  # noqa: E402

MAX = 12


def lesen(a):
    fehler = ""
    try:
        if a.get("quelle") == "Arbeitsagentur" and BA_REFNR.match(str(a.get("refnr", ""))):
            text = ba_text(a["refnr"])
        elif a.get("quelle") == "StepStone" and ST_ANZEIGE.match(str(a.get("link", ""))):
            text = st_text(a["link"])
            if not text:
                fehler = "Anzeigentext nicht gefunden (Seite umgebaut oder blockiert)"
        else:
            return {"id": a.get("id", ""), "an": "", "unsicher": "", "lesefehler": "Diese Quelle wird online nicht unterstützt"}
    except Exception as e:
        text, fehler = "", (str(e).strip().splitlines() or [type(e).__name__])[0]
    return {"id": a["id"], "an": mail_finden(text), "unsicher": mail_unsicher(text), **({"lesefehler": fehler} if fehler else {})}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            laenge = int(self.headers.get("Content-Length", "0"))
            if not 0 < laenge <= 20000:
                return antwort(self, 400, {"fehler": "Ungültige Anfrage."})
            liste = json.loads(self.rfile.read(laenge)).get("anzeigen", [])
            if not isinstance(liste, list) or not 0 < len(liste) <= MAX or not all(isinstance(a, dict) and a.get("id") for a in liste):
                return antwort(self, 400, {"fehler": f"Bitte 1 bis {MAX} Anzeigen schicken."})
            with ThreadPoolExecutor(4) as pool:
                return antwort(self, 200, {"ergebnisse": list(pool.map(lesen, liste))})
        except ValueError:
            return antwort(self, 400, {"fehler": "Ungültige Anfrage."})
        except Exception as e:
            return antwort(self, 502, {"fehler": f"Fehler beim Lesen der Anzeigen ({type(e).__name__})."})
