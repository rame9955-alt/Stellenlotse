// Stellenlotse Web: Suche, Filter, Passung und Merklisten laufen im Browser; die Funktionen unter /api holen nur die Anzeigen.
// Gemerkt wird ausschließlich im lokalen Speicher dieses Browsers (nichts davon liegt auf dem Server).

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const norm = s => String(s ?? '').toLowerCase().replace(/[^a-zäöüß0-9]+/g, ' ').trim();
const adresseOK = s => /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(s);
const fehlerText = e => '<span class="fehler">Fehler: ' + esc(String(e.message || e)) + '</span>';
const MAX_VORB = 60;  // so viele Anzeigen werden höchstens auf einmal im Detail gelesen (schont StepStone und die Arbeitsagentur)

const speicher = {  // lokaler Speicher kann gesperrt sein (privates Fenster): dann geht alles weiter, nur ohne Merken
  lesen(k, std) { try { return JSON.parse(localStorage.getItem(k)) ?? std; } catch { return std; } },
  schreiben(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ohne Merken weitermachen */ } },
};

let alle = [], stand = {};                      // stand: Kopfdaten der angezeigten Suche
let aus = speicher.lesen('sl.aus', {});         // aussortierte Anzeigen (id -> Titel, Firma, Link)
let beworben = speicher.lesen('sl.beworben', {});  // Bewerbungen, die raus sind (id -> Titel, Firma, Link, Datum, Art)
let profil = speicher.lesen('sl.profil', {});
let cvDatei = null;                             // der gewählte Lebenslauf (PDF); nur im Speicher dieser Seite, geht an die E-Mail-Datei
let aktuelleEchte = [], vorbereitet = [];
const zurueck = new Set();                      // Firmen oder Gruppen, die der Nutzer wieder sehen will

// ---------- Meine Angaben ----------
const ABSATZ_ARTEN = ['IT', 'Disposition', 'Logistik', 'Personal', 'Büro'];
const angaben = speicher.lesen('sl.angaben', { absaetze: {} });
function angabenLaden() {
  ['name', 'anschrift', 'telefon', 'email', 'schluss'].forEach(f => $('an_' + f).value = angaben[f] || '');
  ABSATZ_ARTEN.forEach(a => $('ab_' + a).value = (angaben.absaetze || {})[a] || '');
}
function angabenSpeichern() {
  ['name', 'anschrift', 'telefon', 'email', 'schluss'].forEach(f => angaben[f] = $('an_' + f).value.trim());
  angaben.absaetze = Object.fromEntries(ABSATZ_ARTEN.map(a => [a, $('ab_' + a).value.trim()]).filter(([, t]) => t));
  speicher.schreiben('sl.angaben', angaben);
}
document.querySelectorAll('#angaben input, #angaben textarea').forEach(el => el.addEventListener('input', angabenSpeichern));
angabenLaden();

