"""KI-Hilfe (freiwillig): Der Browser schickt den bereinigten Berufs- und Fähigkeitenteil eines Lebenslaufs, die Funktion fragt Groq nach
Berufen und Stichwörtern. Der Text wird weder gespeichert noch protokolliert. POST /api/ki mit {"text": "..."}.
Der Schlüssel steht nur als Umgebungsvariable GROQ_API_KEY bei Vercel (nie im Code). Optional: KI_MODELL (Modellname), KI_URL (nur für Tests)."""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _lib import antwort  # noqa: E402

URL = os.environ.get("KI_URL", "https://api.groq.com/openai/v1/chat/completions")
MODELL = os.environ.get("KI_MODELL", "openai/gpt-oss-20b")
MAX_ZEICHEN = 8000
SYSTEM = ("Du liest den Berufs- und Fähigkeitenteil eines deutschen Lebenslaufs. Antworte nur mit JSON der Form "
          '{"berufe": [...], "woerter": [...]}. "berufe": höchstens 8 Berufsbezeichnungen auf Deutsch, zu denen der Lebenslauf passt '
          '(als Suchbegriff für eine Jobbörse, z. B. "IT-Support", "Disponent"), die besten zuerst, auch Einstiegsberufe. '
          '"woerter": höchstens 25 kleingeschriebene Stichwörter aus dem Lebenslauf (Programme, Fähigkeiten, Tätigkeiten), nichts erfinden.')


def aufrufen(text, schluessel, json_modus):
    nutzlast = {"model": MODELL, "temperature": 0.2, "max_tokens": 1500,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]}
    if json_modus:
        nutzlast["response_format"] = {"type": "json_object"}
    anfrage = urllib.request.Request(URL, data=json.dumps(nutzlast).encode(), method="POST", headers={
        "Authorization": f"Bearer {schluessel}", "Content-Type": "application/json", "User-Agent": "Stellenlotse"})
    with urllib.request.urlopen(anfrage, timeout=40) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def json_aus(roh):
    """Das JSON in der Antwort, auch wenn Text oder Code-Zeichen drumherum stehen; sonst None."""
    a, b = roh.find("{"), roh.rfind("}")
    try:
        return json.loads(roh[a:b + 1]) if 0 <= a < b else None
    except ValueError:
        return None


def liste(d, schluessel, grenze):
    v = d.get(schluessel) if isinstance(d, dict) else None
    if not isinstance(v, list):  # ein Text würde sonst Buchstabe für Buchstabe zu "Berufen"
        return []
    return [s for s in (str(x).strip() for x in v) if 2 <= len(s) <= 60 and "\n" not in s][:grenze]


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        schluessel = os.environ.get("GROQ_API_KEY", "")
        if not schluessel:
            return antwort(self, 503, {"fehler": "Die KI-Hilfe ist hier nicht eingeschaltet."})
        if self.headers.get("Origin", "").split("://", 1)[-1] != self.headers.get("Host", "-"):  # nur von dieser Seite, nicht von fremden
            return antwort(self, 403, {"fehler": "Nicht erlaubt."})
        try:
            laenge = int(self.headers.get("Content-Length", "0"))
            if not 0 < laenge <= MAX_ZEICHEN * 4:
                return antwort(self, 400, {"fehler": "Ungültige Anfrage."})
            text = str(json.loads(self.rfile.read(laenge)).get("text", "")).strip()
            if not 100 <= len(text) <= MAX_ZEICHEN:
                return antwort(self, 400, {"fehler": f"Der Text muss zwischen 100 und {MAX_ZEICHEN} Zeichen lang sein."})
            d, roh = None, ""
            for json_modus in (True, False):  # zweiter Versuch ohne JSON-Modus: manches Modell kennt ihn nicht oder liefert damit nichts
                try:
                    roh = aufrufen(text, schluessel, json_modus) or ""
                except urllib.error.HTTPError as e:
                    if e.code != 400 or not json_modus:
                        raise
                    continue
                d = json_aus(roh)
                if liste(d, "berufe", 8):
                    break
            berufe = liste(d, "berufe", 8)
            if not berufe:  # Ausschnitt der Antwort der KI (nicht dein Text) hilft bei der Fehlersuche
                return antwort(self, 502, {"fehler": f"Die KI hat keine lesbare Antwort geliefert. Bitte noch einmal versuchen. (Antwort: {roh.strip()[:120] or 'leer'})"})
            return antwort(self, 200, {"berufe": berufe, "woerter": [w.lower() for w in liste(d, "woerter", 25)]})
        except urllib.error.HTTPError as e:
            meldung = {401: "Der KI-Schlüssel ist ungültig.", 404: "Das KI-Modell gibt es nicht (KI_MODELL bei Vercel prüfen).",
                       429: "Die KI ist gerade ausgelastet (Gratis-Grenze). Bitte später noch einmal versuchen."}.get(e.code, f"Die KI antwortet mit Fehler {e.code}.")
            return antwort(self, 502, {"fehler": meldung})
        except ValueError:
            return antwort(self, 502, {"fehler": "Die KI-Antwort war nicht lesbar. Bitte noch einmal versuchen."})
        except Exception as e:
            return antwort(self, 502, {"fehler": f"Die KI antwortet nicht ({type(e).__name__})."})
