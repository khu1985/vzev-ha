"""Vorschau aus den Home-Assistant-Zählerständen für die Zeit nach dem letzten Primeo-Lastgang.

Grundlage sind die Zählerstände, die der Datensammler alle 15 Minuten speichert:
- 1. OG, 2. OG, Allgemein: whatwatt (total_increasing, kWh)
- Ladestation: go-e (total_increasing, kWh)
- PV-Anlage: Solis-Tageswerte PV-Ertrag + Batterie entladen − Batterie geladen (setzen um Mitternacht zurück).
  Ein negativer Wert gilt als Netzbezug der PV-Anlage (Standby).
Die Rechnung selbst ist dieselbe wie mit den Primeo-Lastgängen. Rechnungsgrundlage bleiben die Lastgänge;
sobald sie da sind, ersetzen sie die Vorschau.
"""
import numpy as np
import pandas as pd

import core

VIERTEL = pd.Timedelta(minutes=15)


def _deltas(werte, taeglich):
    """Verbrauch pro Viertelstunde aus Zählerständen; gehört zur Viertelstunde, in der der Stand abgelesen wurde."""
    w = werte.sort_index()
    d = w.diff().shift(-1)  # Differenz zum nächsten Stand gehört zur aktuellen Viertelstunde
    if taeglich:  # Tageswert: nach Mitternacht beginnt er wieder bei 0
        neu = w.shift(-1)
        d = d.where(d >= 0, neu)
    else:
        d = d.where(d >= 0)  # Zählerwechsel o. Ä. ignorieren
    return d.dropna()


def waermepumpen(cfg):
    """Konfigurierte Unterzähler am Allgemeinzähler: [{name, entity, faktor}]."""
    out = []
    for w in (cfg.get("homeassistant") or {}).get("waermepumpen") or []:
        if isinstance(w, dict) and w.get("entity"):
            out.append(dict(name=w.get("name") or w["entity"], entity=w["entity"], faktor=float(w.get("faktor") or 1.0)))
    return out


def verteilen(stand, max_luecke=16):
    """Zählerstände → kWh pro Viertelstunde. Fehlen Ablesungen, wird die Differenz gleichmässig auf die Viertelstunden
    dazwischen verteilt (bis 4 Stunden); längere Lücken und Rücksprünge (Zählerwechsel) werden nicht geschätzt."""
    stand = stand.sort_index()
    stand = stand[~stand.index.duplicated(keep="last")]
    if len(stand) < 2:
        return pd.Series(dtype=float)
    t = stand.index[:-1]
    n = np.maximum(1, np.round((stand.index[1:] - t) / VIERTEL).astype(int))
    diff = np.diff(stand.to_numpy())
    ok = (diff >= 0) & (n <= max_luecke)
    zeiten = np.concatenate([t[i] + np.arange(n[i]) * VIERTEL for i in np.flatnonzero(ok)]) if ok.any() else []
    werte = np.repeat(diff[ok] / n[ok], n[ok])
    return pd.Series(werte, index=pd.DatetimeIndex(zeiten)).groupby(level=0).sum()


def unterzaehler_einzeln(db, cfg, ab=None):
    """kWh pro Viertelstunde je Wärmepumpe (Zählerstand total_increasing × Faktor) als DataFrame, sonst None."""
    wps = waermepumpen(cfg)
    if not wps:
        return None
    ids = [w["entity"] for w in wps]
    q = f"SELECT ts, entity, wert FROM messwerte WHERE entity IN ({','.join('?' * len(ids))})" + (" AND ts >= ?" if ab else "")
    with db() as c:
        roh = pd.read_sql_query(q, c, params=ids + ([str(ab)] if ab else []))
    if roh.empty:
        return None
    roh["ts"] = pd.to_datetime(roh["ts"])
    tab = roh.pivot_table(index="ts", columns="entity", values="wert", aggfunc="last")
    with db() as c:
        einheit = dict(c.execute(f"SELECT entity, einheit FROM entitaeten WHERE entity IN ({','.join('?' * len(ids))})", ids).fetchall())
    spalten = {}
    for w in wps:
        if w["entity"] not in tab:
            continue
        spalten[w["name"]] = verteilen(tab[w["entity"]].dropna()) * w["faktor"] * (0.001 if einheit.get(w["entity"]) == "Wh" else 1.0)
    return pd.DataFrame(spalten).fillna(0.0) if spalten else None


def unterzaehler(db, cfg, ab=None):
    """Summe aller Wärmepumpen in kWh pro Viertelstunde (für core.compute), sonst None."""
    t = unterzaehler_einzeln(db, cfg, ab)
    return None if t is None else t.sum(axis=1)