// ---------- Anfrage an die Funktionen ----------
async function api(url, body) {
  const r = await fetch(url, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  let d = {};
  try { d = await r.json(); } catch { /* keine JSON-Antwort */ }
  if (!r.ok || d.fehler) throw new Error(d.fehler || `Fehler ${r.status}`);
  return d;
}

// ---------- Suche ----------
const zeitstempel = () => { const d = new Date(), z = n => String(n).padStart(2, '0'); return `${z(d.getDate())}.${z(d.getMonth() + 1)}. ${z(d.getHours())}:${z(d.getMinutes())}`; };

async function stepstoneLesen(p) {
  const gesamt = new Map();
  for (let n = 1; n <= 8; n++) {  // 25 Anzeigen je Seite; hinter der letzten passenden Seite kommen nur noch Vorschläge
    const d = await api('/api/suche?' + new URLSearchParams({ ...p, quelle: 'st', seite: n }));
    const neu = d.anzeigen.filter(a => !gesamt.has(a.id));
    neu.forEach(a => gesamt.set(a.id, a));
    if (!neu.length) break;
  }
  return [...gesamt.values()];
}

$('los').onclick = async () => {
  const bundesweit = $('umkreis').value === 'remote';  // bundesweit: ohne PLZ, nur Arbeitsagentur
  const meldung = t => { $('ergebnis').hidden = false; $('info').innerHTML = `<span class="fehler">${t}</span>`; $('liste').innerHTML = ''; };
  if (!bundesweit && !/^\d{5}$/.test($('stadt').value.trim())) return meldung('Bitte eine fünfstellige PLZ eingeben, z. B. 10115.');
  const quellen = bundesweit ? ['ba'] : [...document.querySelectorAll('input[name=quelle]:checked')].map(q => q.value);
  if (!quellen.length) return meldung('Bitte mindestens eine Quelle wählen.');
  const p = { begriff: $('begriff').value.trim(), plz: $('stadt').value.trim(), umkreis: $('umkreis').value };
  $('los').disabled = true;
  $('los').textContent = 'Läuft, liest die Jobbörsen (etwa 10 bis 20 Sekunden) ...';
  try {
    const teile = [];
    if (quellen.includes('ba')) teile.push(['Arbeitsagentur', api('/api/suche?' + new URLSearchParams({ ...p, quelle: 'ba' })).then(d => d.anzeigen)]);
    if (quellen.includes('st')) teile.push(['StepStone', stepstoneLesen(p)]);
    const ergebnis = await Promise.allSettled(teile.map(([, t]) => t));
    const anzahl = {}, fehler = [];
    let anzeigen = [];
    ergebnis.forEach((r, i) => {
      if (r.status === 'fulfilled') { anzeigen = anzeigen.concat(r.value); anzahl[teile[i][0]] = r.value.length; }
      else fehler.push(`${teile[i][0]}: ${r.reason.message || r.reason}`);
    });
    if (!anzeigen.length && fehler.length) throw new Error(fehler.join(' · '));
    // NEU: Anzeigen, die bei der letzten gleichen Suche fehlten (bei der ersten Suche gibt es nichts zu vergleichen)
    const schluessel = 'sl.gesehen.' + [p.begriff, p.plz, p.umkreis, quellen.join()].join('|').toLowerCase();
    const frueher = speicher.lesen(schluessel, null);
    if (frueher) { const set = new Set(frueher); anzeigen.forEach(a => a.neu = !set.has(a.id)); }
    speicher.schreiben(schluessel, anzeigen.map(a => a.id).slice(0, 3000));
    uebernehmen({ anzeigen, anzahl, zeit: zeitstempel(), begriff: p.begriff, stadt: p.plz, umkreis: p.umkreis, quellen, fehler });
    merkeSuche({ begriff: p.begriff, stadt: p.plz, umkreis: p.umkreis, quellen, zeit: zeitstempel() });
  } catch (e) {
    meldung('Fehler: ' + esc(e.message || e));
  }
  $('los').disabled = false;
  $('los').textContent = 'Suche starten';
};

function uebernehmen(d) {
  alle = d.anzeigen;
  stand = d;
  zurueck.clear();
  zeigen();
}

const QUELLE = { ba: 'Arbeitsagentur', st: 'StepStone' };
function merkeSuche(s) {
  const l = speicher.lesen('sl.suchen', []).filter(x => !(x.begriff === s.begriff && x.stadt === s.stadt && x.umkreis === s.umkreis));
  speicher.schreiben('sl.suchen', [s, ...l].slice(0, 8));
  suchenZeigen();
}
function suchenZeigen() {
  const l = speicher.lesen('sl.suchen', []);
  $('gespeichert').hidden = !l.length;
  $('liste3').innerHTML = l.map((s, i) => `<div class="such" data-i="${i}">
      <span>${esc(s.begriff)} · ${s.umkreis === 'remote' ? 'bundesweit Remote' : esc(s.stadt) + ' · ' + (s.umkreis ? esc(s.umkreis) + ' km' : 'Umkreis egal')} · ${s.quellen.map(q => QUELLE[q]).join(' + ')}</span><span>${esc(s.zeit)}</span></div>`).join('');
  $('liste3').querySelectorAll('.such').forEach(el => el.onclick = () => {
    const s = speicher.lesen('sl.suchen', [])[+el.dataset.i];  // die Suche wird neu gestartet (Ergebnisse speichern wir nicht)
    $('begriff').value = s.begriff; $('stadt').value = s.stadt; $('umkreis').value = s.umkreis || '';
    document.querySelectorAll('input[name=quelle]').forEach(q => q.checked = s.quellen.includes(q.value));
    $('los').click();
  });
}
suchenZeigen();

// ---------- Merklisten ----------
function ausZeigen() {
  const eintraege = Object.entries(aus);
  $('aussortiert').hidden = !eintraege.length;
  $('ausKopf').textContent = `Aussortiert (${eintraege.length})`;
  $('liste5').innerHTML = eintraege.map(([id, a]) => `<div class="weg"><span><a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.titel)}</a>${a.firma ? ' · ' + esc(a.firma) : ''}</span><button data-id="${esc(id)}">zurückholen</button></div>`).join('');
  $('liste5').querySelectorAll('button').forEach(b => b.onclick = () => { delete aus[b.dataset.id]; speicher.schreiben('sl.aus', aus); zeigen(); });
}
function bewZeigen() {
  const eintraege = Object.entries(beworben).reverse();  // zuletzt Eingetragene zuerst
  $('beworbenKarte').hidden = !eintraege.length;
  $('bewKopf').textContent = `Beworben (${eintraege.length})`;
  $('liste6').innerHTML = eintraege.map(([id, a]) => `<div class="weg"><span>${a.link ? `<a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.titel)}</a>` : esc(a.titel)}${a.firma ? ' · ' + esc(a.firma) : ''}<br><span class="klein">${esc(a.datum || '')} · ${esc(a.art || '')}</span></span><button data-id="${esc(id)}">zurückholen</button></div>`).join('');
  $('liste6').querySelectorAll('button').forEach(b => b.onclick = () => { delete beworben[b.dataset.id]; speicher.schreiben('sl.beworben', beworben); zeigen(); });
}
const eintrag = a => ({ titel: a.titel, firma: a.firma || '', link: a.link });

