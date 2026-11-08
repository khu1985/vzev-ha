"""Speicher mit Netzladung (Speicher NT) und Bonus aus dem dynamischen Tarif (ab 2027)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import core
import invoices


def _cfg(**regeln):
    return {
        "regeln": {"ladestation_grundlast_kwh": 0.02, "allgemein_mieteranteil": 0.5,
                   "speicher_ab": "2027-01-01", "pva_standby_max_kwh": 0.05, "speicher_wirkungsgrad": 0.9, **regeln},
        "tarife": {"solar": [{"ab": date(2026, 1, 1), "chf": 0.238}],
                   "netz": [{"ab": date(2026, 1, 1), "ht": 0.34, "nt": 0.27}],
                   "ruecklieferung": [{"ab": date(2026, 1, 1), "chf": 0.08}],
                   "grundpreis_zaehler": [{"ab": date(2026, 1, 1), "chf": 8.25}]},
        "mietverhaeltnisse": [{"einheit": "1OG", "name": "Test", "von": date(2026, 1, 1), "bis": None}],
        "dynamisch": {"bonus": True, "bonus_ab": "2027-01-01", "konzession_prozent": 4.1, "mwst_prozent": 8.1},
        "vzev_start": date(2026, 1, 1),
    }


def _df(start):
    """4 Viertelstunden: 1) Speicher lädt 1 kWh aus dem Netz (Standby 0.05), 2) Speicher liefert 0.5 kWh an 1OG,
    3) PV liefert 1 kWh an 1OG (davon 0.4 noch aus dem Netzvorrat), 4) nur Netzbezug 1OG."""
    idx = pd.date_range(start, periods=4, freq="15min")
    return pd.DataFrame({"1OG": [0.0, 0.5, 1.0, 2.0], "2OG": 0.0, "Allg": 0.0, "PVA": [1.05, 0, 0, 0],
                         "Prod": [0.0, 0.5, 1.0, 0.0], "tarif": ["NT", "NT", "HT", "HT"]}, index=idx)


def test_speicher_fifo():
    out = core.speicher_fifo(np.array([1.0, 0, 0, 0]), np.array([0, 0.5, 1.0, 0]), 0.9)
    assert list(np.round(out, 3)) == [0, 0.5, 0.4, 0]


def test_netzladung_ab_2027():
    res = core.compute(_df("2027-01-05 00:00"), None, _cfg(), ev=pd.Series(0.0, index=_df("2027-01-05").index))
    assert res["Laden"].sum() == pytest.approx(1.0)
    assert res["N_AllgC"].sum() == pytest.approx(0.05)          # nur Standby im Allgemeinstrom
    assert res["P_1OG"].sum() == pytest.approx(0.9)             # 0.5 + 0.4 Netzstrom aus Speicher
    assert res["S_1OG"].sum() == pytest.approx(0.6)             # echter Solarstrom
    assert res["N_1OG"].sum() == pytest.approx(2.0)
    netz = core.abgleich(res.assign(), {"primeo_rechnungen": [{"nr": 1, "von": "2027-01-05", "bis": "2027-01-05",
                                                              "netz_ht": 2.0, "netz_nt": 1.05, "ruecklieferung": []}]})
    assert netz["ok"].all()                                      # Netzladung zählt beim Abgleich mit


def test_vor_2027_unveraendert():
    df = _df("2026-06-05 00:00")
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index))
    assert res["Laden"].sum() == 0 and res["P_1OG"].sum() == 0
    assert res["N_AllgC"].sum() == pytest.approx(1.05)
    assert res["B_1OG"].sum() == 0


def test_bonus_und_rechnung():
    df = _df("2027-01-05 00:00")
    dyn = pd.DataFrame({"integrated": 0.20, "grid_usage": 0.10}, index=df.index)
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index), dyn=dyn)
    preis = (0.20 + 0.041 * 0.10) * 1.081
    assert res["dynprice"].iloc[0] == pytest.approx(preis)
    assert res["B_1OG"].sum() == pytest.approx(2.0 * (0.34 - preis))   # nur direkter Netzbezug
    rows = invoices.lines_for(res, _cfg(), "1OG", date(2027, 1, 1), date(2027, 1, 31))
    r = rows[0]
    assert r["speicher"] == pytest.approx(0.9) and r["speicher_chf"] == pytest.approx(round(0.9 * 0.238, 2))
    assert r["bonus"] == pytest.approx(round(2.0 * (0.34 - preis), 2))
    assert r["total"] == pytest.approx(round(r["solar_chf"] + r["netz_chf"] + r["speicher_chf"] + r["grundpreis"] - r["bonus"], 2))


def test_bonus_nie_negativ_und_ohne_preis_null():
    df = _df("2027-01-05 00:00")
    teuer = pd.DataFrame({"integrated": 0.60, "grid_usage": 0.0}, index=df.index)
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index), dyn=teuer)
    assert invoices.lines_for(res, _cfg(), "1OG", date(2027, 1, 1), date(2027, 1, 31))[0]["bonus"] == 0
    res = core.compute(df, None, _cfg(), ev=pd.Series(0.0, index=df.index), dyn=None)
    r = invoices.lines_for(res, _cfg(), "1OG", date(2027, 1, 1), date(2027, 1, 31))[0]
    assert r["bonus"] == 0 and r["dyn_fehlt"] == 1


def test_pdf_mit_speicher_und_bonus(tmp_path):
    df = _df("2027-01-05 00:00")
    dyn = pd.DataFrame({"integrated": 0.20, "grid_usage": 0.10}, index=df.index)
    cfg = _cfg()
    cfg["betreiber"] = {"name": "Test", "strasse": "Weg", "hausnr": "1", "plz": "9999", "ort": "Ort", "bank": "B",
                        "iban": "CH9300762011623852957"}
    cfg["rechnungen"] = {"zahlungsfrist_tage": 30, "nummer": "{jahr}-Q{quartal}-{einheit}"}
    res = core.compute(df, None, cfg, ev=pd.Series(0.0, index=df.index), dyn=dyn)
    rows = invoices.lines_for(res, cfg, "AllgC", date(2027, 1, 1), date(2027, 1, 31))
    total = invoices.render_jahr(tmp_path / "j.pdf", cfg, rows, 2027, date(2027, 1, 1), date(2027, 1, 31), True)
    assert (tmp_path / "j.pdf").stat().st_size > 1000
    assert total == pytest.approx(sum(r["total"] for r in rows))
