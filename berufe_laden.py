"""Einmalig ausführen: holt für jedes Berufsfeld der Arbeitsagentur die häufigsten Berufsbezeichnungen und speichert sie in berufsfelder.json.
Aufruf: python berufe_laden.py   (dauert einige Minuten, später nur zum Auffrischen nötig; danach das Programm neu starten)"""
import json
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import app

SEITEN = 3  # je 100 Stellen pro Berufsfeld, davon die häufigsten Bezeichnungen
MAX_PRO_FELD = 60
GLEICHZEITIG = 3  # bei 6 gleichzeitigen Abfragen hat die Schnittstelle die Verbindung geschlossen
VERSUCHE = 4


def holen(pfad):
    """app._ba_holen mit Wiederholung: ein Verbindungsabbruch soll nicht den ganzen Lauf kosten."""
    for n in range(VERSUCHE):
        try:
            return app._ba_holen(pfad)
        except OSError:
            if n == VERSUCHE - 1:
                raise
            time.sleep(1 + n)


def feld_laden(feld):
    z = Counter()
    for n in range(1, SEITEN + 1):
        liste = holen("v6/jobs?" + urllib.parse.urlencode({"berufsfeld": feld, "size": 100, "page": n})).get("ergebnisliste", [])
        z.update(j["hauptberuf"] for j in liste if j.get("hauptberuf"))
        if len(liste) < 100:
            break
    return feld, [b for b, _ in z.most_common(MAX_PRO_FELD)]


if __name__ == "__main__":
    felder = holen("v6/jobs?size=1&facetten=berufsfeld")["facetten"]["berufsfeld"]["counts"]
    with ThreadPoolExecutor(GLEICHZEITIG) as ex:
        ergebnis = dict(ex.map(feld_laden, felder))
    (Path(__file__).parent / "berufsfelder.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=0), "utf-8")
    print(len(ergebnis), "Berufsfelder,", sum(len(v) for v in ergebnis.values()), "Berufsbezeichnungen")
