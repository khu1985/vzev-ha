"""Usability- und UX-Score (wie in der Finanz-App)."""
import types
from datetime import date, timedelta

import pytest

import usability as us
import ux


def test_pruefen_html():
    html = ("<main><div class='grid'>" + "<div class='kpi'>x</div>" * 8 + "</div>"
            + "<table class='wide'><tr>" + "<th>a</th>" * 9 + "</tr><tr><td>1</td></tr></table>"
            + "<form><input name='a'><input name='b' placeholder='B'><button>OK</button></form>"
            + "<svg></svg><svg aria-label='Diagramm'></svg>"
            + "<details><div class='card'></div>" * 0 + "</main>")
    titel = {p.titel for p in us.pruefen_html(html)}
    assert {"Viele Kennzahlen auf einmal", "Tabelle scrollt auf dem Handy seitlich", "Eingabefelder ohne Beschriftung",
            "Diagramme ohne Beschreibung"} <= titel
    assert us.pruefen_html("<main><div class='card'><p>kurz</p></div></main>") == []
    # zugeklappte Teile zählen nicht
    assert us.pruefen_html("<main><details>" + "<div class='card'></div>" * 20 + "</details></main>") == []


def test_kontrast_und_darstellung():
    assert us.kontrast("#000000", "#ffffff") == pytest.approx(21, abs=0.1)
    css = ":root{--ink:#16201C;--muted:#BBBBBB;--card:#ffffff;--bg:#F6F7F5}html[data-theme=dark]{--card:#1A211E;--ink:#E6EBE8}"
    p = us.darstellung(css)
    assert any("grauer Text auf Karten" in x.titel and "hell" in x.titel for x in p)


@pytest.fixture
def server(tmp_path, monkeypatch):
    s = types.SimpleNamespace(DATA=tmp_path, NAVIGATION=[("Überblick", [("./", "Energiefluss"), ("uebersicht", "Übersicht")]),
                                                         ("App", [("einstellungen", "Einstellungen")])],
                              _cache={}, RECHNEN={}, VERSION="9.9.9", config=lambda: {}, log=types.SimpleNamespace(info=print, warning=print, debug=print))
    monkeypatch.setattr(ux, "S", s)
    monkeypatch.setattr(us, "S", s)
    monkeypatch.setattr(ux, "_PUFFER", [])
    return s


def test_befragung_und_score(server, monkeypatch):
    import zahlungen
    monkeypatch.setattr(zahlungen, "uebersicht", lambda: {"n_ueberfaellig": 0})
    heute = date(2026, 11, 15)
    with pytest.raises(ValueError):
        ux.umfrage_speichern({"u0": "1"}, heute)
    antworten = {f"u{i}": "2" for i in range(4)} | {f"u{i}": "0" for i in range(4, 8)} | {"vertrauen": "5", "nutzen": "3"}
    ux.umfrage_speichern(antworten, heute)
    b = ux.befragung(heute)
    assert b.pragmatisch == 2 and b.hedonisch == 0 and b.vertrauen == 5
    assert b.score == round(((5 / 6) + 0.5 + 1 + 0.5) / 4 * 100)
    assert not ux.umfrage_faellig(heute) and ux.umfrage_faellig(heute + timedelta(days=90))
    # Verhalten: 14 Tage Aufrufe, 2 Formulare mit Fehler von 4
    for i in range(14):
        server_zeit = (heute - timedelta(days=i)).isoformat() + "T10:00:00"
        ux._PUFFER.append((server_zeit, "aufruf", "./"))
    ux._PUFFER += [(heute.isoformat() + "T11:00:00", a, "einstellungen") for a in ("ok", "fehler", "fehler", "ok")]
    ux.sichern()
    v = ux.verhalten(heute)
    assert v.tage == 14 and v.seiten_genutzt == 1 and v.formulare == 4 and v.eingabefehler == 2
    assert v.teile["Formulare ohne Fehler"] == 0.5
    e = ux.berechnen(heute)
    assert e.usability is None and e.score == round((b.score * 0.4 + v.score * 0.4) / 0.8)
    assert any("Eingabefehler" in t for t, _, _ in e.hinweise)
    assert any("nutzen" in t.lower() or "erleichtert" in t for t, _, _ in e.hinweise)   # Nutzen 3 von 5
