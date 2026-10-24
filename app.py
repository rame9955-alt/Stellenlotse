"""Stellenlotse: liest Kleinanzeigen und die Jobbörse der Arbeitsagentur, das Dashboard filtert Doppelanzeigen."""
import base64
import html
import json
import os
import re
import threading
import time
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, parse_qs, urljoin

from playwright.sync_api import sync_playwright

import bewerbung
import lebenslauf

PORT = 4910
MAX_SEITEN = 40  # ponytail: feste Obergrenze, gegen Endlosschleifen
GLEICHZEITIG = 4  # so viele Anzeigen liest "Bewerbungen vorbereiten" parallel
UNNOETIG = {"image", "font", "media"}
FERTIG = "domcontentloaded"  # Inhalt ist da, auf Werbung und Nachladen wird nicht gewartet
BASIS = "https://www.kleinanzeigen.de"
# offene Schnittstelle der Arbeitsagentur, beschrieben auf jobsuche.api.bund.dev; der Schlüssel ist dort öffentlich
BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
BA_SCHLUESSEL = {"X-API-Key": "jobboerse-jobsuche"}
BA_MAX_SEITEN = 20  # je 100 Stellen
BA_REMOTE_SEITEN = 5  # bei der bundesweiten Remote-Suche je Suchwort höchstens 500 Stellen, sonst dauert es zu lange
ST_BASIS = "https://www.stepstone.de"
ST_MAX_SEITEN = 8  # je 25 Anzeigen; bei "Sachbearbeiter" Berlin enden die passenden Treffer nach etwa 6 Seiten
ST_PAUSE = 0.5  # Sekunden zwischen zwei Seiten, damit StepStone nicht gedrosselt wird
ST_VERSUCHE = 3
ST_KOPF = {  # wie ein Browser; mit weniger Headern antwortet StepStone bei Anzeigenseiten nicht
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Referer": ST_BASIS + "/", "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
}
KENNUNG = "Stellenlotse"  # Wert des Headers X-Requested-With; wird beim Ausliefern in die Seite eingesetzt
SEITE = (Path(__file__).parent / "index.html").read_text("utf-8").replace("__KENNUNG__", KENNUNG).encode("utf-8")
ORDNER = bewerbung.ERGEBNISSE

LESEN_JS = """() => [...document.querySelectorAll('#srchrslt-adtable article[data-adid]')].map(a => {
  // Kopfzeile: Ort, bei Umkreissuche dann "(4 km)", dann Datum; deshalb nach Inhalt statt nach Position
  const spans = [...a.querySelectorAll(':scope > div:last-child > div:first-child span')].map(s => s.innerText.trim());
  const km = spans.find(s => /^\\((ca\\. )?\\d+\\s*km\\)$/.test(s)) || '';
  const rest = spans.filter(s => s !== km);
  return {
    id: a.dataset.adid,
    link: a.dataset.href,
    titel: a.querySelector('h3 a')?.innerText.trim() || '',
    ort: rest[0] || '',
    datum: rest[1] || '',
    entfernung: km.slice(1, -1),
    text: a.querySelector('h3 + p')?.innerText.trim() || '',
    firma: a.querySelector('a[href^="/pro/"] span')?.innerText.trim() || '',
  };
})"""