document.querySelectorAll('input[name=zeit], #ohneZA, #abFirma, #abGleich, #sortierung, #homeoffice').forEach(el => el.oninput = () => alle.length && zeigen());

// ---------- Filter ----------
// Remote oder Homeoffice nach Titel, Text und (bei der Arbeitsagentur und StepStone) dem Merkmal "Homeoffice möglich".
// Gibt 'remote' (komplett von zu Hause), 'moeglich' (Homeoffice, oft nur einzelne Tage) oder '' zurück.
const VOLL_RE = /100\s?%\s*(remote|home\s?-?office|mobil)|(remote|home\s?-?office)\W{0,6}100\s?%|\bfull[\s-]?remote\b|(komplett|vollständig|ausschließlich|rein)\w*\s+(remote|von zu hause|im home\s?-?office)/i;
const TEIL_RE = /\b\d{1,2}\s?%\s*(remote|home\s?-?office)|remote\W{0,3}(möglich|optional|teilweise|hybrid|nach absprache)|teil(weise)?[\s-]*remote|hybrid|(remote|home\s?-?office)\s*(&|und|\/|oder)\s*(präsenz|büro|office|vor ort)|(präsenz|büro|vor ort)\s*(&|und|\/|oder)\s*(remote|home\s?-?office)/i;
const REMOTE_RE = /\bremote\b(?![\s-]*(support|access|desktop|zugriff|wartung|service|monitoring|steuerung|administration))/i;
const HOME_RE = /home\s?-?office|mobiles?\s+arbeiten|mobile\s+work|von\s+zu\s+hause|hybrid|arbeiten\s+von\s+überall/i;
function homeofficeArt(a) {
  const t = `${a.titel || ''} ${a.text || ''}`;
  if (VOLL_RE.test(t)) return 'remote';
  if (TEIL_RE.test(t)) return 'moeglich';
  if (REMOTE_RE.test(t)) return 'remote';
  return a.homeoffice === true || HOME_RE.test(t) ? 'moeglich' : '';
}
function passtHome(a) {
  const w = $('homeoffice').value;
  return w === 'egal' || (w === 'remote' ? homeofficeArt(a) === 'remote' : homeofficeArt(a) !== '');
}

