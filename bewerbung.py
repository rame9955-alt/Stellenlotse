"""Bewerbungen vorbereiten (E-Mail aus Anzeige, Anschreiben) und als Gmail-Entwurf ablegen."""
import imaplib
import json
import os
import re
import smtplib
import threading
import time
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

PROGRAMM = Path(__file__).parent
ERGEBNISSE = PROGRAMM / "Ergebnisse"
EINSTELLUNGEN = PROGRAMM / "einstellungen.json"  # eigene Angaben, nicht im Repository (Vorlage: einstellungen.beispiel.json)
PASSWORT_DATEI = PROGRAMM / "gmail_app_passwort.txt"
BEWORBEN = ERGEBNISSE / "entwuerfe.json"
_SPERRE = threading.RLock()  # schützt entwuerfe.json und das einmalige Senden (der Server bearbeitet Anfragen gleichzeitig)

MAIL_RE = re.compile(r"[\w.+-]+\s*(?:@|\(at\)|\[at\])\s*[\w-]+(?:\.[\w-]+)+", re.I)
GUT = re.compile(r"bewerb|job|karriere|career|personal|recruit|hr[@.]|stelle", re.I)
SCHLECHT = re.compile(r"datenschutz|privacy|noreply|no-reply|rechnung|kleinanzeigen|newsletter|support@", re.I)
# Endungen, die als Bewerbungsadresse plausibel sind und vorbelegt werden. Andere ("tempton.der", "firma.cm") werden nicht vorbelegt,
# aber über mail_unsicher() im Dashboard als Hinweis gezeigt, damit keine echte Adresse still verloren geht.
ENDUNGEN = {"de", "com", "net", "org", "eu", "info", "berlin", "biz", "at", "ch", "io", "jobs", "online", "cloud", "email", "gmbh",
            "nl", "fr", "uk", "pl", "cz", "dk", "se", "no", "fi", "it", "es", "be", "lu", "li", "us", "co", "ag",
            "group", "services", "consulting", "solutions", "tech", "app", "agency", "team", "work", "company",
            "global", "digital", "energy", "health", "swiss", "bayern", "hamburg", "koeln", "nrw"}


def _adressen(text):
    mails = [re.sub(r"\s*(\(at\)|\[at\])\s*", "@", m, flags=re.I).replace(" ", "").rstrip(".")
             for m in MAIL_RE.findall(text)]
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


ARTEN = [
    ("IT", r"\bit[- ]|support|helpdesk|administrator|system"),
    ("Disposition", r"disponent|disposition|dispatcher|(nah|güter|personen|schienen|bus)verkehr|verkehrs(plan|organisation|disponent|leit)|fahrdienst|tourenplan|einsatzplan|leitstelle|leitzentrale|mobilität"),
    ("Logistik", r"logistik|lager|spedition|transport|fuhrpark|versand"),
    ("Personal", r"personal|recruit|\bhr\b"),
]


def art(titel):
    """Art der Stelle nur nach dem Titel; der Anzeigentext erwähnt zu oft fremde Begriffe (Systeme, Verkehrsanbindung)."""
    for name, muster in ARTEN:
        if re.search(muster, titel.lower()):
            return name
    return "Büro"


def stelle(titel):
    """Stellentitel ohne Gehalts- und Ortsanhängsel."""
    return re.split(r"\s+[|*]|\s+\d[\d.,]*\s*(?:€|EUR)", titel)[0].strip(" -–") or titel


def einstellungen():
    """Eigene Angaben (Name, Anschrift, Gmail, Lebenslauf, Absätze fürs Anschreiben) aus einstellungen.json; sie liegt nur auf dem eigenen Rechner."""
    if not EINSTELLUNGEN.exists():
        raise RuntimeError("einstellungen.json fehlt: einstellungen.beispiel.json kopieren, in einstellungen.json umbenennen und ausfüllen.")
    return json.loads(EINSTELLUNGEN.read_text("utf-8"))


ARTEN_NAMEN = ("IT", "Disposition", "Logistik", "Personal", "Büro")
EINST_FELDER = ("name", "anschrift", "telefon", "gmail", "lebenslauf_pdf", "schlussabsatz")


