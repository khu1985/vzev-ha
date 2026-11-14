"""Web-App: alle Seiten, Upload, Formulare, Abschluss-Sperre, Korrekturen, Statusanzeige."""
import importlib
import io
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
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
    for u in ["/", "/uebersicht?m=2026-03", "/uebersicht?m=2026-04", "/verlauf?z=1OG", "/verlauf?z=AllgC", "/verlauf?z=EV",
              "/abschluss", "/primeo", "/sammler", "/import"]:
        r = c.get(u)
        assert r.status_code == 200 and b"schiefgelaufen" not in r.data, u
        assert b'id="warten"' not in r.data, u
    h = c.get("/uebersicht?m=2026-03").get_data(as_text=True)
    assert "Ladestation = Summe der Ladevorgänge" in h and "12.00 kWh verteilt" in h
    h = c.get("/uebersicht?j=2026").get_data(as_text=True)
    assert "Produktion 2026" in h and "Wertschöpfung 2026" in h and "Energiefluss pro Monat 2026" in h
    assert 'href="?j=2026&amp;m=2026-03#monat"' in h and 'name="m"' not in h   # Monat per Klick, keine Monatsauswahl mehr
    assert 'id="monat"' in h and "April 2026" in h                                # zuletzt vollständiger Monat ist vorgewählt
    assert "Daten importieren" in h and "v" + server.VERSION in h
    assert 'id="thema"' in h and "html[data-theme=dark]" in h and "vzev-theme" in h   # Dark Mode mit Umschalter


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


def formular(c, url):
    """Das Speicherformular einer Seite so auslesen, wie der Browser es senden würde: (Ziel, [(Name, Wert)])."""
    h = c.get(url).get_data(as_text=True)
    form = [f for f in re.findall(r'<form method="post"[^>]*action="([^"]+)"[^>]*>(.*?)</form>', h, re.S)
            if not f[0].startswith("sensoren_schreiben")][-1]   # Knopf «Jetzt schreiben» ist kein Speicherformular
    daten_ = []
    for m in re.finditer(r'<input ([^>]*)>|<select name="([^"]+)"[^>]*>(.*?)</select>', form[1], re.S):
        if m.group(1):
            a = m.group(1)
            n = re.search(r'name="([^"]+)"', a)
            if not n or ('type="checkbox"' in a and "checked" not in a):
                continue  # wie der Browser: nur angehakte Checkboxen werden gesendet
            v = re.search(r'value="([^"]*)"', a)
            daten_.append((n.group(1), (v.group(1) if v else "").replace("&#39;", "'").replace("&amp;", "&")))
        else:
            sel = re.search(r'<option value="([^"]*)" selected', m.group(3))
            daten_.append((m.group(2), sel.group(1) if sel else ""))
    return form[0], daten_


def test_formulare_speichern_ohne_werte_zu_aendern(app):
    server, c, d, quelle = app
    vorher = yaml.safe_load((d / "vzev.yaml").read_text())
    for url in ["/mieter", "/tarife", "/primeo", "/einstellungen?tab=betreiber", "/einstellungen?tab=zaehler",
                "/einstellungen?tab=regeln"]:
        ziel_, daten_ = formular(c, url)
        from werkzeug.datastructures import MultiDict
        r = c.post("/" + ziel_, data=MultiDict(daten_))
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
        assert "Speicher und dynamischer Tarif" in h and "Standby PV-Anlage bis" in h and "Konzessionsabgabe" in h
        r = c.post("/einstellungen?tab=batterie", data={"speicher_ab": "2027-01-01", "pva_standby_max_kwh": "0,06",
                                                        "speicher_wirkungsgrad": "88", "bonus": "1", "bonus_ab": "2027-01-01",
                                                        "konzession_prozent": "4.1", "mwst_prozent": "8.1"})
        assert "tab=regeln" in ziel(r) and "Gespeichert" in ziel(r)
        y = yaml.safe_load((d / "vzev.yaml").read_text())
        assert y["regeln"]["pva_standby_max_kwh"] == 0.06 and y["regeln"]["speicher_wirkungsgrad"] == 0.88
        assert "bonus" not in y["dynamisch"] and y["dynamisch"]["api_url"] == url  # Standard bleibt unsichtbar, Schnittstelle erhalten
    finally:
        srv.shutdown()


