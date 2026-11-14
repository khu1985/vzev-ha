"""Nebenkostenabrechnung (Neben- und Betriebskosten nach Mietvertrag, Art. 257a/b OR, Art. 4–8 VMWG).

Abrechnungsperiode 1.7.–30.6. Kosten werden pro Periode erfasst (mit Beleg) oder kommen aus der App
(Strom der Wärmepumpen, Allgemeinstrom) und nach dem Schlüssel ihrer Kategorie verteilt:

  Heizung       Grundanteil nach m², Rest nach Wärmezähler (Wohnungen ohne eigenen Zähler teilen den Rest des
                Gesamtzählers nach m²)
  Warmwasser    nach Personen (× Tage)
  Wasser        nach Personen (× Tage)
  Fläche        übrige Neben- und Betriebskosten nach m²
  Direkt        ganz einer Wohnung (z. B. Einstellplatz-Anteil aus der Abrechnung der Nachbarliegenschaft)

Innerhalb einer Wohnung zählt jedes Mietverhältnis nach Tagen; Tage ohne Mieter (Leerstand, selbst bewohnt) trägt
der Vermieter. Dazu kommt das Honorar für die Abrechnung (Prozent oder fester Betrag). Abgezogen werden die
Akontozahlungen; eine Nachzahlung kommt mit Einzahlungsschein ins Zahlungsregister.

Alles Persönliche (Flächen, Personen, Akonto, Beträge, Belege) liegt in nebenkosten.json und im Datenordner.
"""
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

S = None
_SPERRE = threading.Lock()

KATEGORIEN = {
    "heizung": ("Heizung", "Grundanteil nach m², Rest nach Wärmezähler"),
    "warmwasser": ("Warmwasser", "nach Personen"),
    "wasser": ("Wasser/Abwasser", "nach Personen"),
    "flaeche": ("Übrige Neben- und Betriebskosten", "nach m²"),
    "direkt": ("Direkt einer Wohnung", "ganz der Wohnung"),
}
VORSCHLAEGE = ["Wartung und Service Heizung", "Wasser und Abwasser", "Kehricht und Grünabfuhr", "Hauswartung und Garten",
               "Treppenhausreinigung", "Gemeinschaftsantenne", "Entstopfen und Schwemmen Abwasserleitungen",
               "Einstellplatz Nachbarliegenschaft (Abrechnung Verwaltung)"]
# Üblich sind 3–5 % der Nebenkosten (oder ein Ansatz nach Aufwand); einstellbar.
STANDARD = {"heizung_grundanteil": 30.0, "honorar_art": "prozent", "honorar_wert": 3.0,
            "einheiten": {}, "waerme": {}, "mieter": {}}


# ---------------------------------------------------------------- Speicher

def _datei():
    return S.DATA / "nebenkosten.json"


