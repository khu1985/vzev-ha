"""Dynamische Strompreise (Primeo Dynamisch / NetzDynamisch) abrufen und speichern.

Schnittstelle laut Merkblatt Primeo NetzDynamisch:
    GET {api_url}?start_timestamp=…&end_timestamp=…&tariff_type=…&tariff_name=…
    Zeitstempel ISO 8601 mit Zeitzone (z. B. 2027-01-01T00:00:00+01:00), Preise pro Viertelstunde in CHF/kWh,
    veröffentlicht täglich bis 18 Uhr für den nächsten Tag.
    Antwort: {"publication_timestamp": …, "tariff_name": …, "prices": [{"start_timestamp": …, "end_timestamp": …,
              "<typ>": [{"unit": "CHF_kWh", "value": 0.0503}], …}, …]}
Nicht enthalten: kantonale/kommunale Abgaben und MWST; die rechnet die Abrechnung dazu.

Adresse, Tarifname und Tariftyp stehen in vzev.yaml (Abschnitt «dynamisch») und lassen sich auf der Seite
«Batterie» ändern.
"""
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger("vzev")

STANDARD = {
    "api_url": "https://tarife.primeo-energie.ch/api/v1/tariffs",
    "tarif_name": "NetzDynamisch",
    "tarif_typ": "",          # leer = alle Typen (grid, grid_usage, electricity, integrated)
    "abrufen_ab": "2027-01-01",
    "aktiv": True,
}
TYPEN = ["integrated", "electricity", "grid", "grid_usage"]


def einstellungen(cfg):
    e = dict(STANDARD)
    e.update({k: v for k, v in (cfg.get("dynamisch") or {}).items() if v not in (None, "")})
    alt = (cfg.get("batterie") or {}).get("preis_api")  # frühere Einstellung auf der Batterie-Seite
    if alt and not (cfg.get("dynamisch") or {}).get("api_url"):
        e["api_url"] = alt
    return e