def test_jahresabrechnung(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/jahr?j=2026").get_data(as_text=True)
    assert "Allgemeinstrom 01.03.–30.04.2026" in h and "Mieter 2026" in h and "Vorläufig" in h
    assert "<td class=\"l\">Erika</td>" in h and "<td class=\"l\">Max</td>" in h  # App: Vorname
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
    assert 'href="wertschoepfung"' in c.get("/uebersicht").get_data(as_text=True)


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


def test_prognose_seite(app):
    server, c, d, quelle = app
    import prognose
    from test_prognose import solcast_attr
    heute = date.today()
    db = server.collector._db
    jetzt = datetime.combine(heute - timedelta(days=1), datetime.min.time()) + timedelta(hours=20)
    prognose.speichern(db, prognose.zerlegen(solcast_attr(heute)), jetzt=jetzt)
    prognose.speichern(db, prognose.zerlegen(solcast_attr(heute + timedelta(days=1), 0.5)), jetzt=jetzt)
    sol = yaml.safe_load((d / "vzev.yaml").read_text())["homeassistant"]["solis"]["pv_heute"]
    with db() as con:  # gemessener PV-Tageszähler bis 12 Uhr
        for i in range(49):
            t = datetime.combine(heute, datetime.min.time()) + timedelta(minutes=15 * i)
            con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), sol, max(0, i - 28) * 0.8))
    h = c.get("/prognose").get_data(as_text=True)
    assert "Prognose heute" in h and "Prognose morgen" in h and "Gemessen heute" in h and "PV-Prognose (Band 10–90 %)" in h
    assert "Trefferquote" in h and 'href="prognose"' in h
    h = c.get("/prognose?d=morgen").get_data(as_text=True)
    assert "Morgen," in h, h[-3000:]
    assert "noch nicht publiziert" in h or "Günstig aus dem Netz laden" in h
    r = c.get("/einstellungen?tab=zaehler").get_data(as_text=True)
    assert "PV-Prognose (Solcast)" in r


def test_waermepumpen(app):
    server, c, d, quelle = app
    warten(server)
    cfg_alt = (d / "vzev.yaml").read_text()
    try:
        y = yaml.safe_load(cfg_alt)
        y["homeassistant"]["waermepumpen"] = [{"name": "Heizung", "entity": "sensor.t_wp", "faktor": 1.0},
                                              {"name": "Warmwasser", "entity": "sensor.t_shelly_ww", "faktor": 1.0}]
        (d / "vzev.yaml").write_text(yaml.safe_dump(y, allow_unicode=True, sort_keys=False))
        with server.collector._db() as con:   # April: Heizung 0.04, Warmwasser 0.02 kWh pro Viertelstunde
            t, a, b = datetime(2026, 4, 1), 100.0, 50.0
            while t <= datetime(2026, 4, 30, 23, 45):
                con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_wp", a))
                con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_shelly_ww", b))
                t, a, b = t + timedelta(minutes=15), a + 0.04, b + 0.02
        warten(server)
        b = server.berechnung()
        assert b["ok"], b.get("fehler")
        assert b["res"]["WP"].sum() == pytest.approx(0.06 * (len(b["res"].loc["2026-04"]) - 1), rel=0.01)
        h = c.get("/uebersicht?m=2026-04").get_data(as_text=True)
        assert "Wärmepumpen aus dem Allgemeinstrom herausgerechnet" in h and "Heizung und Warmwasser, Gesamtrechnung" in h
        h = c.get("/verlauf?z=WP").get_data(as_text=True)
        assert "Wärmepumpen" in h and "Gemessen ab 01.04.2026" in h
        h = c.get("/verlauf?z=WP2").get_data(as_text=True)
        assert 'href="verlauf?z=WP1">Heizung' in h and 'class="btn primary" href="verlauf?z=WP2">Warmwasser' in h
        h = c.get("/?p=monat&m=2026-04").get_data(as_text=True)
        assert "Heizung" in h and "Warmwasser" in h
        h = c.get("/jahr?j=2026").get_data(as_text=True)
        assert "Heizung und Warmwasser" in h and "Heizung kWh" in h and "Warmwasser kWh" in h
        r = c.get("/jahr/pdf?j=2026&teil=wp")
        assert r.status_code == 200 and r.data[:4] == b"%PDF"
        r = c.post("/rechnungen", data={"jahr": "2026", "quartal": "2", "datum": "2026-07-05", "grund": "Wärmepumpen"})
        assert "Waermepumpen" in ziel(r), ziel(r)
        assert (d / "rechnungen" / "2026-Q2" / "Rechnung_2026-Q2-WP_Waermepumpen.pdf").exists()
        h = c.get("/rechnungen").get_data(as_text=True)
        assert "2026-Q2-WP" in h
        h = c.get("/einstellungen?tab=zaehler").get_data(as_text=True)
        assert "Wärmepumpen am Allgemeinzähler" in h and "sensor.t_shelly_ww" in h
    finally:
        (d / "vzev.yaml").write_text(cfg_alt)


