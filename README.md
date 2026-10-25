# Stellenlotse

Lebenslauf hochladen, Jobbörsen durchsuchen lassen, passende Stellen oben sehen, Bewerbungen als Gmail-Entwurf vorbereiten. Läuft lokal auf dem eigenen Rechner.

## Was es kann
- Sucht in **Kleinanzeigen**, der **Jobbörse der Arbeitsagentur** und **StepStone** (Umkreis, Vollzeit/Teilzeit, Homeoffice/Remote; die bundesweite Remote-Suche läuft nur über die Arbeitsagentur). StepStone liefert je Suche höchstens 200 passende Anzeigen.
- Blendet Zeitarbeitsfirmen und doppelte Anzeigen aus, sortiert nach Datum oder nach **Passung zum Lebenslauf**.
- Liest den **Lebenslauf (PDF)** und schlägt Suchbegriffe vor. Grundlage sind eine Wortliste und die Berufsbezeichnungen aus den 144 Berufsfeldern der Arbeitsagentur. Optional kann ein lokales **Ollama** ergänzen.
- Findet Bewerbungs-E-Mail-Adressen im Anzeigentext, schreibt ein Anschreiben nach Art der Stelle und legt es als **Gmail-Entwurf** an (Versand per Knopf nur nach Rückfrage).
- Merkt sich „Beworben“ und „Nicht interessant“.

## Starten
Voraussetzungen: Windows, Python 3.10 oder neuer.

```
pip install playwright pypdf
playwright install chromium
python berufe_laden.py          (einmalig, lädt die Berufsliste der Arbeitsagentur, einige Minuten)
```

Eigene Angaben: `einstellungen.beispiel.json` kopieren, in `einstellungen.json` umbenennen und ausfüllen (Name, Anschrift, Gmail, Pfad zum Lebenslauf-PDF, Absätze fürs Anschreiben). Für Gmail ein App-Passwort in `gmail_app_passwort.txt` eintragen.

Dann `START.bat` doppelklicken. Das Programm öffnet `http://localhost:4910`.

## Web-Version (Ordner `web`)
Läuft ohne Konto und ohne eigenen Server, gedacht für Vercel. Der Lebenslauf wird nur im Browser gelesen (pdf.js), nichts wird gespeichert; „Beworben“ und „Aussortiert“ liegen im lokalen Speicher des Browsers. Die Funktionen unter `web/api` holen nur Anzeigen von der Arbeitsagentur und StepStone (Kleinanzeigen geht online nicht, es braucht einen Browser). Statt Gmail gibt es eine E-Mail-Datei (`.eml`) mit Lebenslauf im Anhang, die das Mailprogramm als Entwurf öffnet.

KI-Hilfe (freiwillig, aus, bis ein Schlüssel gesetzt ist): `web/api/ki.py` schickt den vom Browser bereinigten Lebenslauftext (ohne Name, Anschrift, Telefon, E-Mail, Geburtsdaten; der Nutzer sieht und ändert ihn vorher) nur nach ausdrücklicher Einwilligung an Groq. Der Schlüssel steht als Umgebungsvariable `GROQ_API_KEY` bei Vercel, optional `KI_MODELL`. Die Bereinigung ist eine automatische Suche und garantiert nichts.

Lokal testen: `python web/dev.py` (öffnet `http://localhost:4920`). Bei Vercel einstellen: `vercel deploy --prod --cwd web`.

## Stand
Frühe Version, nur lokal gedacht. Die Jobbörsen haben eigene Nutzungsbedingungen, die jede Person für sich prüfen muss. Keine Gewähr.