@contextmanager
def seite():
    """Unsichtbarer Browser mit einer deutschen Seite."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(locale="de-DE")
        pg.set_default_navigation_timeout(45000)
        # Bilder, Schriften und Videos braucht das Auslesen nicht; ohne sie lädt jede Seite schneller
        pg.route("**/*", lambda r: r.abort() if r.request.resource_type in UNNOETIG else r.continue_())
        try:
            yield pg
        finally:
            browser.close()


def kleinanzeigen(begriff, stadt, umkreis):
    felder = {"keywords": begriff, "locationStr": stadt, "categoryId": 102}
    if umkreis:
        felder["radius"] = umkreis
    start = f"{BASIS}/s-suchanfrage.html?" + urlencode(felder)
    anzeigen, seiten = {}, 0
    with seite() as pg:
        pg.goto(start, wait_until=FERTIG)
        # nur Angebote, keine Gesuche (dort suchen Leute selbst Arbeit)
        nur_angebote = pg.query_selector('a[href*="anzeige:angebote"]')
        if nur_angebote:
            pg.goto(urljoin(BASIS, nur_angebote.get_attribute("href")), wait_until=FERTIG)
        # welchen Ort Kleinanzeigen wirklich nimmt (Ortsnamen sind oft mehrdeutig)
        kopf = re.search(r"Jobs für „[^“]*“ in (.+?)(?: und Umgebung|,|\n|$)", pg.inner_text("main"))
        ort_ka = kopf.group(1).strip() if kopf else ""
        # Kleinanzeigen verlinkt nur 5 Seiten, weitere gehen aber direkt per Adresse
        vorne, wort, code = pg.url.rsplit("/", 2)
        for n in range(1, MAX_SEITEN + 1):
            if n > 1:
                pg.goto(f"{vorne}/seite:{n}/{wort}/{code}", wait_until=FERTIG)
            neu = 0
            for a in pg.evaluate(LESEN_JS):
                if a["id"] not in anzeigen:
                    a["link"] = urljoin(BASIS, a["link"])
                    a["quelle"] = "Kleinanzeigen"
                    anzeigen[a["id"]] = a
                    neu += 1
            if not neu:  # hinter der letzten Seite kommt nichts Neues mehr
                break
            seiten = n
    return {"seiten": seiten, "ort_ka": ort_ka, "anzeigen": list(anzeigen.values())}


def _ba_holen(pfad):
    anfrage = urllib.request.Request(f"{BA}/{pfad}", headers=BA_SCHLUESSEL)
    with urllib.request.urlopen(anfrage, timeout=30) as r:
        return json.load(r)


def _ba_liste(felder, max_seiten=BA_MAX_SEITEN):
    jobs = []
    for seite_nr in range(1, max_seiten + 1):
        d = _ba_holen("v6/jobs?" + urlencode({**felder, "size": 100, "page": seite_nr}))
        jobs += d.get("ergebnisliste", [])
        if not d.get("ergebnisliste") or len(jobs) >= d.get("maxErgebnisse", 0):
            break
    return jobs


def _ba_anzeige(j, zeitarbeit):
    ort = (j.get("stellenlokationen") or [{}])[0].get("adresse", {})
    voll = j.get("arbeitszeitVollzeit", False)
    teil = any(j.get(k) for k in ("arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag",
                                  "arbeitszeitTeilzeitAbend", "arbeitszeitTeilzeitFlexibel"))
    tag = j.get("datumErsteVeroeffentlichung", "")
    return {
        "id": "ba-" + j["referenznummer"],
        "refnr": j["referenznummer"],
        "link": "https://www.arbeitsagentur.de/jobsuche/jobdetail/" + j["referenznummer"],
        "titel": j.get("stellenangebotsTitel", ""),
        "ort": f"{ort.get('plz', '')} {ort.get('ort', '')}".strip(),
        "datum": ".".join(reversed(tag.split("-"))) if tag else "",
        "entfernung": f"{j['entfernung']} km" if "entfernung" in j else "",
        "text": j.get("hauptberuf", ""),
        "firma": j.get("firma", ""),
        "arbeitszeit": "voll" if voll and not teil else "teil" if teil and not voll else "",
        "homeoffice": bool(j.get("homeofficemoeglich")),  # Merkmal der Arbeitsagentur, oft nicht gesetzt: das Dashboard prüft zusätzlich Stichwörter
        "zeitarbeit": j["referenznummer"] in zeitarbeit,
        "quelle": "Arbeitsagentur",
    }


def arbeitsagentur(begriff, plz, umkreis):
    felder = {"was": begriff, "wo": plz}
    if umkreis:
        felder["umkreis"] = umkreis
    # die Liste sagt nicht, ob eine Stelle Zeitarbeit ist; die Suche mit diesem Filter schon
    zeitarbeit = {j["referenznummer"] for j in _ba_liste({**felder, "zeitarbeit": "true"})}
    return [_ba_anzeige(j, zeitarbeit) for j in _ba_liste(felder)]


def arbeitsagentur_remote(begriff):
    """Bundesweit, ohne Ort: Suchbegriff plus "remote" und plus "homeoffice". Die Arbeitsagentur hat keinen Remote-Filter,
    die Wörter stehen aber oft im Titel; die Stichwortprüfung im Dashboard trennt danach 100 % Remote von Homeoffice möglich."""
    jobs, zeitarbeit = {}, set()
    for wort in ("remote", "homeoffice"):
        felder = {"was": f"{begriff} {wort}".strip()}
        for j in _ba_liste(felder, BA_REMOTE_SEITEN):
            jobs.setdefault(j["referenznummer"], j)
        zeitarbeit |= {j["referenznummer"] for j in _ba_liste({**felder, "zeitarbeit": "true"}, BA_REMOTE_SEITEN)}
    return [_ba_anzeige(j, zeitarbeit) for j in jobs.values()]


def _st_holen(url):
    """Seite von StepStone als Text. Ohne die vollen Browser-Header antwortet StepStone bei Anzeigenseiten nicht (Zeitüberschreitung)."""
    url = quote(url, safe=":/?&=%")  # Umlaute und Sonderzeichen im Link (urllib versteht nur ASCII)
    for n in range(ST_VERSUCHE):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=ST_KOPF), timeout=25) as r:
                return r.read().decode("utf-8", "ignore")
        except OSError:
            if n == ST_VERSUCHE - 1:
                raise
            time.sleep(1 + n)


def _st_treffer(seite_text):
    """Die Anzeigen einer Suchseite: StepStone legt sie als JSON in ein Skript der Seite, die Anführungszeichen des JSON als &#34;.
    Nur diese werden zurückgetauscht: ein &quot; im Anzeigentext darf nicht zu einem echten Anführungszeichen werden (das bricht das JSON)."""
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", seite_text, re.S):
        if "harmonisedId" in m.group(1):
            s = m.group(1).replace("&#34;", '"')
            return json.JSONDecoder().raw_decode(s[s.rfind("[", 0, s.index('{"harmonisedId"')):])[0]
    return []


def _st_anzeige(j):
    tag = (j.get("datePosted") or "")[:10]
    return {
        "id": f"st-{j['id']}",
        "link": html.unescape(j["url"]).split("?")[0],
        "titel": html.unescape(j.get("title", "")),
        "ort": html.unescape(j.get("location", "")),
        "datum": ".".join(reversed(tag.split("-"))) if tag else "",
        "entfernung": "",
        "text": html.unescape(j.get("textSnippet", "")),
        "firma": "" if j.get("isAnonymous") else html.unescape(j.get("companyName", "")),
        "homeoffice": j.get("workFromHome") in (1, 2),  # 0 = vor Ort; was 1 und 2 genau heißen, sagt StepStone nicht (2 steht bei Stellen mit "Home-Office" im Ort)
        "quelle": "StepStone",
    }


def stepstone(begriff, plz, umkreis):
    """Suchergebnisse von stepstone.de; nur "main" (zur Suche passend), nicht die lose verwandten Vorschläge. Höchstens ST_MAX_SEITEN Seiten à 25."""
    wort = quote(re.sub(r"\W+", "-", begriff.strip().lower()).strip("-"))
    pfad = f"{ST_BASIS}/jobs/{wort}/in-{plz}"
    anzeigen = {}
    for n in range(1, ST_MAX_SEITEN + 1):
        felder = {**({"radius": umkreis} if umkreis else {}), **({"page": n} if n > 1 else {})}
        main = [j for j in _st_treffer(_st_holen(pfad + ("?" + urlencode(felder) if felder else ""))) if j.get("section") == "main"]
        neu = [j for j in main if f"st-{j['id']}" not in anzeigen]
        anzeigen.update({f"st-{j['id']}": _st_anzeige(j) for j in neu})
        if not neu:  # hinter der letzten passenden Seite kommen nur noch Vorschläge
            break
        time.sleep(ST_PAUSE)
    return list(anzeigen.values())


def stepstone_text(link):
    """Beschreibung einer StepStone-Anzeige (JobPosting in den Seitendaten) als Text, mit den Adressen aus mailto-Links."""
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', _st_holen(link), re.S):
        d = json.loads(m.group(1))
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            roh = html.unescape(d.get("description", ""))
            mails = re.findall(r'mailto:([^"\'?\s>]+)', roh)
            return re.sub(r"<[^>]+>", " ", roh) + " " + " ".join(mails)
    return ""


def suchen(begriff, stadt, umkreis, quellen):
    if umkreis == "remote":  # bundesweit: nur Arbeitsagentur, Kleinanzeigen hat keine Remote-Angabe und ist an den Ort gebunden
        ba = arbeitsagentur_remote(begriff)
        return {"seiten": 0, "ort_ka": "", "anzeigen": ba, "anzahl": {"Arbeitsagentur": len(ba)}, "quellen": ["ba"]}
    daten = {"seiten": 0, "ort_ka": "", "anzeigen": [], "anzahl": {}, "quellen": quellen}
    if "st" in quellen:
        st = stepstone(begriff, stadt, umkreis)
        daten["anzeigen"] += st
        daten["anzahl"]["StepStone"] = len(st)
    if "ka" in quellen:
        ka = kleinanzeigen(begriff, stadt, umkreis)
        daten.update(seiten=ka["seiten"], ort_ka=ka["ort_ka"])
        daten["anzeigen"] += ka["anzeigen"]
        daten["anzahl"]["Kleinanzeigen"] = len(ka["anzeigen"])
    if "ba" in quellen:
        ba = arbeitsagentur(begriff, stadt, umkreis)
        daten["anzeigen"] += ba
        daten["anzahl"]["Arbeitsagentur"] = len(ba)
    return daten


def speichern(begriff, stadt, umkreis, daten):
    """Speichert die Suche und markiert Anzeigen, die bei der letzten gleichen Suche fehlten."""
    # nur Kleinanzeigen behält den alten Dateinamen, damit NEU mit früheren Suchen vergleicht
    zusatz = "" if daten["quellen"] == ["ka"] else " " + " ".join(daten["quellen"])
    ort = f"{stadt} {umkreis or 'egal'}km" if umkreis != "remote" else "bundesweit remote"
    name = re.sub(r"[^a-z0-9äöüß]+", "-", f"{begriff} {ort}{zusatz}".lower()).strip("-")
    datei = ORDNER / f"{name}.json"
    if datei.exists():
        alt = {a["id"] for a in json.loads(datei.read_text("utf-8"))["anzeigen"]}
        for a in daten["anzeigen"]:
            a["neu"] = a["id"] not in alt
    daten.update(begriff=begriff, stadt=stadt, umkreis=umkreis, datei=name,
                 zeit=datetime.now().strftime("%d.%m. %H:%M"))
    ORDNER.mkdir(exist_ok=True)
    datei.write_text(json.dumps(daten, ensure_ascii=False), "utf-8")
    return daten


# Zwei Merklisten im Programmordner (nicht in Ergebnisse, das sind nur Suchen), beide id -> Titel, Firma, Link:
AUSSORTIERT = bewerbung.PROGRAMM / "aussortiert.json"  # Anzeigen, die der Nutzer nicht mehr sehen will
BEWORBEN = bewerbung.PROGRAMM / "beworben.json"        # Bewerbungen, die raus sind (per Senden-Knopf oder vom Nutzer als versendet markiert), dazu Datum und Art
_LISTEN_SPERRE = threading.Lock()


def _liste(pfad):
    with _LISTEN_SPERRE:
        return json.loads(pfad.read_text("utf-8")) if pfad.exists() else {}


def _liste_aendern(pfad, aendern):
    """Liest frisch, ändert und ersetzt die Datei in einem Zug (Hilfsdatei, dann austauschen)."""
    with _LISTEN_SPERRE:
        d = json.loads(pfad.read_text("utf-8")) if pfad.exists() else {}
        aendern(d)
        hilfsdatei = pfad.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
        os.replace(hilfsdatei, pfad)
        return d


def _eintrag(a, **extra):
    return {k: a.get(k, "") for k in ("titel", "firma", "link")} | extra


def aussortieren(a):
    return _liste_aendern(AUSSORTIERT, lambda d: d.update({a["id"]: _eintrag(a)}))


def zurueckholen(id_):
    return _liste_aendern(AUSSORTIERT, lambda d: d.pop(id_, None))


def beworben_eintragen(a, art):
    """art: 'per Senden-Knopf' oder 'von Hand versendet'."""
    return _liste_aendern(BEWORBEN, lambda d: d.update({a["id"]: _eintrag(a, datum=datetime.now().strftime("%d.%m.%Y"), art=art)}))


def beworben_entfernen(id_):
    return _liste_aendern(BEWORBEN, lambda d: d.pop(id_, None))


_KOPF = {}  # Datei -> (Änderungszeit, Kopfdaten): geändert wird nur neu gelesen, was sich geändert hat


def gespeicherte():
    if not ORDNER.exists():
        return []
    liste = []
    for f in sorted(ORDNER.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        if f == bewerbung.BEWORBEN:  # Liste der Gmail-Entwürfe, keine Suche
            continue
        zeit = f.stat().st_mtime
        if _KOPF.get(f, (None,))[0] != zeit:
            d = json.loads(f.read_text("utf-8"))
            _KOPF[f] = (zeit, {**{k: d[k] for k in ("datei", "begriff", "stadt", "umkreis", "zeit")},
                               "quellen": d.get("quellen", ["ka"])})
        liste.append(_KOPF[f][1])
    return liste


def _vorbereiten_teil(anzeigen):
    fertig = []
    with ExitStack() as stack:
        pg = None  # der Browser startet erst bei der ersten Kleinanzeigen-Anzeige; Arbeitsagentur und StepStone brauchen ihn nicht
        for a in anzeigen:
            fehler = ""
            try:
                if a.get("quelle") == "Arbeitsagentur":
                    nr = base64.b64encode(a["refnr"].encode()).decode()
                    text = _ba_holen(f"v4/jobdetails/{nr}").get("stellenangebotsBeschreibung") or ""
                elif a.get("quelle") == "StepStone":
                    text = stepstone_text(a["link"])
                    if not text:
                        fehler = "Anzeigentext nicht gefunden (Seite umgebaut oder blockiert)"
                else:
                    if pg is None:
                        pg = stack.enter_context(seite())
                    pg.goto(a["link"], wait_until=FERTIG)
                    el = pg.query_selector("#viewad-description-text")
                    text = el.inner_text() if el else ""
                    if not el:
                        fehler = "Anzeigentext nicht gefunden (Seite leer, blockiert oder umgebaut)"
            except Exception as e:
                text = ""
                fehler = (str(e).strip().splitlines() or [type(e).__name__])[0]  # nur die erste Zeile, Playwright hängt ein langes Protokoll an
            b = bewerbung.vorbereiten(a, text)
            if fehler:
                b["lesefehler"] = fehler  # das Dashboard sagt dann "Text nicht geladen" statt "keine Adresse"
            fertig.append(b)
    return fertig


def vorbereiten(anzeigen):
    """Liest jede Anzeige im Detail und baut daraus Adresse, Betreff und Anschreiben."""
    # mehrere Browser gleichzeitig, jeder mit eigenem Teil der Liste; Reihenfolge bleibt erhalten
    teile = [anzeigen[i::GLEICHZEITIG] for i in range(GLEICHZEITIG)]
    with ThreadPoolExecutor(GLEICHZEITIG) as pool:
        fertig = {b["id"]: b for teil in pool.map(_vorbereiten_teil, teile) for b in teil}
    return [fertig[a["id"]] for a in anzeigen]


class Handler(BaseHTTPRequestHandler):
    def _eigene_seite(self):
        # Fremde Webseiten können diesen Header nur nach einer Rückfrage (Preflight) senden, die der Server nie bestätigt.
        # So kann keine andere Seite im Browser Suchen, Entwürfe oder Mails über dieses Programm auslösen.
        # Der Host muss localhost sein, sonst könnte eine Seite ihren Namen auf 127.0.0.1 umleiten (DNS-Rebinding) und den Header selbst setzen.
        host = self.headers.get("Host", "").rsplit(":", 1)[0]
        if self.headers.get("X-Requested-With") != KENNUNG or host not in ("localhost", "127.0.0.1"):
            raise PermissionError("Anfrage nicht von der eigenen Seite.")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/suche", "/gespeichert", "/laden", "/entwuerfe", "/aussortiert", "/beworben", "/profil"):
                self._eigene_seite()
            if url.path == "/suche":
                b, s, u = q.get("begriff", ""), q.get("stadt", ""), q.get("umkreis", "")
                quellen = [x for x in ("ka", "ba", "st") if x in q.get("quellen", "ka").split(",")]
                if not quellen:
                    raise ValueError("Bitte mindestens eine Quelle wählen.")
                self.json(speichern(b, s, u, suchen(b, s, u, quellen)))
            elif url.path == "/gespeichert":
                self.json(gespeicherte())
            elif url.path == "/laden":
                name = Path(q.get("datei", "")).name  # nur Dateien aus dem Ordner Ergebnisse
                self.antwort(200, (ORDNER / f"{name}.json").read_bytes(), "application/json")
            elif url.path == "/entwuerfe":
                self.json(bewerbung.entwuerfe())
            elif url.path == "/aussortiert":
                self.json(_liste(AUSSORTIERT))
            elif url.path == "/beworben":
                self.json(_liste(BEWORBEN))
            elif url.path == "/profil":
                self.json(lebenslauf.gespeichert())
            else:
                self.antwort(200, SEITE, "text/html; charset=utf-8")
        except PermissionError as e:
            self.json({"fehler": str(e)}, 403)
        except Exception as e:  # Fehler im Dashboard zeigen statt still abbrechen
            self.json({"fehler": str(e)}, 500)

    def do_POST(self):
        try:
            self._eigene_seite()
            daten = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/vorbereiten":
                self.json(vorbereiten(daten))
            elif self.path == "/entwurf":
                self.json(bewerbung.entwurf_anlegen(daten))
            elif self.path == "/senden":
                ergebnis = bewerbung.senden(daten)
                try:
                    beworben_eintragen(daten, "per Senden-Knopf")
                except OSError:
                    pass  # die Mail ist raus und in entwuerfe.json als gesendet vermerkt; nur die Liste "Beworben" fehlt dann
                self.json(ergebnis)
            elif self.path == "/lebenslauf":
                self.json(lebenslauf.hochladen(daten))
            elif self.path == "/lebenslauf-ki":
                self.json(lebenslauf.mit_ki())
            elif self.path == "/aussortieren":
                self.json(aussortieren(daten))
            elif self.path == "/zurueckholen":
                self.json(zurueckholen(daten["id"]))
            elif self.path == "/beworben-markieren":
                self.json(beworben_eintragen(daten, "von Hand versendet"))
            elif self.path == "/beworben-entfernen":
                self.json(beworben_entfernen(daten["id"]))
            else:
                self.json({}, 404)
        except PermissionError as e:
            self.json({"fehler": str(e)}, 403)
        except Exception as e:
            self.json({"fehler": str(e)}, 500)

    def json(self, daten, code=200):
        self.antwort(code, json.dumps(daten, ensure_ascii=False).encode("utf-8"), "application/json")

    def antwort(self, code, body, typ):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Stellenlotse laeuft auf http://localhost:{PORT}  (Fenster offen lassen)")
    webbrowser.open(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
