"""Vorschläge für die Weiterentwicklung – aus den eigenen Daten abgeleitet und anonymisiert zum Weitergeben.

Wie in der Finanz-App. Quellen:
- Protokoll: Warnungen und Fehler der letzten 30 Tage, gruppiert
- Kontrollen: Kontrollen der letzten 12 Monate, die nicht stimmen
- Import: Dateien, die nicht zugeordnet oder gelesen werden konnten
- Korrekturen: wieder geöffnete Monate, neu erstellte Rechnungen, von Hand geänderte Rechnungsdaten
- Datensammler: Sensoren ohne Werte
- Prognose: systematische Abweichung der Solcast-Prognose
- eigene Ideen

Weitergegeben wird nur, was die Person selbst kopiert, herunterlädt oder als GitHub-Issue öffnet. Namen, Adressen,
Messpunkte, Sensor-Seriennummern, IBAN, E-Mail, Datumsangaben und Beträge werden ersetzt.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import quote

HOCH, MITTEL, TIEF = 3, 2, 1
PRIO_TEXT = {HOCH: "hoch", MITTEL: "mittel", TIEF: "tief"}
ISSUE_MAX = 6000
REPOSITORY = "https://github.com/khu1985/vzev-ha"
BEREICHE = ["Fehler und Warnungen", "Kontrollen", "Import", "Korrekturen", "Datensammler", "Prognose", "Eigene Ideen"]
S = None


@dataclass
class Vorschlag:
    bereich: str
    titel: str
    detail: str = ""
    anzahl: int = 1
    gewicht: int = MITTEL
    schluessel: str = field(default="", init=False)

    def __post_init__(self):
        self.schluessel = hashlib.sha1(f"{self.bereich}|{self.titel}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------- Anonymisieren

MUSTER = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "‹E-Mail›"),
    (re.compile(r"\bCH\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]\b", re.I), "‹IBAN›"),
    (re.compile(r"\bCH[0-9A-Z]{20,40}\b", re.I), "‹Messpunkt›"),
    (re.compile(r"(?:\+41|\b0)\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}\b"), "‹Telefon›"),
    (re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:19|20)\d{2}\b|\b(?:19|20)\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b"), "‹Datum›"),
    (re.compile(r"\b(?:19|20)\d{2}-Q[1-4]\b"), "‹Quartal›"),
    (re.compile(r"\b(?:19|20)\d{2}-\d{2}\b"), "‹Monat›"),
    (re.compile(r"\bhttps?://\S+"), "‹Adresse›"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "‹IP›"),
    (re.compile(r"(?:/[\w.\-]+){2,}"), "‹Pfad›"),
    (re.compile(r"(?:CHF|Fr\.)\s?-?\d[\d'’ .,]*"), "‹Betrag›"),
    (re.compile(r"(?<=_)[0-9a-f]{6,}(?=[_\b.]|$)", re.I), "‹Nr›"),          # Seriennummern in Sensor-IDs
    (re.compile(r"\b\d{1,3}(?:['’]\d{3})+(?:[.,]\d+)?\b|\b\d{4,}(?:[.,]\d+)?\b"), "‹Zahl›"),
]


def _muster(text):
    for m, ersatz in MUSTER:
        text = m.sub(ersatz, text)
    return text


def private_texte(cfg):
    """Persönliche Zeichenketten aus vzev.yaml: Betreiber, Mieter, Adressen, Bank, Messpunkte, Zugangsdaten."""
    gefunden = set()
    b = cfg.get("betreiber") or {}
    for k in ("name", "strasse", "ort", "bank", "iban", "email", "telefon"):
        if b.get(k):
            gefunden.add(str(b[k]))
    for m in cfg.get("mietverhaeltnisse") or []:
        for k in ("name", "strasse", "ort", "email", "telefon"):
            if m.get(k):
                gefunden.add(str(m[k]))
    gefunden.update(str(k) for k in (cfg.get("messpunkte") or {}))
    for k in ("url", "benutzer", "passwort", "token"):
        for abschnitt in ("evcc", "homeassistant"):
            v = (cfg.get(abschnitt) or {}).get(k)
            if v:
                gefunden.add(str(v))
    teile = set()
    for t in gefunden:
        t = t.strip()
        if len(t) >= 3:
            teile.add(t)
            teile.update(w for w in re.split(r"[\s,;/-]+", t) if len(w) >= 3 and not w.isdigit())
    allgemein = {"str", "strasse", "weg", "gasse", "platz", "bank", "raiffeisen", "ubs", "postfinance", "kantonalbank", "the"}
    return sorted((t for t in teile if t.lower() not in allgemein), key=len, reverse=True)


def anonymisieren(text, private):
    for t in private:  # zuerst die konkreten Werte (z. B. Messpunkt), dann die Muster
        text = re.sub(r"(?<!\w)" + re.escape(t) + r"(?!\w)", "‹…›", text, flags=re.I)
    return _muster(text)


# ---------------------------------------------------------------- Quellen

def _zaehlen(erg, schluessel, gewicht=MITTEL, n=1):
    a, g = erg.get(schluessel, (0, gewicht))
    erg[schluessel] = (a + n, max(g, gewicht))


def _normalisieren(meldung):
    erste = meldung.splitlines()[0]
    ausnahme = ""
    if "Traceback" in meldung:
        zeilen = [z.strip() for z in meldung.splitlines() if z.strip()]
        stelle = next((re.sub(r'.*[/\\](\w+\.py)", line \d+, in (\w+).*', r"\1:\2", z)
                       for z in reversed(zeilen) if z.startswith("File ") and "/app/" in z.replace("\\", "/")), "")
        ausnahme = (zeilen[-1].split(":")[0] if zeilen else "") + (f" in {stelle}" if stelle else "")
    erste = re.sub(r"'[^']*'|\"[^\"]*\"|«[^»]*»", "‹…›", _muster(erste))
    erste = re.sub(r"\b\d+(?:[.,]\d+)?\b", "#", erste)
    return (erste[:160] + (f" – {ausnahme}" if ausnahme else "")).strip()


def seit_version(eintraege, version, muster):
    """Zeit des ersten Starts der aktuellen Version (nach dem letzten Start einer anderen Version), sonst None.
    `eintraege`: Dicts mit zeit/text, neueste zuerst; `muster`: Regex mit einer Gruppe für die Version."""
    seit, vorher = None, None
    for e in reversed(eintraege):
        m = re.search(muster, e["text"])
        if not m:
            continue
        if m.group(1) == version and vorher != version:
            seit = e["zeit"]
        vorher = m.group(1)
    return seit if vorher == version else None


def _protokoll(erg, tage=30):
    """Warnungen und Fehler seit dem Start der installierten Version – Behobenes aus älteren Versionen zählt nicht."""
    alle = S.protokoll(20000)
    seit = seit_version(alle, S.VERSION, r"App gestartet \(Version ([^)]+)\)")
    grenze = seit or (datetime.now() - timedelta(days=tage)).strftime("%Y-%m-%d")
    hinweis = f"seit Version {S.VERSION}" if seit else f"im Protokoll der letzten {tage} Tage"
    for e in alle:
        if e["zeit"] < grenze or e["stufe"] not in ("WARNING", "ERROR", "CRITICAL"):
            continue
        if "abgelehnt – nur über Home Assistant" in e["text"]:
            continue  # Zugriffsschutz wirkt wie vorgesehen
        gewicht = HOCH if e["stufe"] in ("ERROR", "CRITICAL") or "Traceback" in e["text"] else MITTEL
        _zaehlen(erg, ("Fehler und Warnungen", f"{e['stufe']}: {_normalisieren(e['text'])}", hinweis), gewicht)


# Kontrollen, die auf eine Grenze der App hinweisen (nicht nur «noch nicht erledigt»)
KONTROLLE_GEWICHT = {
    "Ladestation = Summe der Ladevorgänge": HOCH,
    "Alle Primeo-Zähler liefern Daten": HOCH,
    "Abgleich mit Primeo": HOCH,
    "Wärmepumpen aus dem Allgemeinstrom herausgerechnet": MITTEL,
    "Netzladung passt zum Wechselrichter": MITTEL,
    "Dynamische Preise vollständig": MITTEL,
    "Solarpreis höchstens 80 % des Standardprodukts": TIEF,
    "Wärmepumpen erfasst": TIEF,
}
KONTROLLE_HINWEIS = {
    "Ladestation = Summe der Ladevorgänge": "Verteilung der Ladevorgänge auf Viertelstunden geht nicht auf",
    "Alle Primeo-Zähler liefern Daten": "Lücken im 15-Minuten-Raster – Import oder Primeo-Export prüfen",
    "Abgleich mit Primeo": "Rechnung der App weicht von der Primeo-Rechnung ab",
    "Wärmepumpen aus dem Allgemeinstrom herausgerechnet": "gemessener Verbrauch grösser als Allgemeinzähler (Zeitversatz?)",
    "Netzladung passt zum Wechselrichter": "Standby-Grenze oder Wirkungsgrad passen nicht",
    "Dynamische Preise vollständig": "Viertelstunden ohne Preis",
}


def _kontrollen(erg, monate=12):
    import uebersicht
    d = uebersicht.daten()
    if d["res"] is None:
        return
    mon = uebersicht._memo("monate", lambda: uebersicht.monate(d["res"]))
    for p in list(mon.index)[-monate:]:
        if mon.loc[p, "vorlaeufig"]:
            continue
        try:
            kontr, _, _, _ = uebersicht.kontrollen_fuer(d, mon, p)
        except Exception as e:  # noqa: BLE001
            _zaehlen(erg, ("Fehler und Warnungen", f"Kontrollen nicht berechenbar – {type(e).__name__}", ""), HOCH)
            continue
        for ok, titel, _text in kontr:
            if ok is False and titel in KONTROLLE_GEWICHT:
                _zaehlen(erg, ("Kontrollen", f"«{titel}» stimmt nicht", KONTROLLE_HINWEIS.get(titel, "")), KONTROLLE_GEWICHT[titel])


def _import(erg):
    import core
    b = S.berechnung() if any(S.PRIMEO.glob("*")) else {}
    fehler = b.get("fehler") or ""
    for t in list(core.LETZTE_PROBLEME) + ([fehler] if fehler else []):
        t = re.sub(r"^[^:]+\.(?:xlsx|csv|xls)(?: und [^ ]+)?:?\s*", "", t)   # Dateinamen weg
        art = ("Messpunkt nicht zugeordnet" if "keinem Zähler zugeordnet" in t else
               "Datei nicht lesbar" if "nicht lesbar" in t else
               "Ladevorgänge ohne lesbares Datum" if "ohne lesbares Datum" in t else
               "zwei Dateien für denselben Zähler" if "gehören beide" in t else
               "Lastgang fehlt" if "Lastgang fehlt" in t else _normalisieren(t))
        _zaehlen(erg, ("Import", art, "beim Einlesen der Primeo- bzw. Wallbox-Dateien"), HOCH if "nicht lesbar" in t else MITTEL)


def _korrekturen(erg):
    import seiten
    import zahlungen
    a = seiten.abschluss_laden()
    geoeffnet = [k for k in a.get("korrekturen", []) if "geöffnet" in str(k.get("art", "")).lower()]
    uebernommen = [k for k in a.get("korrekturen", []) if "übernommen" in str(k.get("art", "")).lower()]
    if geoeffnet:
        _zaehlen(erg, ("Korrekturen", "Abgeschlossene Monate wieder geöffnet",
                       "Was führte dazu? Evtl. fehlt eine Kontrolle vor dem Abschluss"), MITTEL, len(geoeffnet))
    if uebernommen:
        _zaehlen(erg, ("Korrekturen", "Neue Werte in abgeschlossene Monate übernommen",
                       "Daten kamen nach dem Abschluss noch einmal anders"), TIEF, len(uebernommen))
    reg = zahlungen.laden()["rechnungen"].values()
    ersetzt = [r for r in reg if r.get("status") == "ersetzt"]
    if ersetzt:
        _zaehlen(erg, ("Korrekturen", "Quartalsrechnungen neu erstellt", "Rechnungen mussten korrigiert werden"), MITTEL, len(ersetzt))
    datum = [r for r in reg if r.get("aenderungen")]
    if datum:
        _zaehlen(erg, ("Korrekturen", "Rechnungsdatum oder Fälligkeit von Hand geändert",
                       "Standard für Rechnungsdatum bzw. Zahlungsfrist passt evtl. nicht"), TIEF, len(datum))
    teil = [r for r in reg if r.get("status") != "ersetzt" and r.get("zahlungen") and len(r["zahlungen"]) > 1]
    if teil:
        _zaehlen(erg, ("Korrekturen", "Rechnungen in mehreren Teilzahlungen beglichen",
                       "Ratenzahlung oder Abweichungen beim Betrag"), TIEF, len(teil))


def _datensammler(erg):
    try:
        zeilen = S.collector.status()["zeilen"]
    except Exception:  # noqa: BLE001
        return
    for z in zeilen:
        if z.get("geprueft") and not z.get("ok"):  # vom Datensammler geprüft und trotzdem ohne Wert
            zweck = re.sub(r"\s*·\s*.*$", "", z.get("zweck") or "Sensor")
            _zaehlen(erg, ("Datensammler", f"Sensor ohne Werte ({zweck})",
                           "nicht verfügbar oder keine Zahl – Entität geändert oder Integration offline"), MITTEL)


def _prognose(erg):
    try:
        import prognose
        tr = prognose.treffer(S.collector._db, S.config(), date.today(), 30)
    except Exception:  # noqa: BLE001
        return
    abw = [r["abw"] for r in tr if r["abw"] is not None]
    if len(abw) >= 10:
        m = sum(abw) / len(abw)
        if abs(m) > 20:
            _zaehlen(erg, ("Prognose", f"Solcast liegt im Mittel {'über' if m > 0 else 'unter'} dem gemessenen Ertrag (mehr als 20 %)",
                           "Korrekturfaktor in der App oder Hinweis auf die Solcast-Einstellungen"), TIEF)
        im_band = sum(r["im_band"] for r in tr) / len(tr)
        if im_band < 0.5:
            _zaehlen(erg, ("Prognose", "Gemessener Ertrag liegt selten im Band 10–90 %", "Bandbreite von Solcast passt nicht"), TIEF)


# ---------------------------------------------------------------- Status und eigene Ideen

def _datei():
    return S.DATA / "vorschlaege.json"


def laden():
    try:
        return json.loads(_datei().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"status": {}, "ideen": []}


def speichern(st):
    tmp = _datei().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_datei())


def ausblenden(schluessel, status="ausgeblendet"):
    st = laden()
    for s in schluessel:
        if status:
            st["status"][s] = {"status": status, "datum": datetime.now().isoformat(timespec="seconds")}
        else:
            st["status"].pop(s, None)
    speichern(st)


def idee_speichern(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Bitte eine Idee eingeben")
    st = laden()
    st["ideen"].append({"id": max([i["id"] for i in st["ideen"]] + [0]) + 1, "text": text[:2000],
                        "datum": datetime.now().isoformat(timespec="seconds")})
    speichern(st)


def idee_loeschen(iid):
    st = laden()
    st["ideen"] = [i for i in st["ideen"] if i["id"] != iid]
    speichern(st)


# ---------------------------------------------------------------- Sammeln und Bericht

def sammeln():
    """Alle Vorschläge, bereits anonymisiert, wichtigste zuerst."""
    erg = {}
    for quelle in (_protokoll, _kontrollen, _import, _korrekturen, _datensammler, _prognose):
        try:
            quelle(erg)
        except Exception as e:  # noqa: BLE001 – eine Quelle darf die anderen nicht verhindern
            _zaehlen(erg, ("Fehler und Warnungen", f"Vorschläge: Quelle «{quelle.__name__.strip('_')}» fehlgeschlagen – {type(e).__name__}", ""), MITTEL)
    private = private_texte(S.config())
    liste = [Vorschlag(bereich, anonymisieren(titel, private), anonymisieren(detail, private), anzahl, gewicht)
             for (bereich, titel, detail), (anzahl, gewicht) in erg.items()]
    eigene = {}
    for i in laden()["ideen"]:
        t = anonymisieren(i["text"].strip(), private)
        eigene[t] = eigene.get(t, 0) + 1
    liste += [Vorschlag("Eigene Ideen", t, "", n, MITTEL) for t, n in eigene.items()]
    liste.sort(key=lambda v: (-v.gewicht, BEREICHE.index(v.bereich) if v.bereich in BEREICHE else 9, -v.anzahl, v.titel))
    return liste


def bericht(vorschlaege, version):
    kopf = [f"Vorschläge aus der vZEV-App {version}", "",
            "_Automatisch abgeleitet und anonymisiert (keine Namen, Adressen, Messpunkte, Beträge oder Daten)._", ""]
    teile = []
    for bereich in dict.fromkeys(v.bereich for v in vorschlaege):
        teile.append(f"### {bereich}")
        for v in (x for x in vorschlaege if x.bereich == bereich):
            n = f" ({v.anzahl}×)" if v.anzahl > 1 else ""
            d = f" – {v.detail}" if v.detail else ""
            teile.append(f"- [{PRIO_TEXT[v.gewicht]}] {v.titel}{n}{d}")
        teile.append("")
    return "\n".join(kopf + (teile or ["Keine Vorschläge."])).strip() + "\n"


def issue_link(text, version):
    body = text if len(text) <= ISSUE_MAX else text[:ISSUE_MAX] + "\n\n… (gekürzt – vollständig als Datei herunterladen)"
    return f"{REPOSITORY}/issues/new?title=" + quote(f"Vorschläge aus der App ({version})") + "&body=" + quote(body)


# ---------------------------------------------------------------- Seite

SEITE = """
<style>.vs{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--line2)}.vs:last-child{border-bottom:0}
.vs input{margin-top:3px}.vs .p{display:inline-block;min-width:52px;text-align:center;font-size:11px;font-weight:700;border-radius:99px;padding:1px 8px;margin-right:6px}
.p3{background:var(--warnbg);color:var(--warn)}.p2{background:var(--soft);color:var(--ink)}.p1{background:var(--line2);color:var(--muted)}
.vs small{display:block;color:var(--muted);margin-top:2px}textarea.bericht{width:100%;min-height:220px;font:12px/1.5 ui-monospace,Menlo,monospace}</style>
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div class="t">Vorschläge offen</div><div class="v">{{ sichtbar|length }}</div></div>
 <div class="kpi"><div class="t">davon wichtig</div><div class="v">{{ hoch }}</div></div>
 <div class="kpi"><div class="t">gemeldet</div><div class="v">{{ gemeldet }}</div></div>
 <div class="kpi"><div class="t">ausgeblendet</div><div class="v">{{ ausgeblendet }}</div></div>