def laden():
    try:
        d = json.loads(_datei().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("einstellungen", {})
    for k, v in STANDARD.items():
        d["einstellungen"].setdefault(k, json.loads(json.dumps(v)))
    d.setdefault("perioden", {})
    return d


def speichern(d):
    with _SPERRE:
        tmp = _datei().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(_datei())


def periode_daten(d, p):
    return d["perioden"].setdefault(p, {"positionen": [], "auto_aus": [], "waerme": {}})


# ---------------------------------------------------------------- Perioden

def periode_grenzen(p):
    """«2026-27» → (1.7.2026, 30.6.2027)."""
    j = int(p[:4])
    return date(j, 7, 1), date(j + 1, 6, 30)


def periode_name(von):
    return f"{von.year}-{(von.year + 1) % 100:02d}"


def periode_text(p):
    von, bis = periode_grenzen(p)
    return f"{von:%d.%m.%Y}–{bis:%d.%m.%Y}"


def perioden(cfg, heute=None):
    heute = heute or date.today()
    start = _datum(cfg.get("vzev_start")) or heute
    j = start.year if start.month >= 7 else start.year - 1
    j_ende = heute.year if heute.month >= 7 else heute.year - 1
    return [f"{x}-{(x + 1) % 100:02d}" for x in range(j_ende, j - 1, -1)]


def _datum(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def mieter_key(m):
    return f"{m['einheit']}|{_datum(m['von'])}"


def _monate(von, bis):
    """Akonto ist monatlich im Voraus fällig: Anzahl Monatsersten in [von, bis] (Einzug am 1. zählt)."""
    n, d = 0, date(von.year, von.month, 1)
    if d < von:
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    while d <= bis:
        n += 1
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return n


# ---------------------------------------------------------------- Berechnung

@dataclass
class Abschnitt:
    """Ein Zeitraum einer Wohnung: Mietverhältnis oder Vermieter (Leerstand/selbst bewohnt)."""
    einheit: str
    von: date
    bis: date
    personen: float
    mieter: dict = None       # Mietverhältnis aus vzev.yaml, None = Vermieter
    akonto: float = 0.0       # pro Monat
    zeilen: list = field(default_factory=list)

    @property
    def tage(self):
        return (self.bis - self.von).days + 1

    @property
    def name(self):
        return self.mieter["name"] if self.mieter else "Vermieter"


def belegung(cfg, ein, von, bis, wohnungen):
    out = []
    for u in wohnungen:
        mv = sorted((m for m in cfg.get("mietverhaeltnisse") or [] if m.get("einheit") == u
                     and _datum(m["von"]) <= bis and (not m.get("bis") or _datum(m["bis"]) >= von)), key=lambda m: _datum(m["von"]))
        frei = float((ein["einheiten"].get(u) or {}).get("personen_ohne_mieter") or 0)
        t = von
        for m in mv:
            a, b = max(_datum(m["von"]), von), min(_datum(m["bis"]) if m.get("bis") else bis, bis)
            if a > t:
                out.append(Abschnitt(u, t, a - timedelta(days=1), frei))
            md = ein["mieter"].get(mieter_key(m)) or {}
            out.append(Abschnitt(u, a, b, float(md.get("personen") or 0), m, float(md.get("akonto") or 0)))
            t = b + timedelta(days=1)
        if t <= bis:
            out.append(Abschnitt(u, t, bis, frei))
    return out


def auto_positionen(cfg, res, von, bis):
    """Kosten aus der App: Strom der Wärmepumpen (Heizung/Warmwasser) und Allgemeinstrom, wie in den Gesamtrechnungen."""
    import core
    import invoices
    if res is None or not len(res):
        return [], None
    ende = min(bis, res.index.max().date())
    if ende < von:
        return [], ende
    out = []
    for key, name in core.wp_namen(cfg):
        if f"S_{key}" not in res:
            continue
        betrag = round(sum(r["total"] for r in invoices.lines_for(res, cfg, key, von, ende, grundpreis_ja=False)), 2)
        kat = "warmwasser" if "warm" in name.lower() or "boiler" in name.lower() else "heizung"
        out.append(dict(titel=f"Strom Wärmepumpe {name}", kategorie=kat, betrag=betrag, auto=f"wp:{name}"))
    betrag = round(sum(r["total"] for r in invoices.lines_for(res, cfg, "AllgC", von, ende)), 2)
    out.append(dict(titel="Allgemeinstrom (inkl. Grundpreis)", kategorie="flaeche", betrag=betrag, auto="allgemein"))
    return out, ende


def waerme_anteile(ein, per, wohnungen):
    """{Wohnung: Anteil am Wärmeverbrauch} aus den Zählerständen der Periode – None, wenn sie fehlen."""
    w = per.get("waerme") or {}

    def delta(k):
        x = w.get(k) or {}
        try:
            return float(x["ende"]) - float(x["start"])
        except (KeyError, TypeError, ValueError):
            return None
    gesamt = delta("gesamt")
    if not gesamt or gesamt <= 0:
        return None, "Stand Beginn und Ende des Gesamtzählers fehlen"
    eigen = {u: delta(u) for u in wohnungen if u in (ein.get("waerme") or {}) or (w.get(u) or {})}
    eigen = {u: v for u, v in eigen.items() if v is not None}
    if any(v < 0 for v in eigen.values()) or sum(eigen.values()) > gesamt * 1.001:
        return None, "Wohnungszähler zusammen grösser als der Gesamtzähler oder rückwärts – Stände prüfen"
    rest = gesamt - sum(eigen.values())
    ohne = [u for u in wohnungen if u not in eigen]
    flaeche = {u: float((ein["einheiten"].get(u) or {}).get("flaeche") or 0) for u in ohne}
    fsum = sum(flaeche.values())
    anteile = {u: v / gesamt for u, v in eigen.items()}
    for u in ohne:
        anteile[u] = (rest * (flaeche[u] / fsum if fsum else 1 / len(ohne))) / gesamt
    return anteile, None


def abrechnen(cfg, res, p, d=None, heute=None):
    """Verteilung einer Periode. Gibt dict mit Abschnitten, Positionen, Summen und Hinweisen zurück."""
    import seiten
    d = d or laden()
    ein, per = d["einstellungen"], periode_daten(d, p)
    von, bis = periode_grenzen(p)
    D = (bis - von).days + 1
    wohnungen = [u for u in seiten._einheiten(cfg)]
    flaeche = {u: float((ein["einheiten"].get(u) or {}).get("flaeche") or 0) for u in wohnungen}
    F = sum(flaeche.values())
    hinweise = []
    if not F or any(v <= 0 for v in flaeche.values()):
        hinweise.append("Fläche (m²) aller Wohnungen unter «Grundlagen» eintragen – ohne sie kann nicht verteilt werden")
    ab = belegung(cfg, ein, von, bis, wohnungen)
    for a in ab:
        if a.mieter and a.personen <= 0:
            hinweise.append(f"Personen für das Mietverhältnis {a.mieter['name']} fehlen (Warmwasser und Wasser nach Personen)")
        if a.mieter and a.akonto <= 0:
            hinweise.append(f"Akonto für {a.mieter['name']} fehlt (Betrag pro Monat aus dem Mietvertrag)")
    auto, daten_bis = auto_positionen(cfg, res, von, bis)
    aus = set(per.get("auto_aus") or [])
    positionen = [x for x in auto if x["auto"] not in aus] + [dict(x, auto=None) for x in per.get("positionen") or []]
    anteile_w, w_fehler = waerme_anteile(ein, per, wohnungen)
    g = float(ein.get("heizung_grundanteil") or 0) / 100
    if any(x["kategorie"] == "heizung" for x in positionen) and anteile_w is None:
        hinweise.append(f"Heizung vorläufig ganz nach m² verteilt: {w_fehler}")
    pers = {id(a): a.personen * a.tage for a in ab}
    P = sum(pers.values())

    def anteil(a, x):
        fl = (flaeche[a.einheit] / F if F else 0) * a.tage / D
        k = x["kategorie"]
        if k == "flaeche":
            return fl, f"{flaeche[a.einheit]:g}/{F:g} m²"
        if k in ("warmwasser", "wasser"):
            if not P:
                return fl, "nach m² (keine Personen erfasst)"
            return pers[id(a)] / P, f"{a.personen:g} Pers. · {pers[id(a)]:g}/{P:g} Pers.-Tage"
        if k == "heizung":
            if anteile_w is None:
                return fl, f"{flaeche[a.einheit]:g}/{F:g} m² (vorläufig)"
            w = anteile_w.get(a.einheit, 0) * a.tage / D
            return g * fl + (1 - g) * w, f"{g * 100:g} % m² + {(1 - g) * 100:g} % Wärme {anteile_w.get(a.einheit, 0) * 100:.1f} %"
        if k == "direkt":
            return (a.tage / D if x.get("einheit") == a.einheit else 0.0), "direkt"
        return 0.0, "?"
    for a in ab:
        a.zeilen = []
        for x in positionen:
            q, text = anteil(a, x)
            tage = f" · {a.tage}/{D} T." if a.tage < D and x["kategorie"] not in ("warmwasser", "wasser") else ""
            a.zeilen.append(dict(titel=x["titel"], kategorie=x["kategorie"], total=x["betrag"], anteil=q,
                                 schluessel=text + tage, betrag=round(x["betrag"] * q, 2), auto=x.get("auto")))
    kosten = round(sum(x["betrag"] for x in positionen), 2)
    # Honorar
    art, wert = ein.get("honorar_art") or "prozent", float(ein.get("honorar_wert") or 0)
    for a in ab:
        summe = round(sum(z["betrag"] for z in a.zeilen), 2)
        if art == "prozent":
            hon = round(summe * wert / 100, 2)
            hon_text = f"{wert:g} % der Nebenkosten"
        else:
            q = (flaeche[a.einheit] / F if F else 0) * a.tage / D
            hon = round(wert * q, 2)
            hon_text = f"CHF {wert:.2f} nach m2"
        a.summe, a.honorar, a.honorar_text = summe, hon, hon_text
        a.monate = _monate(a.von, a.bis) if a.mieter else 0
        a.akonto_total = round(a.monate * a.akonto, 2)
        a.saldo = round(summe + hon - a.akonto_total, 2)
    verteilt = round(sum(a.summe for a in ab), 2)
    if positionen and abs(verteilt - kosten) > 0.05 * max(1, len(ab)):
        hinweise.append(f"Verteilt CHF {verteilt:.2f}, Kosten CHF {kosten:.2f} – Schlüssel prüfen")
    heute = heute or date.today()
    return dict(periode=p, von=von, bis=bis, tage=D, abschnitte=ab, positionen=positionen, auto=auto, auto_aus=aus,
                kosten=kosten, verteilt=verteilt, hinweise=hinweise, daten_bis=daten_bis, flaeche=flaeche,
                waerme=anteile_w, abgelaufen=heute > bis, vollstaendig=bool(daten_bis and daten_bis >= bis))


# ---------------------------------------------------------------- PDF

def render(path, cfg, a, erg, nummer, datum):
    import invoices
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    INK, MUTED, LINE, AMBER = invoices.INK, invoices.MUTED, invoices.LINE, invoices.AMBER
    chf, de = invoices.chf, invoices.de
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"Nebenkostenabrechnung {nummer}")
    b = cfg["betreiber"]
    L, R = 20 * mm, W - 20 * mm
    y = H - 20 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(L, y, b["name"])
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(L, y - 5 * mm, f"{b['strasse']} {b['hausnr']} · {b['plz']} {b['ort']}")
    c.drawString(L, y - 9 * mm, f"{b.get('bank', '')} · IBAN {invoices.iban_fmt(b['iban'])}")
    c.setStrokeColor(AMBER)
    c.setLineWidth(1.5)
    c.line(L, y - 13 * mm, R, y - 13 * mm)
    m = a.mieter
    ry = H - 45 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 10)
    for i, ln in enumerate([m["name"], f"{m.get('strasse', '')} {m.get('hausnr', '')}", f"{m.get('plz', '')} {m.get('ort', '')}"]):
        c.drawString(118 * mm, ry - i * 4.6 * mm, ln)
    c.setFont("Helvetica", 8.5)
    import seiten
    for i, (k, v) in enumerate([("Datum", de(datum)), ("Nummer", nummer), ("Wohnung", seiten._einheiten(cfg).get(a.einheit, a.einheit)),
                                ("Zeitraum", f"{de(a.von)} – {de(a.bis)}")]):
        c.setFillColor(MUTED)
        c.drawString(L, ry - i * 4.6 * mm, k)
        c.setFillColor(INK)
        c.drawString(L + 20 * mm, ry - i * 4.6 * mm, v)
    ty = H - 72 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(L, ty, f"Nebenkostenabrechnung {de(erg['von'])} – {de(erg['bis'])}")
    # Tabelle
    yy = ty - 10 * mm
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(MUTED)
    c.drawString(L, yy, "Position")
    c.drawRightString(L + 100 * mm, yy, "Kosten Haus")
    c.drawString(L + 104 * mm, yy, "Verteilung")
    c.drawRightString(R, yy, "Ihr Anteil")
    yy -= 2 * mm
    c.setStrokeColor(LINE)
    c.line(L, yy, R, yy)
    yy -= 4.5 * mm
    for z in a.zeilen:
        c.setFillColor(INK)
        c.setFont("Helvetica", 8.5)
        c.drawString(L, yy, z["titel"][:52])
        c.drawRightString(L + 100 * mm, yy, chf(z["total"]))
        c.setFont("Helvetica", 7)
        c.setFillColor(MUTED)
        c.drawString(L + 104 * mm, yy, z["schluessel"].replace("²", "2")[:46])
        c.setFont("Helvetica", 8.5)
        c.setFillColor(INK)
        c.drawRightString(R, yy, chf(z["betrag"]))
        yy -= 5 * mm
    c.line(L, yy + 2.5 * mm, R, yy + 2.5 * mm)
    zeilen = [("Nebenkosten", a.summe, False), (f"Honorar Abrechnung ({a.honorar_text})", a.honorar, False),
              (f"Akontozahlungen ({a.monate} × CHF {chf(a.akonto)})", -a.akonto_total, False)]
    for k, v, _ in zeilen:
        c.setFont("Helvetica", 9)
        c.drawString(L, yy - 1 * mm, k)
        c.drawRightString(R, yy - 1 * mm, chf(v))
        yy -= 5 * mm
    c.setStrokeColor(INK)
    c.line(L + 100 * mm, yy + 2.5 * mm, R, yy + 2.5 * mm)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(L, yy - 2 * mm, "Nachzahlung" if a.saldo > 0 else "Guthaben" if a.saldo < 0 else "Saldo")
    c.drawRightString(R, yy - 2 * mm, f"CHF {chf(abs(a.saldo))}")
    yy -= 11 * mm
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    frist = int((cfg.get("rechnungen") or {}).get("zahlungsfrist_tage", 30))
    text = ([f"Bitte überweisen Sie die Nachzahlung bis {de(datum + timedelta(days=frist))} mit dem Einzahlungsschein unten."]
            if a.saldo > 0 else ["Das Guthaben überweisen wir Ihnen in den nächsten Tagen."] if a.saldo < 0 else [])
    text += ["Verteilung gemäss Mietvertrag: Heizung verbrauchsabhängig, Warmwasser und Wasser/Abwasser nach Personen,",
             "übrige Neben- und Betriebskosten nach m2. Der Strom in der Wohnung wird separat abgerechnet (vZEV).",
             "Die Belege können Sie nach Absprache einsehen (Art. 257b Abs. 2 OR)."]
    if erg.get("waerme"):
        text.append("Wärmeanteile: " + ", ".join(f"{seiten._einheiten(cfg).get(u, u)} {v * 100:.1f} %" for u, v in erg["waerme"].items()))
    for ln in text:
        c.drawString(L, yy, ln)
        yy -= 4.2 * mm
    if a.saldo > 0:
        invoices.draw_qr_bill(c, cfg, {"partei": m}, a.saldo, nummer, zweck="Nebenkostenabrechnung")
    c.showPage()
    c.save()


