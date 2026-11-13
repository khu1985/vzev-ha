"""Leistung der App messen: Ladezeiten der Seiten und Aktionen, Rechenzeit der grossen Berechnungen,
Hintergrundaufgaben, Datenmengen und Ressourcen – als Grundlage für technische Verbesserungen (Seite «Vorschläge»).

Gemessen wird im Speicher (wenige Mikrosekunden pro Aufruf) und alle 15 Minuten in leistung.json geschrieben,
getrennt pro App-Version, damit sich Verbesserungen von Version zu Version vergleichen lassen.
Gespeichert werden nur Zeiten und Mengen – keine Inhalte, keine Namen.
"""
import functools
import importlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("vzev")
S = None
_SPERRE = threading.Lock()
_DATEI_SPERRE = threading.Lock()
_WERTE = {}            # (Art, Name) → [Anzahl, Summe ms, Max ms]
_START = time.time()

# Berechnungen, die gemessen werden (Modul, Funktion). Ersetzt wird die Funktion im Modul – auch Aufrufe
# innerhalb des Moduls (z. B. core.run → load → compute) laufen dann über die Messung.
FUNKTIONEN = [
    ("core", "run"), ("core", "load"), ("core", "compute"), ("core", "speicher_fifo"),
    ("invoices", "main"), ("invoices", "render"), ("invoices", "render_jahr"),
    ("uebersicht", "daten"), ("uebersicht", "monate"), ("uebersicht", "kontrollen_fuer"),
    ("jahr", "daten"), ("fluss", "werte"), ("aufgaben", "stand"), ("aufgaben", "naechste"),
    ("zahlungen", "nachtragen"), ("zahlungen", "uebersicht"),
    ("vorschau", "berechnen"), ("vorschau", "unterzaehler"), ("vorschau", "waermepumpen"), ("vorschau", "jaz"),
    ("prognose", "treffer"), ("prognose", "ueblicher_verbrauch"), ("preise", "serie"),
    ("hastatistik", "fuellen"), ("sensoren", "berechnen"), ("sensoren", "schreiben"), ("vorschlaege", "sammeln"),
]
LANGSAM_SEITE_MS = 1500
LANGSAM_FUNKTION_MS = 800
# hängt am Netz oder läuft selten und darf dauern – keine Vorschläge wegen Langsamkeit
OHNE_VORSCHLAG = ("hastatistik.", "invoices.main", "core.run", "core.load")
NICHT_MESSEN = {"static", "status"}  # Dateien und die Abfrage der Warteseite (läuft im Sekundentakt)


def erfassen(art, name, ms):
    with _SPERRE:
        w = _WERTE.setdefault((art, name), [0, 0.0, 0.0])
        w[0] += 1
        w[1] += ms
        w[2] = max(w[2], ms)


def gemessen(name):
    def deko(f):
        @functools.wraps(f)
        def innen(*a, **kw):
            t = time.perf_counter()
            try:
                return f(*a, **kw)
            finally:
                erfassen("funktion", name, (time.perf_counter() - t) * 1000)
        innen.__gemessen__ = True
        return innen
    return deko


def instrumentieren():
    """Die Funktionen aus FUNKTIONEN in ihren Modulen durch gemessene Fassungen ersetzen (einmal beim Start)."""
    n = 0
    for modul, funktion in FUNKTIONEN:
        try:
            m = importlib.import_module(modul)
            f = getattr(m, funktion, None)
            if f and not getattr(f, "__gemessen__", False):
                setattr(m, funktion, gemessen(f"{modul}.{funktion}")(f))
                n += 1
        except Exception as e:  # noqa: BLE001
            log.debug("Messung %s.%s nicht möglich: %s", modul, funktion, e)
    return n


class Stoppuhr:
    """with Stoppuhr("hintergrund", "Datensammler ablesen"): … – für Abläufe ohne eigene Funktion."""

    def __init__(self, art, name):
        self.art, self.name = art, name

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *_):
        erfassen(self.art, self.name, (time.perf_counter() - self.t) * 1000)


# ---------------------------------------------------------------- Speichern (leistung.json)

def _datei():
    return S.DATA / "leistung.json"