def einstellungen_lesen():
    """Die Angaben für die Seite; leer, wenn es die Datei noch nicht gibt."""
    return json.loads(EINSTELLUNGEN.read_text("utf-8")) if EINSTELLUNGEN.exists() else {}


def einstellungen_speichern(neu):
    """Übernimmt Änderungen aus der Seite (nur bekannte Felder) und schreibt die Datei atomar."""
    with _SPERRE:
        e = einstellungen_lesen()
        for k in EINST_FELDER:
            if k in neu:
                e[k] = str(neu[k]).strip()
        if "absaetze" in neu:
            e["absaetze"] = {a: str(t).strip() for a, t in neu["absaetze"].items() if a in ARTEN_NAMEN and str(t).strip()}
        if e.get("gmail") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e["gmail"], re.I):
            raise ValueError("Die E-Mail-Adresse sieht nicht richtig aus.")
        hilfsdatei = EINSTELLUNGEN.with_suffix(".tmp")
        hilfsdatei.write_text(json.dumps(e, ensure_ascii=False, indent=2), "utf-8")
        os.replace(hilfsdatei, EINSTELLUNGEN)
        return e


def anschreiben(titel, firma, kategorie):
    e = einstellungen()
    absaetze = e.get("absaetze", {})
    bei = f" bei {firma}" if firma else ""
    teile = [
        "Sehr geehrte Damen und Herren,",
        f"mit großem Interesse habe ich Ihre Anzeige für die Stelle als {stelle(titel)}{bei} gelesen und bewerbe mich hiermit.",
        absaetze.get(kategorie) or absaetze.get("Büro", ""),  # fehlt die Art, gilt der Absatz "Büro"
        e.get("schlussabsatz", ""),
        "Meinen Lebenslauf finden Sie im Anhang. Über eine Einladung zu einem persönlichen Gespräch freue ich mich sehr.",
        "Mit freundlichen Grüßen",
        "\n".join(x for x in [e.get("name", ""), e.get("anschrift", ""), " · ".join(y for y in [e.get("telefon", ""), e.get("gmail", "")] if y)] if x),
    ]
    return "\n\n".join(t for t in teile if t) + "\n"


def mail_aus_impressum(text):
    """Adresse aus den rechtlichen Angaben einer Kleinanzeigen-Anzeige (Kontakt der Firma). Vorrang: steht davor "Bewerbung", dann eine Bewerbungs-Adresse
    (bewerbung@, jobs@, karriere@), sonst die erste mit üblicher Endung."""
    kandidaten = [m for m in _adressen(text or "") if _endung_ok(m)]
    for m in kandidaten:
        i = text.lower().find(m.lower())
        if "bewerb" in text[max(0, i - 120):i].lower():
            return m
    return next((m for m in kandidaten if GUT.search(m)), kandidaten[0] if kandidaten else "")


def vorbereiten(anzeige, volltext, impressum=""):
    kat = art(anzeige["titel"])
    an = mail_finden(volltext)
    quelle = "anzeige" if an else ""
    if not an:
        an = mail_aus_impressum(impressum)
        quelle = "impressum" if an else ""
    return {
        "id": anzeige["id"],
        "an": an,
        "an_quelle": quelle,  # "impressum": Firmenkontakt aus den rechtlichen Angaben, nicht ausdrücklich für Bewerbungen
        "unsicher": mail_unsicher(volltext),
        "betreff": f"Bewerbung als {stelle(anzeige['titel'])}",
        "text": anschreiben(anzeige["titel"], anzeige.get("firma", ""), kat),
        "art": kat,
    }


def entwuerfe():
    with _SPERRE:  # nie eine Datei lesen, die gerade geschrieben wird
        return json.loads(BEWORBEN.read_text("utf-8")) if BEWORBEN.exists() else {}


def _zugang():
    """Einstellungen, App-Passwort und Lebenslauf-PDF, oder eine verständliche Fehlermeldung."""
    e = einstellungen()
    passwort = PASSWORT_DATEI.read_text("utf-8").strip().replace(" ", "") if PASSWORT_DATEI.exists() else ""
    if not passwort:
        raise RuntimeError("App-Passwort fehlt: gmail_app_passwort.txt im Programmordner ausfüllen.")
    pdf = Path(e["lebenslauf_pdf"])
    if not pdf.exists():
        raise RuntimeError(f"Lebenslauf nicht gefunden: {pdf}")
    return e, passwort, pdf


