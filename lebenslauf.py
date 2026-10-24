"""Lebenslauf lesen und daraus Suchbegriffe und Passungswörter ableiten, ohne KI: feste Liste von Berufen mit ihren Stichwörtern."""
import base64
import io
import json
import os
import re
import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

DATEI = Path(__file__).parent / "lebenslauf.json"  # der zuletzt hochgeladene Lebenslauf samt Text, nur lokal; der Text verlässt den Server nicht
_SPERRE = threading.Lock()  # Upload und KI-Knopf schreiben dieselbe Datei

# Beruf (wird zum Suchbegriff) -> Wörter, die im Lebenslauf für diesen Beruf sprechen und in Anzeigen als Treffer zählen
BERUFE = {
    "IT-Support": ["it-support", "support", "helpdesk", "service desk", "fernwartung", "windows", "microsoft 365", "active directory",
                   "entra", "intune", "netzwerk", "dns", "vpn", "wlan", "druckereinrichtung", "powershell", "bash", "hardware"],
    "Systemadministrator": ["administrator", "administration", "active directory", "entra", "intune", "microsoft 365", "server", "netzwerk",
                            "powershell", "hosting", "deployment", "linux"],
    "Webentwickler": ["next.js", "react", "javascript", "typescript", "node", "postgresql", "supabase", "github", "web-anwendung",
                      "online-shop", "deployment", "vercel", "frontend", "backend"],
    "Disponent": ["disposition", "disponent", "tourenplanung", "fuhrpark", "flotte", "personenbeförderung", "schichtkoordination", "logistik"],
    "Logistik": ["logistik", "lager", "versand", "schichtkoordination", "supply chain", "transport", "verkehrswesen"],
    "Recruiter": ["recruiter", "recruiting", "bewerbermanagement", "interviews", "onboarding", "personalreferent", "personal"],
    "Sachbearbeiter": ["sachbearbeiter", "dateneingabe", "datenmanagement", "dokumentation", "ms office", "excel", "word", "büro", "verwaltung"],
    "Büro": ["büro", "office", "verwaltung", "sekretariat", "assistenz", "ms office", "excel", "dokumentation"],
    "Teamleiter": ["teamleiter", "teamleitung", "teamsteuerung", "führung", "operative leitung", "schichtkoordination"],
    "Projektmanager": ["projektmanager", "projektleitung", "projektmanagement", "prozessoptimierung", "automatisierung", "strategie"],
    "Kundenservice": ["kundenservice", "kundenberatung", "kundensupport", "kundenbetreuung", "beratung", "support"],
    "Buchhaltung": ["buchhaltung", "finanzbuchhaltung", "rechnungswesen", "controlling", "finanzen", "kostenoptimierung"],
}


def text_aus(daten):
    """daten: {"pdf": base64}; liefert den Text des Lebenslaufs."""
    pdf = PdfReader(io.BytesIO(base64.b64decode(daten["pdf"])))
    text = "\n".join(s.extract_text() or "" for s in pdf.pages)
    if len(text.strip()) < 100:
        raise ValueError("Im Lebenslauf konnte kaum Text gelesen werden (Scan ohne Textebene?). Bitte ein PDF mit Text hochladen.")
    return text


FELDER = Path(__file__).parent / "berufsfelder.json"  # von berufe_laden.py: Berufsfeld -> häufigste Berufsbezeichnungen der Arbeitsagentur
ZU_ALLGEMEIN = {"katholisch", "mitarbeiter", "wirtschaft", "spanisch", "englisch", "deutsch", "arabisch", "französisch", "helfer", "fachkraft"}


def _basis(beruf):
    """"Fachinformatiker/in - Systemintegration" -> ["fachinformatiker", "systemintegration"]; zu kurze Teile fallen weg."""
    b = re.sub(r"/[-\w]*", "", re.sub(r"\(.*?\)", "", beruf))
    return [x.strip().lower() for x in re.split(r" - |, ", b) if len(x.strip()) >= 8]


def kommt_vor(wort, t):
    """Ganzes Wort mit höchstens 3 Buchstaben Endung ("Verkäuferin" für "verkäufer"), nicht mitten im Wort ("excel" in "excellent", "word" in "keywords")."""
    return wort in t and re.search(r"(?<!\w)" + re.escape(wort) + r"\w{0,3}(?!\w)", t) is not None  # "wort in t" vorab: spart bei fast allen die teure Regex-Suche


@lru_cache(maxsize=1)  # einmal pro Programmstart aus berufsfelder.json; nach berufe_laden.py das Programm neu starten
def _ba_woerter():
    """[(Berufswort, Berufsfelder)] aus berufsfelder.json; leer, wenn die Datei fehlt."""
    if not FELDER.exists():
        return ()
    woerter = {}
    for feld, berufe in json.loads(FELDER.read_text("utf-8")).items():
        for b in berufe:
            for c in _basis(b):
                if c not in ZU_ALLGEMEIN:
                    woerter.setdefault(c, set()).add(feld)
    return tuple(woerter.items())


def ba_berufe(t):
    """Berufsbezeichnungen der Arbeitsagentur, die im Lebenslauf stehen: {Wort: {Berufsfelder}}."""
    return {c: fs for c, fs in _ba_woerter() if kommt_vor(c, t)}


