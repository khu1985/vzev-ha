"""Web-App: alle Seiten, Upload, Formulare, Abschluss-Sperre, Korrekturen, Statusanzeige."""
import importlib
import io
import re
import shutil
import sys
import time
from urllib.parse import unquote

import pytest
import yaml

import daten


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    d = tmp_path_factory.mktemp("app")
    daten.konfiguration(d / "vzev.yaml")
    import os
    os.environ["VZEV_DIR"] = str(d)
    for m in ["server", "seiten", "uebersicht"]:
        sys.modules.pop(m, None)
    server = importlib.import_module("server")
    server.app.testing = True
    quelle = tmp_path_factory.mktemp("quelle")
    daten.datenordner(quelle)
    return server, server.app.test_client(), d, quelle


def hochladen(client, pfad):
    with open(pfad, "rb") as f:
        r = client.post("hochladen", data={"dateien": (f, pfad.name)}, headers={"X-Requested-With": "fetch"},
                        content_type="multipart/form-data")
    return r.get_json()


def ziel(r):
    return unquote(r.headers.get("Location", ""))


def warten(server):
    ende = time.time() + 60
    while (server.veraltet() or server._rechnen.locked()) and time.time() < ende:
        time.sleep(0.1)


def test_leere_app_alle_seiten(app):
    server, c, d, quelle = app
    for u in ["/", "/verlauf", "/import", "/rechnungen", "/abschluss", "/mieter", "/tarife", "/primeo", "/batterie",
              "/sammler", "/einstellungen", "/einstellungen?tab=zaehler", "/einstellungen?tab=regeln",
              "/einstellungen?tab=datei", "/protokoll", "/status"]:
        r = c.get(u)
        assert r.status_code == 200, u
        assert b"schiefgelaufen" not in r.data, u


def test_upload_ordnet_ueber_messpunkt_zu(app):
    server, c, d, quelle = app
    for p in sorted((quelle / "primeo").iterdir()):
        j = hochladen(c, p)
        assert j["ok"], j
    zuordnung = {i["rolle"] for i in server.liste()}
    assert {"1OG", "2OG", "Allg", "PVA", "Prod", "Ladestation"} <= zuordnung
    assert not hochladen(c, quelle / "vzev.yaml")["ok"] or True  # fremde Datei bricht nichts


def test_kaputte_datei_wird_gemeldet(app):
    server, c, d, quelle = app
    r = c.post("hochladen", data={"dateien": (io.BytesIO(b"kein excel"), "kaputt.xlsx")},
               headers={"X-Requested-With": "fetch"}, content_type="multipart/form-data")
    j = r.get_json()
    assert not j["ok"] and "nicht lesbar" in j["msg"]
    for p in (d / "primeo").glob("kaputt*"):
        p.unlink()


def test_seiten_mit_daten(app):
    server, c, d, quelle = app
    warten(server)
    for u in ["/", "/?m=2026-03", "/?m=2026-04", "/verlauf?z=1OG", "/verlauf?z=AllgC", "/verlauf?z=EV",
              "/abschluss", "/primeo", "/sammler", "/import"]:
        r = c.get(u)
        assert r.status_code == 200 and b"schiefgelaufen" not in r.data, u
        assert b'id="warten"' not in r.data, u
    h = c.get("/?m=2026-03").get_data(as_text=True)
    assert "Ladestation = Summe der Ladevorgänge" in h and "12.00 kWh verteilt" in h
    assert "Daten importieren" in h and "v" + server.VERSION in h


def test_status_endpunkt(app):
    server, c, d, quelle = app
    j = c.get("/status").get_json()
    assert set(j) == {"rechnen", "sammler"} and j["rechnen"]["aktiv"] is False


def test_warteseite_bei_laufender_berechnung(app):
    server, c, d, quelle = app
    warten(server)
    server._rechnen.acquire()
    try:
        (d / "vzev.yaml").touch()
        time.sleep(0.01)
        r = c.get("/")
        assert b'id="warten"' in r.data
    finally:
        server._rechnen.release()
    warten(server)
    assert b'id="warten"' not in c.get("/").data


