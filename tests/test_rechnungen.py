"""Quartalsrechnungen: Aufteilung nach Mietverhältnis, Grundpreis anteilig, QR-Einzahlungsschein."""
from datetime import date

import pytest

import core
import invoices


def test_rechnungen_pro_mietverhaeltnis_und_allgemein(ergebnis):
    cfg, res, *_ = ergebnis
    rech = invoices.invoices_for_quarter(res, cfg, 2026, 1)
    assert [(r["art"], r["partei"]["name"] if r["partei"] else None) for r in rech] == [
        ("wohnung", "Erika Muster"), ("allgemein", None)]
    erika = rech[0]
    assert erika["von"] == date(2026, 3, 1) and erika["bis"] == date(2026, 3, 20)
    rech2 = invoices.invoices_for_quarter(res, cfg, 2026, 2)
    assert [r["partei"]["name"] for r in rech2 if r["partei"]] == ["Max Beispiel"]
    assert rech2[0]["von"] == date(2026, 4, 10)


def test_grundpreis_anteilig_nach_miettagen(ergebnis):
    cfg, res, *_ = ergebnis
    erika = invoices.invoices_for_quarter(res, cfg, 2026, 1)[0]
    gp = sum(r["grundpreis"] for r in erika["rows"])
    assert gp == pytest.approx(8.25 * 20 / 31, abs=0.01)


def test_wohnungsbetrag_aus_kwh_und_tarifen(ergebnis):
    cfg, res, *_ = ergebnis
    erika = invoices.invoices_for_quarter(res, cfg, 2026, 1)[0]
    teil = res.loc["2026-03-01":"2026-03-20"]
    solar = teil["S_1OG"].sum() * 0.20
    netz = (teil["N_1OG"] * teil["price"]).sum()
    total = sum(r["total"] for r in erika["rows"])
    assert total == pytest.approx(solar + netz + 8.25 * 20 / 31, abs=0.02)


def test_allgemeinstrom_ohne_ladestation(ergebnis):
    cfg, res, *_ = ergebnis
    allg = invoices.invoices_for_quarter(res, cfg, 2026, 1)[-1]
    kwh = sum(r["solar"] + r["ht"] + r["nt"] for r in allg["rows"])
    maerz = res.loc["2026-03"]
    assert kwh == pytest.approx(maerz["AllgC"].sum() + maerz["PVA"].sum(), abs=0.01)
    assert kwh < maerz["Allg"].sum() + maerz["PVA"].sum() - 5  # 6 kWh Ladestation sind draussen


def test_qr_daten_nach_standard(ergebnis):
    cfg, res, *_ = ergebnis
    erika = invoices.invoices_for_quarter(res, cfg, 2026, 1)[0]
    zeilen = invoices.qr_payload(cfg, erika, 12.3, "2026-Q1-1OG").split("\r\n")
    assert zeilen[:3] == ["SPC", "0200", "1"]
    assert zeilen[3] == cfg["betreiber"]["iban"]
    assert zeilen[18:20] == ["12.30", "CHF"]
    assert "NON" in zeilen and zeilen[-1] == "EPD"
    assert len(zeilen) == 31


def test_pdfs_werden_erstellt(ordner, tmp_path):
    made = invoices.main(ordner / "primeo", 2026, 1, tmp_path, "2026-04-05", ordner / "vzev.yaml")
    assert len(made) == 2
    for name, total, rows in made:
        p = tmp_path / name
        assert p.exists() and p.read_bytes()[:4] == b"%PDF" and p.stat().st_size > 5000
        assert total > 0