def tarifmuster(res):
    """HT/NT nach Wochentag und Uhrzeit, so wie Primeo es in den Lastgängen verwendet."""
    if res is None or "tarif" not in res:
        return None
    t = res["tarif"].dropna()
    key = list(zip(t.index.dayofweek, t.index.hour, t.index.minute))
    return pd.Series(t.values, index=pd.MultiIndex.from_tuples(key)).groupby(level=[0, 1, 2]).agg(lambda x: x.value_counts().index[0])


def _tarif(index, muster):
    if muster is None:  # Rückfall: HT Mo–Fr 07–20 Uhr
        ht = (index.dayofweek < 5) & (index.hour >= 7) & (index.hour < 20)
        return pd.Series(np.where(ht, "HT", "NT"), index=index)
    key = list(zip(index.dayofweek, index.hour, index.minute))
    return pd.Series([muster.get(k, "NT") for k in key], index=index)


def berechnen(db, cfg, ab=None, res_primeo=None):
    """Gibt (res, info) zurück. res hat dieselben Spalten wie die Primeo-Berechnung, info beschreibt die Datenlage."""
    ha = cfg.get("homeassistant") or {}
    z, sol = ha.get("zaehler") or {}, ha.get("solis") or {}
    quellen = {"1OG": (z.get("1OG"), False), "2OG": (z.get("2OG"), False), "Allg": (z.get("Allg"), False),
               "EV": (z.get("ladestation"), False), "pv": (sol.get("pv_heute"), True),
               "ent": (sol.get("batterie_entladen_heute"), True), "gel": (sol.get("batterie_geladen_heute"), True)}
    ids = [e for e, _ in quellen.values() if e]
    info = {"fehlend": [k for k in ("1OG", "2OG", "Allg", "pv") if not quellen[k][0]], "ab": ab}
    if info["fehlend"]:
        return None, info
    with db() as c:
        roh = pd.read_sql_query(f"SELECT ts, entity, wert FROM messwerte WHERE entity IN ({','.join('?' * len(ids))})", c, params=ids)
    if roh.empty:
        info["fehlend"] = ["noch keine Zählerstände gespeichert"]
        return None, info
    roh["ts"] = pd.to_datetime(roh["ts"])
    tab = roh.pivot_table(index="ts", columns="entity", values="wert", aggfunc="last")
    spalten = {}
    for k, (e, taeglich) in quellen.items():
        if e and e in tab:
            spalten[k] = _deltas(tab[e].dropna(), taeglich)
    start = tab.index.min()
    if ab is not None:
        start = max(start, pd.Timestamp(ab))
    ende = tab.index.max() - VIERTEL  # die letzte Viertelstunde ist noch nicht abgeschlossen
    if ende < start:
        info["fehlend"] = ["noch zu wenige Zählerstände"]
        return None, info
    idx = pd.date_range(start.ceil("15min"), ende.floor("15min"), freq="15min")
    df = pd.DataFrame({k: s.reindex(idx) for k, s in spalten.items()}, index=idx)
    vorhanden = df[["1OG", "2OG", "Allg", "pv"]].notna().all(axis=1)
    info.update(von=idx.min(), bis=idx.max() + VIERTEL, viertelstunden=len(idx), abdeckung=float(vorhanden.mean()) if len(idx) else 0.0)
    df = df.fillna(0.0)
    for k in ("ent", "gel", "EV"):
        if k not in df:
            df[k] = 0.0
    anlage = df["pv"] + df["ent"] - df["gel"]
    df["Prod"] = anlage.clip(lower=0)
    df["PVA"] = (-anlage).clip(lower=0)
    df["tarif"] = _tarif(idx, tarifmuster(res_primeo))
    dyn = None
    try:
        import preise
        r = core.dyn_regeln(cfg)
        dyn = preise.serie(db, r["bonus_ab"]) if r["bonus"] else None
    except Exception:
        pass
    res = core.compute(df[["1OG", "2OG", "Allg", "PVA", "Prod", "tarif"]], None, cfg, ev=df["EV"], dyn=dyn,
                       wp=unterzaehler(db, cfg, start))
    res["ha_ok"] = vorhanden.values
    return res, info


def vergleich(res_ha, res_primeo):
    """Für den Zeitraum, in dem beides vorliegt: Summen aus Home Assistant und aus den Primeo-Lastgängen."""
    if res_ha is None or res_primeo is None:
        return []
    gemeinsam = res_ha.index[res_ha["ha_ok"]].intersection(res_primeo.index)  # nur Viertelstunden mit allen Zählerständen
    if len(gemeinsam) < 96:
        return []
    out = []
    for k, label in [("1OG", "1. OG"), ("2OG", "2. OG"), ("Allg", "Allgemein inkl. Ladestation"), ("Prod", "Produktion PV"), ("Export", "Rücklieferung")]:
        a, b = res_ha.loc[gemeinsam, k].sum(), res_primeo.loc[gemeinsam, k].sum()
        out.append(dict(zaehler=label, ha=a, primeo=b, diff=a - b, prozent=(a - b) / b * 100 if b else None))
    return out