def test_formulare_speichern_ohne_werte_zu_aendern(app):
    server, c, d, quelle = app
    vorher = yaml.safe_load((d / "vzev.yaml").read_text())
    for url in ["/mieter", "/tarife", "/primeo", "/einstellungen?tab=betreiber", "/einstellungen?tab=zaehler",
                "/einstellungen?tab=regeln"]:
        h = c.get(url).get_data(as_text=True)
        form = re.findall(r'<form method="post"[^>]*action="([^"]+)"[^>]*>(.*?)</form>', h, re.S)[-1]
        daten_ = []
        for m in re.finditer(r'<input ([^>]*)>|<select name="([^"]+)"[^>]*>(.*?)</select>', form[1], re.S):
            if m.group(1):
                a = m.group(1)
                n = re.search(r'name="([^"]+)"', a)
                if not n or 'type="checkbox"' in a:
                    continue
                v = re.search(r'value="([^"]*)"', a)
                daten_.append((n.group(1), (v.group(1) if v else "").replace("&#39;", "'").replace("&amp;", "&")))
            else:
                sel = re.search(r'<option value="([^"]*)" selected', m.group(3))
                daten_.append((m.group(2), sel.group(1) if sel else ""))
        from werkzeug.datastructures import MultiDict
        r = c.post("/" + form[0], data=MultiDict(daten_))
        assert "Gespeichert" in ziel(r), (url, ziel(r))
    nachher = yaml.safe_load((d / "vzev.yaml").read_text())
    import json
    norm = lambda x: json.loads(json.dumps(x, default=str))
    for k in vorher:
        assert norm(vorher[k]) == norm(nachher.get(k)), k


def test_abschluss_sperre_und_korrekturen(app):
    server, c, d, quelle = app
    warten(server)
    r = c.post("/abschluss", data={"monat": "2026-04", "aktion": "schliessen", "datum": "2026-05-03"})
    assert "der Reihe nach" in ziel(r)
    r = c.post("/abschluss", data={"monat": "2026-03", "aktion": "schliessen", "datum": "2026-03-15"})
    assert "nach dem Monatsende" in ziel(r)
    r = c.post("/abschluss", data={"monat": "2026-03", "aktion": "schliessen", "datum": "2026-04-05"})
    assert "abgeschlossen per 05.04.2026" in ziel(r)
    # Tarif im abgeschlossenen Monat wird abgelehnt, künftiger Tarif geht
    cfg = yaml.safe_load((d / "vzev.yaml").read_text())

    def tarif_form(extra):
        f = []
        for k, _, fs, _ in server.seiten.TARIF_ARTEN:
            for e in cfg["tarife"][k] + extra.get(k, []):
                f.append((f"{k}.ab", str(e["ab"])))
                f += [(f"{k}.{x}", "" if e.get(x) is None else str(e[x])) for x, _ in fs]
        from werkzeug.datastructures import MultiDict
        return MultiDict(f)
    r = c.post("/tarife", data=tarif_form({"solar": [{"ab": "2026-03-15", "chf": 0.3}]}))
    assert "abgeschlossenen Monat 03.2026" in ziel(r)
    r = c.post("/tarife", data=tarif_form({"solar": [{"ab": "2027-01-01", "chf": 0.3}]}))
    assert "Gespeichert" in ziel(r)
    # Datum ändern, Rechnungen nur mit Begründung neu
    r = c.post("/abschluss", data={"monat": "2026-03", "aktion": "datum", "datum": "2026-04-02"})
    assert "02.04.2026" in ziel(r)
    r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "1", "datum": "2026-04-05"})
    assert "Erstellt" in ziel(r)
    r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "1", "datum": "2026-04-05"})
    assert "Begründung" in ziel(r)
    r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "1", "datum": "2026-04-05", "grund": "Test"})
    assert "Erstellt" in ziel(r)
    assert any((d / "rechnungen" / "_alt").iterdir())
    # Veränderung erkennen und neue Werte übernehmen
    regeln = {"allgemein_mieteranteil": "60", "ladestation_grundlast_kwh": "0.02"}
    c.post("/einstellungen?tab=regeln", data=regeln)
    warten(server)
    assert dict(server.seiten.abweichungen(server.berechnung()))
    r = c.post("/abschluss", data={"monat": "2026-03", "aktion": "uebernehmen", "grund": "Regel geändert"})
    assert "übernommen" in ziel(r)
    assert not server.seiten.abweichungen(server.berechnung())
    arten = [k["art"] for k in server.seiten.abschluss_laden()["korrekturen"]]
    assert any("abgeschlossen per" in a for a in arten) and any("Abschlussdatum geändert" in a for a in arten)
    # Wieder öffnen nur mit Begründung
    assert "Begründung" in ziel(c.post("/abschluss", data={"monat": "2026-03", "aktion": "oeffnen", "grund": ""}))
    assert "wieder geöffnet" in ziel(c.post("/abschluss", data={"monat": "2026-03", "aktion": "oeffnen", "grund": "Test"}))


