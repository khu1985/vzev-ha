"""UX-Score (wie in der Finanz-App): wie die App erlebt und genutzt wird – Befragung, Verhalten und Usability.

Abgrenzung: Der Usability-Score (usability.py) prüft automatisch, ob die Oberfläche handwerklich gut bedienbar ist
(ISO 9241-11). UX (ISO 9241-210) umfasst das ganze Erleben: Nutzen, Vertrauen, ob man gerne zurückkommt und ob die
Abrechnung à jour bleibt.

Teile (0–100, gewichtet 40/40/20; fehlt ein Teil, zählen die übrigen im gleichen Verhältnis):
- Befragung: UEQ-S (User Experience Questionnaire, Kurzform; Schrepp, Hinderks & Thomaschewski 2017) mit 8
  Gegensatzpaaren von −3 bis +3 – pragmatische Qualität (Bedienung) und hedonische Qualität (Erleben) – plus zwei
  eigene Aussagen (1–5). Alle 90 Tage.
- Verhalten (angelehnt an Googles HEART-Modell), letzte 90 Tage: Wochen mit Nutzung, Anteil genutzter Seiten,
  Formulare ohne Eingabefehler und ob die Abrechnung à jour ist (Primeo-Daten, offene Monate, überfällige Rechnungen).
- Usability: der automatische Score der aktuellen Version.

Aufgezeichnet werden nur Seitenaufrufe und Formulare (Seite, Zeit, ob mit Eingabefehler) – keine Inhalte, nur in
ux.sqlite im Datenordner; ausschalten mit `ux: {aufzeichnen: false}` in vzev.yaml. Einträge älter als 400 Tage werden
gelöscht.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

S = None
UEQ_S = [  # (negativ, positiv, Skala)
    ("behindernd", "unterstützend", "pragmatisch"),
    ("kompliziert", "einfach", "pragmatisch"),
    ("ineffizient", "effizient", "pragmatisch"),
    ("verwirrend", "übersichtlich", "pragmatisch"),
    ("langweilig", "spannend", "hedonisch"),
    ("uninteressant", "interessant", "hedonisch"),
    ("konventionell", "originell", "hedonisch"),
    ("herkömmlich", "neuartig", "hedonisch"),
]
EIGENE = [("vertrauen", "Ich vertraue den Zahlen der App."),
          ("nutzen", "Die App erleichtert mir die Abrechnung.")]
GEWICHTE = {"befragung": 0.4, "verhalten": 0.4, "usability": 0.2}
UMFRAGE_TAGE = 90
FENSTER = 90
QUELLEN = [("UEQ – User Experience Questionnaire (Kurzform UEQ-S)", "https://www.ueq-online.org/"),
           ("HEART-Framework (Google Research)",
            "https://research.google/pubs/measuring-the-user-experience-on-a-large-scale-user-centered-metrics-for-web-applications/")]
NICHT_AUFZEICHNEN = {"static", "status", "datei", "nebenkosten_beleg", "sicherung", "vorschlaege_md"}

_PUFFER = []
_SPERRE = threading.Lock()


def an():
    try:
        return bool((S.config().get("ux") or {}).get("aufzeichnen", True))
    except Exception:  # noqa: BLE001
        return True


@contextmanager
def db():
    c = sqlite3.connect(S.DATA / "ux.sqlite", timeout=10)
    try:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS ux_ereignisse (zeit TEXT NOT NULL, art TEXT NOT NULL, seite TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ux_ereignisse_zeit ON ux_ereignisse (zeit);
            CREATE TABLE IF NOT EXISTS ux_umfrage (datum TEXT PRIMARY KEY, antworten TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ux_verlauf (datum TEXT PRIMARY KEY, score INTEGER NOT NULL, teile TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usability (version TEXT PRIMARY KEY, zeit TEXT NOT NULL, daten TEXT NOT NULL);
        """)
        yield c
        c.commit()
    finally:
        c.close()


def erfassen(art, seite):
    """art: aufruf | ok | fehler. Nur im Speicher – `sichern` schreibt in die Datenbank."""
    with _SPERRE:
        _PUFFER.append((datetime.now().isoformat(timespec="seconds"), art, seite or "./"))
        if len(_PUFFER) > 5000:
            del _PUFFER[:1000]


