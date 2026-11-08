"""Rechnungsregister und Zahlungseingang."""
from datetime import date, timedelta

import zahlungen


def test_stand_berechnung():
    heute = date(2026, 5, 10)
    r = {"art": "wohnung", "betrag": 100.0, "status": "aktiv", "faellig": "2026-05-05", "zahlungen": []}
    assert zahlungen.stand(r, heute)["stand"] == "überfällig"
    r["faellig"] = "2026-06-01"
    assert zahlungen.stand(r, heute)["stand"] == "offen"
    r["zahlungen"] = [{"betrag": 40.0}]
    s = zahlungen.stand(r, heute)
    assert s["stand"] == "teilweise" and s["offen"] == 60.0
    r["zahlungen"].append({"betrag": 60.0})
    assert zahlungen.stand(r, heute)["stand"] == "bezahlt"
    r["zahlungen"].append({"betrag": 5.0})
    assert zahlungen.stand(r, heute)["stand"] == "überzahlt"
    assert zahlungen.stand(dict(r, art="allgemein"), heute)["stand"] == "intern"
    assert zahlungen.stand(dict(r, status="ersetzt"), heute)["stand"] == "ersetzt"


def test_dateiname_zerlegen():
    assert zahlungen._meta("Rechnung_2026-Q3-1OG_Alessio.pdf") == ("2026-Q3-1OG", "Alessio", "wohnung")
    assert zahlungen._meta("Rechnung_2026-Q3-ALLG_Allgemeinstrom.pdf") == ("2026-Q3-ALLG", "Allgemeinstrom", "allgemein")