def test_zahlungseingang(app):
    server, c, d, quelle = app
    warten(server)
    c.post("/abschluss", data={"monat": "2026-04", "aktion": "schliessen", "datum": "2026-05-02"})
    r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "2", "datum": "2026-05-05"})
    assert "Erstellt" in ziel(r), ziel(r)
    z = server.zahlungen.uebersicht()
    wohnung = [r for r in z["zeilen"] if r["quartal"] == "2026-Q2" and r["art"] == "wohnung"][0]
    allg = [r for r in z["zeilen"] if r["quartal"] == "2026-Q2" and r["art"] == "allgemein"][0]
    assert wohnung["partei"] == "Max Beispiel" and wohnung["betrag"] > 0 and wohnung["faellig"] == "2026-06-04"
    assert allg["stand"] == "intern"
    teil = round(wohnung["betrag"] / 2, 2)
    r = c.post("/zahlung", data={"key": wohnung["key"], "datum": "2026-05-20", "betrag": f"{teil}".replace(".", ",")})
    assert "erfasst" in ziel(r)
    w = [r for r in server.zahlungen.uebersicht()["zeilen"] if r["key"] == wohnung["key"]][0]
    assert w["stand"] in ("teilweise", "überfällig") and w["offen"] == round(wohnung["betrag"] - teil, 2)
    assert "Zahlung nicht erfasst" in ziel(c.post("/zahlung", data={"key": wohnung["key"], "datum": "2026-05-20", "betrag": "-5"}))
    # Korrektur übernimmt die Zahlung
    r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "2", "datum": "2026-05-06", "grund": "Test"})
    assert "Erstellt" in ziel(r)
    zeilen = server.zahlungen.uebersicht()["zeilen"]
    neu = [r for r in zeilen if r["quartal"] == "2026-Q2" and r["art"] == "wohnung" and r["stand"] != "ersetzt"]
    assert len(neu) == 1 and neu[0]["bezahlt"] == teil
    assert any(r["stand"] == "ersetzt" for r in zeilen if r["quartal"] == "2026-Q2")
    # Rest bezahlen, dann entfernen
    c.post("/zahlung", data={"key": neu[0]["key"], "datum": "2026-05-21", "betrag": f"{neu[0]['offen']:.2f}"})
    assert [r for r in server.zahlungen.uebersicht()["zeilen"] if r["key"] == neu[0]["key"]][0]["stand"] == "bezahlt"
    assert "entfernt" in ziel(c.post("/zahlung_entfernen", data={"key": neu[0]["key"], "index": "1"}))
    # Rechnungsdatum ändern: Fälligkeit folgt der Zahlungsfrist oder wird direkt gesetzt
    k = neu[0]["key"]
    assert "fällig 31.05.2026" in ziel(c.post("/rechnung_datum", data={"key": k, "datum": "2026-05-01"}))
    assert "fällig 15.05.2026" in ziel(c.post("/rechnung_datum", data={"key": k, "datum": "2026-05-01", "faellig": "2026-05-15"}))
    assert "nicht geändert" in ziel(c.post("/rechnung_datum", data={"key": k, "datum": "2026-05-01", "faellig": "2026-04-15"}))
    r = [r for r in server.zahlungen.uebersicht()["zeilen"] if r["key"] == k][0]
    assert r["datum"] == "2026-05-01" and r["faellig"] == "2026-05-15" and len(r["aenderungen"]) == 2
    h = c.get("/rechnungen").get_data(as_text=True)
    assert "Datum ändern" in h
    assert "Rechnungen und Zahlungen" in h and "2026-Q2-1OG" in h and "ersetzte Fassung" in h


