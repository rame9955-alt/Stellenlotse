# Stellenlotse

Lebenslauf hochladen, Jobbörsen durchsuchen lassen, passende Stellen oben sehen, Bewerbungen als Gmail-Entwurf vorbereiten. Läuft lokal auf dem eigenen Rechner.

## Was es kann
- Sucht in **Kleinanzeigen** und der **Jobbörse der Arbeitsagentur** (Umkreis, Vollzeit/Teilzeit, Homeoffice/Remote, bundesweit nur Remote).
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

## Stand
Frühe Version, nur lokal gedacht. Die Jobbörsen haben eigene Nutzungsbedingungen, die jede Person für sich prüfen muss. Keine Gewähr.
