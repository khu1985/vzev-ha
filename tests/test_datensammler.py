"""Datensammler: Neustarts von Home Assistant und kurze Aussetzer einzelner Sensoren erzeugen keine Warnungen."""
import logging

import pytest

import collector as C


class Antwort:
    def __init__(self, code, state="1.0"):
        self.status_code, self._state = code, state

    def json(self):
        return {"state": self._state, "attributes": {}}


class Fang(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def caplog():
    """Eigener Handler direkt am Logger der App (der Logger der App gibt nicht immer an die Wurzel weiter)."""
    f = Fang()
    alt = C.log.level
    C.log.addHandler(f)
    C.log.setLevel(logging.DEBUG)
    yield f
    C.log.removeHandler(f)
    C.log.setLevel(alt)


@pytest.fixture
def sammler(tmp_path, monkeypatch):
    cfg = {"homeassistant": {"url": "http://ha", "token": "x",
                             "zaehler": {"a": "sensor.zaehler_a", "b": "sensor.gateway_waerme"},
                             "solis": {"heute": "sensor.solis_energy_today"}}}
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    return C.Collector(str(tmp_path / "m.sqlite"), lambda: cfg)


def test_neustart_von_home_assistant(sammler, monkeypatch, caplog):
    aufrufe = []
    monkeypatch.setattr(C.requests, "get", lambda url, **k: aufrufe.append(url) or Antwort(502))
    with pytest.raises(ConnectionError):
        sammler.read_now()
    assert len(aufrufe) == 2                       # erste Entität zweimal versucht, die übrigen nicht mehr abgewartet
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_kurzer_aussetzer_ohne_warnung(sammler, monkeypatch, caplog):
    zustand = {"sensor.gateway_waerme": "unavailable", "sensor.solis_energy_today": "unknown"}
    monkeypatch.setattr(C.requests, "get", lambda url, **k: Antwort(200, zustand.get(url.rsplit("/", 1)[1], "5")))
    for _ in range(3):
        sammler.read_now()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    sammler.read_now()                             # eine Stunde ohne Wert: jetzt melden – nur das Gateway
    w = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(w) == 1 and "gateway_waerme" in w[0] and "solis" not in w[0]
    zustand.clear()
    sammler.read_now()
    assert any("wieder Werte" in r.getMessage() for r in caplog.records)


def test_geduld():
    assert C.geduld("sensor.solis_inverter_1_solis_energy_today") > 40
    assert C.geduld("sensor.buderus_gateway_1_erzeugte_warme_gesamt") == 4