// Wann eine Anzeige eingestellt wurde, als Zeitwert (0 = unbekannt); beide Jobbörsen liefern "21.10.2026"
function eingestellt(a) {
  const m = String(a.datum || '').match(/^(\d\d)\.(\d\d)\.(\d{4})/);
  return m ? new Date(+m[3], +m[2] - 1, +m[1]).getTime() : 0;
}
function passtZeit(a) {
  const z = document.querySelector('input[name=zeit]:checked').value;
  if ($('ohneZA').checked && a.zeitarbeit) return false;  // nur die Arbeitsagentur sagt, was Zeitarbeit ist
  if (a.arbeitszeit !== undefined) return z === 'egal' || !a.arbeitszeit || a.arbeitszeit === z;  // die Arbeitsagentur liefert die Arbeitszeit mit
  const t = (a.titel + ' ' + a.text).toLowerCase();
  const voll = t.includes('vollzeit'), teil = /teilzeit|minijob|aushilfe/.test(t);
  if (z === 'voll') return !(teil && !voll);
  if (z === 'teil') return !(voll && !teil);
  return true;
}

// Passung zum Lebenslauf: Beruf im Titel zählt 5, jedes Wort in Titel oder Text 1
function passung(a) {
  if (!profil.berufe) return 0;
  const titel = norm(a.titel), t = titel + ' ' + norm(a.text || '');
  return profil.berufe.reduce((s, b) => s + (titel.includes(norm(b)) ? 5 : 0), 0) + profil.woerter.reduce((s, w) => s + (t.includes(norm(w)) ? 1 : 0), 0);
}