def _laden():
    try:
        return json.loads(_datei().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sichern(version=None):
    """Gesammelte Werte in leistung.json übernehmen und im Speicher leeren."""
    version = version or S.VERSION
    with _SPERRE:
        werte = dict(_WERTE)
        _WERTE.clear()
    if not werte:
        return 0
    with _DATEI_SPERRE:
        alle = _laden()
        v = alle.setdefault(version, {})
        jetzt = datetime.now().isoformat(timespec="seconds")
        for (art, name), (n, s, mx) in werte.items():
            w = v.setdefault(f"{art}\t{name}", [0, 0.0, 0.0, jetzt])
            v[f"{art}\t{name}"] = [w[0] + int(n), round(w[1] + s, 1), round(max(w[2], mx), 1), jetzt]
        for alt in sorted(alle, key=_vt)[:-5]:  # die letzten fünf Versionen genügen für den Vergleich
            del alle[alt]
        tmp = _datei().with_suffix(".tmp")
        tmp.write_text(json.dumps(alle, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_datei())
    return len(werte)


@dataclass
class Messung:
    art: str
    name: str
    anzahl: int
    mittel_ms: float
    max_ms: float
    vorher_ms: float = None      # Mittel der Vorversion


def _vt(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v or "0"))


def messungen(version=None):
    """Messungen der aktuellen Version (inkl. noch nicht gesicherter), mit dem Mittel der Vorversion zum Vergleich."""
    version = version or S.VERSION
    sichern(version)
    alle = _laden()
    vorher = max((v for v in alle if _vt(v) < _vt(version)), key=_vt, default="")
    alt = {k: w[1] / max(1, w[0]) for k, w in alle.get(vorher, {}).items()}
    erg = []
    for k, (n, s, mx, _) in alle.get(version, {}).items():
        art, name = k.split("\t", 1)
        erg.append(Messung(art, name, n, round(s / max(1, n), 1), round(mx, 1),
                           round(alt[k], 1) if k in alt else None))
    erg.sort(key=lambda m: -(m.mittel_ms * m.anzahl))
    return erg, vorher


# ---------------------------------------------------------------- System und Daten

def _meminfo():
    erg = {}
    try:
        for z in Path("/proc/meminfo").read_text().splitlines():
            teile = z.split()
            if len(teile) >= 2 and teile[1].isdigit():
                erg[teile[0].rstrip(":")] = int(teile[1]) * 1024
    except OSError:
        pass
    return erg


def _rss():
    try:
        for z in Path("/proc/self/status").read_text().splitlines():
            if z.startswith("VmRSS:"):
                return int(z.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _ordner(p):
    try:
        return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())
    except OSError:
        return 0


def _groesse(p):
    try:
        return Path(p).stat().st_size
    except OSError:
        return 0


def system():
    mem = _meminfo()
    try:
        last = os.getloadavg()
    except OSError:
        last = (0.0, 0.0, 0.0)
    db = S.DATA / "messwerte.sqlite"
    zeilen = {}
    if db.exists():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) as c:
                for t in ("messwerte", "preise", "prognose", "evcc_sessions"):
                    try:
                        zeilen[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    except sqlite3.Error:
                        pass
        except sqlite3.Error:
            pass
    try:
        zeilen["primeo_dateien"] = sum(1 for p in S.PRIMEO.iterdir() if p.is_file())
    except OSError:
        pass
    return {
        "kerne": os.cpu_count() or 1,
        "last": tuple(round(x, 2) for x in last),
        "ram_total": mem.get("MemTotal", 0),
        "ram_frei": mem.get("MemAvailable", 0),
        "prozess": _rss(),
        "laufzeit_h": round((time.time() - _START) / 3600, 1),
        "db": _groesse(db),
        "dateien": _ordner(S.PRIMEO) + _ordner(S.RECHNUNGEN),
        "cache": _ordner(S.DATA / ".cache"),
        "log": _groesse(S.LOGFILE),
        "zeilen": zeilen,
        "rechnung_s": (getattr(S, "RECHNEN", None) or {}).get("dauer"),
    }


def _mb(b):
    return f"{b / 1024 / 1024:.1f} MB"


def vorschlaege():
    """(Titel, Detail, Gewicht 3/2/1) – technische Verbesserungen aus den Messungen."""
    ms, vorher = messungen()
    s = system()
    erg = []
    for m in ms:
        if m.art in ("seite", "aktion") and m.mittel_ms >= LANGSAM_SEITE_MS and m.anzahl >= 3:
            erg.append((f"{'Seite' if m.art == 'seite' else 'Aktion'} «{m.name}» lädt langsam",
                        f"Ø {m.mittel_ms / 1000:.1f} s bei {m.anzahl} Aufrufen, längster {m.max_ms / 1000:.1f} s",
                        3 if m.mittel_ms >= 3000 else 2))
        elif m.art == "funktion" and m.mittel_ms >= LANGSAM_FUNKTION_MS and m.anzahl >= 3 and not m.name.startswith(OHNE_VORSCHLAG):
            erg.append((f"Berechnung «{m.name}» ist langsam",
                        f"Ø {m.mittel_ms:.0f} ms bei {m.anzahl} Aufrufen – Kandidat für Zwischenspeicher", 2))
        if m.vorher_ms and m.anzahl >= 5 and m.mittel_ms > 1.5 * m.vorher_ms and m.mittel_ms - m.vorher_ms > 200:
            erg.append((f"«{m.name}» ist langsamer geworden", f"Ø {m.vorher_ms:.0f} ms in {vorher} → {m.mittel_ms:.0f} ms", 2))
    run = next((m for m in ms if m.name == "core.run"), None)
    if run and run.mittel_ms > 60_000:
        erg.append(("Die ganze Berechnung dauert über eine Minute", f"Ø {run.mittel_ms / 1000:.0f} s bei {run.anzahl} Läufen", 2))
    if s["db"] > 200 * 1024 * 1024:
        erg.append(("Messwert-Datenbank über 200 MB", _mb(s["db"]) + " – alte Messwerte verdichten oder aufräumen", 1))
    if s["cache"] > 200 * 1024 * 1024:
        erg.append(("Zwischenspeicher über 200 MB", _mb(s["cache"]) + " – alte Rechenstände aufräumen", 1))
    if s["ram_total"] and s["ram_frei"] / s["ram_total"] < 0.1:
        erg.append(("Wenig freier Arbeitsspeicher im System", f"{_mb(s['ram_frei'])} von {_mb(s['ram_total'])} frei", 2))
    if s["prozess"] > 500 * 1024 * 1024:
        erg.append(("Die App belegt viel Arbeitsspeicher", _mb(s["prozess"]), 2))
    if s["last"][1] > s["kerne"] * 0.9:
        erg.append(("Das System ist stark ausgelastet", f"Last (5 Min.) {s['last'][1]} bei {s['kerne']} Kernen", 1))
    return erg


def bericht_text(anzahl=12):
    """Zeilen für den Text zum Weitergeben (nur Zeiten und Mengen, keine Inhalte)."""
    ms, vorher = messungen()
    s = system()
    zeilen = [f"System: {s['kerne']} Kerne, RAM {_mb(s['ram_total'])} (frei {_mb(s['ram_frei'])}), App {_mb(s['prozess'])}, "
              f"Last {s['last'][0]}/{s['last'][1]}/{s['last'][2]}, Datenbank {_mb(s['db'])}, Dateien {_mb(s['dateien'])}, "
              f"Zwischenspeicher {_mb(s['cache'])}",
              "Datensätze: " + (", ".join(f"{t} {n}" for t, n in s["zeilen"].items() if n) or "keine")]
    for m in ms[:anzahl]:
        v = f" (vorher {m.vorher_ms:.0f})" if m.vorher_ms is not None else ""
        zeilen.append(f"{m.art} {m.name}: {m.anzahl}×, Ø {m.mittel_ms:.0f} ms{v}, max {m.max_ms:.0f} ms")
    if vorher:
        zeilen.append(f"Vergleich mit Version {vorher}")
    return zeilen


# ---------------------------------------------------------------- Karte auf der Seite «Vorschläge»

KARTE = """
<div class="card"><h2>Leistung</h2>
<div class="grid" style="margin-bottom:12px">
 <div class="kpi"><div class="t">{{ s.kerne }} Kerne</div><div class="v">{{ s.last[1] }}</div><div class="muted">Last 1/5/15 Min.: {{ s.last[0] }} / {{ s.last[1] }} / {{ s.last[2] }}</div></div>
 <div class="kpi"><div class="t">RAM frei</div><div class="v">{{ mb(s.ram_frei) }}</div><div class="muted">von {{ mb(s.ram_total) }}</div></div>
 <div class="kpi"><div class="t">Speicher der App</div><div class="v">{{ mb(s.prozess) }}</div><div class="muted">läuft seit {{ s.laufzeit_h }} h</div></div>
 <div class="kpi"><div class="t">Daten</div><div class="v">{{ mb(s.db + s.dateien) }}</div><div class="muted">Datenbank {{ mb(s.db) }}, Dateien {{ mb(s.dateien) }}</div></div>
</div>
{% if ms %}<details><summary>Ladezeiten und Rechenzeiten dieser Version ({{ ms|length }})</summary>
<div style="overflow-x:auto"><table><tr><th class="l">Was</th><th class="l">Art</th><th>Aufrufe</th><th>Ø</th><th>Längster</th><th>{{ "Ø " ~ vorher if vorher else "Vorversion" }}</th></tr>
{% for m in ms[:40] %}<tr><td class="l"><span class="ampel" style="background:{{ farbe(m) }}"></span>{{ m.name }}</td><td class="l">{{ arten.get(m.art, m.art) }}</td>
<td>{{ m.anzahl }}</td><td>{{ zeit(m.mittel_ms) }}</td><td>{{ zeit(m.max_ms) }}</td><td>{{ zeit(m.vorher_ms) if m.vorher_ms is not none else "" }}</td></tr>{% endfor %}
</table></div></details>{% else %}<p class="muted">Noch keine Messungen in dieser Version.</p>{% endif %}
{% if daten %}<p class="muted">Datensätze: {{ daten }}</p>{% endif %}
<p class="muted">Gemessen werden die Ladezeit jeder Seite und Aktion, die grossen Berechnungen (Berechnung aller Zähler,
Übersicht, Kontrollen, Rechnungen, Wärmepumpen, Prognose, Sensoren) und die Hintergrundaufgaben – pro Version, sortiert
nach der gesamten Zeit. Langsame Stellen erscheinen oben als Vorschlag im Bereich «Leistung»; die Messwerte (nur Zeiten
und Mengen) stehen auch im Text zum Weitergeben.</p>
<style>.ampel{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}</style></div>
"""


def karte():
    from flask import render_template_string
    ms, vorher = messungen()
    s = system()

    def zeit(v):
        return f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms" if v >= 1 else "< 1 ms"

    def farbe(m):
        grenze = LANGSAM_SEITE_MS if m.art in ("seite", "aktion") else LANGSAM_FUNKTION_MS
        return "#c0392b" if m.mittel_ms >= 2 * grenze else "#d4a017" if m.mittel_ms >= grenze else "#2e9e5b"
    daten = ", ".join(f"{t} {n:,}".replace(",", "'") for t, n in s["zeilen"].items() if n)
    return render_template_string(KARTE, ms=ms, vorher=vorher, s=s, mb=lambda b: f"{b / 1024 / 1024:,.0f} MB".replace(",", "'"),
                                  zeit=zeit, farbe=farbe, daten=daten,
                                  arten={"seite": "Seite", "aktion": "Aktion", "funktion": "Berechnung", "hintergrund": "Hintergrund"})


# ---------------------------------------------------------------- Einbindung

def _vor_anfrage():
    from flask import g
    g._leistung_t0 = time.perf_counter()


def _nach_anfrage(_fehler=None):
    from flask import g, request
    t0 = g.pop("_leistung_t0", None)
    if t0 is None or not request.endpoint or request.endpoint in NICHT_MESSEN:
        return
    erfassen("aktion" if request.method == "POST" else "seite", request.endpoint, (time.perf_counter() - t0) * 1000)


def hintergrund(intervall=900):
    def schleife():
        while True:
            time.sleep(intervall)
            try:
                sichern()
            except Exception as e:  # noqa: BLE001
                log.debug("Leistung nicht gesichert: %s", e)
    t = threading.Thread(target=schleife, name="leistung", daemon=True)
    t.start()
    return t


def register(app, server, starten=True):
    global S
    S = server
    app.before_request_funcs.setdefault(None, []).insert(0, _vor_anfrage)  # vor Zugriffsschutz und Warteseite
    app.teardown_request(_nach_anfrage)
    if starten:
        hintergrund()
