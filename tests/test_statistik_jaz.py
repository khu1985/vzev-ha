"""Langzeit-Statistik über WebSocket (rückwirkende Wärmepumpen-Werte) und Jahresarbeitszahl."""
import base64
import hashlib
import json
import socket
import sqlite3
import struct
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

import hastatistik
import vorschau


def _frame_lesen(conn):
    def n(k):
        b = b""
        while len(b) < k:
            b += conn.recv(k - len(b))
        return b
    b1, b2 = n(2)
    ln = b2 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", n(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", n(8))[0]
    maske = n(4)
    daten = bytes(x ^ maske[i % 4] for i, x in enumerate(n(ln)))
    return b1 & 0x0F, daten


def _frame_senden(conn, obj, teilen=False):
    d = json.dumps(obj).encode()
    stuecke = [d[:10], d[10:]] if teilen and len(d) > 20 else [d]
    for i, st in enumerate(stuecke):
        op = (0x1 if i == 0 else 0x0) | (0x80 if i == len(stuecke) - 1 else 0)
        kopf = bytes([op])
        if len(st) < 126:
            kopf += bytes([len(st)])
        elif len(st) < 65536:
            kopf += bytes([126]) + struct.pack(">H", len(st))
        else:
            kopf += bytes([127]) + struct.pack(">Q", len(st))
        conn.sendall(kopf + st)


class FakeHA:
    """Home-Assistant-WebSocket mit auth und recorder/statistics_during_period."""

    def __init__(self, statistik):
        self.statistik, self.anfragen = statistik, []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.lauf, daemon=True).start()

    def lauf(self):
        conn, _ = self.srv.accept()
        kopf = b""
        while b"\r\n\r\n" not in kopf:
            kopf += conn.recv(4096)
        assert b"GET /api/websocket " in kopf
        key = [z.split(b": ")[1] for z in kopf.split(b"\r\n") if z.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        _frame_senden(conn, {"type": "auth_required"})
        _, d = _frame_lesen(conn)
        assert json.loads(d) == {"type": "auth", "access_token": "geheim"}
        _frame_senden(conn, {"type": "auth_ok"})
        _, d = _frame_lesen(conn)
        a = json.loads(d)
        self.anfragen.append(a)
        _frame_senden(conn, {"id": a["id"], "type": "result", "success": True, "result": self.statistik}, teilen=True)
        try:
            _frame_lesen(conn)
        except Exception:
            pass
        conn.close()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "m.sqlite"
    verbinden = lambda: sqlite3.connect(p)  # noqa: E731
    with verbinden() as c:
        c.execute("CREATE TABLE messwerte (ts TEXT, entity TEXT, wert REAL, PRIMARY KEY (ts, entity))")
        c.execute("CREATE TABLE entitaeten (entity TEXT PRIMARY KEY, name TEXT, einheit TEXT, zustand TEXT, geprueft TEXT)")
    return verbinden


def test_ws_url():
    assert hastatistik.ws_url("http://supervisor/core/api") == "ws://supervisor/core/websocket"
    assert hastatistik.ws_url("https://ha.local:8123/api") == "wss://ha.local:8123/api/websocket"


def test_statistik_fuellen_vor_erster_ablesung(db):
    # eigene erste Ablesung am 09.11.2026 10:00 (Lokalzeit), Stand 500
    with db() as c:
        c.execute("INSERT INTO messwerte VALUES ('2026-11-09T10:00', 'sensor.wp', 500.0)")
    # Statistik: stündlich vom 08.11. 23:00 UTC an, Stand steigt um 0.5 kWh pro Stunde
    start = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    zeilen = [{"start": (start + timedelta(hours=i)).timestamp() * 1000, "end": (start + timedelta(hours=i + 1)).timestamp() * 1000,
               "state": 495.0 + 0.5 * i, "sum": 10 + 0.5 * i} for i in range(12)]
    ha = FakeHA({"sensor.wp": zeilen})
    erg = hastatistik.fuellen(db, f"http://127.0.0.1:{ha.port}/api", "geheim", ["sensor.wp"], date(2026, 11, 9),
                              heute=datetime(2026, 11, 9, 12, 0))
    assert ha.anfragen[0]["type"] == "recorder/statistics_during_period" and ha.anfragen[0]["period"] == "hour"
    n, von, bis = erg["sensor.wp"]
    assert von == datetime(2026, 11, 9, 1, 0) and bis == datetime(2026, 11, 9, 9, 0)      # UTC+1, nur vor der eigenen Ablesung
    with db() as c:
        assert c.execute("SELECT wert FROM messwerte WHERE ts='2026-11-09T10:00'").fetchone()[0] == 500.0   # nicht überschrieben
        assert c.execute("SELECT wert FROM messwerte WHERE ts='2026-11-09T09:00'").fetchone()[0] == pytest.approx(499.0)
    v = vorschau.verteilen(__import__("pandas").Series(
        [w for _, w in db().execute("SELECT ts, wert FROM messwerte ORDER BY ts").fetchall()],
        index=__import__("pandas").to_datetime([t for t, _ in db().execute("SELECT ts, wert FROM messwerte ORDER BY ts").fetchall()])))
    assert v.loc["2026-11-09 02:00":"2026-11-09 02:45"].tolist() == [0.125] * 4                # Stunde auf Viertelstunden verteilt


def test_jahresarbeitszahl(db):
    cfg = {"homeassistant": {"waermepumpen": [{"name": "Heizung", "entity": "sensor.strom", "waerme": "sensor.waerme"}]}}
    with db() as c:
        c.execute("INSERT INTO entitaeten VALUES ('sensor.waerme', 'W', 'MWh', '', '')")
        t, s, w = datetime(2026, 11, 1), 100.0, 2.0
        for _ in range(96 * 3):
            c.execute("INSERT INTO messwerte VALUES (?, 'sensor.strom', ?)", (t.isoformat(timespec="minutes"), s))
            c.execute("INSERT INTO messwerte VALUES (?, 'sensor.waerme', ?)", (t.isoformat(timespec="minutes"), w))
            t, s, w = t + timedelta(minutes=15), s + 0.2, w + 0.0007   # 0.7 kWh Wärme aus 0.2 kWh Strom
    j = vorschau.jaz(db, cfg, date(2026, 11, 1), date(2026, 11, 30))["Heizung"]
    assert j["jaz"] == pytest.approx(3.5, rel=0.001) and j["strom"] == pytest.approx(0.2 * (96 * 3 - 1))