def profil(text):
    """Berufe: erst aus der festen Liste nach Zahl der Stichwörter (ab 3 Treffer, 2 reichen bei Wörtern wie "finanzen" nicht), dann Berufsbezeichnungen
    der Arbeitsagentur, die im Lebenslauf stehen. Dazu alle gefundenen Wörter für die Passung und die Berufsfelder, in denen die meisten Treffer liegen."""
    t = " ".join(re.sub(r"[^\wäöüß.+# -]+", " ", text.lower()).split())
    treffer = {b: [w for w in ws if kommt_vor(w, t)] for b, ws in BERUFE.items()}
    berufe = sorted((b for b, w in treffer.items() if len(w) >= 3), key=lambda b: -len(treffer[b]))
    ba = ba_berufe(t)
    vorhanden = {b.lower() for b in berufe}
    for c in sorted(ba, key=lambda c: -len(ba[c])):
        if c not in vorhanden:
            berufe.append(c.capitalize())
            treffer[c.capitalize()] = [c]
    woerter = {w for b in berufe for w in treffer[b]}
    felder = sorted({f for fs in ba.values() for f in fs}, key=lambda f: -sum(f in fs for fs in ba.values()))[:5]
    return {"berufe": berufe, "woerter": sorted(woerter), "treffer": {b: treffer[b] for b in berufe}, "felder": felder}


def _speichern(p):
    """Atomar (Hilfsdatei, dann ersetzen), damit ein gleichzeitiges Lesen nie eine halbe Datei sieht."""
    tmp = DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False), "utf-8")
    os.replace(tmp, DATEI)


def hochladen(daten):
    text = text_aus(daten)
    p = profil(text)
    if not p["berufe"]:
        raise ValueError("Im Lebenslauf wurde kein bekannter Beruf erkannt. Die Suchbegriffe kannst du weiter selbst eintippen.")
    with _SPERRE:
        _speichern({**p, "text": text})  # der Text bleibt auf dem Server; der Knopf "Mit KI erkennen" braucht ihn
    return p


OLLAMA = "http://localhost:11434"
MODELL = "qwen3:14b"
FRAGE = ("Du liest einen deutschen Lebenslauf. Antworte nur mit JSON der Form "
         '{"berufe": [...], "woerter": [...]}. "berufe": höchstens 8 Berufsbezeichnungen auf Deutsch, zu denen der Lebenslauf passt '
         "(als Suchbegriff für eine Jobbörse, z. B. \"IT-Support\", \"Disponent\"), die besten zuerst, auch Einstiegsberufe. "
         '"woerter": höchstens 25 kleingeschriebene Stichwörter aus dem Lebenslauf (Programme, Fähigkeiten, Tätigkeiten), nichts erfinden.\n\nLebenslauf:\n')


def mit_ki():
    """Fragt das lokale Ollama nach Berufen und Stichwörtern und ergänzt das gespeicherte Profil; die KI-Berufe stehen vorn."""
    text = _lesen().get("text")
    if not text:
        raise ValueError("Bitte zuerst einen Lebenslauf hochladen.")
    anfrage = urllib.request.Request(OLLAMA + "/api/generate", headers={"Content-Type": "application/json"}, data=json.dumps(
        {"model": MODELL, "prompt": FRAGE + text[:6000], "stream": False, "think": False, "format": "json"}).encode())
    try:
        with urllib.request.urlopen(anfrage, timeout=300) as r:
            roh = json.load(r)["response"]
    except OSError as e:
        raise RuntimeError(f"Ollama antwortet nicht ({e}). Ist Ollama gestartet und das Modell {MODELL} geladen?")
    try:
        antwort = json.loads(roh)
    except ValueError:
        raise RuntimeError("Die KI-Antwort war kein gültiges JSON. Bitte nochmal versuchen.")

    def liste(schluessel):  # nur echte Listen; ein Text würde sonst Buchstabe für Buchstabe zu "Berufen"
        v = antwort.get(schluessel) if isinstance(antwort, dict) else None
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    ki = liste("berufe")[:8]
    if not ki:
        raise RuntimeError("Die KI hat keine Berufe geliefert. Bitte nochmal versuchen.")
    with _SPERRE:
        p = _lesen()  # frisch lesen: der Nutzer kann während der Wartezeit einen anderen Lebenslauf hochgeladen haben
        if p.get("text") != text:
            raise RuntimeError("Der Lebenslauf wurde inzwischen ersetzt. Bitte die KI nochmal starten.")
        alt = {b.lower() for b in ki}
        p["berufe"] = ki + [b for b in p["berufe"] if b.lower() not in alt]
        for b in ki:
            p["treffer"].setdefault(b, ["KI"])
        p["woerter"] = sorted({*p["woerter"], *(w.lower() for w in liste("woerter"))})
        _speichern(p)
    return {k: v for k, v in p.items() if k != "text"}


def _lesen():
    return json.loads(DATEI.read_text("utf-8")) if DATEI.exists() else {}


def gespeichert():
    """Das Profil für die Seite: ohne den Lebenslauftext (Anschrift, Telefon, Geburtsdatum), den die Seite nicht braucht."""
    return {k: v for k, v in _lesen().items() if k != "text"}


if __name__ == "__main__":
    probe = ("Erfahrung in Disposition und Logistik, Schichtkoordination im Logistikbetrieb, Teamsteuerung. Einstieg in den IT-Support. "
             "Windows, Fernwartung, MS Office, Microsoft 365, Active Directory, Intune, Netzwerk (IP, DNS, VPN). "
             "Bewerbermanagement, Interviews, Onboarding. " * 2)
    p = profil(probe)
    assert p["berufe"][0] == "IT-Support" and "Disponent" in p["berufe"] and "Recruiter" in p["berufe"], p
    assert "webentwickler" not in [b.lower() for b in p["berufe"]], p
    print("Selbsttest ok:", p["berufe"])
