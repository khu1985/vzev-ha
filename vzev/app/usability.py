"""Usability-Prüfung (wie in der Finanz-App): alle Seiten mit den eigenen Daten anzeigen und automatisch prüfen.

Pro Seite startet der Score bei 100 und verliert Punkte für:
- lange Seiten (viele Karten, sehr viel Text)
- Tabellen, die auf dem Handy seitlich scrollen (breite Tabellen mit mehr als 7 Spalten) oder sehr lang werden
- grosse Formulare mit nur einem Knopf, Eingabefelder ohne Beschriftung
- mehr als 6 Kennzahlen in einer Reihe, Diagramme ohne Beschreibung
- langsame Ladezeit (Messungen unter «Leistung»), Fehler beim Anzeigen
Zugeklappte Teile (<details>) zählen nicht. Dazu kommt die Darstellung für alle Seiten: Kontrast der Farben in Hell und
Dunkel nach WCAG (mindestens 4.5:1 für Text). Das Ergebnis wird pro Version gespeichert (ux.sqlite); die Prüfung läuft
einmal am Tag im Hintergrund oder auf Knopfdruck unter «Vorschläge».
"""
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser

S = None
UEBERSPRINGEN = {"vorschlaege", "neu"}   # die Seite mit dem Ergebnis; das Changelog ist absichtlich lang
KONTRAST_MIN = 4.5
PRUEF_KOPF = "X-VZEV-Pruefung"           # Seitenaufrufe der Prüfung zählen weder für UX noch für die Leistung


@dataclass
class Problem:
    titel: str
    detail: str
    abzug: int


@dataclass
class Seite:
    pfad: str
    titel: str
    score: int
    probleme: list = field(default_factory=list)
    ms: int = 0


@dataclass
class Ergebnis:
    version: str
    zeit: str
    score: int
    seiten: list
    darstellung: list