def erstellen(cfg, res, p, datum=None):
    """PDF je Mietverhältnis der Periode; Nachzahlungen ins Zahlungsregister."""
    erg = abrechnen(cfg, res, p)
    datum = datum or date.today()
    ordner = S.RECHNUNGEN / f"NK-{p}"
    ordner.mkdir(parents=True, exist_ok=True)
    made = []
    for a in erg["abschnitte"]:
        if not a.mieter:
            continue
        nachname = a.mieter["name"].split()[-1]
        mehrere = sum(1 for x in erg["abschnitte"] if x.mieter and x.einheit == a.einheit) > 1  # Mieterwechsel
        nummer = f"NK-{p}-{a.einheit}" + (f"-{a.von:%m%d}" if mehrere else "")
        name = f"Rechnung_{nummer}_{nachname}.pdf"
        render(ordner / name, cfg, a, erg, nummer, datum)
        made.append((name, a.saldo, a))
    import zahlungen
    zahlungen.registrieren(f"NK-{p}", [(n, s, None) for n, s, _ in made if s > 0], datum, cfg, art="nebenkosten")
    return made


# ---------------------------------------------------------------- Seite

SEITE = """
<p class="muted">Neben- und Betriebskosten nach Mietvertrag, Abrechnungsperiode 1.7.–30.6. Strom aus der App
(Wärmepumpen, Allgemeinstrom) kommt automatisch dazu; die übrigen Kosten mit Beleg erfassen. Rechtliches (Art. 257a/b OR,
VMWG): nur im Mietvertrag aufgeführte Kosten, zu den tatsächlichen Kosten.</p>
<form method="get" style="margin:8px 0 16px"><select name="p" onchange="this.form.submit()">{% for x in liste %}
<option value="{{ x }}" {{ 'selected' if x == p }}>{{ text(x) }}</option>{% endfor %}</select></form>
{% for h in e.hinweise %}<div class="msg warn">{{ h }}</div>{% endfor %}
{% if not e.vollstaendig %}<div class="msg">Vorschau: Stromkosten bis {{ e.daten_bis|dmy if e.daten_bis else '–' }} – die Abrechnung lässt sich nach dem {{ e.bis|dmy }} erstellen, wenn die Lastgänge bis Ende Juni da sind.</div>{% endif %}

<div class="card"><h2>Verteilung</h2>
<div style="overflow-x:auto"><table><tr><th class="l">Position</th><th class="l">Schlüssel</th><th>Kosten</th>
{% for a in e.abschnitte %}<th>{{ a.name|vorname if a.mieter else 'Vermieter' }}<div class="muted" style="font-weight:normal">{{ einheiten.get(a.einheit, a.einheit) }} · {{ a.tage }} T.</div></th>{% endfor %}</tr>
{% for x in e.positionen %}{% set i = loop.index0 %}<tr><td class="l">{{ x.titel }}{% if x.auto %} <span class="muted">(App)</span>{% endif %}</td><td class="l muted">{{ kat[x.kategorie][1] }}{% if x.kategorie == 'direkt' %}: {{ einheiten.get(x.get('einheit'), x.get('einheit')) }}{% endif %}</td><td>{{ x.betrag|f2 }}</td>
{% for a in e.abschnitte %}<td>{{ a.zeilen[i].betrag|f2 }}</td>{% endfor %}</tr>{% endfor %}
<tr><td class="l"><b>Nebenkosten</b></td><td></td><td><b>{{ e.kosten|f2 }}</b></td>{% for a in e.abschnitte %}<td><b>{{ a.summe|f2 }}</b></td>{% endfor %}</tr>
<tr><td class="l">Honorar Abrechnung</td><td class="l muted">{{ honorar }}</td><td></td>{% for a in e.abschnitte %}<td>{{ a.honorar|f2 if a.mieter else '' }}</td>{% endfor %}</tr>
<tr><td class="l">Akonto</td><td></td><td></td>{% for a in e.abschnitte %}<td>{{ ('−' ~ (a.akonto_total|f2)) if a.mieter else '' }}</td>{% endfor %}</tr>
<tr><td class="l"><b>Saldo</b></td><td class="l muted">+ Nachzahlung / − Guthaben</td><td></td>{% for a in e.abschnitte %}<td><b>{{ a.saldo|f2 if a.mieter else '' }}</b></td>{% endfor %}</tr>
</table></div>
<p class="muted">Vermieter = Tage ohne Mieter (Leerstand, selbst bewohnt): dieser Anteil wird nicht verrechnet.</p></div>

<div class="card"><h2>Kosten {{ text(p) }}</h2>
{% if e.auto %}<form method="post"><input type="hidden" name="aktion" value="auto"><input type="hidden" name="p" value="{{ p }}">
<table><tr><th class="l">Aus der App</th><th class="l">Kategorie</th><th>CHF</th><th>verrechnen</th></tr>
{% for x in e.auto %}<tr><td class="l">{{ x.titel }}</td><td class="l">{{ kat[x.kategorie][0] }}</td><td>{{ x.betrag|f2 }}</td>
<td><input type="checkbox" name="an" value="{{ x.auto }}" {{ '' if x.auto in e.auto_aus else 'checked' }}></td></tr>{% endfor %}</table>
<button>Übernehmen</button></form>{% endif %}
<table style="margin-top:12px"><tr><th class="l">Erfasst</th><th class="l">Kategorie</th><th>CHF</th><th class="l">Beleg</th><th></th></tr>
{% for x in per.positionen %}<tr><td class="l">{{ x.titel }}</td><td class="l">{{ kat[x.kategorie][0] }}{% if x.kategorie == 'direkt' %}: {{ einheiten.get(x.get('einheit'), x.get('einheit')) }}{% endif %}</td><td>{{ x.betrag|f2 }}</td>
<td class="l">{% if x.get('beleg') %}<a href="nebenkosten_beleg?p={{ p }}&d={{ x.beleg|urlencode }}" target="_blank">{{ x.beleg }}</a>{% else %}<span class="muted">–</span>{% endif %}</td>
<td><form method="post" style="margin:0"><input type="hidden" name="aktion" value="loeschen"><input type="hidden" name="p" value="{{ p }}"><input type="hidden" name="i" value="{{ loop.index0 }}"><button>Entfernen</button></form></td></tr>
{% else %}<tr><td class="l muted" colspan="5">Noch nichts erfasst.</td></tr>{% endfor %}</table>
<form method="post" enctype="multipart/form-data" style="margin-top:12px"><input type="hidden" name="aktion" value="position"><input type="hidden" name="p" value="{{ p }}">
<input name="titel" list="nk-titel" placeholder="z. B. Wasser und Abwasser" required style="min-width:240px">
<datalist id="nk-titel">{% for v in vorschlaege %}<option value="{{ v }}">{% endfor %}</datalist>
<select name="kategorie">{% for k, v in kat.items() %}<option value="{{ k }}">{{ v[0] }} ({{ v[1] }})</option>{% endfor %}</select>
<select name="einheit" title="nur für «Direkt»">{% for k, v in einheiten.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
<input name="betrag" placeholder="CHF" required style="width:100px"> <input type="file" name="beleg" accept=".pdf,.jpg,.jpeg,.png">
<button>Erfassen</button></form></div>

<div class="card"><h2>Wärmezähler {{ text(p) }}</h2>
<form method="post"><input type="hidden" name="aktion" value="waerme"><input type="hidden" name="p" value="{{ p }}">
<table><tr><th class="l">Zähler</th><th>Stand 1.7. (kWh)</th><th>Stand 30.6. (kWh)</th><th>Verbrauch</th></tr>
{% for k, label in zaehler %}{% set w = per.waerme.get(k) or {} %}<tr><td class="l">{{ label }}</td>
{% set s0, s1 = w.get('start'), w.get('ende') %}
<td><input name="{{ k }}_start" value="{{ s0 if s0 is not none else '' }}" style="width:110px"></td>
<td><input name="{{ k }}_ende" value="{{ s1 if s1 is not none else '' }}" style="width:110px"></td>
<td>{{ ((s1|float - s0|float)|round(1)) if s0 is not none and s1 is not none else '' }}</td></tr>{% endfor %}</table>
<button>Speichern</button>{% if ha_waerme %} <button name="ha" value="1">Stände aus Home Assistant holen</button>{% endif %}</form>
<p class="muted">Wohnungen ohne eigenen Wärmezähler teilen sich den Rest des Gesamtzählers nach m².</p></div>

<div class="card"><h2>Grundlagen</h2>
<form method="post"><input type="hidden" name="aktion" value="grundlagen"><input type="hidden" name="p" value="{{ p }}">
<table><tr><th class="l">Wohnung</th><th>Fläche m²</th><th>Personen ohne Mieter</th><th class="l">Wärmezähler (Sensor, optional)</th></tr>
{% for k, v in einheiten.items() %}{% set u = ein.einheiten.get(k) or {} %}<tr><td class="l">{{ v }}</td>
<td><input name="flaeche_{{ k }}" value="{{ u.get('flaeche') or '' }}" style="width:80px"></td>
<td><input name="personen_{{ k }}" value="{{ u.get('personen_ohne_mieter') or '' }}" style="width:60px" title="z. B. selbst bewohnt"></td>
<td class="l"><input name="sensor_{{ k }}" value="{{ ein.waerme.get(k) or '' }}" placeholder="sensor.…" list="energie" style="min-width:260px"></td></tr>{% endfor %}
<tr><td class="l">Gesamtzähler</td><td></td><td></td><td class="l"><input name="sensor_gesamt" value="{{ ein.waerme.get('gesamt') or '' }}" placeholder="sensor.…" list="energie" style="min-width:260px"></td></tr></table>
<table style="margin-top:12px"><tr><th class="l">Mietverhältnis</th><th>Personen</th><th>Akonto / Monat</th></tr>
{% for a in e.abschnitte if a.mieter %}{% set md = ein.mieter.get(key(a.mieter)) or {} %}<tr><td class="l">{{ a.name }} <span class="muted">({{ einheiten.get(a.einheit, a.einheit) }}, ab {{ a.mieter.von|dmy }})</span></td>
<td><input name="mp_{{ key(a.mieter) }}" value="{{ md.get('personen') or '' }}" style="width:60px"></td>
<td><input name="ma_{{ key(a.mieter) }}" value="{{ md.get('akonto') or '' }}" style="width:90px"></td></tr>{% endfor %}</table>
<p>Heizung: <input name="grundanteil" value="{{ ein.heizung_grundanteil }}" style="width:60px"> % Grundanteil nach m², Rest nach Wärmezähler ·
Honorar: <input name="honorar_wert" value="{{ ein.honorar_wert }}" style="width:70px">
<select name="honorar_art"><option value="prozent" {{ 'selected' if ein.honorar_art == 'prozent' }}>% der Nebenkosten</option>
<option value="betrag" {{ 'selected' if ein.honorar_art == 'betrag' }}>CHF pro Periode (nach m²)</option></select></p>
<button>Speichern</button></form>
<datalist id="energie">{% for s in sensoren %}<option value="{{ s }}">{% endfor %}</datalist>
<p class="muted">Üblich sind 3–5 % Honorar; 30–50 % Grundanteil bei verbrauchsabhängiger Heizkostenabrechnung. Personen und Akonto stehen im Mietvertrag.</p></div>

<div class="card"><h2>Abrechnung erstellen</h2>
{% if e.abgelaufen and e.vollstaendig and not e.hinweise %}
<form method="post"><input type="hidden" name="aktion" value="erstellen"><input type="hidden" name="p" value="{{ p }}">
Datum <input type="date" name="datum" value="{{ heute }}"> <button>Abrechnungen erstellen</button></form>
<p class="muted">Je Mietverhältnis ein PDF; Nachzahlungen kommen mit Einzahlungsschein unter «Rechnungen» ins Zahlungsregister.</p>
{% else %}<p class="muted">Möglich, sobald die Periode vorbei ist, die Stromdaten bis 30.6. vorliegen und keine Hinweise oben mehr offen sind.</p>{% endif %}
<form method="post"><input type="hidden" name="aktion" value="vorschau"><input type="hidden" name="p" value="{{ p }}"><button>Vorschau als PDF</button></form>
{% if dateien %}<ul>{% for f in dateien %}<li><a href="datei?pfad=NK-{{ p }}/{{ f }}" target="_blank">{{ f }}</a></li>{% endfor %}</ul>{% endif %}</div>
"""


