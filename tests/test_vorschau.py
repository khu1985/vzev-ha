"""Vorschau aus Home-Assistant-Zählerständen."""
import sqlite3

import pandas as pd
import pytest

import core
import daten
import vorschau


def test_deltas_zaehler_und_tageswerte():
    idx = pd.date_range("2026-11-01 23:00", periods=6, freq="15min")
    total = pd.Series([10.0, 10.5, 11.0, 11.0, 12.0, 12.5], index=idx)
    d = vorschau._deltas(total, taeglich=False)
    assert list(d.round(3)) == [0.5, 0.5, 0.0, 1.0, 0.5]
    tag = pd.Series([3.0, 3.4, 3.8, 4.0, 0.0, 0.3], index=idx)  # Reset um Mitternacht
    d = vorschau._deltas(tag, taeglich=True)
    assert list(d.round(3)) == [0.4, 0.4, 0.2, 0.0, 0.3]


def test_negativer_zaehlersprung_wird_ignoriert():
    idx = pd.date_range("2026-11-01", periods=4, freq="15min")
    d = vorschau._deltas(pd.Series([10.0, 10.5, 2.0, 2.5], index=idx), taeglich=False)
    assert list(d.round(3)) == [0.5, 0.5]


def _db(tmp_path, cfg, idx, res):
    db = tmp_path / "m.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE messwerte (ts TEXT, entity TEXT, wert REAL, PRIMARY KEY (ts, entity))")
    z, sol = cfg["homeassistant"]["zaehler"], cfg["homeassistant"]["solis"]
    quellen = {z["1OG"]: res["1OG"], z["2OG"]: res["2OG"], z["Allg"]: res["Allg"], z["ladestation"]: res["EV"]}
    for ent, s in quellen.items():
        stand = 100.0
        for ts in idx:
            c.execute("INSERT INTO messwerte VALUES (?,?,?)", (ts.isoformat(timespec="minutes"), ent, stand))
            stand += float(s.get(ts, 0.0))
    for ent in (sol["pv_heute"],):
        for tag, g in res["Prod"].groupby(res.index.date):
            stand = 0.0
            for ts, v in g.items():
                c.execute("INSERT INTO messwerte VALUES (?,?,?)", (ts.isoformat(timespec="minutes"), ent, stand))
                stand += v
    for ent in (sol["batterie_geladen_heute"], sol["batterie_entladen_heute"]):
        for ts in idx:
            c.execute("INSERT INTO messwerte VALUES (?,?,?)", (ts.isoformat(timespec="minutes"), ent, 0.0))
    c.commit()
    return lambda: sqlite3.connect(db)


def test_vorschau_stimmt_mit_lastgaengen_ueberein(ergebnis, tmp_path):
    cfg, res, *_ = ergebnis
    teil = res.loc["2026-04-02":"2026-04-12"]  # mit Ladetag
    db = _db(tmp_path, cfg, teil.index, teil)
    res_v, info = vorschau.berechnen(db, cfg, None, res)
    assert info["abdeckung"] > 0.95
    v = vorschau.vergleich(res_v, res)
    for zeile in v:
        if zeile["zaehler"] != "Produktion PV":  # Tageswert am Tagesende wird erst nach Mitternacht gelesen
            assert abs(zeile["diff"]) < 0.5, zeile


def test_tarifmuster_aus_lastgaengen(ergebnis):
    _, res, *_ = ergebnis
    m = vorschau.tarifmuster(res)
    assert m[(0, 12, 0)] == "HT" and m[(6, 12, 0)] == "NT" and m[(2, 3, 0)] == "NT"
