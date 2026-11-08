"""Rechnungsregister und Zahlungseingang.

Jede erstellte Rechnung wird in rechnungen/register.json festgehalten (Betrag, Rechnungsdatum, Fälligkeit).
Zahlungen werden von Hand erfasst. Wird ein Quartal korrigiert, übernimmt die neue Rechnung die bereits
erfassten Zahlungen der alten; die alte bleibt als «ersetzt» sichtbar.
Die Allgemeinstrom-Rechnung ist eine Gesamtrechnung für die Nebenkostenabrechnung und wird nicht bezahlt («intern»).
"""
import json
from datetime import date, datetime, timedelta

S = None


def _pfad():
    return S.RECHNUNGEN / "register.json"


def laden():
    try:
        return json.loads(_pfad().read_text(encoding="utf-8"))
    except Exception:
        return {"rechnungen": {}}


def speichern(reg):
    _pfad().parent.mkdir(parents=True, exist_ok=True)
    tmp = _pfad().with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_pfad())


def _meta(datei):
    """Rechnung_{nummer}_{name}.pdf → Nummer, Partei, Art."""
    stamm = datei[:-4] if datei.endswith(".pdf") else datei
    teile = stamm.split("_", 2)
    nummer = teile[1] if len(teile) > 1 else stamm
    name = teile[2] if len(teile) > 2 else ""
    art = "allgemein" if name == "Allgemeinstrom" or nummer.endswith("-ALLG") else "wohnung"
    return nummer, name, art


def _voller_name(cfg, kurz):
    for m in cfg.get("mietverhaeltnisse") or []:
        if m.get("name") and m["name"].split(" ")[-1] == kurz:
            return m["name"]
    return kurz


def registrieren(quartal, made, rechnungsdatum, cfg):
    """Nach dem Erstellen: neue Rechnungen eintragen, Zahlungen alter Fassungen übernehmen."""
    reg = laden()
    frist = int((cfg.get("rechnungen") or {}).get("zahlungsfrist_tage", 30))
    rd = rechnungsdatum or date.today()
    jetzt = datetime.now().strftime("%Y-%m-%d %H:%M")
    for name, total, _rows in made:
        nummer, partei, art = _meta(name)
        partei = _voller_name(cfg, partei)
        alte = [k for k, r in reg["rechnungen"].items() if r["nummer"] == nummer and r["status"] != "ersetzt"]
        zahlungen = []
        for k in alte:
            zahlungen += reg["rechnungen"][k].get("zahlungen", [])
            reg["rechnungen"][k]["status"] = "ersetzt"
            reg["rechnungen"][k]["ersetzt_am"] = jetzt
        key = f"{quartal}/{name}@{datetime.now():%Y%m%d%H%M%S%f}"
        reg["rechnungen"][key] = {
            "quartal": quartal, "datei": f"{quartal}/{name}", "nummer": nummer, "partei": partei, "art": art,
            "betrag": round(float(total), 2), "datum": rd.isoformat(),
            "faellig": (rd + timedelta(days=frist)).isoformat(), "erstellt": jetzt,
            "status": "aktiv", "zahlungen": zahlungen,
        }
    speichern(reg)


def nachtragen():
    """Rechnungen, die vor dem Register erstellt wurden: Betrag aus der aktuellen Berechnung, Datum der Datei."""
    reg = laden()
    bekannt = {r["datei"] for r in reg["rechnungen"].values()}
    fehlend = [p for p in S.RECHNUNGEN.glob("*/*.pdf") if p.parent.name != "_alt" and f"{p.parent.name}/{p.name}" not in bekannt]
    if not fehlend:
        return
    b = S.berechnung() if any(S.PRIMEO.iterdir()) else {}
    import invoices
    for p in fehlend:
        quartal = p.parent.name
        nummer, partei, art = _meta(p.name)
        partei = _voller_name(b.get("cfg") or S.config(), partei)
        betrag = None
        if b.get("ok"):
            try:
                j, q = int(quartal[:4]), int(quartal[-1])
                for inv in invoices.invoices_for_quarter(b["res"], b["cfg"], j, q):
                    n = b["cfg"]["rechnungen"]["nummer"].format(jahr=j, quartal=q, einheit=inv["einheit"])
                    if n == nummer:
                        betrag = round(sum(r["total"] for r in inv["rows"]), 2)
            except (ValueError, KeyError):
                pass
        rd = date.fromtimestamp(p.stat().st_mtime)
        frist = int((b.get("cfg") or S.config()).get("rechnungen", {}).get("zahlungsfrist_tage", 30))
        reg["rechnungen"][f"{quartal}/{p.name}@nachgetragen"] = {
            "quartal": quartal, "datei": f"{quartal}/{p.name}", "nummer": nummer, "partei": partei, "art": art,
            "betrag": betrag, "datum": rd.isoformat(), "faellig": (rd + timedelta(days=frist)).isoformat(),
            "erstellt": rd.isoformat(), "status": "aktiv", "zahlungen": [], "nachgetragen": True,
        }
    speichern(reg)