function zeigen() {
  ausZeigen();
  bewZeigen();
  if (!alle.length) return;  // noch keine Suche geladen: nur die Kästen "Beworben" und "Aussortiert" sind zu zeigen
  const abFirma = Math.max(2, +$('abFirma').value || 3);
  const abGleich = Math.max(2, +$('abGleich').value || 3);

  // 1. Firmen mit vielen Anzeigen
  const proFirma = {};
  alle.forEach(a => { if (a.firma) proFirma[a.firma] = (proFirma[a.firma] || 0) + 1; });
  const firmaWeg = f => f && proFirma[f] >= abFirma && !zurueck.has('f:' + f);

  // 2. Gleiche Anzeige mehrfach: gleiche Firma und gleicher Titel ohne Ortsnamen und PLZ
  const schluessel = a => {
    const ortWorte = norm(a.ort).split(' ');
    return norm(a.firma) + '|' + norm(a.titel).split(' ').filter(w => !ortWorte.includes(w) && w !== norm(stand.stadt || '')).join(' ');
  };
  const gruppen = {};
  alle.forEach(a => (gruppen[schluessel(a)] ||= []).push(a));

  const echte = [], wegGruppen = [];
  Object.entries(gruppen).forEach(([k, g]) => {
    if (firmaWeg(g[0].firma)) return;  // steht schon unter der Firma bei „Ausgeblendet“
    if (g.length >= abGleich && !zurueck.has('g:' + k)) { wegGruppen.push([k, g]); return; }
    const a = g.find(a => passtZeit(a) && passtHome(a) && !aus[a.id] && !beworben[a.id]);  // aussortierte und schon beworbene Anzeigen werden nie gezeigt
    if (a) echte.push({ ...a, mal: g.length });
  });

  $('ergebnis').hidden = false;
  const sortierung = $('sortierung').value;
  if (sortierung === 'neu') echte.sort((x, y) => (y.neu === true) - (x.neu === true));  // NEU nach oben
  else if (sortierung === 'passung') {  // Passung einmal je Anzeige berechnen; bei gleicher Punktzahl NEU zuerst, dann neueste
    echte.forEach(a => a.p = passung(a));
    echte.sort((x, y) => (y.p - x.p) || ((y.neu === true) - (x.neu === true)) || (eingestellt(y) - eingestellt(x)));
  } else {  // nach Datum; Anzeigen ohne Datum stehen immer ganz unten
    const richtung = sortierung === 'neueste' ? -1 : 1;
    echte.sort((x, y) => (!eingestellt(x) - !eingestellt(y)) || richtung * (eingestellt(x) - eingestellt(y)));
  }
  aktuelleEchte = echte;
  $('vorb').hidden = !echte.length;
  $('vorb').textContent = `Bewerbungen für ${echte.length > MAX_VORB ? 'die ersten ' + MAX_VORB : echte.length} Jobs vorbereiten`;
  const neue = echte.filter(a => a.neu === true).length;
  const gelesen = Object.entries(stand.anzahl || {}).map(([q, n]) => `${n} ${q}`).join(' + ');
  $('info').textContent = `${gelesen} gelesen, Stand ${stand.zeit}, ${echte.length} echte` + (neue ? `, davon ${neue} neu` : '');
  if ((stand.fehler || []).length) $('info').insertAdjacentHTML('beforeend', `<div class="klein fehler" style="font-weight:400">Nicht erreichbar: ${esc(stand.fehler.join(' · '))}</div>`);
  $('liste').innerHTML = echte.map(a => `<div class="job">
      ${a.neu === true ? '<span class="neu">NEU</span>' : ''}${profil.berufe ? `<span class="klein" title="Treffer aus deinem Lebenslauf">[Passung ${a.p ?? passung(a)}] </span>` : ''}<a href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.titel)}</a>
      <div class="klein">${esc(a.ort)}${a.entfernung ? ' (' + esc(a.entfernung) + ')' : ''}${a.datum ? ' · ' + esc(a.datum) : ''}${a.firma ? ' · ' + esc(a.firma) : ' · ohne Firmenname'}${a.mal > 1 ? ' · ' + a.mal + '× eingestellt' : ''} · ${esc(a.quelle)}${a.zeitarbeit ? ' · Zeitarbeit' : ''}${{ remote: ' · Remote', moeglich: ' · Homeoffice möglich' }[homeofficeArt(a)] || ''}</div>
      <div class="klein">${esc(a.text)}</div></div>`).join('') || '<div class="klein">Keine Anzeigen übrig.</div>';

  const wegFirmen = Object.entries(proFirma).filter(([f]) => firmaWeg(f)).sort((x, y) => y[1] - x[1]);
  const zeilen = [
    ...wegFirmen.map(([f, n]) => `<div class="weg"><span>${esc(f)} <b>${n}×</b></span><button data-k="f:${esc(f)}">zeigen</button></div>`),
    ...wegGruppen.map(([k, g]) => `<div class="weg"><span>Gleiche Anzeige <b>${g.length}×</b>: ${esc(g[0].titel)}</span><button data-k="g:${esc(k)}">zeigen</button></div>`),
  ];
  $('ausgeblendet').hidden = !zeilen.length;
  $('liste2').innerHTML = zeilen.join('');
  $('liste2').querySelectorAll('button').forEach(b => b.onclick = () => { zurueck.add(b.dataset.k); zeigen(); });
}

// ---------- Lebenslauf ----------
function profilZeigen(meldung) {
  $('cvInfo').textContent = meldung || (profil.berufe ? 'Erkannt, Klick auf einen Beruf setzt den Suchbegriff:' : '');
  $('cvFelder').textContent = (profil.felder || []).length ? 'Berufsfelder der Arbeitsagentur, die zum Lebenslauf passen: ' + profil.felder.join(' · ') : '';
  $('cvBerufe').innerHTML = (profil.berufe || []).map(b => `<button class="cvb" data-b="${esc(b)}">${esc(b)} <span class="klein">${profil.treffer[b].length}</span></button>`).join(' ');
  $('cvBerufe').querySelectorAll('button').forEach(k => k.onclick = () => { $('begriff').value = k.dataset.b; });
}
$('cv').onchange = async () => {
  const f = $('cv').files[0];
  if (!f) return;
  cvDatei = f;
  $('cvInfo').textContent = 'Lese Lebenslauf ...';
  try {
    const p = await profilBauen(await pdfText(f));
    if (!p.berufe.length) throw new Error('Im Lebenslauf wurde kein bekannter Beruf erkannt. Die Suchbegriffe kannst du weiter selbst eintippen.');
    profil = p;
    speicher.schreiben('sl.profil', p);  // nur Berufe und Stichwörter, nicht der Text
    profilZeigen();
    if (alle.length) zeigen();
  } catch (e) { $('cvInfo').innerHTML = fehlerText(e); }
};
if (profil.berufe) profilZeigen('Zuletzt erkannt (der Lebenslauf selbst wird nicht gespeichert, für die E-Mail-Datei bitte das PDF oben wieder auswählen). Klick auf einen Beruf setzt den Suchbegriff:');

