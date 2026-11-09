"""Langzeit-Statistik aus Home Assistant (Recorder) über die WebSocket-API.

Die REST-API von Home Assistant liefert keine Statistik; die WebSocket-API schon («recorder/statistics_during_period»).
Ein kleiner WebSocket-Client nur mit der Standardbibliothek genügt dafür (keine zusätzliche Abhängigkeit im Image).

Verwendung: Zählerstände der Wärmepumpen rückwirkend füllen. Home Assistant hält für Energie-Zähler stündliche Werte
dauerhaft; die App schreibt sie als Zählerstand am Stundenende in die Messwerte – nur vor der ersten eigenen Ablesung,
eigene Werte werden nie überschrieben. Die Verteilung auf Viertelstunden übernimmt danach vorschau.verteilen().
"""
import base64
import json
import os
import socket
import ssl
import struct
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


class WebSocket:
    """Minimaler WebSocket-Client (RFC 6455): Textnachrichten senden und empfangen."""

    def __init__(self, url, timeout=30):
        u = urlparse(url)
        port = u.port or (443 if u.scheme == "wss" else 80)
        sock = socket.create_connection((u.hostname, port), timeout=timeout)
        if u.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
        self.sock = sock
        key = base64.b64encode(os.urandom(16)).decode()
        pfad = (u.path or "/") + (f"?{u.query}" if u.query else "")
        self.sock.sendall((f"GET {pfad} HTTP/1.1\r\nHost: {u.hostname}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        kopf = b""
        while b"\r\n\r\n" not in kopf:
            teil = self.sock.recv(4096)
            if not teil:
                raise ConnectionError("WebSocket: Verbindung beim Aufbau geschlossen")
            kopf += teil
        kopf, self._rest = kopf.split(b"\r\n\r\n", 1)
        if b" 101 " not in kopf.split(b"\r\n", 1)[0]:
            raise ConnectionError("WebSocket abgelehnt: " + kopf.split(b"\r\n", 1)[0].decode(errors="replace"))

    def _lesen(self, n):
        while len(self._rest) < n:
            teil = self.sock.recv(65536)
            if not teil:
                raise ConnectionError("WebSocket: Verbindung geschlossen")
            self._rest += teil
        d, self._rest = self._rest[:n], self._rest[n:]
        return d

    def senden(self, obj):
        daten = json.dumps(obj).encode()
        kopf = bytearray([0x81])
        n = len(daten)
        if n < 126:
            kopf.append(0x80 | n)
        elif n < 65536:
            kopf.append(0x80 | 126)
            kopf += struct.pack(">H", n)
        else:
            kopf.append(0x80 | 127)
            kopf += struct.pack(">Q", n)
        maske = os.urandom(4)
        self.sock.sendall(bytes(kopf) + maske + bytes(b ^ maske[i % 4] for i, b in enumerate(daten)))

    def empfangen(self):
        teile = []
        while True:
            b1, b2 = self._lesen(2)
            fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._lesen(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._lesen(8))[0]
            maske = self._lesen(4) if b2 & 0x80 else None
            daten = self._lesen(n)
            if maske:
                daten = bytes(b ^ maske[i % 4] for i, b in enumerate(daten))
            if op == 0x8:
                raise ConnectionError("WebSocket vom Server geschlossen")
            if op == 0x9:  # Ping → Pong
                self.sock.sendall(bytes([0x8A, 0x80 | len(daten)]) + b"\0\0\0\0" + daten)
                continue
            if op in (0x1, 0x0):
                teile.append(daten)
                if fin:
                    return json.loads(b"".join(teile).decode())

    def schliessen(self):
        try:
            self.sock.sendall(bytes([0x88, 0x80]) + b"\0\0\0\0")
            self.sock.close()
        except OSError:
            pass


def ws_url(api_base):
    """http://supervisor/core/api → ws://supervisor/core/websocket; http://host:8123/api → ws://host:8123/api/websocket."""
    u = api_base.rstrip("/")
    u = u.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return u[:-len("/core/api")] + "/core/websocket" if u.endswith("/core/api") else u + "/websocket"


def statistik(api_base, token, entitaeten, von, bis, timeout=60):
    """Stündliche Statistik {entity: [(ende_utc, state, sum)]} für total_increasing-Sensoren."""
    ws = WebSocket(ws_url(api_base), timeout=timeout)
    try:
        m = ws.empfangen()
        if m.get("type") == "auth_required":
            ws.senden({"type": "auth", "access_token": token})
            m = ws.empfangen()
        if m.get("type") != "auth_ok":
            raise PermissionError("Home Assistant: Anmeldung abgelehnt")
        ws.senden({"id": 1, "type": "recorder/statistics_during_period", "start_time": von.isoformat(), "end_time": bis.isoformat(),
                   "statistic_ids": list(entitaeten), "period": "hour", "types": ["state", "sum"]})
        while True:
            m = ws.empfangen()
            if m.get("id") == 1 and m.get("type") == "result":
                break
        if not m.get("success"):
            raise RuntimeError(f"Statistik: {(m.get('error') or {}).get('message', 'Fehler')}")
        out = {}
        for e, zeilen in (m.get("result") or {}).items():
            out[e] = [(_zeit(z.get("end")) or _zeit(z.get("start")) + timedelta(hours=1), z.get("state"), z.get("sum")) for z in zeilen]
        return out
    finally:
        ws.schliessen()


def _zeit(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):  # neuere Home-Assistant-Versionen: Millisekunden seit 1970
        return datetime.fromtimestamp(x / 1000, tz=timezone.utc)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).astimezone(timezone.utc)


def lokal(t_utc):
    """UTC → Schweizer Ortszeit ohne Zeitzone (wie Lastgänge und Messwerte)."""
    import preise
    t = t_utc.replace(tzinfo=None)
    return t + preise.offset((t + timedelta(hours=1)).date())


def fuellen(db, api_base, token, entitaeten, ab, heute=None):
    """Zählerstände vor der ersten eigenen Ablesung aus der Statistik eintragen. Gibt {entity: (anzahl, von, bis)} zurück."""
    heute = heute or datetime.now()
    with db() as c:
        erste = {e: c.execute("SELECT MIN(ts) FROM messwerte WHERE entity=?", (e,)).fetchone()[0] for e in entitaeten}
    bis = max([datetime.fromisoformat(v) for v in erste.values() if v] + [heute]) + timedelta(hours=2)
    von_utc = datetime.combine(ab, datetime.min.time()).replace(tzinfo=timezone.utc) - timedelta(hours=2)
    roh = statistik(api_base, token, entitaeten, von_utc, bis.replace(tzinfo=timezone.utc))
    ergebnis = {}
    for e in entitaeten:
        zeilen = roh.get(e) or []
        grenze = datetime.fromisoformat(erste[e]) if erste[e] else None
        werte = [(lokal(t), s, su) for t, s, su in zeilen if t is not None]
        werte = [(t, s, su) for t, s, su in werte if t.date() >= ab and (grenze is None or t < grenze)]
        if not werte:
            ergebnis[e] = (0, None, None)
            continue
        if all(s is not None for _, s, _ in werte):
            stand = [(t, float(s)) for t, s, _ in werte]
        else:  # nur «sum»: an die erste eigene Ablesung anschliessen
            with db() as c:
                ref = c.execute("SELECT wert FROM messwerte WHERE entity=? AND ts=?", (e, erste[e])).fetchone() if erste[e] else None
            versatz = (float(ref[0]) - float(werte[-1][2])) if ref and werte[-1][2] is not None else 0.0
            stand = [(t, float(su) + versatz) for t, _, su in werte if su is not None]
        with db() as c:
            c.executemany("INSERT OR IGNORE INTO messwerte (ts, entity, wert) VALUES (?, ?, ?)",
                          [(t.isoformat(timespec="minutes"), e, w) for t, w in stand])
        ergebnis[e] = (len(stand), stand[0][0], stand[-1][0])
    return ergebnis
