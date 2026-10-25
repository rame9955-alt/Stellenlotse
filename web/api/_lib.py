"""Gemeinsame Bausteine der Vercel-Funktionen: Arbeitsagentur, StepStone, Adresssuche im Anzeigentext.
Die Funktionen speichern nichts und sehen nie einen Lebenslauf. Dieser Code ist aus app.py und bewerbung.py übernommen
(dort hängt alles an Playwright und Dateien, was Vercel nicht hat); Änderungen an der Suche bitte an beiden Stellen machen."""
import base64
import html
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

BA = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
BA_SCHLUESSEL = {"X-API-Key": "jobboerse-jobsuche"}  # öffentlicher Schlüssel, beschrieben auf jobsuche.api.bund.dev
BA_MAX_SEITEN = 10  # je 100 Stellen
BA_REMOTE_SEITEN = 5
ST_BASIS = "https://www.stepstone.de"
ST_VERSUCHE = 3
ST_KOPF = {  # wie ein Browser; mit weniger Headern antwortet StepStone bei Anzeigenseiten nicht
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Referer": ST_BASIS + "/", "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
}
ST_ANZEIGE = re.compile(r"^https://www\.stepstone\.de/stellenangebote--[\w%.\-]+\.html$")  # nur echte Anzeigenlinks: sonst wäre die Funktion ein offener Abruf-Dienst
BA_REFNR = re.compile(r"^[\w/-]{5,50}$")  # Referenznummern können einen Schrägstrich enthalten ("13319-893134/1_622342LS-S")


# ---------- Arbeitsagentur ----------
def ba_holen(pfad):
    for n in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{BA}/{pfad}", headers=BA_SCHLUESSEL), timeout=25) as r:
                return json.load(r)
        except OSError:
            if n == 2:
                raise
            time.sleep(1 + n)


def ba_liste(felder, max_seiten=BA_MAX_SEITEN):
    jobs = []
    for seite_nr in range(1, max_seiten + 1):
        d = ba_holen("v6/jobs?" + urlencode({**felder, "size": 100, "page": seite_nr}))
        jobs += d.get("ergebnisliste", [])
        if not d.get("ergebnisliste") or len(jobs) >= d.get("maxErgebnisse", 0):
            break
    return jobs


def ba_anzeige(j, zeitarbeit):
    ort = (j.get("stellenlokationen") or [{}])[0].get("adresse", {})
    voll = j.get("arbeitszeitVollzeit", False)
    teil = any(j.get(k) for k in ("arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag", "arbeitszeitTeilzeitAbend", "arbeitszeitTeilzeitFlexibel"))
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
        "homeoffice": bool(j.get("homeofficemoeglich")),
        "zeitarbeit": j["referenznummer"] in zeitarbeit,
        "quelle": "Arbeitsagentur",
    }


def arbeitsagentur(begriff, plz, umkreis):
    felder = {"was": begriff, "wo": plz}
    if umkreis:
        felder["umkreis"] = umkreis
    with ThreadPoolExecutor(2) as pool:  # die Liste sagt nicht, ob eine Stelle Zeitarbeit ist; die Suche mit diesem Filter schon
        alle = pool.submit(ba_liste, felder)
        za = pool.submit(ba_liste, {**felder, "zeitarbeit": "true"})
        zeitarbeit = {j["referenznummer"] for j in za.result()}
        return [ba_anzeige(j, zeitarbeit) for j in alle.result()]


def arbeitsagentur_remote(begriff):
    """Bundesweit, ohne Ort: Suchbegriff plus "remote" und plus "homeoffice" (die Arbeitsagentur hat keinen Remote-Filter)."""
    jobs, zeitarbeit = {}, set()
    for wort in ("remote", "homeoffice"):
        felder = {"was": f"{begriff} {wort}".strip()}
        for j in ba_liste(felder, BA_REMOTE_SEITEN):
            jobs.setdefault(j["referenznummer"], j)
        zeitarbeit |= {j["referenznummer"] for j in ba_liste({**felder, "zeitarbeit": "true"}, BA_REMOTE_SEITEN)}
    return [ba_anzeige(j, zeitarbeit) for j in jobs.values()]


def ba_text(refnr):
    nr = base64.b64encode(refnr.encode()).decode()
    return ba_holen(f"v4/jobdetails/{nr}").get("stellenangebotsBeschreibung") or ""


# ---------- StepStone ----------
def st_holen(url):
    url = quote(url, safe=":/?&=%")  # Umlaute und Sonderzeichen im Link (urllib versteht nur ASCII)
    for n in range(ST_VERSUCHE):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=ST_KOPF), timeout=25) as r:
                return r.read().decode("utf-8", "ignore")
        except OSError:
            if n == ST_VERSUCHE - 1:
                raise
            time.sleep(1 + n)


