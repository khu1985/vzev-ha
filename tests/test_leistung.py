"""Leistung messen: Erfassen, pro Version sichern, mit der Vorversion vergleichen, Vorschläge ableiten."""
import types

import leistung as le
import vorschlaege as vs


def _server(tmp_path, version):
    (tmp_path / "primeo").mkdir(exist_ok=True)
    (tmp_path / "rechnungen").mkdir(exist_ok=True)
    return types.SimpleNamespace(DATA=tmp_path, PRIMEO=tmp_path / "primeo", RECHNUNGEN=tmp_path / "rechnungen",
                                 LOGFILE=tmp_path / "vzev.log", VERSION=version, RECHNEN={})


def test_messen_sichern_vergleichen(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "S", _server(tmp_path, "1.0.0"))
    le._WERTE.clear()
    for ms in (2500, 3500, 3000):
        le.erfassen("seite", "verlauf", ms)
    le.erfassen("funktion", "uebersicht.kontrollen_fuer", 100)
    assert le.sichern() == 2 and (tmp_path / "leistung.json").exists()
    le.S.VERSION = "1.1.0"
    for _ in range(5):
        le.erfassen("funktion", "uebersicht.kontrollen_fuer", 400)
    ms, vorher = le.messungen()
    assert vorher == "1.0.0" and ms[0].name == "uebersicht.kontrollen_fuer" and ms[0].vorher_ms == 100
    ms, _ = le.messungen("1.0.0")
    assert {m.name: m.mittel_ms for m in ms}["verlauf"] == 3000
    titel = [t for t, _, _ in le.vorschlaege()]
    assert "«uebersicht.kontrollen_fuer» ist langsamer geworden" in titel
    le.S.VERSION = "1.0.0"
    assert "Seite «verlauf» lädt langsam" in [t for t, _, _ in le.vorschlaege()]
    s = le.system()
    assert s["kerne"] >= 1 and "zeilen" in s
    zeilen = le.bericht_text()
    assert zeilen[0].startswith("System:") and any(z.startswith("seite verlauf: 3×") for z in zeilen)
    t = vs.bericht([], "1.0.0", zeilen)
    assert "### Leistung (Messwerte dieser Version)" in t and "Keine Vorschläge." in t


def test_nur_fuenf_versionen(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "S", _server(tmp_path, "1.0.0"))
    le._WERTE.clear()
    for i in range(8):
        le.erfassen("seite", "index", 10)
        le.sichern(f"1.{i}.0")
    assert sorted(le._laden(), key=le._vt) == [f"1.{i}.0" for i in range(3, 8)]


def test_instrumentieren(monkeypatch):
    import uebersicht
    monkeypatch.setattr(uebersicht, "monate", uebersicht.monate)  # nach dem Test zurücksetzen
    monkeypatch.setattr(le, "FUNKTIONEN", [("uebersicht", "monate"), ("gibtsnicht", "x")])
    assert le.instrumentieren() == 1 and getattr(uebersicht.monate, "__gemessen__", False)
    assert le.instrumentieren() == 0


def test_stoppuhr():
    le._WERTE.clear()
    with le.Stoppuhr("hintergrund", "Datensammler ablesen"):
        pass
    assert le._WERTE[("hintergrund", "Datensammler ablesen")][0] == 1


def test_sensoren_nur_geaenderte(monkeypatch):
    import sensoren
    werte = [sensoren.Sensor("a", "A", 1, "kWh"), sensoren.Sensor("b", "B", 2, "kWh")]
    monkeypatch.setattr(sensoren, "berechnen", lambda heute=None: list(werte))
    monkeypatch.setattr(sensoren, "einstellungen", lambda cfg: (True, "vzev"))
    monkeypatch.setattr(sensoren, "S", types.SimpleNamespace(config=lambda: {}))
    monkeypatch.setattr(sensoren, "_GESENDET", {})
    monkeypatch.setattr(sensoren, "_letzter", {"zeit": None, "anzahl": 0, "fehler": "", "werte": []})
    gesendet = []
    monkeypatch.setattr(sensoren, "_senden_ha", lambda e, n: gesendet.append(e))
    sensoren.schreiben()
    assert sorted(gesendet) == ["sensor.vzev_a", "sensor.vzev_b"]
    gesendet.clear()
    werte[1] = sensoren.Sensor("b", "B", 3, "kWh")
    sensoren.schreiben()
    assert gesendet == ["sensor.vzev_b"] and sensoren.status()["gesendet"] == 1 and sensoren.status()["anzahl"] == 2
    gesendet.clear()
    sensoren.schreiben(alle=True)                       # «Jetzt schreiben»
    assert len(gesendet) == 2
    gesendet.clear()
    sensoren._letzter["alle_zeit"] -= 4000              # spätestens stündlich alle (Home Assistant vergisst beim Neustart)
    sensoren.schreiben()
    assert len(gesendet) == 2


def test_sensoren_nicht_als_langsam(tmp_path, monkeypatch):
    monkeypatch.setattr(le, "S", _server(tmp_path, "2.0.0"))
    le._WERTE.clear()
    for _ in range(5):
        le.erfassen("funktion", "sensoren.schreiben", 4000)
    assert not [t for t, _, _ in le.vorschlaege() if "sensoren" in t]
