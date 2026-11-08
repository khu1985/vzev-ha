"""Rechenkern: Einlesen, Ladestation, 15-Minuten-Aufteilung, Tarife, Wertschöpfung."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import core
import daten


# --- Einlesen ----------------------------------------------------------------
def test_kopf_messpunkt(ordner):
    mp, lieferstelle = core.read_header(ordner / "primeo" / "1OG.xlsx")
    assert mp == daten.MP["1OG"]
    assert "Testdorf" in lieferstelle


@pytest.mark.parametrize("variante", [
    {}, {"text_datum": True}, {"summenzeile": True}, {"zeit_als_datetime": True},
    {"text_datum": True, "summenzeile": True, "zeit_als_datetime": True},
])
def test_lastgang_formate(tmp_path, variante):
    p = tmp_path / "x.xlsx"
    daten.lastgang_xlsx(p, "1OG", **variante)
    s, mp, _ = core.read_lastgang(p)
    erwartet = daten.viertelstunden()
    assert mp == daten.MP["1OG"]
    assert len(s) == len(erwartet)
    assert s.index.min() == erwartet.min() and s.index.max() == erwartet.max()
    assert s["kwh"].sum() == pytest.approx(0.1 * len(erwartet))
    assert not s["kwh"].isna().any()


def test_sommerzeit_luecke(ordner):
    s, _, _ = core.read_lastgang(ordner / "primeo" / "Prod.xlsx")
    tag = s.loc["2026-03-29"]
    assert len(tag) == 92 and not ((tag.index.hour == 2).any())


def test_winterzeit_doppelte_viertelstunden(tmp_path):
    p = tmp_path / "w.xlsx"
    daten.lastgang_xlsx(p, "1OG")
    import openpyxl
    wb = openpyxl.load_workbook(p)
    ws = wb["Lastgang"]
    # 02:00 eines Tages doppelt anhängen (wie bei der Umstellung auf Winterzeit)
    for r in range(10, ws.max_row + 1):
        if ws.cell(r, 2).value.hour == 2 and ws.cell(r, 2).value.minute == 0:
            ws.append([ws.cell(r, 1).value, ws.cell(r, 2).value, 0.5, "NT"])
            break
    wb.save(p)
    s, _, _ = core.read_lastgang(p)
    assert not s.index.has_duplicates
    assert s["kwh"].sum() == pytest.approx(0.1 * len(daten.viertelstunden()) + 0.5)


@pytest.mark.parametrize("sekunden", [True, False])
def test_wallbox_mit_und_ohne_sekunden(tmp_path, sekunden):
    d = daten.datenordner(tmp_path)
    daten.wallbox_csv(d / "primeo" / "Ladestation.csv", sekunden=sekunden)
    cfg, res, files, lade, ev = core.run(d / "primeo", d / "vzev.yaml")
    assert len(lade) == 4
    assert lade["kwh"].sum() == pytest.approx(12.0)
    assert res["EV"].sum() == pytest.approx(12.0, abs=0.01)
    assert ev < 0.01


def test_wallbox_unlesbar_bricht_ab(tmp_path):
    d = daten.datenordner(tmp_path)
    p = d / "primeo" / "Ladestation.csv"
    p.write_text(p.read_text().replace("10.03.2026", "kein Datum").replace("10.04.2026", "kein Datum"))
    with pytest.raises(ValueError, match="Ladevorgänge"):
        core.run(d / "primeo", d / "vzev.yaml")


def test_fehlender_lastgang_nennt_zaehler(tmp_path):
    d = daten.datenordner(tmp_path)
    (d / "primeo" / "PVA.xlsx").unlink()
    with pytest.raises(ValueError, match="PVA"):
        core.run(d / "primeo", d / "vzev.yaml")


def test_unbekannter_messpunkt_wird_gemeldet(tmp_path):
    d = daten.datenordner(tmp_path)
    (d / "primeo" / "Prod.xlsx").rename(d / "primeo" / "fremd.xlsx")
    import yaml
    cfg = yaml.safe_load((d / "vzev.yaml").read_text())
    del cfg["messpunkte"][daten.MP["Prod"]]
    (d / "vzev.yaml").write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match="keinem Zähler zugeordnet"):
        core.run(d / "primeo", d / "vzev.yaml")


# --- Aufteilung ----------------------------------------------------------------
def test_ladestation_vollstaendig_und_im_ladefenster(ergebnis):
    cfg, res, files, lade, ev = ergebnis
    assert res["EV"].sum() == pytest.approx(12.0, abs=0.01)
    ausserhalb = res["EV"][~((res.index.day == 10) & res.index.hour.isin([12, 22]))]
    assert ausserhalb.sum() == pytest.approx(0, abs=1e-9)


def test_allgemeinstrom_ohne_ladestation_mit_standby(ergebnis):
    _, res, *_ = ergebnis
    assert np.allclose(res["AllgC"], res["Allg"] - res["EV"])
    assert res["AllgC"].sum() == pytest.approx(0.1 * len(res), abs=0.01)
    # Standby der PV-Anlage ist reiner Netzbezug und landet beim Allgemeinstrom
    assert res["N_AllgC"].sum() - (res["AllgC"] - res["S_AllgC"]).sum() == pytest.approx(res["PVA"].sum())


def test_energieerhaltung_pro_viertelstunde(ergebnis):
    _, res, *_ = ergebnis
    zaehler = ["1OG", "2OG", "AllgC", "EV"]
    verbrauch = sum(res[k] for k in zaehler)
    solar = sum(res[f"S_{k}"] for k in zaehler)
    netz = sum(res[f"N_{k}"] for k in zaehler)
    assert np.allclose(solar + netz, verbrauch + res["PVA"])
    assert np.allclose(solar, np.minimum(res["Prod"], verbrauch))
    assert np.allclose(res["Export"], np.maximum(res["Prod"] - verbrauch, 0))


def test_tagsueber_solar_nachts_netz(ergebnis):
    _, res, *_ = ergebnis
    tag = res[(res.index.hour >= 8) & (res.index.hour < 16)]
    nacht = res[(res.index.hour < 8) | (res.index.hour >= 16)]
    assert tag["N_1OG"].sum() == pytest.approx(0)
    assert nacht["S_1OG"].sum() == pytest.approx(0)
    s = core.zaehler_summen(res, "EV")
    assert s["solar"].sum() == pytest.approx(8.0, abs=0.01)   # Mittagsladungen
    assert (s["ht"] + s["nt"]).sum() == pytest.approx(4.0, abs=0.01)  # Abendladungen


def test_ht_nt_nach_tarifspalte(ergebnis):
    _, res, *_ = ergebnis
    s = core.zaehler_summen(res, "2OG")
    nacht = res[(res.index.hour < 8) | (res.index.hour >= 16)]
    ht = sum(0.2 for ts in nacht.index if daten.ht(ts))
    assert s["ht"].sum() == pytest.approx(ht)
    assert s["nt"].sum() == pytest.approx(0.2 * len(nacht) - ht)


def test_kosten_mit_tarifen(ergebnis):
    _, res, *_ = ergebnis
    s = core.zaehler_summen(res, "2OG")
    assert s["solar_chf"].sum() == pytest.approx(s["solar"].sum() * 0.20)
    assert s["netz_chf"].sum() == pytest.approx(s["ht"].sum() * 0.30 + s["nt"].sum() * 0.25)


# --- Mietverhältnisse und Wertschöpfung ----------------------------------------
def test_belegung_mit_leerstand(ergebnis):
    _, res, *_ = ergebnis
    occ = res["occ_1OG"]
    assert occ.loc["2026-03-20"].eq(1).all()
    assert occ.loc["2026-03-21":"2026-04-09"].eq(0).all()
    assert occ.loc["2026-04-10"].eq(1).all()


def test_wertschoepfung_leerstand_ist_eigenverbrauch(ergebnis):
    cfg, res, *_ = ergebnis
    w = core.wertschoepfung(res, cfg)
    leer = res.loc["2026-03-21":"2026-04-09"]
    assert leer["S_1OG"].sum() > 0
    # Verkauf an Mieter nur in belegten Zeiten
    belegt = res[res["occ_1OG"] > 0]
    erwartet = (belegt["S_1OG"].sum() + 0.5 * belegt["S_AllgC"].sum()) * 0.20
    assert w["mieter_chf"].sum() == pytest.approx(erwartet, rel=1e-6)


def test_ruecklieferung_mit_tarifwechsel(ergebnis):
    cfg, res, *_ = ergebnis
    w = core.wertschoepfung(res, cfg)
    maerz = res.loc["2026-03"]["Export"].sum()
    april = res.loc["2026-04"]["Export"].sum()
    assert w.loc[pd.Period("2026-03", "M"), "export_chf"] == pytest.approx(maerz * 0.10)
    assert w.loc[pd.Period("2026-04", "M"), "export_chf"] == pytest.approx(april * 0.06)


def test_unbekannter_rueckliefertarif_bleibt_offen(tmp_path):
    d = daten.datenordner(tmp_path)
    daten.konfiguration(d / "vzev.yaml", ruecklieferung_april=None)
    cfg, res, *_ = core.run(d / "primeo", d / "vzev.yaml")
    w = core.wertschoepfung(res, cfg)
    assert pd.isna(w.loc[pd.Period("2026-04", "M"), "export_chf"])
    assert not pd.isna(w.loc[pd.Period("2026-03", "M"), "export_chf"])


def test_abgleich_mit_primeo_rechnung(tmp_path):
    d = daten.datenordner(tmp_path)
    cfg, res, *_ = core.run(d / "primeo", d / "vzev.yaml")
    m = res.loc["2026-03"]
    ht = round(sum(m[f"N_{k}"][m["tarif"] == "HT"].sum() for k in ["1OG", "2OG", "AllgC", "EV"]))
    nt = round(sum(m[f"N_{k}"][m["tarif"] != "HT"].sum() for k in ["1OG", "2OG", "AllgC", "EV"]))
    cfg["primeo_rechnungen"] = [{"nr": "T1", "von": date(2026, 3, 1), "bis": date(2026, 3, 31), "netz_ht": ht, "netz_nt": nt,
                                 "ruecklieferung": [[date(2026, 3, 1), date(2026, 3, 31), round(m["Export"].sum())]]}]
    a = core.abgleich(res, cfg)
    assert a["ok"].all(), a
    cfg["primeo_rechnungen"][0]["netz_ht"] = ht + 5
    assert not core.abgleich(res, cfg)["ok"].all()