def stand(r, heute=None):
    heute = heute or date.today()
    bezahlt = round(sum(z["betrag"] for z in r.get("zahlungen", [])), 2)
    offen = None if r["betrag"] is None else round(r["betrag"] - bezahlt, 2)
    if r["status"] == "ersetzt":
        s = "ersetzt"
    elif r["art"] == "allgemein":
        s = "intern"
    elif offen is not None and offen <= 0.004:
        s = "bezahlt" if offen > -0.005 else "überzahlt"
    elif date.fromisoformat(r["faellig"]) < heute:
        s = "überfällig"
    elif bezahlt > 0:
        s = "teilweise"
    else:
        s = "offen"
    return dict(r, bezahlt=bezahlt, offen=offen, stand=s)


def uebersicht():
    nachtragen()
    reg = laden()
    zeilen = sorted((dict(stand(r), key=k) for k, r in reg["rechnungen"].items()),
                    key=lambda r: (r["status"] == "ersetzt", r["quartal"], r["nummer"], r["erstellt"]), reverse=False)
    zeilen.sort(key=lambda r: (r["status"] == "ersetzt", -int(r["quartal"][:4]) * 10 - int(r["quartal"][-1])))
    aktiv = [z for z in zeilen if z["stand"] in ("offen", "teilweise", "überfällig")]
    return dict(zeilen=zeilen,
                offen=round(sum(z["offen"] or 0 for z in aktiv), 2),
                ueberfaellig=round(sum(z["offen"] or 0 for z in aktiv if z["stand"] == "überfällig"), 2),
                n_ueberfaellig=sum(1 for z in aktiv if z["stand"] == "überfällig"))


def zahlung(key, datum, betrag, notiz=""):
    reg = laden()
    r = reg["rechnungen"][key]
    r.setdefault("zahlungen", []).append({"datum": datum.isoformat(), "betrag": round(betrag, 2), "notiz": notiz,
                                          "erfasst": datetime.now().strftime("%Y-%m-%d %H:%M")})
    speichern(reg)
    return r


def daten_aendern(key, datum, faellig=None):
    """Rechnungsdatum (und Fälligkeit) im Register anpassen, z. B. wenn die Rechnung früher verschickt wurde.
    Ohne Fälligkeit wird sie aus Datum + Zahlungsfrist berechnet. Das PDF selbst bleibt unverändert."""
    reg = laden()
    r = reg["rechnungen"][key]
    if faellig is None:
        frist = int((S.config().get("rechnungen") or {}).get("zahlungsfrist_tage", 30))
        faellig = datum + timedelta(days=frist)
    if faellig < datum:
        raise ValueError("Die Fälligkeit liegt vor dem Rechnungsdatum")
    alt = (r["datum"], r["faellig"])
    r["datum"], r["faellig"] = datum.isoformat(), faellig.isoformat()
    r.setdefault("aenderungen", []).append({"zeit": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                            "vorher": {"datum": alt[0], "faellig": alt[1]},
                                            "nachher": {"datum": r["datum"], "faellig": r["faellig"]}})
    speichern(reg)
    return r, alt


def zahlung_entfernen(key, index):
    reg = laden()
    z = reg["rechnungen"][key]["zahlungen"].pop(index)
    speichern(reg)
    return reg["rechnungen"][key], z


def register(app, server):
    global S
    S = server