def _zahl(v, name):
    v = (v or "").strip().replace("'", "").replace(",", ".")
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"{name}: «{v}» ist keine Zahl") from None


def _sicher(name):
    stamm = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._") or "beleg"
    return stamm[:80]


def seite():
    from flask import redirect, render_template_string, request
    cfg = S.config()
    liste = perioden(cfg)
    p = request.values.get("p") or (liste[0] if liste else periode_name(date.today()))
    if p not in liste:
        liste = [p] + liste
    d = laden()
    per = periode_daten(d, p)
    if request.method == "POST":
        try:
            msg = _post(request, cfg, d, per, p)
            return redirect(f"nebenkosten?p={p}&msg={msg}")
        except (ValueError, KeyError) as e:
            return redirect(f"nebenkosten?p={p}&c=warn&msg=Nicht gespeichert: {e}")
    b = S.berechnung("Nebenkosten")
    e = abrechnen(cfg, b.get("res") if b.get("ok") else None, p, d)
    import seiten
    einheiten = seiten._einheiten(cfg)
    zaehler = [("gesamt", "Gesamtzähler")] + [(u, f"Wohnung {v}") for u, v in einheiten.items()]
    ordner = S.RECHNUNGEN / f"NK-{p}"
    dateien = sorted(f.name for f in ordner.glob("*.pdf")) if ordner.exists() else []
    try:
        sensoren = S.collector.energie_sensoren() or []
    except Exception:  # noqa: BLE001
        sensoren = []
    ein = d["einstellungen"]
    honorar = f"{ein['honorar_wert']:g} %" if ein["honorar_art"] == "prozent" else f"CHF {float(ein['honorar_wert']):.2f} nach m²"
    return S.page("Nebenkosten", render_template_string(
        SEITE,
        e=e, p=p, liste=liste, text=periode_text, per=per, ein=ein, kat=KATEGORIEN, einheiten=einheiten, zaehler=zaehler,
        vorschlaege=VORSCHLAEGE, dateien=dateien, sensoren=[s if isinstance(s, str) else s[0] for s in sensoren],
        key=mieter_key, honorar=honorar, heute=date.today().isoformat(), ha_waerme=bool(ein.get("waerme"))))


