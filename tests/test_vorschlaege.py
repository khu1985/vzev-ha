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
