"""Sensoren für Home Assistant: Kennzahlen der vZEV-App als `sensor.vzev_*` (und `binary_sensor.vzev_*`).

Wie in der Finanz-App: Die App schreibt die Zustände über die REST-API von Home Assistant (Supervisor,
`homeassistant_api`). Solche Zustände überstehen keinen Neustart von Home Assistant; die App schreibt sie deshalb
beim Start, alle 15 Minuten und nach einer neuen Berechnung neu. Für Verlauf und Statistik genügt das.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
import requests

log = logging.getLogger("vzev")
S = None
_letzter = {"zeit": None, "anzahl": 0, "fehler": "", "werte": [], "bereich_fehler": {}}
_ausloeser = threading.Event()
MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


@dataclass
class Sensor:
    schluessel: str
    name: str
    zustand: object
    einheit: str = ""
    geraeteklasse: str = ""
    zustandsklasse: str = ""
    symbol: str = "mdi:solar-power-variant"
    attribute: dict = field(default_factory=dict)
    art: str = "sensor"

    def entity_id(self, praefix):
        return f"{self.art}.{praefix}_{self.schluessel}"

    def nutzlast(self):
        attr = {"friendly_name": f"vZEV {self.name}", "icon": self.symbol, **self.attribute}
        if self.einheit:
            attr["unit_of_measurement"] = self.einheit
        if self.geraeteklasse:
            attr["device_class"] = self.geraeteklasse
        if self.zustandsklasse:
            attr["state_class"] = self.zustandsklasse
        return {"state": "unknown" if self.zustand is None else str(self.zustand), "attributes": attr}


def _mit_zone(t):
    """Lokale Zeit (Schweiz) mit UTC-Versatz, unabhängig von der Zeitzone des Containers."""
    import preise
    from datetime import timezone
    return t.replace(tzinfo=timezone(preise.offset(t.date()))).isoformat()


def _r(x, n=1):
    return None if x is None or pd.isna(x) else round(float(x), n)


def berechnen(heute=None):
    """Alle Sensoren aus der aktuellen Berechnung (Primeo + Vorschau), Zahlungen, Aufgaben, Prognose und Preisen."""
    import uebersicht
    heute = heute or date.today()
    s = []
    _letzter["bereich_fehler"] = {}

    def sicher(fn):
        try:
            fn()
        except Exception as e:  # ein fehlerhafter Bereich darf die übrigen Sensoren nicht verhindern
            _letzter["bereich_fehler"][fn.__name__] = f"{type(e).__name__}: {e}"
            log.warning("Sensoren «%s» übersprungen: %s", fn.__name__, e)

    d = uebersicht.daten()
    res, cfg = d["res"], d["cfg"]

    def energie():
        if res is None:
            return
        mon = uebersicht.monate(res)
        p = pd.Period(heute, "M")
        jahr = mon[[x.year == heute.year for x in mon.index]]
        if p in mon.index:
            m = mon.loc[p]
            s.append(Sensor("produktion_monat", "Produktion Monat", _r(m["produktion"]), "kWh", "energy", "total", "mdi:solar-power",
                            {"monat": f"{MONATE[p.month]} {p.year}", "vorlaeufig": bool(m["vorlaeufig"])}))
            s.append(Sensor("autarkie_monat", "Autarkie Monat", _r(m["autarkie"]), "%", "", "measurement", "mdi:home-lightning-bolt"))
            s.append(Sensor("ruecklieferung_monat", "Rücklieferung Monat", _r(m["export"]), "kWh", "energy", "total", "mdi:transmission-tower-export"))
        if len(jahr):
            sol, verb = float(jahr["solar"].sum()), float(jahr["verbrauch"].sum())
            s.append(Sensor("produktion_jahr", "Produktion Jahr", _r(jahr["produktion"].sum(), 0), "kWh", "energy", "total", "mdi:solar-power",
                            {"jahr": heute.year, "bis": str(res.index.max())}))
            s.append(Sensor("autarkie_jahr", "Autarkie Jahr", _r(sol / verb * 100 if verb else None), "%", "", "measurement", "mdi:home-lightning-bolt",
                            {"solar_kwh": round(sol), "verbrauch_kwh": round(verb)}))
            s.append(Sensor("ruecklieferung_jahr", "Rücklieferung Jahr", _r(jahr["export"].sum(), 0), "kWh", "energy", "total",
                            "mdi:transmission-tower-export"))
    sicher(energie)

    def wert():
        if not d["b"].get("ok"):
            return
        import core
        w = core.wertschoepfung(res, cfg)
        wj = w[[x.year == heute.year for x in w.index]]
        s.append(Sensor("wertschoepfung_jahr", "Wertschöpfung Jahr", _r(wj["total_chf"].sum(), 2), "CHF", "monetary", "total", "mdi:cash-plus",
                        {k: _r(wj[k].sum(), 2) for k in ("mieter_chf", "eigen_chf", "export_chf") if k in wj}))
        p = pd.Period(heute, "M")
        if p in w.index:
            s.append(Sensor("wertschoepfung_monat", "Wertschöpfung Monat", _r(w.loc[p, "total_chf"], 2), "CHF", "monetary", "total", "mdi:cash-plus"))
    sicher(wert)

    def rechnungen():
        import core
        import zahlungen
        z = zahlungen.uebersicht()
        offen = [r for r in z["zeilen"] if r["stand"] in ("offen", "teilweise", "überfällig")]
        s.append(Sensor("offene_rechnungen", "Offene Rechnungen", _r(z["offen"], 2), "CHF", "monetary", "total", "mdi:receipt-text-clock",
                        {"anzahl": len(offen), "liste": [{"nummer": r["nummer"], "partei": core.vorname(S.config(), r["partei"]), "offen": r["offen"],
                                                          "faellig": r["faellig"], "stand": r["stand"]} for r in offen[:10]]}))
        s.append(Sensor("ueberfaellig", "Überfällige Rechnungen", z["n_ueberfaellig"], "", "", "measurement", "mdi:alert-circle",
                        {"betrag": z["ueberfaellig"]}))
    sicher(rechnungen)

    def jaz():
        import re
        import vorschau
        for name, j in vorschau.jaz(S.collector._db, cfg, date(heute.year, 1, 1), heute).items():
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")).strip("_")
            s.append(Sensor(f"jaz_{slug}", f"Jahresarbeitszahl {name}", _r(j["jaz"], 2), "", "", "measurement", "mdi:heat-pump",
                            {"strom_kwh": round(j["strom"], 1), "waerme_kwh": round(j["waerme"], 1), "jahr": heute.year}))
    sicher(jaz)

    def aufgaben():
        import aufgaben as af
        n = af.naechste()
        _, abschluss, _, _, offen, _ = af.stand(heute)
        s.append(Sensor("naechste_aufgabe", "Nächste Aufgabe", (n[0][:250] if n else "keine"), "", "", "", "mdi:clipboard-check-outline",
                        {"offene_monate": [str(p) for p in offen]}))
        s.append(Sensor("offene_monate", "Offene Monate", len(offen), "", "", "measurement", "mdi:calendar-alert"))
    sicher(aufgaben)

    def prognose():
        import prognose as pg
        h, m = pg.kurz(S.collector._db)
        if h is not None or m is not None:
            s.append(Sensor("pv_prognose_heute", "PV-Prognose heute", _r(h), "kWh", "energy", "", "mdi:weather-sunny"))
            s.append(Sensor("pv_prognose_morgen", "PV-Prognose morgen", _r(m), "kWh", "energy", "", "mdi:weather-partly-cloudy"))
    sicher(prognose)

    def strompreis():
        import prognose as pg
        db = S.collector._db
        jetzt = datetime.now()
        minute = jetzt.hour * 60 + jetzt.minute // 15 * 15
        heute_p = pg.preise_tag(db, cfg, heute)
        if not heute_p:
            return
        aktuell = next((v for m, v in reversed(heute_p) if m <= minute), None)
        s.append(Sensor("strompreis", "Strompreis dynamisch", _r(aktuell, 2), "Rp./kWh", "", "measurement", "mdi:currency-chf",
                        {"inkl": "Konzessionsabgabe und MWST", "tief_heute": _r(min(v for _, v in heute_p), 2),
                         "hoch_heute": _r(max(v for _, v in heute_p), 2)}))
        # Ladefenster heute (ab jetzt) und morgen
        verbrauch = pg.ueblicher_verbrauch(db, cfg, heute)
        fenster = []
        for tag in (heute, heute + timedelta(days=1)):
            pv = [(t.hour * 60 + t.minute, mi, k50, k10, k90) for t, mi, k50, k10, k90 in pg.tag(db, tag)]
            for f in pg.ladefenster(pv, verbrauch, pg.preise_tag(db, cfg, tag)):
                von = datetime.combine(tag, datetime.min.time()) + timedelta(minutes=f["von_m"])
                bis = datetime.combine(tag, datetime.min.time()) + timedelta(minutes=f["bis_m"])
                if bis > jetzt:
                    fenster.append(dict(von=von, bis=bis, preis=round(f["preis"], 2), fehlt_kwh=round(f["fehlt"], 1)))
        n = fenster[0] if fenster else None
        jetzt_drin = bool(n and n["von"] <= jetzt < n["bis"])
        s.append(Sensor("guenstig_laden", "Günstig aus dem Netz laden", "on" if jetzt_drin else "off", "", "", "", "mdi:battery-charging",
                        {"bis": n["bis"].isoformat() if jetzt_drin else None, "preis": n["preis"] if jetzt_drin else None},
                        art="binary_sensor"))
        s.append(Sensor("naechstes_ladefenster", "Nächstes Ladefenster", _mit_zone(n["von"]) if n else None, "", "timestamp", "",
                        "mdi:clock-start", {"bis": n["bis"].isoformat() if n else None, "preis": n["preis"] if n else None,
                                            "fehlt_kwh": n["fehlt_kwh"] if n else None,
                                            "fenster": [{"von": f["von"].isoformat(), "bis": f["bis"].isoformat(), "preis": f["preis"]} for f in fenster[:8]]}))
    sicher(strompreis)
    return s


# ---------------------------------------------------------------- Schreiben

def einstellungen(cfg):
    c = cfg.get("sensoren") or {}
    praefix = str(c.get("praefix") or "vzev").strip().lower().replace(" ", "_").replace("-", "_")
    return bool(c.get("aktiv", True)), praefix


def _senden_ha(entity_id, nutzlast):
    base, token = S.collector._ha()
    if not token:
        raise RuntimeError("Kein Zugriff auf Home Assistant (Token fehlt)")
    r = requests.post(f"{base}/states/{entity_id}", json=nutzlast, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    r.raise_for_status()


def schreiben(senden=None, heute=None):
    aktiv, praefix = einstellungen(S.config())
    if not aktiv:
        _letzter.update(zeit=datetime.now().isoformat(timespec="seconds"), anzahl=0, fehler="ausgeschaltet", werte=[])
        return []
    senden = senden or _senden_ha
    werte = berechnen(heute)
    fehler = ""
    for x in werte:
        try:
            senden(x.entity_id(praefix), x.nutzlast())
        except Exception as e:
            fehler = str(e)
            break
    _letzter.update(zeit=datetime.now().isoformat(timespec="seconds"), anzahl=0 if fehler else len(werte), fehler=fehler,
                    werte=[(x.entity_id(praefix), x.nutzlast()["state"], x.einheit) for x in werte])
    if fehler:
        # Home Assistant startet neu (502 Bad Gateway, keine Verbindung): erst melden, wenn es auch beim nächsten Mal scheitert
        seit = _letzter.setdefault("fehler_seit", time.time())
        if _letzter.get("gemeldet") != fehler and time.time() - seit >= 600:
            log.warning("Sensoren nicht geschrieben: %s", fehler)
            _letzter["gemeldet"] = fehler
    else:
        _letzter.pop("fehler_seit", None)
        if _letzter.get("gemeldet") is not None or not _letzter.get("einmal"):
            log.info("%d Sensoren an Home Assistant geschrieben (%s_*)", len(werte), praefix)
        _letzter.update(gemeldet=None, einmal=True)
    return werte


def status():
    return dict(_letzter)


def aktualisieren():
    """Nach einer Änderung oder neuen Berechnung: Sensoren im Hintergrund neu schreiben."""
    _ausloeser.set()


def hintergrund(intervall=900):
    def schleife():
        time.sleep(20)
        while True:
            try:
                schreiben()
            except Exception as e:
                log.warning("Sensoren: %s", e)
            _ausloeser.wait(intervall)
            _ausloeser.clear()
            time.sleep(2)

    t = threading.Thread(target=schleife, name="sensoren", daemon=True)
    t.start()
    return t


def register(app, server, starten=True):
    global S
    S = server
    if starten:
        hintergrund()
