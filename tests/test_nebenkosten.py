"""Nebenkostenabrechnung: Verteilung nach Fläche, Personen und Wärme, Tage, Honorar, Akonto, PDF und Register."""
import types
from datetime import date

import pytest

import nebenkosten as nk

CFG = {
    "messpunkte": {"CH1": "1OG", "CH2": "2OG", "CH3": "Allg"},
    "vzev_start": date(2026, 3, 1),
    "betreiber": {"name": "Test Betreiber", "strasse": "Musterweg", "hausnr": "1", "plz": "9999", "ort": "Musterhausen",
                  "iban": "CH9300762011623852957", "bank": "Musterbank"},
    "rechnungen": {"zahlungsfrist_tage": 30},
    "mietverhaeltnisse": [
        {"einheit": "1OG", "name": "Erika Muster", "von": date(2026, 8, 1), "bis": None,
         "strasse": "Musterweg", "hausnr": "1", "plz": "9999", "ort": "Musterhausen"},
    ],
}


@pytest.fixture
def server(tmp_path, monkeypatch):
    (tmp_path / "rechnungen").mkdir()
    s = types.SimpleNamespace(DATA=tmp_path, RECHNUNGEN=tmp_path / "rechnungen",
                              log=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))
    monkeypatch.setattr(nk, "S", s)
    d = nk.laden()
    d["einstellungen"]["einheiten"] = {"1OG": {"flaeche": 90}, "2OG": {"flaeche": 110, "personen_ohne_mieter": 2}}
    d["einstellungen"]["mieter"] = {"1OG|2026-08-01": {"personen": 2, "akonto": 180}}
    per = nk.periode_daten(d, "2026-27")
    per["positionen"] = [
        {"titel": "Wasser", "kategorie": "wasser", "betrag": 730.0},
        {"titel": "Kehricht", "kategorie": "flaeche", "betrag": 400.0},
        {"titel": "Wartung Heizung", "kategorie": "heizung", "betrag": 1000.0},
        {"titel": "Einstellplatz", "kategorie": "direkt", "betrag": 120.0, "einheit": "1OG"},
    ]
    per["waerme"] = {"gesamt": {"start": 1000, "ende": 11000}, "1OG": {"start": 0, "ende": 4000}}
    nk.speichern(d)
    return s


def test_periode():
    assert nk.periode_grenzen("2026-27") == (date(2026, 7, 1), date(2027, 6, 30))
    assert nk.periode_name(date(2026, 7, 1)) == "2026-27"
    assert nk._monate(date(2026, 8, 1), date(2027, 6, 30)) == 11
    assert nk._monate(date(2026, 8, 15), date(2027, 6, 30)) == 10
    assert nk.perioden(CFG, heute=date(2027, 7, 2)) == ["2027-28", "2026-27", "2025-26"]


def test_verteilung(server):
    e = nk.abrechnen(CFG, None, "2026-27", heute=date(2027, 7, 15))
    ab = e["abschnitte"]
    # 1OG: Juli Leerstand (Vermieter), ab 1.8. Mieter; 2OG ganz Vermieter
    assert [(a.einheit, a.mieter is not None, a.tage) for a in ab] == [("1OG", False, 31), ("1OG", True, 334), ("2OG", False, 365)]
    assert e["verteilt"] == pytest.approx(e["kosten"], abs=0.05)
    m = ab[1]
    z = {x["titel"]: x["betrag"] for x in m.zeilen}
    # Wasser nach Personentagen: 2×334 von 2×334 + 2×365
    assert z["Wasser"] == pytest.approx(730 * 668 / (668 + 730), abs=0.01)
    # Kehricht nach m², 334 von 365 Tagen
    assert z["Kehricht"] == pytest.approx(400 * 90 / 200 * 334 / 365, abs=0.01)
    # Heizung: 30 % nach m², 70 % nach Wärme (1OG 4000 von 10000 kWh)
    assert z["Wartung Heizung"] == pytest.approx(1000 * (0.3 * 0.45 + 0.7 * 0.4) * 334 / 365, abs=0.01)
    assert z["Einstellplatz"] == pytest.approx(120 * 334 / 365, abs=0.01)
    assert m.honorar == pytest.approx(round(m.summe * 0.03, 2))
    assert m.monate == 11 and m.akonto_total == 1980
    assert m.saldo == pytest.approx(round(m.summe + m.honorar - 1980, 2))
    assert not [h for h in e["hinweise"] if "Personen" in h or "Akonto" in h or "Fläche" in h]


def test_ohne_waerme_nach_flaeche(server):
    d = nk.laden()
    d["perioden"]["2026-27"]["waerme"] = {}
    e = nk.abrechnen(CFG, None, "2026-27", d)
    assert any("Heizung vorläufig ganz nach m²" in h for h in e["hinweise"])
    z = {x["titel"]: x["betrag"] for x in e["abschnitte"][1].zeilen}
    assert z["Wartung Heizung"] == pytest.approx(1000 * 0.45 * 334 / 365, abs=0.01)


def test_honorar_betrag(server):
    d = nk.laden()
    d["einstellungen"].update(honorar_art="betrag", honorar_wert=100)
    e = nk.abrechnen(CFG, None, "2026-27", d)
    assert e["abschnitte"][1].honorar == pytest.approx(100 * 0.45 * 334 / 365, abs=0.01)


def test_pdf_und_register(server, monkeypatch):
    import zahlungen
    reg = {"rechnungen": {}}
    monkeypatch.setattr(zahlungen, "laden", lambda: reg)
    monkeypatch.setattr(zahlungen, "speichern", lambda r: None)
    d = nk.laden()
    d["perioden"]["2026-27"]["positionen"].append({"titel": "Hauswart", "kategorie": "flaeche", "betrag": 6000.0})
    nk.speichern(d)
    made = nk.erstellen(CFG, None, "2026-27", date(2027, 7, 20))
    (name, saldo, a), = made
    assert name == "Rechnung_NK-2026-27-1OG_Muster.pdf" and saldo > 0
    pdf = (server.RECHNUNGEN / "NK-2026-27" / name).read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
    (r,) = reg["rechnungen"].values()
    assert r["art"] == "nebenkosten" and r["quartal"] == "NK-2026-27" and r["betrag"] == pytest.approx(saldo)
    assert zahlungen._reihenfolge("NK-2026-27") == 20272 and zahlungen._reihenfolge("2026-Q3") == 20263


def test_guthaben_nicht_ins_register(server, monkeypatch):
    import zahlungen
    reg = {"rechnungen": {}}
    monkeypatch.setattr(zahlungen, "laden", lambda: reg)
    monkeypatch.setattr(zahlungen, "speichern", lambda r: None)
    (_, saldo, _), = nk.erstellen(CFG, None, "2026-27", date(2027, 7, 20))
    assert saldo < 0 and not reg["rechnungen"]   # Kosten < Akonto: Guthaben, keine Forderung
