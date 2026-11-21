"""Vorschläge: Anonymisierung (nichts Persönliches im Text zum Weitergeben)."""
import vorschlaege as vs


CFG = {"betreiber": {"name": "Hans Müller-Brand", "strasse": "Lindenweg", "ort": "Musterhausen", "bank": "Musterbank",
                     "iban": "CH93 0076 2011 6238 5295 7", "email": "hans@example.ch"},
       "mietverhaeltnisse": [{"name": "Nora Testerin", "strasse": "Lindenweg", "ort": "Musterhausen"}],
       "messpunkte": {"CH1234567890123456789012345678901": "1OG"},
       "evcc": {"url": "http://192.168.1.50:7070", "passwort": "geheim123"}}


def test_anonymisieren():
    p = vs.private_texte(CFG)
    t = vs.anonymisieren(
        "Rechnung für Nora Testerin, Lindenweg 5, 9999 Musterhausen: CHF 123.45 am 05.10.2026 (2026-Q3), "
        "Messpunkt CH1234567890123456789012345678901, IBAN CH93 0076 2011 6238 5295 7, Mail hans@example.ch, "
        "Sensor sensor.buderus_gateway_100000001_energie, evcc http://192.168.1.50:7070 Passwort geheim123, Müller-Brand", p)
    for geheim in ("Nora", "Testerin", "Lindenweg", "Musterhausen", "123.45", "05.10.2026", "2026-Q3", "CH1234567890",
                   "CH93", "hans@", "100000001", "192.168", "geheim123", "Müller"):
        assert geheim not in t, (geheim, t)
    assert "sensor.buderus_gateway_" in t and "Rechnung für" in t   # Sinn bleibt erkennbar


def test_normalisieren_gruppiert():
    a = vs._normalisieren("Lastgang 1OG.xlsx nicht lesbar: Zeile 17 falsch")
    b = vs._normalisieren("Lastgang 2OG.xlsx nicht lesbar: Zeile 23 falsch")
    assert a.replace("1OG", "") == b.replace("2OG", "") or "#" in a
    tb = 'Seite fehlgeschlagen\nTraceback (most recent call last):\n  File "/app/uebersicht.py", line 42, in index\nKeyError: \'x\''
    assert vs._normalisieren(tb).endswith("KeyError in uebersicht.py:index")


def test_bericht_und_issue():
    v = [vs.Vorschlag("Kontrollen", "«Abgleich mit Primeo» stimmt nicht", "Hinweis", 3, vs.HOCH)]
    t = vs.bericht(v, "0.16.0")
    assert "### Kontrollen" in t and "- [hoch] «Abgleich mit Primeo» stimmt nicht (3×) – Hinweis" in t
    assert vs.issue_link(t, "0.16.0").startswith("https://github.com/khu1985/vzev-ha/issues/new?title=")


def test_verlauf_erledigt(tmp_path, monkeypatch):
    """Wie in der Finanz-App: was nicht mehr vorkommt, wird abgehakt; nach einem Update erst nach einem Tag."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    monkeypatch.setattr(vs, "S", SimpleNamespace(DATA=tmp_path))
    langsam = vs.Vorschlag("Leistung", "Berechnung «jahr.daten» ist langsam", "Ø 2389 ms")
    label = vs.Vorschlag("Usability", "Seite «Datensammler»: Eingabefelder ohne Beschriftung", "1 Feld")
    sensor = vs.Vorschlag("Datensammler", "Sensor ohne Werte", "")
    idee = vs.Vorschlag("Eigene Ideen", "Dunkles Design", "")
    t0 = datetime(2026, 11, 21, 12, 0)
    vs.verlauf_nachfuehren([langsam, label, sensor, idee], "0.20.2", t0)
    # gleiche Version: Sensor liefert wieder Werte → durch Änderung erledigt
    vs.verlauf_nachfuehren([langsam, label], "0.20.2", t0 + timedelta(hours=1))
    e = vs.erledigt()
    assert [(x["titel"], x["durch"]) for x in e] == [("Sensor ohne Werte", "aenderung")]
    # Update auf 0.20.3: direkt nach dem Start fehlt alles – noch nichts abhaken
    vs.verlauf_nachfuehren([], "0.20.3", t0 + timedelta(hours=2))
    assert len(vs.erledigt()) == 1 and vs.erledigt("0.20.3") == []
    # einen Tag später ist die langsame Berechnung wieder da, das Feld nicht mehr
    vs.verlauf_nachfuehren([langsam], "0.20.3", t0 + timedelta(hours=27))
    mit = vs.erledigt("0.20.3")
    assert [x["titel"] for x in mit] == [label.titel]
    assert all("Ideen" not in x["bereich"] for x in vs.erledigt())
    t = vs.bericht([langsam], "0.20.3", erledigt_=mit)
    assert "### Mit 0.20.3 erledigt" in t and "Eingabefelder ohne Beschriftung (Usability)" in t
    # kommt ein erledigter wieder vor, ist er wieder offen
    vs.verlauf_nachfuehren([langsam, sensor], "0.20.3", t0 + timedelta(hours=28))
    assert "Sensor ohne Werte" not in [x["titel"] for x in vs.erledigt()]