def sichern():
    with _SPERRE:
        neu = list(_PUFFER)
        _PUFFER.clear()
    with db() as c:
        if neu:
            c.executemany("INSERT INTO ux_ereignisse VALUES (?, ?, ?)", neu)
        c.execute("DELETE FROM ux_ereignisse WHERE zeit < ?", ((date.today() - timedelta(days=400)).isoformat(),))


def _nach_anfrage(antwort):
    """Seitenaufrufe und Formulare festhalten (ohne Inhalte)."""
    from flask import request
    try:
        import usability
        if not request.endpoint or request.endpoint in NICHT_AUFZEICHNEN or request.headers.get(usability.PRUEF_KOPF) or not an():
            return antwort
        seite = request.path.strip("/") or "./"
        if request.method == "GET" and antwort.status_code == 200 and antwort.mimetype == "text/html":
            erfassen("aufruf", seite)
        elif request.method == "POST":
            ziel = antwort.headers.get("Location") or ""
            erfassen("fehler" if "c=warn" in ziel or antwort.status_code >= 400 else "ok", seite)
    except Exception:  # noqa: BLE001 – die Aufzeichnung darf nie eine Antwort verhindern
        pass
    return antwort


# ---------------------------------------------------------------- Befragung

def umfrage_speichern(antworten, heute=None):
    for i, _ in enumerate(UEQ_S):
        w = antworten.get(f"u{i}")
        if w in (None, "") or not -3 <= int(w) <= 3:
            raise ValueError("Bitte alle 8 Gegensatzpaare beantworten.")
    for s, _ in EIGENE:
        w = antworten.get(s)
        if w in (None, "") or not 1 <= int(w) <= 5:
            raise ValueError("Bitte beide Aussagen bewerten.")
    daten = {k: int(antworten[k]) for k in [f"u{i}" for i in range(len(UEQ_S))] + [s for s, _ in EIGENE]}
    if antworten.get("notiz"):
        daten["notiz"] = str(antworten["notiz"])[:500]
    with db() as c:
        c.execute("INSERT OR REPLACE INTO ux_umfrage VALUES (?, ?)", ((heute or date.today()).isoformat(), json.dumps(daten, ensure_ascii=False)))


def umfragen():
    with db() as c:
        return [(r[0], json.loads(r[1])) for r in c.execute("SELECT datum, antworten FROM ux_umfrage ORDER BY datum")]


def umfrage_faellig(heute=None):
    heute = heute or date.today()
    u = umfragen()
    return not u or (heute - date.fromisoformat(u[-1][0])).days >= UMFRAGE_TAGE


@dataclass
class Befragung:
    datum: str
    pragmatisch: float
    hedonisch: float
    vertrauen: int
    nutzen: int
    tiefste: str
    score: int


def befragung(heute=None):
    heute = heute or date.today()
    u = umfragen()
    if not u or (heute - date.fromisoformat(u[-1][0])).days > 2 * UMFRAGE_TAGE:
        return None
    datum, a = u[-1]
    werte = [int(a.get(f"u{i}", 0)) for i in range(len(UEQ_S))]
    prag, hed = sum(werte[:4]) / 4, sum(werte[4:]) / 4
    i = min(range(len(werte)), key=lambda j: werte[j])
    score = ((prag + 3) / 6 + (hed + 3) / 6 + (int(a["vertrauen"]) - 1) / 4 + (int(a["nutzen"]) - 1) / 4) / 4 * 100
    return Befragung(datum, round(prag, 2), round(hed, 2), int(a["vertrauen"]), int(a["nutzen"]), f"{UEQ_S[i][0]} – {UEQ_S[i][1]}", round(score))


def bewertung_ueq(wert):
    """Einordnung nach UEQ: über +0,8 positiv, unter −0,8 negativ."""
    return "positiv" if wert > 0.8 else "negativ" if wert < -0.8 else "neutral"


# ---------------------------------------------------------------- Verhalten

@dataclass
class Verhalten:
    tage: int
    wochen_aktiv: int
    wochen: int
    seiten_genutzt: int
    seiten_total: int
    ungenutzt: list
    formulare: int
    eingabefehler: int
    fehler_seiten: list
    primeo_tage: int
    offene_monate: int
    ueberfaellig: int
    teile: dict
    score: int


def _linear(wert, gut, schlecht):
    if wert <= gut:
        return 1.0
    if wert >= schlecht:
        return 0.0
    return 1 - (wert - gut) / (schlecht - gut)


def _seiten():
    return {h: l for _, eintraege in S.NAVIGATION for h, l in eintraege}