</div>
<div class="card"><p>Die App leitet aus deinen Daten ab, wo sie besser werden kann: Fehler im Protokoll, Kontrollen, die nicht stimmen,
Dateien, die sie nicht einlesen konnte, Korrekturen nach dem Abschluss, Sensoren ohne Werte und die Treffsicherheit der Prognose.
Alles ist <b>anonymisiert</b> – Namen, Adressen, Messpunkte, Seriennummern, Beträge und Daten sind ersetzt.
<b>Nichts wird automatisch gesendet:</b> Unten steht genau der Text, den du kopieren, herunterladen oder als GitHub-Issue öffnen kannst.</p></div>
<div class="card"><h2>Vorschläge aus deinen Daten</h2>
{% if sichtbar %}<form method="post" action="vorschlaege">
{% for v in sichtbar %}<label class="vs"><input type="checkbox" name="sel_{{ v.schluessel }}" value="1"><span>
<span class="p p{{ v.gewicht }}">{{ prio[v.gewicht] }}</span>{{ v.titel }}{% if v.anzahl > 1 %} ({{ v.anzahl }}×){% endif %}
<small>{{ v.bereich }}{% if v.detail %} · {{ v.detail }}{% endif %}</small></span></label>{% endfor %}
<p style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px"><button name="aktion" value="ausblenden">Ausgewählte ausblenden</button>
<button name="aktion" value="gemeldet">Ausgewählte als gemeldet markieren</button></p></form>
{% else %}<p class="muted">Keine offenen Vorschläge – die App findet in deinen Daten nichts zu verbessern.</p>{% endif %}
<p class="muted">Ausgeblendete und gemeldete Vorschläge kommen nicht in den Text zum Weitergeben. Rot = wichtig, gelb = mittel, grau = tief.</p></div>
{% if weg %}<details class="card"><summary><b>Ausgeblendet und gemeldet ({{ weg|length }})</b></summary><form method="post" action="vorschlaege">
{% for v, s in weg %}<label class="vs"><input type="checkbox" name="sel_{{ v.schluessel }}" value="1"><span><span class="p p{{ v.gewicht }}">{{ prio[v.gewicht] }}</span>{{ v.titel }}
<small>{{ v.bereich }} · {{ s }}</small></span></label>{% endfor %}
<p style="display:flex;gap:8px;flex-wrap:wrap"><button name="aktion" value="einblenden">Ausgewählte wieder einblenden</button>
<button name="aktion" value="alle_einblenden">Alle wieder einblenden</button></p></form></details>{% endif %}
<div class="card"><h2>Eigene Idee</h2><form method="post" action="vorschlaege">
{% if ideen %}<ul>{% for i in ideen %}<li>{{ i.text }} <button name="aktion" value="idee_loeschen_{{ i.id }}" style="min-height:28px;padding:0 8px">Löschen</button></li>{% endfor %}</ul>{% endif %}
<textarea name="idee" rows="3" style="width:100%" placeholder="Was fehlt dir, was stört dich?"></textarea>
<p><button class="primary" name="aktion" value="idee">Hinzufügen</button></p></form>
<p class="muted">Namen, Beträge und Daten werden beim Weitergeben ersetzt – schreib trotzdem nichts Persönliches hinein.</p></div>
<div class="card"><h2>Weitergeben</h2><textarea id="vs-text" class="bericht" readonly>{{ text }}</textarea>
<p style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" onclick="navigator.clipboard.writeText(document.getElementById('vs-text').value);this.textContent='Kopiert'">Kopieren</button>
<a class="btn" href="vorschlaege.md">Herunterladen (.md)</a>
<a class="btn primary" href="{{ link }}" target="_blank" rel="noopener">Als GitHub-Issue öffnen</a></p>
<p class="muted">Das Issue öffnet sich auf GitHub als Entwurf; abgeschickt wird erst, wenn du dort auf «Create» klickst.</p></div>
"""


def seite():
    from flask import render_template_string
    alle = sammeln()
    st = laden()["status"]
    sichtbar = [v for v in alle if v.schluessel not in st]
    weg = [(v, st[v.schluessel]["status"]) for v in alle if v.schluessel in st]
    text = bericht(sichtbar, S.VERSION)
    return S.page("Vorschläge", render_template_string(
        SEITE, sichtbar=sichtbar, weg=weg, hoch=sum(1 for v in sichtbar if v.gewicht == HOCH),
        gemeldet=sum(1 for _, s in weg if s == "gemeldet"), ausgeblendet=sum(1 for _, s in weg if s == "ausgeblendet"),
        ideen=laden()["ideen"], text=text, link=issue_link(text, S.VERSION), prio=PRIO_TEXT))


def aktion():
    from flask import redirect, request
    a = request.form.get("aktion") or ""
    try:
        if a == "idee":
            idee_speichern(request.form.get("idee"))
            return redirect("vorschlaege?msg=Idee gespeichert")
        if a.startswith("idee_loeschen_"):
            idee_loeschen(int(a.rsplit("_", 1)[1]))
            return redirect("vorschlaege?msg=Idee gelöscht")
        auswahl = [k[4:] for k in request.form if k.startswith("sel_")]
        if a == "alle_einblenden":
            auswahl = list(laden()["status"])
        if not auswahl:
            raise ValueError("Nichts ausgewählt")
        if a in ("einblenden", "alle_einblenden"):
            ausblenden(auswahl, "")
            return redirect(f"vorschlaege?msg={len(auswahl)} Vorschlag/Vorschläge wieder eingeblendet")
        ausblenden(auswahl, "gemeldet" if a == "gemeldet" else "ausgeblendet")
        return redirect(f"vorschlaege?msg={len(auswahl)} Vorschlag/Vorschläge "
                        + ("als gemeldet markiert" if a == "gemeldet" else "ausgeblendet"))
    except ValueError as e:
        return redirect(f"vorschlaege?c=warn&msg={e}")


def herunterladen():
    from flask import Response
    st = laden()["status"]
    text = bericht([v for v in sammeln() if v.schluessel not in st], S.VERSION)
    return Response(text.encode("utf-8"), mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="vzev-vorschlaege.md"'})


def register(app, server):
    global S
    S = server
    app.add_url_rule("/vorschlaege", "vorschlaege", seite)
    app.add_url_rule("/vorschlaege", "vorschlaege_aktion", aktion, methods=["POST"])
    app.add_url_rule("/vorschlaege.md", "vorschlaege_md", herunterladen)