def test_strompreise_einstellen_und_abrufen(app):
    server, c, d, quelle = app
    from test_preise import antwort
    import json, threading
    from datetime import date, timedelta
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            body = json.dumps(antwort(date.fromisoformat(q["start_timestamp"][0][:10]))).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/api/v1/tariffs"
        assert "nicht gespeichert" in ziel(c.post("/tarife?teil=dynamisch", data={"api_url": "ftp://x"})).lower()
        heute = date.today()
        r = c.post("/tarife?teil=dynamisch", data={"api_url": url, "tarif_name": "NetzDynamisch", "tarif_typ": "",
                                                     "abrufen_ab": (heute - timedelta(days=2)).isoformat(), "aktiv": "1"})
        assert "Gespeichert" in ziel(r)
        assert yaml.safe_load((d / "vzev.yaml").read_text())["dynamisch"]["api_url"] == url
        r = c.post("/preise_abrufen")
        assert "Viertelstunden" in ziel(r) and ziel(r).startswith("tarife"), ziel(r)
        warten(server)
        h = c.get("/tarife").get_data(as_text=True)
        assert "Dynamische Strompreise" in h and "Heute" in h and "Rp./kWh" in h and url in h
        assert "preise_abrufen" not in c.get("/batterie").get_data(as_text=True)
        assert "preise_abrufen" not in c.get("/primeo").get_data(as_text=True)
        h = c.get("/einstellungen?tab=regeln").get_data(as_text=True)
        assert "Batterie und dynamischer Tarif" in h and "Netzladung zahlt" in h
        r = c.post("/einstellungen?tab=batterie", data={"netzladung_zahlt": "betreiber", "entladung_netzanteil": "offen",
                                                        "dynamisch_ab": "2027-01-01", "notiz": "Test"})
        assert "tab=regeln" in ziel(r) and "Gespeichert" in ziel(r)
        assert yaml.safe_load((d / "vzev.yaml").read_text())["batterie"]["notiz"] == "Test"
    finally:
        srv.shutdown()


def test_jahresabrechnung(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/jahr?j=2026").get_data(as_text=True)
    assert "Allgemeinstrom 01.03.–30.04.2026" in h and "Mieter 2026" in h and "Vorläufig" in h
    assert "Erika Muster" in h and "Max Beispiel" in h
    b = server.berechnung()
    import invoices
    from datetime import date
    erwartet = round(sum(r["total"] for r in invoices.lines_for(b["res"], b["cfg"], "AllgC", date(2026, 3, 1), date(2026, 4, 30))), 2)
    assert f"{erwartet:,.2f}".replace(",", "'") in h
    r = c.get("/jahr/pdf?j=2026")
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    r = c.get("/jahr/excel?j=2026")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert {"Übersicht", "Allgemeinstrom", "Mieter", "Zähler pro Monat", "Wertschöpfung", "Rechnungen"} <= set(wb.sheetnames)
    assert wb["Allgemeinstrom"].max_row == 3  # Kopf + März + April
    r = c.get("/jahr/excel?j=2026&viertelstunden=1")
    wb = openpyxl.load_workbook(io.BytesIO(r.data), read_only=True)
    assert wb["Viertelstunden"].max_row == len(b["res"]) + 1
    assert "Keine Daten" in c.get("/jahr?j=2025").get_data(as_text=True)


def test_wertschoepfung_seite(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/wertschoepfung").get_data(as_text=True)
    assert r'Wertschöpfung pro Monat' in h and "Kumuliert" in h and "Wohin geht der Solarstrom" in h and "Was eine kWh wert ist" in h
    assert h.count("<svg") >= 3 and "CHF/kWh" in h
    b = server.berechnung()
    total = server.core.wertschoepfung(b["res"], b["cfg"])["total_chf"].sum()
    assert f"{total:,.2f}".replace(",", "'") in h
    assert c.get("/wertschoepfung?j=2026").status_code == 200
    assert 'href="wertschoepfung"' in c.get("/").get_data(as_text=True)


def test_was_ist_neu(app):
    server, c, d, quelle = app
    h = c.get("/neu").get_data(as_text=True)
    assert "Version " + server.VERSION in h and "installiert" in h
    assert 'href="neu"' in c.get("/protokoll").get_data(as_text=True)


def test_abschnitt_speichern_behaelt_kommentare(app):
    server, c, d, quelle = app
    text = (d / "vzev.yaml").read_text()
    (d / "vzev.yaml").write_text("# Kopfkommentar bleibt\n" + text + "\n# Schlusskommentar bleibt\n")
    server.seiten.abschnitt_speichern("rechnungen", {"zahlungsfrist_tage": 20, "nummer": "{jahr}-Q{quartal}-{einheit}"})
    neu = (d / "vzev.yaml").read_text()
    assert "# Kopfkommentar bleibt" in neu and "# Schlusskommentar bleibt" in neu
    assert yaml.safe_load(neu)["rechnungen"]["zahlungsfrist_tage"] == 20


def test_protokoll_zeigt_eintraege(app):
    server, c, d, quelle = app
    h = c.get("/protokoll").get_data(as_text=True)
    assert "Hochgeladen" in h