def _post(request, cfg, d, per, p):
    aktion = request.form.get("aktion")
    if aktion == "position":
        kat = request.form["kategorie"]
        if kat not in KATEGORIEN:
            raise ValueError("Kategorie unbekannt")
        betrag = _zahl(request.form.get("betrag"), "Betrag")
        if betrag is None:
            raise ValueError("Betrag fehlt")
        x = dict(titel=request.form["titel"].strip()[:80], kategorie=kat, betrag=round(betrag, 2))
        if kat == "direkt":
            x["einheit"] = request.form.get("einheit")
        fs = request.files.get("beleg")
        if fs and fs.filename:
            ordner = S.DATA / "nebenkosten" / p
            ordner.mkdir(parents=True, exist_ok=True)
            name = f"{datetime.now():%Y%m%d%H%M%S}_{_sicher(fs.filename)}"
            fs.save(ordner / name)
            x["beleg"] = name
        per["positionen"].append(x)
        speichern(d)
        S.log.info("Nebenkosten %s: Position erfasst (%s)", p, KATEGORIEN[kat][0])
        return "Erfasst"
    if aktion == "loeschen":
        x = per["positionen"].pop(int(request.form["i"]))
        speichern(d)
        S.log.info("Nebenkosten %s: Position entfernt", p)
        return f"Entfernt: {x['titel']}"
    if aktion == "auto":
        b = S.berechnung("Nebenkosten")
        auto, _ = auto_positionen(cfg, b.get("res") if b.get("ok") else None, *periode_grenzen(p))
        an = set(request.form.getlist("an"))
        per["auto_aus"] = [x["auto"] for x in auto if x["auto"] not in an]
        speichern(d)
        return "Übernommen"
    if aktion == "waerme":
        if request.form.get("ha"):
            st = _waerme_aus_ha(d["einstellungen"], p)
            per["waerme"].update(st)
            speichern(d)
            return f"Aus Home Assistant: {len(st)} Zähler"
        w = {}
        for k in ["gesamt"] + list(__import__("seiten")._einheiten(cfg)):
            s, e = _zahl(request.form.get(f"{k}_start"), "Stand"), _zahl(request.form.get(f"{k}_ende"), "Stand")
            if s is not None or e is not None:
                w[k] = {"start": s, "ende": e}
        per["waerme"] = w
        speichern(d)
        return "Gespeichert"
    if aktion == "grundlagen":
        import seiten
        ein = d["einstellungen"]
        for u in seiten._einheiten(cfg):
            fl, pe = _zahl(request.form.get(f"flaeche_{u}"), "Fläche"), _zahl(request.form.get(f"personen_{u}"), "Personen")
            ein["einheiten"][u] = {k: v for k, v in (("flaeche", fl), ("personen_ohne_mieter", pe)) if v is not None}
        w = {}
        for k in ["gesamt"] + list(seiten._einheiten(cfg)):
            s = (request.form.get(f"sensor_{k}") or "").strip()
            if s:
                if not s.startswith("sensor."):
                    raise ValueError("Wärmezähler: Sensor muss mit «sensor.» beginnen")
                w[k] = s
        ein["waerme"] = w
        for m in cfg.get("mietverhaeltnisse") or []:
            k = mieter_key(m)
            pe, ak = _zahl(request.form.get(f"mp_{k}"), "Personen"), _zahl(request.form.get(f"ma_{k}"), "Akonto")
            if pe is not None or ak is not None:
                ein["mieter"][k] = {kk: v for kk, v in (("personen", pe), ("akonto", ak)) if v is not None}
        g = _zahl(request.form.get("grundanteil"), "Grundanteil")
        h = _zahl(request.form.get("honorar_wert"), "Honorar")
        if g is not None:
            if not 0 <= g <= 100:
                raise ValueError("Grundanteil zwischen 0 und 100 %")
            ein["heizung_grundanteil"] = g
        if h is not None:
            if h < 0:
                raise ValueError("Honorar nicht negativ")
            ein["honorar_wert"] = h
        ein["honorar_art"] = "betrag" if request.form.get("honorar_art") == "betrag" else "prozent"
        speichern(d)
        S.log.info("Nebenkosten: Grundlagen gespeichert")
        return "Gespeichert"
    if aktion in ("erstellen", "vorschau"):
        b = S.berechnung("Nebenkosten")
        if not b.get("ok"):
            raise ValueError(b.get("fehler") or "keine Berechnung")
        if aktion == "vorschau":
            erg = abrechnen(b["cfg"], b["res"], p, d)
            ordner = S.RECHNUNGEN / f"NK-{p}"
            ordner.mkdir(parents=True, exist_ok=True)
            n = 0
            for a in erg["abschnitte"]:
                if a.mieter:
                    render(ordner / f"Vorschau_NK-{p}-{a.einheit}.pdf", b["cfg"], a, erg, f"Vorschau NK-{p}-{a.einheit}", date.today())
                    n += 1
            return f"{n} Vorschau-PDF erstellt (unten)"
        erg = abrechnen(b["cfg"], b["res"], p, d)
        if not (erg["abgelaufen"] and erg["vollstaendig"]) or erg["hinweise"]:
            raise ValueError("Periode noch nicht vollständig oder Hinweise offen")
        datum = date.fromisoformat(request.form.get("datum") or date.today().isoformat())
        made = erstellen(b["cfg"], b["res"], p, datum)
        S.log.info("Nebenkostenabrechnung %s erstellt: %d Mietverhältnisse", p, len(made))
        return "Erstellt: " + ", ".join(f"{n} (Saldo CHF {s:.2f})" for n, s, _ in made)
    raise ValueError("unbekannte Aktion")


