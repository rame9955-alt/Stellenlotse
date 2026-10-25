// Alles, was mit dem Lebenslauf zu tun hat, läuft im Browser: Der Lebenslauf verlässt den Rechner des Nutzers nie.
// Berufserkennung: Übernahme von lebenslauf.py (feste Wortliste plus Berufsbezeichnungen der Arbeitsagentur aus berufsfelder.json).

const BERUFE = {
  'IT-Support': ['it-support', 'support', 'helpdesk', 'service desk', 'fernwartung', 'windows', 'microsoft 365', 'active directory',
    'entra', 'intune', 'netzwerk', 'dns', 'vpn', 'wlan', 'druckereinrichtung', 'powershell', 'bash', 'hardware'],
  'Systemadministrator': ['administrator', 'administration', 'active directory', 'entra', 'intune', 'microsoft 365', 'server', 'netzwerk',
    'powershell', 'hosting', 'deployment', 'linux'],
  'Webentwickler': ['next.js', 'react', 'javascript', 'typescript', 'node', 'postgresql', 'supabase', 'github', 'web-anwendung',
    'online-shop', 'deployment', 'vercel', 'frontend', 'backend'],
  'Disponent': ['disposition', 'disponent', 'tourenplanung', 'fuhrpark', 'flotte', 'personenbeförderung', 'schichtkoordination', 'logistik'],
  'Logistik': ['logistik', 'lager', 'versand', 'schichtkoordination', 'supply chain', 'transport', 'verkehrswesen'],
  'Recruiter': ['recruiter', 'recruiting', 'bewerbermanagement', 'interviews', 'onboarding', 'personalreferent', 'personal'],
  'Sachbearbeiter': ['sachbearbeiter', 'dateneingabe', 'datenmanagement', 'dokumentation', 'ms office', 'excel', 'word', 'büro', 'verwaltung'],
  'Büro': ['büro', 'office', 'verwaltung', 'sekretariat', 'assistenz', 'ms office', 'excel', 'dokumentation'],
  'Teamleiter': ['teamleiter', 'teamleitung', 'teamsteuerung', 'führung', 'operative leitung', 'schichtkoordination'],
  'Projektmanager': ['projektmanager', 'projektleitung', 'projektmanagement', 'prozessoptimierung', 'automatisierung', 'strategie'],
  'Kundenservice': ['kundenservice', 'kundenberatung', 'kundensupport', 'kundenbetreuung', 'beratung', 'support'],
  'Buchhaltung': ['buchhaltung', 'finanzbuchhaltung', 'rechnungswesen', 'controlling', 'finanzen', 'kostenoptimierung'],
};
const ZU_ALLGEMEIN = new Set(['katholisch', 'mitarbeiter', 'wirtschaft', 'spanisch', 'englisch', 'deutsch', 'arabisch', 'französisch', 'helfer', 'fachkraft']);
const BUCHSTABE = '[\\p{L}\\p{N}_]';  // \w kennt in JavaScript keine Umlaute

const regexEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Ganzes Wort mit höchstens 3 Buchstaben Endung ("Verkäuferin" für "verkäufer"), nicht mitten im Wort ("excel" in "excellent")
function kommtVor(wort, t) {
  return t.includes(wort) && new RegExp(`(?<!${BUCHSTABE})${regexEsc(wort)}${BUCHSTABE}{0,3}(?!${BUCHSTABE})`, 'u').test(t);
}

function basis(beruf) {  // "Fachinformatiker/in - Systemintegration" -> ["fachinformatiker", "systemintegration"]; zu kurze Teile fallen weg
  const b = beruf.replace(/\(.*?\)/g, '').replace(/\/[-\p{L}\p{N}_]*/gu, '');
  return b.split(/ - |, /).map(x => x.trim().toLowerCase()).filter(x => x.length >= 8);
}

let baWoerter = null;  // Berufswort -> Berufsfelder, einmal aus berufsfelder.json gebaut
async function baWoerterLaden() {
  if (baWoerter) return baWoerter;
  baWoerter = new Map();
  try {
    const felder = await (await fetch('berufsfelder.json')).json();
    for (const [feld, berufe] of Object.entries(felder))
      for (const b of berufe) for (const c of basis(b)) if (!ZU_ALLGEMEIN.has(c)) (baWoerter.get(c) || baWoerter.set(c, new Set()).get(c)).add(feld);
  } catch { /* ohne die Liste gilt nur die feste Wortliste */ }
  return baWoerter;
}

