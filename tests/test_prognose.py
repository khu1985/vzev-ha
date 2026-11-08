"""PV-Prognose aus Solcast: Attribute zerlegen, Vortags-Prognose festhalten, Ladefenster, Abruf aus Home Assistant."""
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import prognose


def solcast_attr(d, faktor=1.0):
    """Wie die Solcast-Integration: halbstündlich, Glockenkurve 07–17 Uhr, Spitze 4 kW."""
    out = []
    for i in range(48):
        t = datetime(d.year, d.month, d.day) + timedelta(minutes=30 * i)
        h = t.hour + t.minute / 60
        kw = max(0.0, 4 * (1 - ((h - 12) / 5) ** 2)) * faktor
        out.append({"period_start": t.isoformat() + "+01:00", "pv_estimate": round(kw, 4),
                    "pv_estimate10": round(kw * 0.6, 4), "pv_estimate90": round(kw * 1.2, 4)})
    return {"friendly_name": "Solcast Prognose", "unit_of_measurement": "kWh", "detailedForecast": out}


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "m.sqlite"
    verbinden = lambda: sqlite3.connect(p)  # noqa: E731
    prognose.init(verbinden)
    with verbinden() as c:
        c.execute("CREATE TABLE IF NOT EXISTS messwerte (ts TEXT, entity TEXT, wert REAL, PRIMARY KEY (ts, entity))")
        c.execute("CREATE TABLE IF NOT EXISTS preise (start_utc TEXT, typ TEXT, start_lokal TEXT, ende_lokal TEXT, chf_kwh REAL, publiziert TEXT, abgerufen TEXT, PRIMARY KEY (start_utc, typ))")
    return verbinden


def test_zerlegen_halbstunden():
    z = prognose.zerlegen(solcast_attr(date(2027, 1, 4)))
    assert len(z) == 48 and z[0][0] == datetime(2027, 1, 4, 0, 0) and z[0][1] == 30
    assert max(k for _, _, k, _, _ in z) == pytest.approx(4.0)
    assert sum(k * m / 60 for _, m, k, _, _ in z) == pytest.approx(26.6, abs=0.5)


def test_vortag_wird_festgehalten(db):
    d = date(2027, 1, 5)
    prognose.speichern(db, prognose.zerlegen(solcast_attr(d, 1.0)), jetzt=datetime(2027, 1, 4, 20, 0))   # am Vortag
    prognose.speichern(db, prognose.zerlegen(solcast_attr(d, 0.5)), jetzt=datetime(2027, 1, 5, 9, 0))    # am Tag selbst
    neu = prognose.tagessummen(db, d, d)[d][0]
    vortag = prognose.tagessummen(db, d, d, "prognose_vortag")[d][0]
    assert vortag == pytest.approx(2 * neu)          # die Korrektur am Tag selbst überschreibt den Vortag nicht


def test_ladefenster():
    pv = [(m, 30, (3.0 if 600 <= m < 900 else 0.0), 0, 0) for m in range(0, 1440, 30)]
    verbrauch = [(m, 1.0) for m in range(0, 1440, 15)]
    preis = [(m, 10.0 if 120 <= m < 240 or 660 <= m < 720 else 30.0) for m in range(0, 1440, 15)]
    f = prognose.ladefenster(pv, verbrauch, preis)
    assert [(x["von"], x["bis"]) for x in f] == [("02:00", "04:00")]   # mittags günstig, aber die Sonne reicht
    assert f[0]["preis"] == pytest.approx(10.0) and f[0]["fehlt"] == pytest.approx(2.0)


def test_abruf_findet_solcast_sensoren(db, tmp_path):
    heute = date.today()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            alle = [{"entity_id": "sensor.solcast_pv_forecast_prognose_heute", "state": "12.3", "attributes": solcast_attr(heute)},
                    {"entity_id": "sensor.solcast_pv_forecast_prognose_morgen", "state": "8", "attributes": solcast_attr(heute + timedelta(days=1), 0.6)},
                    {"entity_id": "sensor.anderes", "state": "1", "attributes": {}}]
            if self.path.endswith("/api/states"):
                body = alle
            else:
                body = next(s for s in alle if self.path.endswith(s["entity_id"]))
            assert self.headers["Authorization"] == "Bearer test"
            daten = json.dumps(body).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(daten)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = {"homeassistant": {"url": f"http://127.0.0.1:{srv.server_port}", "token": "test"}}

        class C:
            _db = staticmethod(db)

            def _ha(self):
                return cfg["homeassistant"]["url"] + "/api", "test"
        p = prognose.Prognose(C(), lambda: cfg)
        assert p.abrufen() == 96
        assert p.entitaeten == ["sensor.solcast_pv_forecast_prognose_heute", "sensor.solcast_pv_forecast_prognose_morgen"]
        heute_kwh, morgen_kwh = prognose.kurz(db)
        assert morgen_kwh == pytest.approx(0.6 * heute_kwh, rel=0.01)
        cfg["homeassistant"]["solcast"] = ["sensor.solcast_pv_forecast_prognose_heute"]   # fest eingestellt
        assert p.abrufen() == 48
    finally:
        srv.shutdown()