def _waerme_aus_ha(ein, p):
    """Zählerstände der Wärmezähler am 1.7. 00:00 und 30.6. 24:00 (nächster gespeicherter Wert)."""
    von, bis = periode_grenzen(p)
    t0, t1 = f"{von.isoformat()}T00:00", f"{(bis + timedelta(days=1)).isoformat()}T00:00"
    out = {}
    with S.collector._db() as c:
        for k, ent in (ein.get("waerme") or {}).items():
            a = c.execute("SELECT wert FROM messwerte WHERE entity=? AND ts>=? ORDER BY ts LIMIT 1", (ent, t0)).fetchone()
            b = c.execute("SELECT wert FROM messwerte WHERE entity=? AND ts<=? ORDER BY ts DESC LIMIT 1", (ent, t1)).fetchone()
            if a or b:
                out[k] = {"start": round(float(a[0]), 3) if a else None, "ende": round(float(b[0]), 3) if b else None}
    return out


def beleg():
    from flask import abort, request, send_file
    ordner = (S.DATA / "nebenkosten" / _sicher(request.args.get("p", ""))).resolve()
    f = (ordner / _sicher(request.args.get("d", ""))).resolve()
    if ordner not in f.parents or not f.is_file():
        abort(404)
    return send_file(f)


def wp_entitaeten(ein):
    """Wärmezähler-Sensoren, die der Datensammler mitlesen soll."""
    return [v for v in (ein.get("waerme") or {}).values() if v]


def register(app, server):
    global S
    S = server
    app.add_url_rule("/nebenkosten", "nebenkosten", seite, methods=["GET", "POST"])
    app.add_url_rule("/nebenkosten_beleg", "nebenkosten_beleg", beleg)