// ---------- Bewerbungen vorbereiten ----------
$('vorb').onclick = async () => {
  const liste = aktuelleEchte.slice(0, MAX_VORB);
  $('vorb').disabled = true;
  try {
    const gelesen = new Map();
    const pakete = [];
    for (let i = 0; i < liste.length; i += 12) pakete.push(liste.slice(i, i + 12));
    let fertig = 0;
    const lauf = async () => {  // 3 Pakete gleichzeitig
      while (pakete.length) {
        const paket = pakete.shift();
        const d = await api('/api/vorbereiten', { anzeigen: paket.map(a => ({ id: a.id, quelle: a.quelle, refnr: a.refnr, link: a.link })) });
        d.ergebnisse.forEach(r => gelesen.set(r.id, r));
        fertig += paket.length;
        $('vorb').textContent = `Liest Anzeigen im Detail: ${fertig} von ${liste.length} ...`;
      }
    };
    await Promise.all([lauf(), lauf(), lauf()]);
    vorbereitet = liste.map(a => {
      const r = gelesen.get(a.id) || {}, k = art(a.titel);
      return { id: a.id, anzeige: a, an: r.an || '', unsicher: r.unsicher || '', lesefehler: r.lesefehler || '', art: k,
        betreff: `Bewerbung als ${stelle(a.titel)}`, text: anschreiben(a.titel, a.firma || '', k, angaben) };
    });
    bewerbungenZeigen();
    $('bewerben').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    alert('Fehler: ' + (e.message || e));
  }
  $('vorb').disabled = false;
  zeigen();  // setzt die Beschriftung des Knopfes zurück
};