# --- Zeitzone Schweiz ohne zusätzliche Pakete --------------------------------
def _letzter_sonntag(jahr, monat):
    d = date(jahr, monat + 1, 1) - timedelta(days=1) if monat < 12 else date(jahr, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def offset(d):
    """UTC-Versatz der Schweiz am Tagesbeginn (00:00 Lokalzeit): +1 h Winter, +2 h Sommer."""
    sommer = _letzter_sonntag(d.year, 3) < d <= _letzter_sonntag(d.year, 10)
    return timedelta(hours=2 if sommer else 1)


def tag_grenzen(d):
    """Start und Ende eines lokalen Tages als ISO-Zeitstempel mit Versatz."""
    def iso(x):
        o = offset(x)
        return datetime(x.year, x.month, x.day, tzinfo=timezone(o)).isoformat()
    return iso(d), iso(d + timedelta(days=1))


# --- Speicher -----------------------------------------------------------------
def init(db):
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS preise (
            start_utc TEXT, typ TEXT, start_lokal TEXT, ende_lokal TEXT, chf_kwh REAL,
            publiziert TEXT, abgerufen TEXT, PRIMARY KEY (start_utc, typ))""")
        c.execute("CREATE INDEX IF NOT EXISTS preise_abgerufen ON preise (abgerufen)")


def _utc(ts):
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes")


def _lokal(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None).isoformat(timespec="minutes")


def zerlegen(daten):
    """JSON der Schnittstelle → Zeilen (start_utc, typ, start_lokal, ende_lokal, chf_kwh, publiziert)."""
    pub = daten.get("publication_timestamp")
    zeilen = []
    for p in daten.get("prices") or []:
        s, e = p.get("start_timestamp"), p.get("end_timestamp")
        if not s:
            continue
        for typ, werte in p.items():
            if typ in ("start_timestamp", "end_timestamp") or not isinstance(werte, list):
                continue
            for w in werte:
                if isinstance(w, dict) and w.get("value") is not None and str(w.get("unit", "CHF_kWh")).upper().startswith("CHF"):
                    wert = float(w["value"])
                    if "RP" in str(w.get("unit", "")).upper():
                        wert /= 100
                    zeilen.append((_utc(s), typ, _lokal(s), _lokal(e) if e else None, wert, pub))
    return zeilen


def abrufen_tag(db, e, d, session=None):
    """Preise eines Tages holen und speichern; gibt die Anzahl Viertelstunden zurück."""
    start, ende = tag_grenzen(d)
    params = {"start_timestamp": start, "end_timestamp": ende, "tariff_name": e["tarif_name"]}
    if e.get("tarif_typ"):
        params["tariff_type"] = e["tarif_typ"]
    r = (session or requests).get(e["api_url"], params=params, timeout=20)
    r.raise_for_status()
    zeilen = zerlegen(r.json())
    jetzt = datetime.now().isoformat(timespec="seconds")
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO preise VALUES (?, ?, ?, ?, ?, ?, ?)", [z + (jetzt,) for z in zeilen])
    return len({z[0] for z in zeilen})


def vorhandene_tage(db, typ=None):
    with db() as c:
        q = "SELECT substr(start_lokal, 1, 10), COUNT(DISTINCT start_utc) FROM preise"
        rows = c.execute(q + (" WHERE typ=?" if typ else "") + " GROUP BY 1", ((typ,) if typ else ())).fetchall()
    return {d: n for d, n in rows}


class Preisabruf:
    def __init__(self, db, get_config):
        self.db = db
        self.get_config = get_config
        self.status = "noch nicht abgerufen"
        self.letzter = None
        self.fehler = None
        init(db)
        tage = sorted(vorhandene_tage(db))
        if tage:
            self.status = f"{len(tage)} Tag(e) gespeichert, bis {tage[-1][8:10]}.{tage[-1][5:7]}.{tage[-1][:4]}"

    def faellige_tage(self, jetzt=None, max_tage=31):
        jetzt = jetzt or datetime.now()
        e = einstellungen(self.get_config())
        ab = date.fromisoformat(str(e["abrufen_ab"])[:10])
        bis = jetzt.date() + (timedelta(days=1) if jetzt.hour >= 18 else timedelta(0))
        vorhanden = vorhandene_tage(self.db)
        tage, d = [], max(ab, bis - timedelta(days=max_tage - 1))
        while d <= bis:
            if vorhanden.get(d.isoformat(), 0) < 92:  # 92–100 Viertelstunden je nach Zeitumstellung
                tage.append(d)
            d += timedelta(days=1)
        return tage

    def abrufen(self, tage=None):
        e = einstellungen(self.get_config())
        if not e.get("aktiv"):
            self.status = "ausgeschaltet"
            return 0
        tage = self.faellige_tage() if tage is None else tage
        if not tage:
            self.status = "aktuell"
            return 0
        s, n, leer = requests.Session(), 0, []
        try:
            for d in tage:
                k = abrufen_tag(self.db, e, d, s)
                n += k
                if not k:
                    leer.append(d)
            self.fehler = None
        except Exception as ex:
            if self.fehler != str(ex):
                log.error("Strompreise: %s", ex)
            self.fehler = str(ex)
            self.status = f"Fehler: {ex}"
            return n
        self.letzter = datetime.now()
        self.status = f"{n} Viertelstunden für {len(tage) - len(leer)} Tag(e) gespeichert" + (
            f"; noch keine Preise für {', '.join(d.strftime('%d.%m.') for d in leer)}" if leer else "")
        if n:
            log.info("Strompreise: %s", self.status)
        return n


def tag(db, d, typ):
    """Viertelstundenpreise eines lokalen Tages: Liste (start_lokal, chf_kwh)."""
    with db() as c:
        return c.execute("SELECT start_lokal, chf_kwh FROM preise WHERE typ=? AND substr(start_lokal,1,10)=? ORDER BY start_utc",
                         (typ, d.isoformat())).fetchall()


def typen_vorhanden(db):
    with db() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT typ FROM preise")]


def verbinden(pfad):
    return lambda: sqlite3.connect(pfad, timeout=30)


def serie(db, ab=None):
    """Gespeicherte Preise als Tabelle: Index = Viertelstunde Lokalzeit (wie die Lastgänge), Spalten je Tariftyp."""
    import pandas as pd
    with db() as c:
        rows = c.execute("SELECT start_lokal, typ, chf_kwh FROM preise" + (" WHERE start_lokal >= ?" if ab else ""),
                         ((str(ab),) if ab else ())).fetchall()
    if not rows:
        return None
    t = pd.DataFrame(rows, columns=["zeit", "typ", "chf"])
    t["zeit"] = pd.to_datetime(t["zeit"])
    return t.groupby(["zeit", "typ"])["chf"].first().unstack("typ")


def stand(db):
    """Kurzer Schlüssel, der sich ändert, sobald neue Preise gespeichert werden (für den Rechen-Zwischenspeicher)."""
    try:
        with db() as c:
            return tuple(c.execute("SELECT COUNT(*), MAX(abgerufen) FROM preise").fetchone())
    except Exception:
        return (0, None)
