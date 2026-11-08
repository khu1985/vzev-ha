"""Dynamische Strompreise: Zeitzone, Antwort zerlegen, Abruf gegen eine nachgebaute Primeo-Schnittstelle."""
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import preise


def test_zeitzone_schweiz():
    assert preise.tag_grenzen(date(2027, 1, 1)) == ("2027-01-01T00:00:00+01:00", "2027-01-02T00:00:00+01:00")
    assert preise.tag_grenzen(date(2027, 3, 28)) == ("2027-03-28T00:00:00+01:00", "2027-03-29T00:00:00+02:00")  # Umstellung
    assert preise.tag_grenzen(date(2027, 7, 1))[0].endswith("+02:00")
    assert preise.tag_grenzen(date(2027, 10, 31)) == ("2027-10-31T00:00:00+02:00", "2027-11-01T00:00:00+01:00")


def antwort(d, typen=("grid", "electricity", "integrated")):
    """Wie im Primeo-Merkblatt: Viertelstunden mit Listen aus {unit, value} pro Tariftyp."""
    start, ende = preise.tag_grenzen(d)
    t = datetime.fromisoformat(start)
    stop = datetime.fromisoformat(ende)
    prices = []
    while t < stop:
        lokal = t.astimezone(timezone(preise.offset(d) if t.date() == d else preise.offset(d + timedelta(days=1))))
        h = t.astimezone(timezone(timedelta(hours=1))).hour
        grid, energie = 0.05 + 0.01 * (h >= 7), 0.08 + 0.002 * h
        e = {"start_timestamp": t.isoformat(), "end_timestamp": (t + timedelta(minutes=15)).isoformat()}
        for typ, v in {"grid": grid, "electricity": energie, "integrated": grid + energie}.items():
            if typ in typen:
                e[typ] = [{"unit": "CHF_kWh", "value": round(v, 4)}]
        prices.append(e)
        t += timedelta(minutes=15)
    return {"publication_timestamp": f"{d - timedelta(days=1)}T18:00:00+01:00", "tariff_name": "NetzDynamisch", "prices": prices}


def test_zerlegen():
    z = preise.zerlegen(antwort(date(2027, 1, 4)))
    assert len(z) == 96 * 3
    erste = [x for x in z if x[1] == "integrated"][0]
    assert erste[0] == "2027-01-03T23:00" and erste[2] == "2027-01-04T00:00" and erste[4] == pytest.approx(0.13)


@pytest.fixture
def schnittstelle():
    abrufe = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            abrufe.append(q)
            d = date.fromisoformat(q["start_timestamp"][0][:10])
            if d > date(2027, 1, 5):  # noch nicht veröffentlicht
                body = {"publication_timestamp": None, "tariff_name": "NetzDynamisch", "prices": []}
            else:
                body = antwort(d)
            daten = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(daten)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/api/v1/tariffs", abrufe
    srv.shutdown()


def test_abruf_speichert_und_ist_wiederholbar(tmp_path, schnittstelle):
    url, abrufe = schnittstelle
    db = preise.verbinden(tmp_path / "p.sqlite")
    cfg = {"dynamisch": {"api_url": url, "abrufen_ab": "2027-01-01"}}
    pa = preise.Preisabruf(db, lambda: cfg)
    tage = pa.faellige_tage(datetime(2027, 1, 4, 19, 0))
    assert tage == [date(2027, 1, d) for d in range(1, 6)]  # nach 18 Uhr auch morgen
    assert pa.abrufen(tage) == 5 * 96
    assert abrufe[0]["tariff_name"] == ["NetzDynamisch"] and "tariff_type" not in abrufe[0]
    assert abrufe[0]["start_timestamp"] == ["2027-01-01T00:00:00+01:00"]
    assert pa.abrufen(tage) == 5 * 96  # nochmals: überschreibt, keine Duplikate
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM preise WHERE typ='integrated'").fetchone()[0] == 5 * 96
    assert pa.faellige_tage(datetime(2027, 1, 4, 19, 0)) == []
    rows = preise.tag(db, date(2027, 1, 2), "integrated")
    assert len(rows) == 96 and rows[0][0] == "2027-01-02T00:00"


def test_noch_nicht_veroeffentlicht(tmp_path, schnittstelle):
    url, _ = schnittstelle
    db = preise.verbinden(tmp_path / "p.sqlite")
    pa = preise.Preisabruf(db, lambda: {"dynamisch": {"api_url": url, "abrufen_ab": "2027-01-06"}})
    assert pa.abrufen([date(2027, 1, 6)]) == 0
    assert "noch keine Preise für 06.01." in pa.status and pa.fehler is None


def test_tariftyp_und_fehler(tmp_path, schnittstelle):
    url, abrufe = schnittstelle
    db = preise.verbinden(tmp_path / "p.sqlite")
    pa = preise.Preisabruf(db, lambda: {"dynamisch": {"api_url": url, "tarif_typ": "integrated", "tarif_name": "NetzDynamischAVAG"}})
    pa.abrufen([date(2027, 1, 1)])
    assert abrufe[-1]["tariff_type"] == ["integrated"] and abrufe[-1]["tariff_name"] == ["NetzDynamischAVAG"]
    kaputt = preise.Preisabruf(db, lambda: {"dynamisch": {"api_url": "http://127.0.0.1:9/nicht-da"}})
    kaputt.abrufen([date(2027, 1, 1)])
    assert kaputt.fehler and kaputt.status.startswith("Fehler")


def test_alte_einstellung_von_der_batterie_seite():
    e = preise.einstellungen({"batterie": {"preis_api": "https://example.test/api"}})
    assert e["api_url"] == "https://example.test/api"
    e = preise.einstellungen({"batterie": {"preis_api": "https://alt"}, "dynamisch": {"api_url": "https://neu"}})
    assert e["api_url"] == "https://neu"