def _nachricht(b, e, pdf):
    msg = EmailMessage()
    msg["From"] = f"{e['name']} <{e['gmail']}>"
    msg["To"] = b["an"]
    msg["Subject"] = b["betreff"]
    msg["Message-ID"] = make_msgid()
    msg.set_content(b["text"])
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
    return msg


def _merken(erledigt):
    BEWORBEN.parent.mkdir(exist_ok=True)
    hilfsdatei = BEWORBEN.with_suffix(".tmp")  # erst vollständig schreiben, dann austauschen: ein Absturz hinterlässt keine halbe Datei
    hilfsdatei.write_text(json.dumps(erledigt, ensure_ascii=False, indent=1), "utf-8")
    os.replace(hilfsdatei, BEWORBEN)


def _entwuerfe_ordner(imap):
    # der Entwürfe-Ordner heißt je nach Gmail-Sprache anders, er trägt aber immer die Markierung \Drafts
    return next(z.decode().split(' "/" ')[-1] for z in imap.list()[1] if b"\\Drafts" in z)


def entwurf_anlegen(liste):
    """Legt jede Bewerbung als Entwurf in Gmail ab. Gesendet wird nichts."""
    e, passwort, pdf = _zugang()
    ergebnis = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(e['gmail'], passwort)
        ordner = _entwuerfe_ordner(imap)
        for b in liste:
            try:
                with _SPERRE:
                    alt = entwuerfe().get(b["id"], {})
                    if alt.get("gesendet") or alt.get("sendet"):  # für gesendete Bewerbungen gibt es keinen Entwurf mehr
                        ergebnis.append({"id": b["id"], "ok": False, "fehler": "schon gesendet"})
                        continue
                msg = _nachricht(b, e, pdf)
                status, _ = imap.append(ordner, "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                ok = status == "OK"
                if ok:
                    # sofort und unter Sperre merken: frisch lesen, nur den eigenen Eintrag ändern (Abbruch und gleichzeitiges Senden verlieren nichts)
                    with _SPERRE:
                        erledigt = entwuerfe()
                        alt = erledigt.get(b["id"], {})
                        erledigt[b["id"]] = {**alt, "an": b["an"], "betreff": b["betreff"], "datum": date.today().isoformat(),
                                             "mids": alt.get("mids", []) + [msg["Message-ID"]]}  # alle Entwürfe merken, nicht nur den letzten
                        _merken(erledigt)
                ergebnis.append({"id": b["id"], "ok": ok})
            except Exception as e:
                # Verbindung weg: die schon angelegten bleiben vermerkt, der Rest wird als nicht angelegt gemeldet
                fehler = (str(e).strip().splitlines() or [type(e).__name__])[0]
                ergebnis += [{"id": r["id"], "ok": False, "fehler": fehler} for r in liste[len(ergebnis):]]
                break
    return ergebnis


def _entwurf_loeschen(imap, mids):
    """Entfernt die eigenen Entwürfe mit diesen Message-IDs aus Gmail; gibt die Zahl der gefundenen zurück."""
    imap.select(_entwuerfe_ordner(imap))
    gefunden = 0
    for mid in mids:
        nummern = imap.search(None, "HEADER", "Message-ID", mid)[1][0].split()
        for n in nummern:
            imap.store(n, "+FLAGS", "\\Deleted")
        gefunden += len(nummern)
    imap.expunge()
    return gefunden


def senden(b):
    """Sendet EINE Bewerbung über Gmail. Vorher angelegte Entwürfe dazu werden danach entfernt."""
    if not b["an"]:
        raise RuntimeError("Ohne E-Mail-Adresse kann nicht gesendet werden.")
    e, passwort, pdf = _zugang()
    # Prüfen und "sendet" vermerken in einem Zug unter Sperre, VOR dem Versand: gleichzeitige Anfragen können nicht beide senden,
    # und bleibt der Ausgang unklar (Verbindung weg nach der Annahme), sperrt der Vermerk ein zweites Senden
    with _SPERRE:
        erledigt = entwuerfe()
        alt = erledigt.get(b["id"], {})
        if alt.get("gesendet"):
            raise RuntimeError(f"Diese Bewerbung wurde schon am {alt['gesendet']} an {alt['an']} gesendet.")
        if alt.get("sendet"):
            raise RuntimeError(f"Der Versand vom {alt['sendet']} ist unklar geblieben. Bitte in Gmail unter „Gesendet“ nachsehen. "
                               "Ist die Mail nicht dort, in Ergebnisse\\entwuerfe.json bei dieser Bewerbung die Zeile \"sendet\" löschen.")
        erledigt[b["id"]] = {**alt, "an": b["an"], "betreff": b["betreff"], "sendet": date.today().isoformat()}
        _merken(erledigt)
    unklar = False
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(e['gmail'], passwort)
            unklar = True  # ab hier kann Gmail die Mail angenommen haben
            smtp.send_message(_nachricht(b, e, pdf))
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
        unklar = False  # Gmail hat die Mail ausdrücklich abgelehnt
        raise
    except Exception:
        if unklar:
            raise RuntimeError("Der Versand ist unklar geblieben (Verbindung unterbrochen). Bitte in Gmail unter „Gesendet“ nachsehen, "
                               "bevor du es erneut versuchst. Bis dahin ist diese Bewerbung gesperrt.")
        raise
    finally:
        if not unklar:  # nichts gesendet: Vermerk zurücknehmen
            with _SPERRE:
                erledigt = entwuerfe()
                if alt:
                    erledigt[b["id"]] = alt
                else:
                    erledigt.pop(b["id"], None)
                _merken(erledigt)
    try:
        with _SPERRE:
            erledigt = entwuerfe()
            erledigt[b["id"]] = {**alt, "an": b["an"], "betreff": b["betreff"], "gesendet": date.today().isoformat()}
            _merken(erledigt)
    except OSError:
        pass  # der Vermerk "sendet" bleibt stehen und sperrt ein zweites Senden
    entwurf_weg = None
    if alt.get("mids"):
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
                imap.login(e['gmail'], passwort)
                entwurf_weg = _entwurf_loeschen(imap, alt["mids"])
        except Exception:
            entwurf_weg = False
    return {"id": b["id"], "ok": True, "entwurf_geloescht": entwurf_weg}


if __name__ == "__main__":
    # kleiner Selbsttest für Adresssuche und Einordnung
    assert mail_finden("Fragen an datenschutz@x.de, Bewerbung an bewerbung@firma-b.de.") == "bewerbung@firma-b.de"
    assert mail_finden("bitte an jobs (at) firma-a.de senden") == "jobs@firma-a.de"
    assert mail_finden("info@firma.de") == "info@firma.de"
    assert mail_finden("keine Adresse") == ""
    assert mail_finden("an max.muster@firma-d.der oder jobs@firma-e.cm") == ""
    assert mail_unsicher("an max.muster@firma-d.der oder jobs@firma.de") == "max.muster@firma-d.der"
    assert mail_finden("bewerbung@firma.group und info@firma.nl") == "bewerbung@firma.group"
    assert mail_finden("Bewerbung an Berlin@Firma-C.de") == "Berlin@Firma-C.de"
    assert mail_aus_impressum("Rechtliche Angaben Bewerbungen bitte an: Muster GmbH Jobs2@firma-beispiel.de Kontakt filiale@firma-beispiel.de") == "Jobs2@firma-beispiel.de"
    assert mail_aus_impressum("Rechtliche Angaben Firma Telefon 040 1 E-Mail: info@firma-x.info Internet: www.firma-x.info") == "info@firma-x.info"
    assert mail_aus_impressum("Rechtliche Angaben Firma Datenschutz: datenschutz@firma.de") == "" and mail_aus_impressum("") == ""
    assert art("Mitarbeiter IT-Support & Administration") == "IT"
    assert art("Disponent Nahverkehr") == "Disposition"
    assert art("Rose B/BRB: Immobilienkaufmann m/w/d") == "Büro"
    assert art("Bürosachbearbeiter (m/w/d) Öffentlicher Dienst") == "Büro"
    assert art("Koordinator Lagerlogistik") == "Logistik"
    assert art("Verkehrsplaner*in (m/w/d)") == "Disposition"
    assert stelle("IT-Spezialist Support (w/m/d) *3272 - 3710 EUR/Monat*") == "IT-Spezialist Support (w/m/d)"
    print("Selbsttest ok")