def st_treffer(seite_text):
    """Die Anzeigen einer Suchseite: StepStone legt sie als JSON in ein Skript der Seite, die Anführungszeichen des JSON als &#34;.
    Nur diese werden zurückgetauscht: ein &quot; im Anzeigentext darf nicht zu einem echten Anführungszeichen werden (das bricht das JSON)."""
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", seite_text, re.S):
        if "harmonisedId" in m.group(1):
            s = m.group(1).replace("&#34;", '"')
            return json.JSONDecoder().raw_decode(s[s.rfind("[", 0, s.index('{"harmonisedId"')):])[0]
    return []


def _st_link(url):
    """Anzeigenlink ohne Suchanhang. Bindestriche mit Trennzeichen, "·" und kaputte Umlaute im Namensteil fallen weg: StepStone findet die Anzeige über die Nummer am Ende."""
    kopf, rest = html.unescape(url).split("?")[0].split("stellenangebote--", 1)
    return kopf + "stellenangebote--" + re.sub(r"[^\w.\-%]", "", rest)


def st_anzeige(j):
    tag = (j.get("datePosted") or "")[:10]
    return {
        "id": f"st-{j['id']}",
        "link": _st_link(j["url"]),
        "titel": html.unescape(j.get("title", "")),
        "ort": html.unescape(j.get("location", "")),
        "datum": ".".join(reversed(tag.split("-"))) if tag else "",
        "entfernung": "",
        "text": html.unescape(j.get("textSnippet", "")),
        "firma": "" if j.get("isAnonymous") else html.unescape(j.get("companyName", "")),
        "homeoffice": j.get("workFromHome") in (1, 2),  # 0 = vor Ort; was 1 und 2 genau heißen, sagt StepStone nicht
        "quelle": "StepStone",
    }


def stepstone_seite(begriff, plz, umkreis, n):
    """Eine Suchseite (25 Anzeigen) von stepstone.de, nur "main" (zur Suche passend). Leere Liste = keine passenden mehr."""
    wort = quote(re.sub(r"\W+", "-", begriff.strip().lower()).strip("-"))
    felder = {**({"radius": umkreis} if umkreis else {}), **({"page": n} if n > 1 else {})}
    url = f"{ST_BASIS}/jobs/{wort}/in-{plz}" + ("?" + urlencode(felder) if felder else "")
    return [st_anzeige(j) for j in st_treffer(st_holen(url)) if j.get("section") == "main"]


def st_text(link):
    """Beschreibung einer StepStone-Anzeige (JobPosting in den Seitendaten) als Text, mit den Adressen aus mailto-Links."""
    for m in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', st_holen(link), re.S):
        d = json.loads(m.group(1))
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            roh = html.unescape(d.get("description", ""))
            mails = re.findall(r'mailto:([^"\'?\s>]+)', roh)
            return re.sub(r"<[^>]+>", " ", roh) + " " + " ".join(mails)
    return ""


# ---------- Bewerbungsadresse im Anzeigentext ----------
MAIL_RE = re.compile(r"[\w.+-]+\s*(?:@|\(at\)|\[at\])\s*[\w-]+(?:\.[\w-]+)+", re.I)
GUT = re.compile(r"bewerb|job|karriere|career|personal|recruit|hr[@.]|stelle", re.I)
SCHLECHT = re.compile(r"datenschutz|privacy|noreply|no-reply|rechnung|kleinanzeigen|newsletter|support@", re.I)
# Endungen, die als Bewerbungsadresse plausibel sind und vorbelegt werden; andere werden nur als Hinweis gezeigt
ENDUNGEN = {"de", "com", "net", "org", "eu", "info", "berlin", "biz", "at", "ch", "io", "jobs", "online", "cloud", "email", "gmbh",
            "nl", "fr", "uk", "pl", "cz", "dk", "se", "no", "fi", "it", "es", "be", "lu", "li", "us", "co", "ag",
            "group", "services", "consulting", "solutions", "tech", "app", "agency", "team", "work", "company",
            "global", "digital", "energy", "health", "swiss", "bayern", "hamburg", "koeln", "nrw"}


def _adressen(text):
    mails = [re.sub(r"\s*(\(at\)|\[at\])\s*", "@", m, flags=re.I).replace(" ", "").rstrip(".") for m in MAIL_RE.findall(text)]
    return [m for m in dict.fromkeys(mails) if not SCHLECHT.search(m)]


def _endung_ok(m):
    return m.rsplit(".", 1)[-1].lower() in ENDUNGEN


def mail_finden(text):
    """Beste Bewerbungsadresse aus dem Anzeigentext, sonst ''."""
    mails = [m for m in _adressen(text) if _endung_ok(m)]
    return next((m for m in mails if GUT.search(m)), mails[0] if mails else "")


def mail_unsicher(text):
    """Erste Adresse mit ungewöhnlicher Endung (nicht vorbelegt, nur als Hinweis), sonst ''."""
    return next((m for m in _adressen(text) if not _endung_ok(m)), "")


# ---------- für die Funktionen ----------
def antwort(h, code, daten):
    body = json.dumps(daten, ensure_ascii=False).encode("utf-8")
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(body)