class _Leser(HTMLParser):
    """Sammelt Tabellen, Formulare, Karten, Kennzahlen, Diagramme und Text einer Seite (vZEV-Markup)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabellen, self.formulare, self.text, self.kpi_gruppen = [], [], [], []
        self.karten = self.kpis = self.svg_ohne = self.ohne_label = 0
        self._tab, self._form, self._label, self._ignorieren, self._zu, self._details = [], None, 0, 0, 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        klasse = (a.get("class") or "").split()
        if tag == "details":
            zu = "open" not in a
            self._details.append(zu)
            self._zu += zu
        if self._zu:
            return
        if tag in ("script", "style", "textarea", "code", "pre"):
            self._ignorieren += 1
        if tag == "div" and "card" in klasse:
            self.karten += 1
        if tag == "div" and ("grid" in klasse or "ampeln" in klasse):
            self.kpi_gruppen.append(0)
        if tag == "div" and "kpi" in klasse:
            self.kpis += 1
            if self.kpi_gruppen:
                self.kpi_gruppen[-1] += 1
        if tag == "svg" and not a.get("aria-label") and not a.get("aria-hidden"):
            self.svg_ohne += 1
        if tag == "table":
            self._tab.append({"klasse": klasse, "spalten": 0, "zeilen": 0, "kopf": True})
        if self._tab:
            t = self._tab[-1]
            if tag == "th" and t["kopf"]:
                t["spalten"] += 1
            if tag == "tr":
                if t["spalten"]:
                    t["kopf"] = False
                if not t["kopf"]:
                    t["zeilen"] += 1
        if tag == "form":
            self._form = {"felder": 0, "knoepfe": 0}
        if tag == "label":
            self._label += 1
        if tag in ("input", "select", "textarea"):
            typ = (a.get("type") or "text").lower()
            if typ not in ("hidden", "submit", "button", "file"):
                if self._form is not None:
                    self._form["felder"] += 1
                if (not self._label and not a.get("aria-label") and not a.get("title") and not a.get("placeholder")
                        and typ not in ("checkbox", "radio")):
                    self.ohne_label += 1
        if tag == "button" and self._form is not None and (a.get("type") or "submit") == "submit":
            self._form["knoepfe"] += 1

    def handle_endtag(self, tag):
        if tag == "details" and self._details:
            self._zu -= self._details.pop()
            return
        if self._zu:
            return
        if tag in ("script", "style", "textarea", "code", "pre") and self._ignorieren:
            self._ignorieren -= 1
        if tag == "table" and self._tab:
            self.tabellen.append(self._tab.pop())
        if tag == "form" and self._form is not None:
            self.formulare.append(self._form)
            self._form = None
        if tag == "label" and self._label:
            self._label -= 1
        if tag == "div" and self.kpi_gruppen and self.kpi_gruppen[-1] == 0:
            pass

    def handle_data(self, data):
        if not self._ignorieren and not self._zu and data.strip():
            self.text.append(data)


def inhalt(html):
    """Nur der Hauptteil (ohne Menü)."""
    m = re.search(r"<main>(.*)</main>", html, re.S)
    return m.group(1) if m else html


def pruefen_html(html):
    lz = _Leser()
    lz.feed(inhalt(html))
    p = []
    if lz.karten > 8:
        p.append(Problem("Seite sehr lang", f"{lz.karten} Karten – Seltenes in Reiter oder aufklappbare Teile verschieben",
                         min(12, 2 * (lz.karten - 8))))
    zeichen = sum(len(t) for t in lz.text)
    if zeichen > 15000:
        p.append(Problem("Sehr viel Text", f"rund {zeichen // 1000}k Zeichen – Erklärungen kürzen oder aufklappbar machen",
                         8 if zeichen > 25000 else 4))
    for t in lz.tabellen:
        breit = "wide" in t["klasse"]   # breite Tabellen scrollen auf dem Handy, die übrigen werden zu Karten
        if breit and t["spalten"] > 7:
            p.append(Problem("Tabelle scrollt auf dem Handy seitlich", f"{t['spalten']} Spalten", 4))
        if not breit and t["zeilen"] * max(1, t["spalten"]) > 240:
            p.append(Problem("Lange Kartenliste auf dem Handy",
                             f"{t['zeilen']} Zeilen × {t['spalten']} Spalten – Filter, Seiten oder aufklappbare Zeilen", 6))
        elif t["zeilen"] > 40:
            p.append(Problem("Lange Tabelle", f"{t['zeilen']} Zeilen – Filter oder «mehr anzeigen»", 4))
    for f in lz.formulare:
        if f["felder"] >= 50 and f["knoepfe"] <= 1:
            p.append(Problem("Sehr grosses Formular", f"{f['felder']} Felder mit einem Knopf – in Abschnitte teilen", 4))
    if lz.ohne_label:
        p.append(Problem("Eingabefelder ohne Beschriftung", f"{lz.ohne_label} Feld(er) ohne Label", min(10, 2 * lz.ohne_label)))
    gross = max(lz.kpi_gruppen, default=0)
    if gross > 6:
        p.append(Problem("Viele Kennzahlen auf einmal", f"{gross} in einer Reihe – die wichtigsten 4–6 zeigen", 4))
    if lz.svg_ohne:
        p.append(Problem("Diagramme ohne Beschreibung", f"{lz.svg_ohne} Diagramm(e) ohne aria-label", min(6, 2 * lz.svg_ohne)))
    return p


# ---------------------------------------------------------------- Farben

def _farben(css):
    erg = {}
    for thema, muster in (("hell", r":root\{([^}]*)\}"), ("dunkel", r"html\[data-theme=dark\]\{([^}]*)\}")):
        block = re.search(muster, css)
        erg[thema] = dict(re.findall(r"--([a-z0-9]+):\s*(#[0-9a-fA-F]{6})", block.group(1) if block else ""))
    for name, wert in erg["hell"].items():
        erg["dunkel"].setdefault(name, wert)
    return erg


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    k = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2]


def kontrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAARE = [("ink", "card", "Text auf Karten"), ("muted", "card", "grauer Text auf Karten"),
         ("muted", "bg", "grauer Text auf dem Hintergrund"), ("link", "card", "Links"), ("nav", "bg", "Navigation"),
         ("ok", "okbg", "grüne Hinweise"), ("warn", "warnbg", "orange Hinweise"), ("auf", "ink", "Text auf Hauptknöpfen")]


def darstellung(css):
    p = []
    for thema, farben in _farben(css).items():
        for vorne, hinten, text in PAARE:
            if vorne in farben and hinten in farben:
                k = kontrast(farben[vorne], farben[hinten])
                if k < KONTRAST_MIN:
                    p.append(Problem(f"Kontrast zu schwach ({thema}): {text}", f"{k:.1f}:1 statt mindestens 4.5:1", 3))
    return p


# ---------------------------------------------------------------- alle Seiten

def seitenliste():
    """(Pfad, Titel) aller Seiten aus der Navigation, dazu die Reiter der Einstellungen."""
    out = [(h, l) for _, eintraege in S.NAVIGATION for h, l in eintraege]
    out += [("protokoll", "Einstellungen · Protokoll"), ("einstellungen?tab=zaehler", "Einstellungen · Zähler"),
            ("einstellungen?tab=regeln", "Einstellungen · Regeln")]
    return [(h, l) for h, l in out if h not in UEBERSPRINGEN]


def _endpunkt(pfad):
    try:
        return S.app.url_map.bind("").match("/" + pfad.split("?")[0].lstrip("./"))[0]
    except Exception:  # noqa: BLE001
        return None


def pruefen(version=None):
    import leistung as le
    version = version or S.VERSION
    zeiten = {}
    try:
        zeiten = {m.name: m.mittel_ms for m in le.messungen()[0] if m.art == "seite"}
    except Exception:  # noqa: BLE001
        pass
    client = S.app.test_client()
    liste = []
    for pfad, titel in seitenliste():
        t0 = time.perf_counter()
        try:
            r = client.get("/" + pfad.lstrip("./"), headers={PRUEF_KOPF: "1"}, environ_base={"REMOTE_ADDR": S.INGRESS_PROXY})
            html = r.get_data(as_text=True)
            if r.status_code >= 400:
                probleme = [Problem("Seite lässt sich nicht anzeigen", f"HTTP {r.status_code}", 40)]
            elif 'id="warten"' in html:
                continue   # Berechnung läuft – die Seite zeigt nur die Warteseite
            else:
                probleme = pruefen_html(html)
        except Exception as e:  # noqa: BLE001
            S.log.warning("Usability: Seite %s nicht anzeigbar: %s", pfad, e)
            probleme = [Problem("Seite lässt sich nicht anzeigen", type(e).__name__, 40)]
        ms = round((time.perf_counter() - t0) * 1000)
        ms_eff = max(ms, int(zeiten.get(_endpunkt(pfad) or "", 0) or 0))
        if ms_eff > 1500:
            probleme.append(Problem("Seite lädt langsam", f"rund {ms_eff / 1000:.1f} s", 20 if ms_eff > 5000 else 10 if ms_eff > 3000 else 5))
        liste.append(Seite(pfad, titel, max(0, 100 - sum(x.abzug for x in probleme)), probleme, ms_eff))
    dar = darstellung(S.BASE)
    mittel = sum(s.score for s in liste) / len(liste) if liste else 100
    return Ergebnis(version, datetime.now().isoformat(timespec="minutes"), max(0, round(mittel - sum(x.abzug for x in dar))),
                    sorted(liste, key=lambda s: s.score), dar)


# ---------------------------------------------------------------- Speicher

def _db():
    import ux
    return ux.db()


def sichern(e):
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO usability VALUES (?, ?, ?)", (e.version, e.zeit, json.dumps(asdict(e), ensure_ascii=False)))


def _laden(d):
    return Ergebnis(d["version"], d["zeit"], d["score"],
                    [Seite(s["pfad"], s["titel"], s["score"], [Problem(**p) for p in s["probleme"]], s.get("ms", 0)) for s in d["seiten"]],
                    [Problem(**p) for p in d["darstellung"]])


def letztes():
    """(neuestes Ergebnis, das der Version davor)."""
    with _db() as c:
        zeilen = c.execute("SELECT daten FROM usability ORDER BY zeit DESC LIMIT 2").fetchall()
    erg = [_laden(json.loads(z[0])) for z in zeilen]
    return (erg[0] if erg else None, erg[1] if len(erg) > 1 else None)


def faellig(version, heute):
    with _db() as c:
        z = c.execute("SELECT zeit FROM usability WHERE version = ?", (version,)).fetchone()
    return not z or z[0][:10] < heute


def vorschlaege():
    """(Titel, Detail, Gewicht) – nur Seitennamen und Mengen."""
    e, _ = letztes()
    if not e:
        return []
    erg = [(p.titel, p.detail, 3 if p.abzug >= 5 else 2) for p in e.darstellung]
    for s in e.seiten:
        for p in s.probleme:
            erg.append((f"Seite «{s.titel}»: {p.titel}", p.detail, 3 if p.abzug >= 10 else 2 if p.abzug >= 5 else 1))
    return erg


def bericht_text():
    e, vorher = letztes()
    if not e:
        return []
    alt = {s.pfad: s.score for s in (vorher.seiten if vorher else [])}
    z = [f"Usability-Score {e.score}/100" + (f" (vorher {vorher.score}, Version {vorher.version})" if vorher else "")]
    for s in e.seiten:
        if s.score < 100:
            z.append(f"{s.titel}: {s.score}" + (f" (vorher {alt[s.pfad]})" if s.pfad in alt else "") + " – "
                     + "; ".join(p.titel for p in s.probleme))
    return z


def register(app, server):
    global S
    S = server
