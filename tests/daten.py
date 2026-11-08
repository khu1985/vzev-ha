"""Synthetische Testdaten im Format der Primeo-Lastgänge und des go-e-Exports.

Keine echten Daten: erfundene Messpunkte, Namen und eine Beispiel-IBAN.
Die Werte sind so gewählt, dass sich die Ergebnisse von Hand nachrechnen lassen:
- Produktion 2.0 kWh pro Viertelstunde von 08:00 bis 15:45, sonst 0
- 1. OG 0.10, 2. OG 0.20, Allgemein 0.10 kWh pro Viertelstunde (+ Ladestation)
- Netzbezug PV-Anlage 0.01 kWh pro Viertelstunde, wenn nicht produziert wird
- Ladestation: am 10. jedes Monats 12:00–13:00 (4 kWh, Solar) und 22:00–23:00 (2 kWh, Netz)
"""
from datetime import date, datetime, time, timedelta
from pathlib import Path

import openpyxl
import pandas as pd
import yaml

MP = {k: f"CH9999999999900000000000000TEST{i}" for i, k in enumerate(["1OG", "2OG", "Allg", "PVA", "Prod"], 1)}
VON, BIS = date(2026, 3, 1), date(2026, 4, 30)
IBAN = "CH9300762011623852957"
LADUNGEN = [(12, 4.0), (22, 2.0)]  # Startstunde, kWh (je 1 Stunde)


def viertelstunden(von=VON, bis=BIS):
    """Lokale Zeit wie bei Primeo: Sommerzeit-Lücke am 29.03. (02:00–02:45 fehlen)."""
    idx = pd.date_range(pd.Timestamp(von), pd.Timestamp(bis) + pd.Timedelta(hours=23, minutes=45), freq="15min")
    return idx[~((idx.date == date(2026, 3, 29)) & (idx.hour == 2))]


def ht(ts):
    return ts.dayofweek < 5 and 7 <= ts.hour < 20


def werte(key, ts):
    tag = 8 <= ts.hour < 16
    if key == "Prod":
        return 2.0 if tag else 0.0
    if key == "PVA":
        return 0.0 if tag else 0.01
    if key == "1OG":
        return 0.10
    if key == "2OG":
        return 0.20
    v = 0.10
    if ts.day == 10:
        for h, kwh in LADUNGEN:
            if ts.hour == h:
                v += kwh / 4
    return v


def lastgang_xlsx(pfad, key, text_datum=False, summenzeile=False, zeit_als_datetime=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lastgang"
    ws["A1"] = "Lastgang"
    ws["A4"], ws["C4"] = "Messpunkt", MP[key]
    ws["A5"], ws["C5"] = "Lieferstelle", f"Testweg 1, 9999 Testdorf ({key})"
    for c, t in zip("ABCD", ["Datum", "Uhrzeit", "kWh", "Tarif"]):
        ws[f"{c}9"] = t
    r = 10
    summe = 0.0
    for ts in viertelstunden():
        d = ts.to_pydatetime()
        ws.cell(r, 1, d.strftime("%d.%m.%Y") if text_datum else datetime(d.year, d.month, d.day))
        ws.cell(r, 2, datetime(1900, 1, 1, d.hour, d.minute) if zeit_als_datetime else time(d.hour, d.minute))
        v = werte(key, ts)
        summe += v
        ws.cell(r, 3, v)
        ws.cell(r, 4, "HT" if ht(ts) else "NT")
        r += 1
    if summenzeile:
        ws.cell(r + 1, 1, "Summe")
        ws.cell(r + 1, 3, summe)
    wb.save(pfad)


def wallbox_csv(pfad, sekunden=True):
    kopf = ('"Session Number";"Start";"Ende";"Energie [kWh]";"Zaehlerstand Differenz [kWh]";'
            '"Zaehlerstand Anfang [kWh]";"Zaehlerstand Ende [kWh]"')
    zeilen, n, stand = [kopf], 1, 0.0
    fmt = "%d.%m.%Y %H:%M:%S" if sekunden else "%d.%m.%Y %H:%M"
    for monat in (3, 4):
        for h, kwh in LADUNGEN:
            s = datetime(2026, monat, 10, h, 0, 7 if sekunden else 0)
            e = s + timedelta(minutes=59)
            k = f"{kwh:.2f}".replace(".", ",")
            zeilen.append(f'"{n}";"{s.strftime(fmt)}";"{e.strftime(fmt)}";"{k}";"{k}";"{stand:.2f}";"{stand + kwh:.2f}"')
            n, stand = n + 1, stand + kwh
    Path(pfad).write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def konfiguration(pfad, ruecklieferung_april=0.06):
    cfg = {
        "betreiber": {"name": "Test Betreiber", "strasse": "Testweg", "hausnr": "1", "plz": "9999", "ort": "Testdorf",
                      "bank": "Testbank", "iban": IBAN},
        "vzev_start": date(2026, 3, 1),
        "messpunkte": {v: k for k, v in MP.items()},
        "tarife": {
            "solar": [{"ab": date(2026, 3, 1), "chf": 0.20}],
            "netz": [{"ab": date(2026, 1, 1), "ht": 0.30, "nt": 0.25}],
            "ruecklieferung": [{"ab": date(2026, 1, 1), "chf": 0.10}, {"ab": date(2026, 4, 1), "chf": ruecklieferung_april}],
            "grundpreis_zaehler": [{"ab": date(2026, 3, 1), "chf": 8.25}],
        },
        "mietverhaeltnisse": [
            {"einheit": "1OG", "name": "Erika Muster", "von": date(2026, 1, 1), "bis": date(2026, 3, 20),
             "strasse": "Testweg", "hausnr": "1", "plz": "9999", "ort": "Testdorf"},
            {"einheit": "1OG", "name": "Max Beispiel", "von": date(2026, 4, 10), "bis": None,
             "strasse": "Testweg", "hausnr": "1", "plz": "9999", "ort": "Testdorf"},
        ],
        "regeln": {"pva_standby_auf": "Allg", "allgemein_rechnung": "gesamt", "allgemein_mieteranteil": 0.5,
                   "ladestation_grundlast_kwh": 0.02},
        "manuell": {"ruecklieferung_vor_start": [], "uebrige_ertraege": []},
        "primeo_rechnungen": [],
        "rechnungen": {"zahlungsfrist_tage": 30, "nummer": "{jahr}-Q{quartal}-{einheit}"},
        "homeassistant": {"zaehler": {"1OG": "sensor.t_1og", "2OG": "sensor.t_2og", "Allg": "sensor.t_allg",
                                       "ladestation": "sensor.t_goe"},
                          "solis": {"pv_heute": "sensor.t_pv", "batterie_geladen_heute": "sensor.t_gel",
                                    "batterie_entladen_heute": "sensor.t_ent", "batterie_soc": "sensor.t_soc"}},
        "evcc": {},
    }
    Path(pfad).write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cfg


def datenordner(ordner, **varianten):
    """Legt vzev.yaml und primeo/ mit allen Dateien an. varianten werden an lastgang_xlsx für 1OG weitergegeben."""
    ordner = Path(ordner)
    (ordner / "primeo").mkdir(parents=True, exist_ok=True)
    konfiguration(ordner / "vzev.yaml")
    for key in MP:
        lastgang_xlsx(ordner / "primeo" / f"{key}.xlsx", key, **(varianten if key == "1OG" else {}))
    wallbox_csv(ordner / "primeo" / "Ladestation.csv")
    return ordner