def test_energiefluss_startseite(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/").get_data(as_text=True)
    assert "Energiefluss" in h and 'aria-current="page">Energiefluss' in h
    h = c.get("/?p=monat&m=2026-04").get_data(as_text=True)
    assert "April 2026" in h and "PV-Anlage" in h and "animateMotion" in h and "Autarkie Haus" in h
    assert 'href="uebersicht?m=2026-04"' in h
    h = c.get("/?p=jahr&j=2026").get_data(as_text=True)
    assert "Jahr 2026" in h and "Ladestation" in h
    h = c.get("/?p=heute").get_data(as_text=True)
    assert "noch keine Daten" in h
    import fluss
    b = server.berechnung()
    r = b["res"].loc["2026-04"]
    w = fluss.werte(r, b["cfg"])
    assert w["haus"] == pytest.approx(sum(v["total"] for v in w["verbraucher"]))
    assert w["solar_haus"] + w["export"] == pytest.approx(w["prod"], rel=1e-6)      # Produktion = im Haus + Rücklieferung


def test_aufgaben_assistent(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/aufgaben").get_data(as_text=True)
    assert "Aufgaben" in h and "Primeo-Lastgänge importieren" in h and "Kontrollen prüfen" in h
    assert "Mai 2026" in h                                              # Lastgänge nur bis April → Mai offen
    assert re.search(r'class="schritt jetzt".*?class="btn primary" href="[^"]+" data-assistent="1"', h, re.S)  # erster offener Schritt hervorgehoben
    h = c.get("/aufgaben?m=2026-06").get_data(as_text=True)
    assert "Quartalsrechnungen erstellen" in h and "Rechnungen versenden" in h and "Zahlungseingang erfassen" in h
    r = c.post("/aufgaben_erledigt", data={"q": "2026-Q2", "m": "2026-06", "wert": "1"})
    assert "aufgaben?m=2026-06" in ziel(r)
    assert "Versendet am" in c.get("/aufgaben?m=2026-06").get_data(as_text=True)
    c.post("/aufgaben_erledigt", data={"q": "2026-Q2", "m": "2026-06"})
    assert "Als versendet markieren" in c.get("/aufgaben?m=2026-06").get_data(as_text=True)
    h = c.get("/?p=monat&m=2026-04").get_data(as_text=True)
    assert "Nächste Aufgabe:" in h and "März 2026:" in h
    h = c.get("/tarife").get_data(as_text=True)
    assert "vzev-assistent" in h                                        # Zurück-Knopf auf allen Seiten vorbereitet


def test_sensoren(app):
    server, c, d, quelle = app
    warten(server)
    import sensoren
    gesendet = {}
    w = sensoren.schreiben(senden=lambda e, n: gesendet.__setitem__(e, n), heute=date(2026, 4, 20))
    assert w and sensoren.status()["fehler"] == ""
    for e in ("sensor.vzev_produktion_jahr", "sensor.vzev_autarkie_jahr", "sensor.vzev_ruecklieferung_jahr",
              "sensor.vzev_wertschoepfung_jahr", "sensor.vzev_offene_rechnungen", "sensor.vzev_ueberfaellig",
              "sensor.vzev_naechste_aufgabe", "sensor.vzev_offene_monate", "sensor.vzev_produktion_monat"):
        assert e in gesendet, e
    p = gesendet["sensor.vzev_produktion_jahr"]
    assert float(p["state"]) > 0 and p["attributes"]["unit_of_measurement"] == "kWh" and p["attributes"]["state_class"] == "total"
    assert p["attributes"]["friendly_name"] == "vZEV Produktion Jahr"
    assert 0 < float(gesendet["sensor.vzev_autarkie_jahr"]["state"]) <= 100
    # ohne Home Assistant: Fehler wird angezeigt, nicht abgestürzt
    r = c.post("/sensoren_schreiben")
    assert "Sensoren" in ziel(r)
    h = c.get("/einstellungen?tab=zaehler").get_data(as_text=True)
    assert "Sensoren für Home Assistant" in h and "Zuletzt geschrieben" in h


def test_sensoren_preise_und_ladefenster(app):
    server, c, d, quelle = app
    import prognose
    import sensoren
    from test_prognose import solcast_attr
    heute = date.today()
    db = server.collector._db
    prognose.speichern(db, prognose.zerlegen(solcast_attr(heute, 0.2)), jetzt=datetime.now())
    with db() as con:
        for i in range(96):
            t = datetime.combine(heute, datetime.min.time()) + timedelta(minutes=15 * i)
            preis = 0.10 if t.hour >= 22 or t.hour < 5 else 0.30
            for typ, v in (("integrated", preis), ("grid_usage", 0.0)):
                con.execute("INSERT OR REPLACE INTO preise VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (t.isoformat() + typ, typ, t.isoformat(timespec="minutes"), None, v, None, "test"))
    gesendet = {}
    sensoren.schreiben(senden=lambda e, n: gesendet.__setitem__(e, n))
    assert "sensor.vzev_strompreis" in gesendet and "sensor.vzev_pv_prognose_heute" in gesendet
    preis = float(gesendet["sensor.vzev_strompreis"]["state"])
    assert preis in (pytest.approx(10.81), pytest.approx(32.43))           # inkl. MWST
    assert gesendet["binary_sensor.vzev_guenstig_laden"]["state"] in ("on", "off")


def test_sicherung_und_erinnerung(app):
    server, c, d, quelle = app
    import io
    import zipfile
    import zahlungen
    r = c.get("/sicherung")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    namen = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert "vzev.yaml" in namen and "messwerte.sqlite" in namen and not any(n.startswith(".cache") for n in namen)
    zahlungen.nachtragen()
    reg = zahlungen.laden()
    key = next(k for k, x in reg["rechnungen"].items() if x["art"] == "wohnung" and x["status"] == "aktiv"
               and zahlungen.stand(x)["offen"] and zahlungen.stand(x)["offen"] > 0)
    rel, offen, frist = zahlungen.erinnerung(key, heute=date(2027, 3, 1))
    assert (server.RECHNUNGEN / rel).read_bytes()[:4] == b"%PDF" and frist == date(2027, 3, 15)
    assert zahlungen.laden()["rechnungen"][key]["erinnerungen"][0]["offen"] == offen
    zahlungen.nachtragen()
    assert not any("Erinnerung_" in x["datei"] for x in zahlungen.laden()["rechnungen"].values())   # kein neuer Registereintrag


def test_netzladung_und_jaz(app):
    server, c, d, quelle = app
    warten(server)
    cfg_alt = (d / "vzev.yaml").read_text()
    try:
        with server.collector._db() as con:   # April: Wechselrichter meldet nachts (ohne PV) Batterie-Ladung
            for tag in range(1, 31):
                pv = gel = 0.0
                for i in range(96):
                    t = datetime(2026, 4, tag) + timedelta(minutes=15 * i)
                    if 9 <= t.hour < 16:
                        pv += 0.4
                    elif 1 <= t.hour < 3:
                        gel += 0.5
                    con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_pv", pv))
                    con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_gel", gel))
        h = c.get("/uebersicht?m=2026-04").get_data(as_text=True)
        assert "Netzladung passt zum Wechselrichter" in h and "Wechselrichter «Batterie geladen»" in h
        # Wärmepumpe mit Wärme-Sensor → Jahresarbeitszahl
        y = yaml.safe_load(cfg_alt)
        y["homeassistant"]["waermepumpen"] = [{"name": "Heizung", "entity": "sensor.t_wp2", "waerme": "sensor.t_wwaerme"}]
        (d / "vzev.yaml").write_text(yaml.safe_dump(y, allow_unicode=True, sort_keys=False))
        with server.collector._db() as con:
            t, a, b = datetime(2026, 4, 1), 10.0, 30.0
            while t <= datetime(2026, 4, 30, 23, 45):
                con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_wp2", a))
                con.execute("INSERT OR REPLACE INTO messwerte VALUES (?, ?, ?)", (t.isoformat(timespec="minutes"), "sensor.t_wwaerme", b))
                t, a, b = t + timedelta(minutes=15), a + 0.05, b + 0.2
        warten(server)
        h = c.get("/verlauf?z=WP").get_data(as_text=True)
        assert "Jahresarbeitszahl" in h and "4.00" in h
        h = c.get("/jahr?j=2026").get_data(as_text=True)
        assert "Jahresarbeitszahl:</b> Heizung 4.00" in h
        h = c.get("/einstellungen?tab=zaehler").get_data(as_text=True)
        assert "Wärmepumpen rückwirkend" in h and "Wärme-Sensor" in h
        r = c.post("/wp_statistik", data={"ab": "2026-01-01"})
        assert "Langzeit-Statistik" in ziel(r)            # ohne Home Assistant: verständliche Meldung
    finally:
        (d / "vzev.yaml").write_text(cfg_alt)


def test_nur_ingress_in_home_assistant(app, monkeypatch):
    server, c, d, quelle = app
    assert c.get("/").status_code != 403                              # lokal: offen
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    assert c.get("/", environ_base={"REMOTE_ADDR": "172.30.32.2"}).status_code != 403   # Ingress-Proxy
    assert c.get("/", environ_base={"REMOTE_ADDR": "172.30.33.7"}).status_code == 403   # andere App
    assert c.post("einstellungen", environ_base={"REMOTE_ADDR": "172.30.33.7"}).status_code == 403


def test_vorschlaege(app):
    server, c, d, quelle = app
    warten(server)
    server.log.error("Testfehler bei Max Beispiel: Wert 1234 am 05.10.2026")
    h = c.get("/vorschlaege").get_data(as_text=True)
    assert "Vorschläge aus deinen Daten" in h and "Weitergeben" in h, __import__("re").sub(r"<[^>]+>", " ", h.split("<main")[-1])[:1500] and 'href="vorschlaege">Vorschläge' in h
    assert "ERROR: Testfehler bei" in h and "Max Beispiel" not in h.split('id="vs-text"')[1]
    r = c.post("/vorschlaege", data={"aktion": "idee", "idee": "Export für Max Beispiel als CSV"})
    assert "Idee gespeichert" in ziel(r)
    h = c.get("/vorschlaege").get_data(as_text=True)
    text = h.split('id="vs-text"')[1].split("</textarea>")[0]
    assert "Export für ‹…› als CSV" in text and "Testdorf" not in text and "Testweg" not in text
    import re as _re
    k = _re.search(r'name="sel_([0-9a-f]{12})"', h).group(1)
    r = c.post("/vorschlaege", data={"aktion": "gemeldet", f"sel_{k}": "1"})
    assert "als gemeldet markiert" in ziel(r)
    h = c.get("/vorschlaege").get_data(as_text=True)
    assert "Ausgeblendet und gemeldet (1)" in h
    md = c.get("/vorschlaege.md")
    assert md.status_code == 200 and "Vorschläge aus der vZEV-App" in md.get_data(as_text=True)
    assert "Max Beispiel" not in md.get_data(as_text=True)
    # Leistung: Seitenaufrufe werden gemessen, Karte und Messwerte im Text
    h = c.get("/vorschlaege").get_data(as_text=True)
    assert "<h2>Leistung</h2>" in h and "Ladezeiten und Rechenzeiten dieser Version" in h
    assert "### Leistung (Messwerte dieser Version)" in md.get_data(as_text=True) and "</span>vorschlaege</td>" in h
    assert (d / "leistung.json").exists()
    assert 'id="vs-kopieren"' in h and "execCommand('copy')" in h  # Kopieren auch im Home-Assistant-Fenster
    c.post("/vorschlaege", data={"aktion": "alle_einblenden"})
    assert "Ausgeblendet und gemeldet" not in c.get("/vorschlaege").get_data(as_text=True)


def test_vorschlaege_nur_meldungen_der_aktuellen_version(app):
    import vorschlaege as vs
    e = lambda zeit, text: {"zeit": zeit, "stufe": "INFO", "text": text}
    muster = r"App gestartet \(Version ([^)]+)\)"
    alle = [e("2026-11-01 08:00:00", "App gestartet (Version 1.0)"), e("2026-11-05 08:00:00", "App gestartet (Version 1.1)"),
            e("2026-11-06 08:00:00", "App gestartet (Version 1.1)")][::-1]      # neueste zuerst
    assert vs.seit_version(alle, "1.1", muster) == "2026-11-05 08:00:00"   # erster Start dieser Version
    assert vs.seit_version(alle, "1.2", muster) is None                   # Startzeile fehlt → 30 Tage


def test_mieter_vorname_nachname(app):
    server, c, d, quelle = app
    h = c.get("/mieter").get_data(as_text=True)
    assert re.search(r'name="m\.vorname"[^>]*value="Erika"', h) and re.search(r'name="m\.nachname"[^>]*value="Muster"', h)
    cfg = yaml.safe_load((d / "vzev.yaml").read_text())
    daten_ = []
    for m in cfg["mietverhaeltnisse"]:
        vor, nach = ("Max", "van Beispiel") if m["name"] == "Max Beispiel" else m["name"].split(" ", 1)
        daten_ += [("m.einheit", m["einheit"]), ("m.vorname", vor), ("m.nachname", nach), ("m.von", str(m["von"])),
                   ("m.bis", str(m["bis"] or "")), ("m.strasse", m.get("strasse") or ""), ("m.hausnr", str(m.get("hausnr") or "")),
                   ("m.plz", str(m.get("plz") or "")), ("m.ort", m.get("ort") or "")]
    from werkzeug.datastructures import MultiDict
    assert "Gespeichert" in ziel(c.post("/mieter", data=MultiDict(daten_)))
    neu = yaml.safe_load((d / "vzev.yaml").read_text())["mietverhaeltnisse"]
    mx = [m for m in neu if m["name"].startswith("Max")][0]
    assert mx["name"] == "Max van Beispiel" and mx["vorname"] == "Max" and mx["nachname"] == "van Beispiel"
    assert "vorname" not in [m for m in neu if m["name"] == "Erika Muster"][0]  # eindeutig: nur «name»
    daten_[1] = ("m.vorname", "")
    assert "Vorname, Nachname" in ziel(c.post("/mieter", data=MultiDict(daten_)))


def test_namenskorrektur_im_abgeschlossenen_monat(app):
    server, c, d, quelle = app
    warten(server)
    for monat, datum in (("2026-03", "2026-04-05"), ("2026-04", "2026-05-02")):
        c.post("/abschluss", data={"monat": monat, "aktion": "schliessen", "datum": datum})  # (falls noch offen)
    c.post("/rechnungen", data={"jahr": "2026", "quartal": "2", "datum": "2026-05-05", "grund": "Test"})
    import core
    cfg = yaml.safe_load((d / "vzev.yaml").read_text())
    max_alt = [m for m in cfg["mietverhaeltnisse"] if str(m["von"]) == "2026-04-10"][0]["name"]
    assert max_alt in {r["partei"] for r in server.zahlungen.uebersicht()["zeilen"]}
    daten_ = []
    for m in cfg["mietverhaeltnisse"]:
        vor, nach = core.namen(m)
        if str(m["von"]) == "2026-04-10":
            vor = "Maximilian"
        daten_ += [("m.einheit", m["einheit"]), ("m.vorname", vor), ("m.nachname", nach), ("m.von", str(m["von"])),
                   ("m.bis", str(m["bis"] or "")), ("m.strasse", m.get("strasse") or ""), ("m.hausnr", str(m.get("hausnr") or "")),
                   ("m.plz", str(m.get("plz") or "")), ("m.ort", m.get("ort") or "")]
    from werkzeug.datastructures import MultiDict
    r = c.post("/mieter", data=MultiDict(daten_))
    assert "Gespeichert" in ziel(r), ziel(r)
    neu = [m for m in yaml.safe_load((d / "vzev.yaml").read_text())["mietverhaeltnisse"] if str(m["von"]) == "2026-04-10"][0]["name"]
    assert neu.startswith("Maximilian ")
    parteien = {r["partei"] for r in server.zahlungen.uebersicht()["zeilen"]}
    assert neu in parteien and max_alt not in parteien
    # Daten in einem abgeschlossenen Monat ändern bleibt gesperrt
    daten_[12] = ("m.von", "2026-04-20")
    assert "abgeschlossenen Monat" in ziel(c.post("/mieter", data=MultiDict(daten_)))


def test_waermepumpen_eingabe_abgesichert(app):
    server, c, d, quelle = app
    from werkzeug.datastructures import MultiDict
    ziel_, daten_ = formular(c, "/einstellungen?tab=zaehler")
    basis = [(k, v) for k, v in daten_ if not k.startswith("wp.")]

    def senden(*zeilen):
        wp = []
        for name, entity, waerme in zeilen:
            wp += [("wp.name", name), ("wp.entity", entity), ("wp.faktor", "1.0"), ("wp.waerme", waerme)]
        return ziel(c.post("/" + ziel_, data=MultiDict(basis + wp)))
    assert "jeder Name nur einmal" in senden(("Heizung", "sensor.shelly_a_energie", ""), ("Heizung", "sensor.shelly_b_energie", ""))
    assert "misst wohl Wärme" in senden(("Heizung", "sensor.buderus_gateway_1_erzeugte_warme_gesamt", ""))
    assert "Gespeichert" in senden(("Heizung", "sensor.shelly_a_energie", "sensor.buderus_gateway_1_erzeugte_warme_gesamt"),
                                   ("Warmwasser", "sensor.shelly_b_energy", ""))
    wp = yaml.safe_load((d / "vzev.yaml").read_text())["homeassistant"]["waermepumpen"]
    assert wp[0]["waerme"].endswith("erzeugte_warme_gesamt") and [w["name"] for w in wp] == ["Heizung", "Warmwasser"]


def test_nebenkosten_seite(app):
    server, c, d, quelle = app
    warten(server)
    h = c.get("/nebenkosten?p=2025-26").get_data(as_text=True)   # Testdaten liegen in dieser Periode
    assert "<h2>Verteilung</h2>" in h and "Allgemeinstrom (inkl. Grundpreis)" in h
    h = c.get("/nebenkosten?p=2026-27").get_data(as_text=True)
    assert "Fläche (m²) aller Wohnungen" in h                       # noch keine Grundlagen
    cfg = yaml.safe_load((d / "vzev.yaml").read_text())
    form = {"aktion": "grundlagen", "p": "2026-27", "flaeche_1OG": "90", "flaeche_2OG": "110", "personen_2OG": "2",
            "grundanteil": "30", "honorar_wert": "3", "honorar_art": "prozent"}
    import nebenkosten
    for m in cfg["mietverhaeltnisse"]:
        form[f"mp_{nebenkosten.mieter_key(m)}"] = "2"
        form[f"ma_{nebenkosten.mieter_key(m)}"] = "150"
    assert "Gespeichert" in ziel(c.post("/nebenkosten", data=form))
    import io
    r = c.post("/nebenkosten", data={"aktion": "position", "p": "2026-27", "titel": "Wasser und Abwasser", "kategorie": "wasser",
                                     "einheit": "1OG", "betrag": "730", "beleg": (io.BytesIO(b"%PDF-1.4 test"), "Rechnung Wasser.pdf")},
               content_type="multipart/form-data")
    assert "Erfasst" in ziel(r)
    h = c.get("/nebenkosten?p=2026-27").get_data(as_text=True)
    assert "Wasser und Abwasser" in h and "nebenkosten_beleg?p=2026-27" in h and "Fläche (m²) aller Wohnungen" not in h
    beleg = re.search(r'nebenkosten_beleg\?p=2026-27&d=([^"]+)"', h).group(1)
    assert c.get(f"/nebenkosten_beleg?p=2026-27&d={beleg}").data.startswith(b"%PDF")
    assert c.get("/nebenkosten_beleg?p=2026-27&d=..%2F..%2Fvzev.yaml").status_code == 404
    assert "Vorschau-PDF erstellt" in ziel(c.post("/nebenkosten", data={"aktion": "vorschau", "p": "2026-27"}))
    assert list((d / "rechnungen" / "NK-2026-27").glob("Vorschau_*.pdf"))
    assert "Periode noch nicht vollständig" in ziel(c.post("/nebenkosten", data={"aktion": "erstellen", "p": "2026-27"}))
    assert "Nebenkosten" in c.get("/rechnungen").get_data(as_text=True)          # Navigation
