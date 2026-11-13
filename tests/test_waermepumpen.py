"""Wärmepumpen (Heizung, Warmwasser) als Unterzähler am Allgemeinzähler."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import core
import invoices
import vorschau
from test_speicher_bonus import _cfg


def _df():
    idx = pd.date_range("2026-11-02 00:00", periods=8, freq="15min")
    return pd.DataFrame({"1OG": 0.1, "2OG": 0.2, "Allg": [0.5, 0.5, 0.5, 0.5, 0.1, 0.1, 0.1, 0.1], "PVA": 0.0,
                         "Prod": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8], "tarif": "NT"}, index=idx)


def test_wp_aus_allgemein_herausgerechnet():
    df = _df()
    wp = pd.Series([0.3, 0.3, 0.3, 0.3, 0.3, 0.0, 0.0, 0.0], index=df.index)   # 5. Viertelstunde: mehr als Allgemein
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index), wp=wp)
    assert res["WP"].sum() == pytest.approx(1.5)            # Überschuss der 5. Viertelstunde eine davor/danach eingepasst
    assert res["WP_gemessen"].sum() == pytest.approx(1.5)
    assert res["AllgC"].sum() == pytest.approx(2.4 - 1.5)
    assert (res["WP"] <= res["Allg"] + 1e-12).all()
    # Energieerhaltung: alle Zähler zusammen = Primeo-Zähler
    k = res[[f"{a}_{z}" for z in core.ZAEHLER for a in ("S", "N", "P")]].sum(axis=1) - res["PVA"]
    assert k.sum() == pytest.approx((df["1OG"] + df["2OG"] + df["Allg"]).sum())
    # Solaranteil gleich wie bei allen Zählern
    assert res["S_WP"].iloc[7] == 0 and res["S_AllgC"].iloc[7] > 0
    rows = invoices.lines_for(res, _cfg(), "WP", date(2026, 11, 1), date(2026, 11, 30), grundpreis_ja=False)
    assert rows[0]["grundpreis"] == 0 and rows[0]["nt"] == pytest.approx(1.5)


def test_ohne_wp_unveraendert():
    df = _df()
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index))
    assert res["WP"].sum() == 0 and res["AllgC"].sum() == pytest.approx(df["Allg"].sum())


def test_wp_rechnung_nur_wenn_verbrauch():
    df = _df()
    cfg = _cfg()
    cfg["vzev_start"] = date(2026, 1, 1)
    res = core.compute(df, None, cfg, ev=pd.Series(0.0, index=df.index))
    assert [i["einheit"] for i in invoices.invoices_for_quarter(res, cfg, 2026, 4)] == ["1OG", "ALLG"]
    res = core.compute(df, None, cfg, ev=pd.Series(0.0, index=df.index), wp=pd.Series(0.2, index=df.index))
    assert [i["einheit"] for i in invoices.invoices_for_quarter(res, cfg, 2026, 4)] == ["1OG", "ALLG", "WP"]


def test_verteilen_ueber_luecken():
    st = pd.Series([10, 10.5, 11, 13, 13.2, 5.0, 5.1],
                   index=pd.to_datetime(["2026-11-08 10:00", "2026-11-08 10:15", "2026-11-08 10:30", "2026-11-08 11:30",
                                         "2026-11-08 11:45", "2026-11-08 12:00", "2026-11-09 12:00"]))
    v = vorschau.verteilen(st)
    assert v.loc["2026-11-08 10:30":"2026-11-08 11:15"].tolist() == [0.5] * 4    # Stunde Lücke: gleichmässig verteilt
    assert "2026-11-08 11:45" not in v.index                                       # Rücksprung (Zählerwechsel): nicht geschätzt
    assert v.sum() == pytest.approx(3.2)                                           # 24-h-Lücke: nicht geschätzt


def test_einzelne_waermepumpen():
    df = _df()
    cfg = _cfg()
    cfg["homeassistant"] = {"waermepumpen": [{"name": "Heizung", "entity": "sensor.a"}, {"name": "Warmwasser", "entity": "sensor.b"}]}
    wp = pd.DataFrame({"Heizung": 0.2, "Warmwasser": 0.1}, index=df.index)
    res = core.compute(df, None, cfg, ev=pd.Series(0.0, index=df.index), wp=wp)
    assert core.wp_namen(cfg) == [("WP1", "Heizung"), ("WP2", "Warmwasser")]
    for a in ("S", "N", "P"):
        assert (res[f"{a}_WP1"] + res[f"{a}_WP2"]).sum() == pytest.approx(res[f"{a}_WP"].sum())
    assert res["WP1"].sum() == pytest.approx(2 * res["WP2"].sum())
    assert res["WP2"].iloc[4] == pytest.approx(0.1 / 3)   # Viertelstunde mit gekapptem Wert: anteilig


def test_ladestation_laesst_platz_fuer_gemessene_wp():
    """Ladevorgänge sind nur als Summe bekannt: verteilt wird auf den Allgemeinstrom ohne die gemessene Wärmepumpe."""
    idx = pd.date_range("2026-11-02 00:00", periods=8, freq="15min")
    df = pd.DataFrame({"1OG": 0.1, "2OG": 0.1, "Allg": [2.0, 2.5, 2.5, 2.0, 2.0, 0.1, 0.1, 0.1], "PVA": 0.0,
                       "Prod": 0.0, "tarif": "NT"}, index=idx)
    wp = pd.Series([0.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0], index=idx)   # Wärmepumpe läuft während des Ladens
    lade = pd.DataFrame({"Start": [idx[0]], "Ende": [idx[4]], "kwh": [9.0]})
    cfg = _cfg()
    cfg["regeln"]["ladestation_grundlast_kwh"] = 0.0
    res = core.compute(df, lade, cfg, wp=wp)
    assert res["EV"].sum() == pytest.approx(9.0)        # Ladevorgang bleibt vollständig
    assert res["WP"].tolist() == pytest.approx(wp.tolist())  # Wärmepumpe in ihrer Viertelstunde, nichts verschoben
    assert (res["AllgC"] >= -1e-12).all()