async function profilBauen(text) {
  const t = text.toLowerCase().replace(/[^\p{L}\p{N}_.+# -]+/gu, ' ').split(/\s+/).filter(Boolean).join(' ');
  const treffer = Object.fromEntries(Object.entries(BERUFE).map(([b, ws]) => [b, ws.filter(w => kommtVor(w, t))]));
  const berufe = Object.keys(treffer).filter(b => treffer[b].length >= 3).sort((x, y) => treffer[y].length - treffer[x].length);
  const ba = new Map([...(await baWoerterLaden())].filter(([c]) => kommtVor(c, t)));
  const vorhanden = new Set(berufe.map(b => b.toLowerCase()));
  [...ba.keys()].sort((x, y) => ba.get(y).size - ba.get(x).size).forEach(c => {
    if (!vorhanden.has(c)) { const name = c[0].toUpperCase() + c.slice(1); berufe.push(name); treffer[name] = [c]; }
  });
  const zaehl = {};
  ba.forEach(fs => fs.forEach(f => zaehl[f] = (zaehl[f] || 0) + 1));
  return {
    berufe, woerter: [...new Set(berufe.flatMap(b => treffer[b]))].sort(),
    treffer: Object.fromEntries(berufe.map(b => [b, treffer[b]])),
    felder: Object.keys(zaehl).sort((x, y) => zaehl[y] - zaehl[x]).slice(0, 5),
  };
}

// PDF lesen mit pdf.js (von cdnjs geladen); liefert den reinen Text
async function pdfText(datei) {
  pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  const doc = await pdfjsLib.getDocument({ data: await datei.arrayBuffer() }).promise;
  let text = '';
  for (let i = 1; i <= doc.numPages; i++) {
    let y = null;  // neue Zeile, wenn pdf.js das Zeilenende meldet oder die Höhe springt (nötig für die KI-Bereinigung, die zeilenweise arbeitet)
    for (const x of (await (await doc.getPage(i)).getTextContent()).items) {
      const hoehe = Math.round(x.transform[5]);
      if (y !== null && Math.abs(hoehe - y) > 3 && !text.endsWith('\n')) text += '\n';
      text += x.str + (x.hasEOL ? '\n' : ' ');
      y = hoehe;
    }
    text += '\n';
  }
  if (text.trim().length < 100) throw new Error('Im Lebenslauf konnte kaum Text gelesen werden (Scan ohne Textebene?). Bitte ein PDF mit Text hochladen.');
  return text;
}

// ---------- Anschreiben (Übernahme von bewerbung.py) ----------
const ARTEN = [
  ['IT', /\bit[- ]|support|helpdesk|administrator|system/],
  ['Disposition', /disponent|disposition|dispatcher|(nah|güter|personen|schienen|bus)verkehr|verkehrs(plan|organisation|disponent|leit)|fahrdienst|tourenplan|einsatzplan|leitstelle|leitzentrale|mobilität/],
  ['Logistik', /logistik|lager|spedition|transport|fuhrpark|versand/],
  ['Personal', /personal|recruit|\bhr\b/],
];
const art = titel => (ARTEN.find(([, m]) => m.test(titel.toLowerCase())) || ['Büro'])[0];  // nur nach dem Titel; der Anzeigentext erwähnt zu oft fremde Begriffe
const stelle = titel => titel.split(/\s+[|*]|\s+\d[\d.,]*\s*(?:€|EUR)/)[0].replace(/^[\s\-–]+|[\s\-–]+$/g, '') || titel;

function anschreiben(titel, firma, kategorie, e) {
  const ab = e.absaetze || {};
  return [
    'Sehr geehrte Damen und Herren,',
    `mit großem Interesse habe ich Ihre Anzeige für die Stelle als ${stelle(titel)}${firma ? ' bei ' + firma : ''} gelesen und bewerbe mich hiermit.`,
    ab[kategorie] || ab['Büro'] || '',  // fehlt die Art, gilt der Absatz "Büro"
    e.schluss || '',
    'Meinen Lebenslauf finden Sie im Anhang. Über eine Einladung zu einem persönlichen Gespräch freue ich mich sehr.',
    'Mit freundlichen Grüßen',
    [e.name, e.anschrift, [e.telefon, e.email].filter(Boolean).join(' · ')].filter(Boolean).join('\n'),
  ].filter(Boolean).join('\n\n') + '\n';
}

// ---------- E-Mail als Datei (.eml) mit dem Lebenslauf im Anhang; das Mailprogramm öffnet sie als Entwurf ----------
const b64Zeilen = b64 => b64.replace(/(.{76})/g, '$1\r\n');
const b64Text = s => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const kopfText = s => /^[\x20-\x7e]*$/.test(s) ? s : `=?UTF-8?B?${b64Text(s)}?=`;  // Umlaute im Betreff
function bytesB64(buffer) {
  let s = '';
  const b = new Uint8Array(buffer);
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000));
  return btoa(s);
}
async function emlBauen({ an, betreff, text, von, name, pdf }) {
  const g = 'stellenlotse-' + Math.random().toString(36).slice(2);
  const zeilen = [
    `From: ${name ? kopfText(name) + ' ' : ''}<${von}>`, `To: ${an}`, `Subject: ${kopfText(betreff)}`, 'X-Unsent: 1', 'MIME-Version: 1.0',
    `Content-Type: multipart/mixed; boundary="${g}"`, '',
    `--${g}`, 'Content-Type: text/plain; charset=utf-8', 'Content-Transfer-Encoding: base64', '', b64Zeilen(b64Text(text)), '',
  ];
  if (pdf) zeilen.push(`--${g}`, `Content-Type: application/pdf; name="${kopfText(pdf.name)}"`, 'Content-Transfer-Encoding: base64',
    `Content-Disposition: attachment; filename="${kopfText(pdf.name)}"`, '', b64Zeilen(bytesB64(await pdf.arrayBuffer())), '');
  zeilen.push(`--${g}--`, '');
  return new Blob([zeilen.join('\r\n')], { type: 'message/rfc822' });
}

