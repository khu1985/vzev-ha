"""Datensammler: speichert alle 15 Minuten die Zählerstände aus Home Assistant und holt evcc-Ladevorgänge.

Home Assistant speichert Detaildaten nur rund 10 Tage; deshalb legt die App die Zählerstände selbst ab.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import requests

SUPERVISOR = "http://supervisor/core/api"
log = logging.getLogger("vzev")


def _zahl(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _zeit(x):
    """evcc-Zeitstempel (ISO mit Zeitzone) in lokale Zeit ohne Zeitzone."""
    if not x or str(x).startswith("0001"):
        return None
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


class Collector:
    def __init__(self, db_path, get_config):
        self.db_path = db_path
        self.get_config = get_config
        self.last_run = None
        self.last_error = None
        self.evcc_status = "noch nicht abgefragt"
        self.aktiv = None          # was gerade im Hintergrund läuft (für die Statusanzeige)
        self.naechster = None      # nächster Abruf der Zählerstände
        self.evcc_naechster = None
        self._init_db()

    # --- Speicher ------------------------------------------------------
    def _db(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def _init_db(self):
        with self._db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS messwerte (ts TEXT, entity TEXT, wert REAL, PRIMARY KEY (ts, entity))")
            c.execute("CREATE TABLE IF NOT EXISTS entitaeten (entity TEXT PRIMARY KEY, name TEXT, einheit TEXT, zustand TEXT, geprueft TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS evcc_sessions (id TEXT PRIMARY KEY, daten TEXT, abgerufen TEXT)")

    # --- Home Assistant ------------------------------------------------
    def _ha(self):
        cfg = self.get_config().get("homeassistant", {})
        token = os.environ.get("SUPERVISOR_TOKEN")
        if token:
            return SUPERVISOR, token
        return cfg.get("url", "").rstrip("/") + "/api", cfg.get("token")

    def entities(self):
        ha = self.get_config().get("homeassistant", {})
        ids = list((ha.get("zaehler") or {}).values())
        ids += [v for k, v in (ha.get("solis") or {}).items() if v and v.startswith("sensor.")]
        ids += [v for v in (ha.get("kia") or {}).values() if v]
        return sorted(set(ids))

    def read_now(self):
        self.aktiv = "Zählerstände abrufen"
        try:
            return self._read_now()
        finally:
            self.aktiv = None

    def _read_now(self):
        base, token = self._ha()
        if not token:
            raise RuntimeError("Kein Zugang zu Home Assistant (läuft die App im HA?)")
        ts = datetime.now().replace(second=0, microsecond=0)
        ts = ts - timedelta(minutes=ts.minute % 15)
        rows, fehlt, meta = [], [], []
        jetzt = datetime.now().isoformat(timespec="seconds")
        for eid in self.entities():
            r = requests.get(f"{base}/states/{eid}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if r.status_code != 200:
                fehlt.append(f"{eid} (HTTP {r.status_code})")
                continue
            j = r.json()
            attr = j.get("attributes") or {}
            meta.append((eid, attr.get("friendly_name"), attr.get("unit_of_measurement"), str(j.get("state")), jetzt))
            try:
                rows.append((ts.isoformat(timespec="minutes"), eid, float(j["state"])))
            except (ValueError, KeyError, TypeError):
                fehlt.append(f"{eid} ({j.get('state')})")  # unavailable/unknown
        meldung = ", ".join(fehlt)
        if meldung != getattr(self, "_fehlt", ""):  # nur Änderungen protokollieren
            if fehlt:
                log.warning("Datensammler: keine Werte für %s", meldung)
            elif getattr(self, "_fehlt", None):
                log.info("Datensammler: alle Entitäten liefern wieder Werte")
            self._fehlt = meldung
        with self._db() as c:
            c.executemany("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", rows)
            c.executemany("INSERT OR REPLACE INTO entitaeten VALUES (?, ?, ?, ?, ?)", meta)
        if self.last_run is None:
            log.info("Datensammler: erster Abruf, %d von %d Entitäten gespeichert", len(rows), len(self.entities()))
        self.last_run = ts
        return len(rows)

    # --- evcc ----------------------------------------------------------
    def fetch_evcc(self):
        self.aktiv = "evcc-Ladevorgänge abrufen"
        try:
            return self._fetch_evcc()
        finally:
            self.aktiv = None

    def _fetch_evcc(self):
        ev = self.get_config().get("evcc") or {}
        if not ev.get("url"):
            self.evcc_status = "nicht konfiguriert"
            return
        s = requests.Session()
        pw = os.environ.get("EVCC_PASSWORD")
        if pw:
            s.post(ev["url"].rstrip("/") + "/api/auth/login", json={"password": pw}, timeout=10)
        r = s.get(ev["url"].rstrip("/") + ev.get("sessions", "/api/sessions"), timeout=15)
        if r.status_code in (401, 403):
            if not self.evcc_status.startswith("Anmeldung"):
                log.warning("evcc: Anmeldung nötig – evcc-Passwort in den App-Optionen eintragen")
            self.evcc_status = "Anmeldung nötig – evcc-Passwort in den App-Optionen eintragen"
            return
        r.raise_for_status()
        data = r.json()
        data = data.get("result", data) if isinstance(data, dict) else data
        now = datetime.now().isoformat(timespec="seconds")
        with self._db() as c:
            for sess in data or []:
                sid = str(sess.get("id") or f"{sess.get('created')}_{sess.get('loadpoint')}")
                c.execute("INSERT OR REPLACE INTO evcc_sessions VALUES (?, ?, ?)", (sid, json.dumps(sess), now))
        if not self.evcc_status[:1].isdigit():
            log.info("evcc: %d Ladevorgänge abgerufen", len(data or []))
        self.evcc_status = f"{len(data or [])} Ladevorgänge abgerufen ({now[:16].replace('T', ' ')})"

    def sessions(self):
        """evcc-Ladevorgänge aufbereitet, neueste zuerst."""
        with self._db() as c:
            roh = [json.loads(d) for (d,) in c.execute("SELECT daten FROM evcc_sessions")]
        out = []
        for s in roh:
            start = _zeit(s.get("created"))
            if start is None:
                continue
            dauer = s.get("chargeDuration")
            if isinstance(dauer, (int, float)) and dauer > 1e7:  # evcc liefert Nanosekunden
                dauer = dauer / 1e9
            kwh = _zahl(s.get("chargedEnergy"))
            if kwh is None and _zahl(s.get("meterStop")) is not None and _zahl(s.get("meterStart")) is not None:
                kwh = _zahl(s.get("meterStop")) - _zahl(s.get("meterStart"))
            out.append(dict(start=start, ende=_zeit(s.get("finished")), ladepunkt=s.get("loadpoint") or "",
                            fahrzeug=s.get("vehicle") or s.get("identifier") or "", kwh=kwh,
                            dauer_min=(dauer / 60) if isinstance(dauer, (int, float)) else None,
                            solar=_zahl(s.get("solarPercentage")), preis=_zahl(s.get("price")),
                            preis_kwh=_zahl(s.get("pricePerKWh")), km=_zahl(s.get("odometer"))))
        return sorted(out, key=lambda s: s["start"], reverse=True)

    # --- Status --------------------------------------------------------
    def status(self):
        with self._db() as c:
            n, first, last = c.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM messwerte").fetchone()
            # SQLite liefert bei MAX() die übrigen Spalten aus derselben Zeile, also den letzten Wert
            per = {e: (n, ts, w) for e, n, ts, w in c.execute("SELECT entity, COUNT(*), MAX(ts), wert FROM messwerte GROUP BY entity")}
            meta = {r[0]: r[1:] for r in c.execute("SELECT * FROM entitaeten")}
            ns = c.execute("SELECT COUNT(*) FROM evcc_sessions").fetchone()[0]
        zweck = {}
        ha = self.get_config().get("homeassistant", {})
        for gruppe in ("zaehler", "solis", "kia"):
            for k, v in (ha.get(gruppe) or {}).items():
                if v:
                    zweck.setdefault(v, f"{gruppe} · {k}")
        zeilen = []
        for e in self.entities():
            anzahl, zeit, wert = per.get(e, (0, None, None))
            name, einheit, zustand, geprueft = meta.get(e, (None, None, None, None))
            zeilen.append(dict(entity=e, zweck=zweck.get(e, ""), name=name, einheit=einheit or "", anzahl=anzahl,
                               zeit=zeit, wert=wert, zustand=zustand, geprueft=geprueft,
                               ok=zustand is not None and wert is not None and zustand not in ("unavailable", "unknown")))
        reihenfolge = {"zaehler": 0, "solis": 1, "kia": 2}
        zeilen.sort(key=lambda z: (reihenfolge.get(z["zweck"].split(" · ")[0], 3), z["zweck"], z["entity"]))
        return {"anzahl": n, "erster": first, "letzter": last, "zeilen": zeilen, "evcc_sessions": ns,
                "evcc_status": self.evcc_status, "fehler": self.last_error}

    # --- Schleife ------------------------------------------------------
    def loop(self):
        tick = 0
        while True:
            try:
                self.read_now()
                self.last_error = None
            except Exception as e:  # weiterlaufen, Fehler anzeigen
                if self.last_error is None or str(e) not in self.last_error:
                    log.error("Datensammler: %s", e)
                self.last_error = f"{datetime.now():%d.%m. %H:%M}: {e}"
            if tick % 4 == 0:
                try:
                    self.fetch_evcc()
                except Exception as e:
                    if self.evcc_status != f"Fehler: {e}":
                        log.error("evcc: %s", e)
                    self.evcc_status = f"Fehler: {e}"
            tick += 1
            now = datetime.now()
            nxt = (now.replace(second=5, microsecond=0) + timedelta(minutes=15 - now.minute % 15))
            if (nxt - now).total_seconds() < 30:
                nxt = now + timedelta(seconds=30)
            self.naechster = nxt
            self.evcc_naechster = nxt + timedelta(minutes=15 * ((4 - tick % 4) % 4))
            time.sleep((nxt - now).total_seconds())

    def start(self):
        threading.Thread(target=self.loop, daemon=True).start()