def verhalten(heute=None):
    heute = heute or date.today()
    von = (heute - timedelta(days=FENSTER)).isoformat()
    with db() as c:
        ereignisse = c.execute("SELECT zeit, art, seite FROM ux_ereignisse WHERE zeit >= ?", (von,)).fetchall()
        erster = c.execute("SELECT MIN(zeit) FROM ux_ereignisse").fetchone()[0]
    tage = min(FENSTER, (heute - date.fromisoformat(erster[:10])).days + 1) if erster else 0
    seiten = _seiten()
    aufrufe = [(z, s) for z, a, s in ereignisse if a == "aufruf"]
    besucht = {s for _, s in aufrufe}
    if "protokoll" in besucht or "neu" in besucht:
        besucht.add("einstellungen")
    ungenutzt = [t for p, t in seiten.items() if p not in besucht]
    wochen = max(1, min(13, (tage + 6) // 7))
    aktiv = len({date.fromisoformat(z[:10]).isocalendar()[:2] for z, _ in aufrufe})
    formulare = [(a, s) for _, a, s in ereignisse if a in ("ok", "fehler")]
    fehler = sum(1 for a, _ in formulare if a == "fehler")
    pro_seite = {}
    for a, s in formulare:
        x = pro_seite.setdefault(s, [0, 0])
        x[1] += 1
        x[0] += a == "fehler"
    fehler_seiten = sorted(((seiten.get(s, s), f, n) for s, (f, n) in pro_seite.items() if f), key=lambda x: -x[1])
    primeo, offen, ueber = None, 0, 0
    b = S._cache if S._cache.get("ok") else {}
    if b.get("res") is not None:
        primeo = (heute - b["res"].index.max().date()).days
        try:
            import aufgaben
            offen = len(aufgaben.stand(heute)[4])
        except Exception:  # noqa: BLE001
            offen = 0
    try:
        import zahlungen
        ueber = int(zahlungen.uebersicht()["n_ueberfaellig"])
    except Exception:  # noqa: BLE001
        ueber = 0
    teile = {}
    if tage >= 7:
        teile["Nutzung"] = min(1.0, aktiv / wochen)
        teile["Seiten genutzt"] = (len(seiten) - len(ungenutzt)) / len(seiten) if seiten else 0.0
    if len(formulare) >= 3:
        teile["Formulare ohne Fehler"] = 1 - fehler / len(formulare)
    akt = [_linear(offen, 1, 4), max(0.0, 1 - ueber / 4)]
    if primeo is not None:
        akt.append(_linear(primeo, 45, 100))
    teile["Abrechnung à jour"] = sum(akt) / len(akt)
    score = round(sum(teile.values()) / len(teile) * 100) if teile else None
    return Verhalten(tage, aktiv, wochen, len(seiten) - len(ungenutzt), len(seiten), ungenutzt, len(formulare), fehler,
                     fehler_seiten, primeo, offen, ueber, teile, score)


# ---------------------------------------------------------------- Gesamt

@dataclass
class Ergebnis:
    score: int
    teile: dict
    befragung: Befragung
    verhalten: Verhalten
    usability: int
    umfrage_faellig: bool
    hinweise: list = field(default_factory=list)   # (Titel, Detail, Gewicht 1–3)


def berechnen(heute=None):
    import usability as us
    heute = heute or date.today()
    b = befragung(heute)
    v = verhalten(heute)
    e, _ = us.letztes()
    u = e.score if e else None
    teile = {"befragung": b.score if b else None, "verhalten": v.score, "usability": u}
    da = {n: w for n, w in teile.items() if w is not None}
    score = round(sum(w * GEWICHTE[n] for n, w in da.items()) / sum(GEWICHTE[n] for n in da)) if da else None
    faellig = umfrage_faellig(heute)
    h = []
    if faellig and v.tage >= 14:
        h.append(("Kurzbefragung zur App ausfüllen", "8 Gegensatzpaare und 2 Aussagen, rund eine Minute – alle 90 Tage.", 2))
    if v.tage >= 30 and v.ungenutzt:
        h.append((f"{len(v.ungenutzt)} Seiten in {min(v.tage, FENSTER)} Tagen nicht geöffnet",
                  ", ".join(v.ungenutzt[:8]) + (" …" if len(v.ungenutzt) > 8 else "") + " – nicht gebraucht, nicht gefunden oder nicht verständlich?", 1))
    for titel, f, n in v.fehler_seiten[:3]:
        if f >= 2 and f / n >= 0.2:
            h.append((f"Formulare auf «{titel}» oft mit Eingabefehler", f"{f} von {n} abgeschickten Formularen", 2))
    if v.offene_monate >= 2:
        h.append((f"{v.offene_monate} Monate nicht abgeschlossen", "Monatsabschluss zu umständlich oder fehlen Daten?", 2))
    if b:
        if b.pragmatisch < 0.8:
            h.append(("Befragung: Bedienung nur neutral bzw. negativ", f"pragmatische Qualität {b.pragmatisch:+.1f} (UEQ, −3 bis +3); "
                      f"schwächstes Paar «{b.tiefste}»", 3 if b.pragmatisch < -0.8 else 2))
        if b.vertrauen <= 3:
            h.append(("Befragung: Vertrauen in die Zahlen tief", f"{b.vertrauen} von 5 – welche Zahlen wirken falsch?", 3))
        if b.nutzen <= 3:
            h.append(("Befragung: App erleichtert die Abrechnung wenig", f"{b.nutzen} von 5", 2))
    return Ergebnis(score, teile, b, v, u, faellig, h)


def verlauf_sichern(heute=None):
    heute = heute or date.today()
    with db() as c:
        if c.execute("SELECT 1 FROM ux_verlauf WHERE datum = ?", (heute.isoformat(),)).fetchone():
            return
    e = berechnen(heute)
    if e.score is not None:
        with db() as c:
            c.execute("INSERT OR REPLACE INTO ux_verlauf VALUES (?, ?, ?)", (heute.isoformat(), e.score, json.dumps(e.teile)))


def verlauf():
    with db() as c:
        return [(r[0], r[1], json.loads(r[2])) for r in c.execute("SELECT * FROM ux_verlauf ORDER BY datum")]


def vorschlaege():
    return list(berechnen().hinweise)


# ---------------------------------------------------------------- Hintergrund

_PRUEFUNG = {"laeuft": False}


def usability_pruefen(warten=False):
    """Usability-Prüfung (alle Seiten anzeigen) – im Hintergrund, nur wenn die Berechnung bereit ist."""
    import usability as us
    if _PRUEFUNG["laeuft"] or S.RECHNEN.get("aktiv") or not S._cache.get("ok"):
        return False

    def lauf():
        try:
            e = us.pruefen()
            us.sichern(e)
            S.log.info("Usability geprüft: Score %d/100", e.score)
        except Exception as ex:  # noqa: BLE001
            S.log.warning("Usability-Prüfung: %s", ex)
        finally:
            _PRUEFUNG["laeuft"] = False
    _PRUEFUNG["laeuft"] = True
    if warten:
        lauf()
    else:
        threading.Thread(target=lauf, name="usability", daemon=True).start()
    return True


def hintergrund(intervall=900):
    def schleife():
        time.sleep(120)
        while True:
            try:
                sichern()
                import usability as us
                if us.faellig(S.VERSION, date.today().isoformat()):
                    usability_pruefen(warten=True)
                verlauf_sichern()
            except Exception as e:  # noqa: BLE001
                S.log.debug("UX im Hintergrund: %s", e)
            time.sleep(intervall)
    threading.Thread(target=schleife, name="ux", daemon=True).start()


# ---------------------------------------------------------------- Karten auf «Vorschläge»

def _farbe(x):
    return "grau" if x is None else "gruen" if x >= 80 else "gelb" if x >= 60 else "rot"


KARTE_UX = """
<div class="card" id="ux"><h2>UX</h2>
<div class="grid" style="margin-bottom:12px">
{% for wert, titel in kpis %}<div class="kpi"><div class="t">{{ licht(farbe(wert))|safe }}{{ titel }}</div><div class="v">{{ (wert ~ '/100') if wert is not none else '–' }}</div></div>{% endfor %}
</div>
{% if e.hinweise %}<ul>{% for t, d, _ in e.hinweise %}<li>{{ t }} <span class="muted">– {{ d }}</span></li>{% endfor %}</ul>{% endif %}
{% if zeilen %}<table><tr><th class="l">Teil</th><th>Wert</th></tr>{% for t, w in zeilen %}<tr><td class="l">{{ t }}</td><td>{{ w }}</td></tr>{% endfor %}</table>{% endif %}
<p class="muted">Aufgezeichnet seit {{ v.tage }} Tag(en) (Fenster {{ fenster }} Tage): Nutzung in {{ v.wochen_aktiv }} von {{ v.wochen }} Wochen,
{{ v.seiten_genutzt }} von {{ v.seiten_total }} Seiten geöffnet, {{ v.formulare }} Formulare ({{ v.eingabefehler }} mit Eingabefehler){% if v.primeo_tage is not none %},
Primeo-Daten {{ v.primeo_tage }} Tage alt{% endif %}{% if v.offene_monate %}, {{ v.offene_monate }} Monat(e) offen{% endif %}{% if v.ueberfaellig %}, {{ v.ueberfaellig }} Rechnung(en) überfällig{% endif %}.</p>
{% if verlauf|length >= 2 %}<p class="muted">Verlauf UX-Score: {% for d, s, _ in verlauf[-12:] %}{{ d[5:] }} {{ s }}{{ ' · ' if not loop.last }}{% endfor %}</p>{% endif %}
<details{{ ' open' if e.umfrage_faellig }}><summary>Kurzbefragung{{ ' – jetzt fällig' if e.umfrage_faellig else (' – zuletzt ' ~ e.befragung.datum) if e.befragung else '' }}</summary>
<form method="post" action="vorschlaege"><input type="hidden" name="aktion" value="ux_umfrage">
<p class="muted">Wie erlebst du die App? Spontan pro Zeile ankreuzen – es gibt kein richtig oder falsch.</p>
{% for neg, pos, _ in ueq %}{% set i = loop.index0 %}<div class="ueq" role="radiogroup" aria-label="{{ neg }} oder {{ pos }}"><span>{{ neg }}</span>
{% for w in range(-3, 4) %}<label title="{{ '%+d'|format(w) }}"><input type="radio" name="u{{ i }}" value="{{ w }}" required><i>{{ '%+d'|format(w) }}</i></label>{% endfor %}<span>{{ pos }}</span></div>{% endfor %}
{% for s, text in eigene %}<p class="ueq-frage">{{ text }}</p><div class="ueq ueq5" role="radiogroup" aria-label="{{ text }}"><span>trifft nicht zu</span>
{% for w in range(1, 6) %}<label><input type="radio" name="{{ s }}" value="{{ w }}" required><i>{{ w }}</i></label>{% endfor %}<span>trifft zu</span></div>{% endfor %}
<label style="display:block;margin-top:10px">Was fehlt oder stört? (freiwillig)<input name="notiz" style="width:100%"></label>
<p><button class="primary">Absenden</button></p></form></details>
<details><summary>UX und Usability – der Unterschied</summary><p>Usability: Kann man die App gut bedienen? Der Usability-Score
prüft das automatisch an jeder Seite. UX: Wie wird die App als Ganzes erlebt – bringt sie etwas, vertraut man ihr, bleibt die
Abrechnung à jour? Dafür zählen die Kurzbefragung (UEQ-S) und das Verhalten der letzten 90 Tage. Aufgezeichnet werden nur
Seitennamen und ob ein Formular einen Eingabefehler hatte, nur im eigenen Datenordner; ausschalten mit
<code>ux: {aufzeichnen: false}</code> in vzev.yaml.</p><ul>{% for t, u in quellen %}<li><a href="{{ u }}" target="_blank" rel="noopener">{{ t }}</a></li>{% endfor %}</ul></details>
<style>.ueq{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin:6px 0}.ueq span{flex:1;min-width:90px;font-size:13px;color:var(--muted)}
.ueq span:last-child{text-align:right}.ueq label{display:inline-flex}.ueq input{position:absolute;opacity:0}
.ueq i{font-style:normal;display:inline-block;min-width:34px;text-align:center;padding:6px 0;border:1px solid var(--rand);border-radius:6px;cursor:pointer;font-size:13px}
.ueq input:checked+i{background:var(--ink);color:var(--auf);border-color:var(--ink)}.ueq input:focus-visible+i{outline:2px solid var(--link)}
.ueq-frage{margin:12px 0 0;font-weight:600;font-size:14px}</style></div>"""

KARTE_US = """
<div class="card" id="usability"><h2>Usability</h2>
{% if e %}<div class="grid" style="margin-bottom:12px">
<div class="kpi"><div class="t">{{ licht(farbe_us(e.score))|safe }}Usability-Score</div><div class="v">{{ e.score }}/100</div>
<div class="s">{% if vorher %}{{ '+' if e.score >= vorher.score }}{{ e.score - vorher.score }} seit {{ vorher.version }}{% else %}Version {{ e.version }}{% endif %}</div></div>
<div class="kpi"><div class="t">Seiten mit Potenzial</div><div class="v">{{ e.seiten|selectattr('score', 'lt', 100)|list|length }}</div><div class="s">von {{ e.seiten|length }}</div></div>
<div class="kpi"><div class="t">Gefundene Punkte</div><div class="v">{{ e.seiten|map(attribute='probleme')|map('length')|sum + e.darstellung|length }}</div></div>
</div>
{% set mit = e.seiten|selectattr('score', 'lt', 100)|list %}{% if mit %}<table><tr><th class="l">Seite</th><th>Score</th><th class="l">Gefunden</th></tr>
{% for s in mit %}<tr><td class="l">{{ licht(farbe_us(s.score))|safe }}<a href="{{ s.pfad }}">{{ s.titel }}</a></td><td>{{ s.score }}</td>
<td class="l">{% for p in s.probleme %}{{ p.titel }} <span class="muted">– {{ p.detail }}</span>{{ '<br>'|safe if not loop.last }}{% endfor %}</td></tr>{% endfor %}</table>{% endif %}
{% set gut = e.seiten|selectattr('score', 'ge', 100)|map(attribute='titel')|list %}{% if gut %}<p class="muted">Ohne Auffälligkeiten: {{ gut|join(', ') }}.</p>{% endif %}
{% if e.darstellung %}<h3>Darstellung (alle Seiten)</h3><ul>{% for p in e.darstellung %}<li>{{ p.titel }} – {{ p.detail }}</li>{% endfor %}</ul>{% endif %}
<p class="muted">Die App zeigt alle Seiten mit deinen Daten an und prüft sie automatisch: lange Seiten, Tabellen, die auf dem Handy
seitlich scrollen oder sehr lang werden, Formulare, Felder ohne Beschriftung, viele Kennzahlen, Diagramme ohne Beschreibung,
Ladezeit und den Farbkontrast in Hell und Dunkel. Pro Seite 100 Punkte minus Abzüge. Geprüft {{ e.zeit.replace('T', ' ') }}
(Version {{ e.version }}); läuft einmal am Tag im Hintergrund.</p>
{% else %}<p class="muted">Noch nicht geprüft – läuft einmal am Tag im Hintergrund, sobald die Berechnung bereit ist.</p>{% endif %}
<form method="post" action="vorschlaege"><input type="hidden" name="aktion" value="usability"><button>Jetzt prüfen</button></form></div>"""


def karten():
    from flask import render_template_string

    import ampel
    import usability as us
    sichern()
    e = berechnen()
    v = e.verhalten
    zeilen = [(n, round(x * 100)) for n, x in v.teile.items()]
    if e.befragung:
        b = e.befragung
        zeilen += [("Bedienung (UEQ pragmatisch, −3 bis +3)", f"{b.pragmatisch:+.1f} {bewertung_ueq(b.pragmatisch)}"),
                   ("Erleben (UEQ hedonisch, −3 bis +3)", f"{b.hedonisch:+.1f} {bewertung_ueq(b.hedonisch)}"),
                   ("Vertrauen in die Zahlen (1–5)", b.vertrauen), ("Erleichtert die Abrechnung (1–5)", b.nutzen)]
    kpis = [(e.score, "UX-Score"), (e.teile["befragung"], "Befragung (40 %)" + (" – fällig" if e.umfrage_faellig else "")),
            (e.teile["verhalten"], "Verhalten (40 %)"), (e.usability, "Usability (20 %)")]
    ux_html = render_template_string(KARTE_UX, e=e, v=v, kpis=kpis, zeilen=zeilen, verlauf=verlauf(), fenster=FENSTER,
                                     ueq=UEQ_S, eigene=EIGENE, quellen=QUELLEN, licht=ampel.licht, farbe=_farbe)
    ue, vorher = us.letztes()
    us_html = render_template_string(KARTE_US, e=ue, vorher=vorher, licht=ampel.licht,
                                     farbe_us=lambda x: "gruen" if x >= 90 else "gelb" if x >= 75 else "rot")
    return ux_html + us_html


def register(app, server, starten=False):
    global S
    S = server
    app.after_request(_nach_anfrage)
    if starten:
        hintergrund()