function bewerbungenZeigen() {
  $('bewerben').hidden = false;
  $('angabenHinweis').hidden = !!(angaben.name && angaben.email);
  $('liste4').innerHTML = vorbereitet.map((b, i) => `<div class="bew">
      <div style="font-size:15px"><b>${esc(b.anzeige.titel)}</b></div>
      <div class="klein">${esc(b.anzeige.firma || 'ohne Firmenname')} · Anschreiben: ${esc(b.art)}</div>
      <div class="knoepfe">
        <button class="grau" data-kopie="${i}">Anschreiben kopieren</button>
        <a class="grau" href="${esc(b.anzeige.link)}" target="_blank" rel="noopener">Anzeige öffnen</a>
        <button class="grau" data-weg="${i}">Nicht interessant</button>
      </div>
      <textarea id="tx${i}">${esc(b.text)}</textarea>
      <div class="klein fehler" id="kein${i}" ${b.an ? 'hidden' : ''}>${b.lesefehler ? '<b>Anzeigentext konnte nicht geladen werden</b> (' + esc(b.lesefehler) + '), deshalb wurde keine Adresse gesucht. Adresse selbst eintragen.' : '<b>Keine E-Mail-Adresse gefunden.</b> Adresse eintragen oder über „Anzeige öffnen“ dort bewerben.' + (b.unsicher ? ' Im Text steht <b>' + esc(b.unsicher) + '</b> (ungewöhnliche Endung, bitte prüfen und selbst eintragen).' : '')}</div>
      <input type="text" id="an${i}" class="${b.an ? '' : 'leer'}" value="${esc(b.an)}" placeholder="E-Mail-Adresse">
      <input type="text" id="be${i}" value="${esc(b.betreff)}">
      <div class="knoepfe">
        <button class="grau" data-eml="${i}" style="flex:1">E-Mail-Datei laden (.eml)</button>
        <button class="grau" data-mailto="${i}" style="flex:1">Im Mailprogramm öffnen</button>
        <button class="grau" data-versendet="${i}" style="flex:1">E-Mail versendet</button>
      </div>
      <div class="klein" id="st${i}"></div>
      </div>`).join('');
  const mal = (i, t) => { $('st' + i).textContent = t; };
  document.querySelectorAll('#liste4 [data-kopie]').forEach(k => k.onclick = async () => {
    const feld = $('tx' + k.dataset.kopie);
    let ok = false;
    try { await navigator.clipboard.writeText(feld.value); ok = true; }
    catch { feld.select(); ok = document.execCommand('copy'); }  // Ersatzweg, falls der Browser die Zwischenablage sperrt
    k.textContent = ok ? 'Kopiert ✓' : 'Bitte Text markieren und Strg+C';
    setTimeout(() => k.textContent = 'Anschreiben kopieren', 2500);
  });
  document.querySelectorAll('#liste4 [data-weg]').forEach(k => k.onclick = () => {
    const a = vorbereitet[+k.dataset.weg].anzeige;
    aus[a.id] = eintrag(a); speicher.schreiben('sl.aus', aus);
    k.closest('.bew').hidden = true;
    zeigen();  // auch aus der Ergebnisliste nehmen
  });
  document.querySelectorAll('#liste4 [data-versendet]').forEach(k => k.onclick = () => {
    const b = vorbereitet[+k.dataset.versendet];
    beworben[b.id] = { ...eintrag(b.anzeige), datum: new Date().toLocaleDateString('de-DE'), art: 'von Hand versendet' };
    speicher.schreiben('sl.beworben', beworben);
    k.closest('.bew').hidden = true;
    zeigen();
  });
  vorbereitet.forEach((b, i) => {
    $('an' + i).oninput = () => {
      const da = !!$('an' + i).value.trim();
      $('kein' + i).hidden = da;
      $('an' + i).classList.toggle('leer', !da);
    };
  });
  document.querySelectorAll('#liste4 [data-eml]').forEach(k => k.onclick = async () => {
    const i = +k.dataset.eml, an = $('an' + i).value.trim();
    if (an && !adresseOK(an)) return mal(i, 'Ungültige E-Mail-Adresse: ' + an);
    if (!angaben.email) return mal(i, 'Bitte oben unter „Meine Angaben“ deine E-Mail-Adresse eintragen (Absender).');
    if (!cvDatei) return mal(i, 'Bitte oben den Lebenslauf (PDF) auswählen, er wird an die E-Mail-Datei angehängt.');
    try {
      const blob = await emlBauen({ an, betreff: $('be' + i).value, text: $('tx' + i).value, von: angaben.email, name: angaben.name, pdf: cvDatei });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'Bewerbung ' + stelle(vorbereitet[i].anzeige.titel).replace(/[^\p{L}\p{N} -]+/gu, '').slice(0, 50) + '.eml';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      mal(i, 'Datei geladen. Öffne sie per Doppelklick im Mailprogramm (z. B. Outlook, Thunderbird, Apple Mail): Sie erscheint als Entwurf mit Lebenslauf im Anhang.');
    } catch (e) { $('st' + i).innerHTML = fehlerText(e); }
  });
  document.querySelectorAll('#liste4 [data-mailto]').forEach(k => k.onclick = () => {
    const i = +k.dataset.mailto, an = $('an' + i).value.trim();
    if (an && !adresseOK(an)) return mal(i, 'Ungültige E-Mail-Adresse: ' + an);
    location.href = `mailto:${encodeURIComponent(an)}?subject=${encodeURIComponent($('be' + i).value)}&body=${encodeURIComponent($('tx' + i).value)}`;
    mal(i, 'Dein Mailprogramm öffnet sich ohne Anhang: Bitte den Lebenslauf selbst anhängen. (Bei sehr langen Texten kürzt manches Programm den Text.)');
  });
}

// ändert sich die Absenderadresse oder ein Absatz, gilt das für die nächsten Anschreiben; bestehende Texte bleiben, wie sie sind