// ---------- Bereinigen vor der KI-Hilfe: Kontaktdaten und Name raus (Heuristik, die Vorschau zeigt, was wirklich gesendet wird) ----------
const KOPF = /^(persönliche\s+daten|personalien|kontakt(daten)?)\s*:?$/i;
const NAECHSTER = /^(profil|über\s+mich|kurzprofil|weiterbildung|praxiserfahrung|berufserfahrung|beruflicher\s+werdegang|werdegang|bildungsweg|ausbildung|kenntnisse|fähigkeiten|kompetenzen|sprachen|sonstiges|zusatzqualifikationen|hobbys|interessen)\b/i;
const KONTAKT = [/@/, /(\+|\b00)\s?\d[\d\s/().-]{6,}/, /\b0\d{2,5}[\s/-]\d{4,}/, /\b\d{5}\s+\p{L}{3,}/u, /https?:\/\/|www\.|linkedin|xing\.com/i,
  /(straße|strasse|str\.|weg|allee|platz|gasse|ring|damm|ufer)\s*\d+\s?[a-z]?\b/i, /geburts|geboren|anschrift|adresse|telefon|\bmobil\b|handy|familienstand|staatsangeh|nationalit|e-?mail/i];

function namenErkennen(text, bekannt = '') {
  const namen = new Set(bekannt.split(/\s+/));
  const z = text.split(/\n+/).map(s => s.trim());
  z.forEach((s, i) => {
    if (/^name\s*:?$/i.test(s) && z[i + 1]) z[i + 1].split(/\s+/).forEach(n => namen.add(n));  // "Name" / "Max Muster"
    if (s.includes('@') && s.includes('|')) s.split('|')[0].trim().split(/\s+/).forEach(n => namen.add(n));  // Kopfzeile "Max Muster | mail | tel"
  });
  return [...namen].map(n => n.replace(/[,;:]/g, '')).filter(n => n.length >= 3 && !/^\d+$/.test(n));
}

function bereinigen(text, bekannterName = '') {
  const namen = namenErkennen(text, bekannterName);
  let ueberspringen = false;
  const zeilen = text.split(/\n/).map(s => s.trim()).filter(Boolean).filter(s => {
    if (KOPF.test(s)) { ueberspringen = true; return false; }          // ganzer Block "Persönliche Daten"
    if (ueberspringen && NAECHSTER.test(s)) ueberspringen = false;
    return !ueberspringen && !KONTAKT.some(m => m.test(s));
  });
  let t = zeilen.join('\n');
  namen.forEach(n => { t = t.replace(new RegExp(`(?<![\p{L}\p{N}_])${regexEsc(n)}(?![\p{L}\p{N}_])`, 'giu'), ''); });
  return t.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').replace(/^\s*[|,;-]+\s*$/gm, '').trim();
}
