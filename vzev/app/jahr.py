"""Jahresabrechnung: Allgemeinstrom fürs Jahr (PDF für die Nebenkostenabrechnung), Mieter, Wertschöpfung, Excel-Export.

Grundlage sind ausschliesslich die Primeo-Lastgänge (keine Vorschau aus Home Assistant).
"""
import io
from datetime import date

import pandas as pd
from flask import redirect, render_template_string, request, send_file

import core
import invoices
import seiten
import zahlungen

S = None
ZL = core.ZL


def _jahre(b, cfg):
    start = seiten._d(cfg.get("vzev_start")) or date.today()
    ende = b["res"].index.max().year if b.get("ok") else date.today().year
    return list(range(ende, start.year - 1, -1))


def daten(jahr):
    """Alle Werte eines Jahres; None, wenn keine Berechnung vorliegt."""
    b = S.berechnung() if any(S.PRIMEO.iterdir()) else {"ok": False, "fehler": "keine Dateien importiert"}
    if not b.get("ok"):
        return b, None
    res, cfg = b["res"], b["cfg"]
    start = max(date(jahr, 1, 1), seiten._d(cfg.get("vzev_start")) or date(jahr, 1, 1))
    ende_daten = res.index.max().date()
    bis = min(date(jahr, 12, 31), ende_daten)
    r = res[(res.index >= pd.Timestamp(start)) & (res.index < pd.Timestamp(bis) + pd.Timedelta(days=1))]
    if r.empty:
        return b, None
    allg = invoices.lines_for(res, cfg, "AllgC", start, bis)
    mit_wp = bool((cfg.get("homeassistant") or {}).get("waermepumpen"))
    wp = invoices.lines_for(res, cfg, "WP", start, bis, grundpreis_ja=False) if mit_wp else []
    wp_einzeln = {}
    if mit_wp:
        try:
            import vorschau
            t = vorschau.unterzaehler_einzeln(S.collector._db, cfg, start)
            if t is not None:
                t = t[(t.index >= pd.Timestamp(start)) & (t.index < pd.Timestamp(bis) + pd.Timedelta(days=1))]
                wp_einzeln = {n: t[n].groupby(t.index.to_period("M")).sum() for n in t.columns}
        except Exception:
            S.log.exception("Wärmepumpen-Zähler nicht lesbar")
    try:
        import vorschau
        wp_jaz = vorschau.jaz(S.collector._db, cfg, start, bis) if mit_wp else {}
    except Exception:
        S.log.exception("Jahresarbeitszahl")
        wp_jaz = {}
    # Mieter
    reg = zahlungen.uebersicht()["zeilen"]
    mieter = []
    for m in cfg.get("mietverhaeltnisse") or []:
        von = max(seiten._d(m["von"]), start)
        mb = seiten._d(m.get("bis"))
        mbis = min(mb, bis) if mb else bis
        if von > mbis:
            continue
        rows = invoices.lines_for(res, cfg, m["einheit"], von, mbis)
        kurz = m["name"].split(" ")[-1]
        rech = [x for x in reg if x["art"] == "wohnung" and x["stand"] != "ersetzt" and x["quartal"].startswith(str(jahr))
                and (x["partei"] == m["name"] or x["partei"] == kurz)]
        mieter.append(dict(name=m["name"], vorname=core.namen(m)[0] or m["name"], einheit=m["einheit"], von=von, bis=mbis, laufend=mb is None or mb > bis,
                           kwh=sum(x["solar"] + x["ht"] + x["nt"] for x in rows), solar=sum(x["solar"] for x in rows),
                           betrag=round(sum(x["total"] for x in rows), 2),
                           gestellt=round(sum(x["betrag"] or 0 for x in rech), 2), bezahlt=round(sum(x["bezahlt"] for x in rech), 2),
                           rechnungen=[x["nummer"] for x in rech]))
    # Zähler pro Monat
    monate = {}
    for k, label in ZL:
        s = core.zaehler_summen(r, k)
        for p, z in s.iterrows():
            monate.setdefault(p, {})[k] = z
    w = core.wertschoepfung(res, cfg)
    w = w[[p.year == jahr for p in w.index]]
    ab = seiten.abschluss_laden()["monate"]
    perioden = [p for p in pd.period_range(start, bis, freq="M")]
    alle_monate = [p for p in pd.period_range(start, date(jahr, 12, 31), freq="M")]
    offen = [str(p) for p in alle_monate if str(p) not in ab]
    kennzahlen = dict(
        produktion=float(r["Prod"].sum()), export=float(r["Export"].sum()),
        export_chf=float((r["Export"] * r["exprice"]).sum(min_count=1)) if r["exprice"].notna().any() else None,
        export_offen=bool(r["exprice"].isna().any()),
        solar=float(sum(r[f"S_{k}"].sum() for k, _ in ZL)), netz=float(sum(r[f"N_{k}"].sum() + r[f"P_{k}"].sum() for k, _ in ZL)),
        wert=float(w["total_chf"].sum()), allg=round(sum(x["total"] for x in allg), 2), wp=round(sum(x["total"] for x in wp), 2),
        wp_kwh=sum(x["solar"] + x["ht"] + x["nt"] + x["speicher"] for x in wp))
    kennzahlen["autarkie"] = kennzahlen["solar"] / (kennzahlen["solar"] + kennzahlen["netz"]) * 100 if kennzahlen["solar"] + kennzahlen["netz"] else 0
    wp_ab = r.index[r["WP_gemessen"] > 0].min() if mit_wp and (r["WP_gemessen"] > 0).any() else None
    return b, dict(jahr=jahr, von=start, bis=bis, daten_bis=ende_daten, allg=allg, wp=wp, wp_einzeln=wp_einzeln, wp_ab=wp_ab, wp_jaz=wp_jaz,
                   mit_wp=mit_wp, mieter=mieter, monate=monate,
                   perioden=perioden, w=w, offen=offen, vorlaeufig=bool(offen) or bis < date(jahr, 12, 31),
                   k=kennzahlen, res=r, cfg=cfg)


SEITE = """
<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin:-8px 0 16px">
<form method="get" action="jahr"><select name="j" onchange="this.form.submit()">{% for y in jahre %}<option {{ 'selected' if y == jahr }}>{{ y }}</option>{% endfor %}</select></form>
{% if d %}<div style="display:flex;gap:8px;flex-wrap:wrap">
<a class="btn primary" href="jahr/pdf?j={{ jahr }}" target="_blank">PDF Allgemeinstrom</a>
{% if d.mit_wp %}<a class="btn primary" href="jahr/pdf?j={{ jahr }}&teil=wp" target="_blank">PDF Heizung und Warmwasser</a>{% endif %}
<a class="btn" href="jahr/excel?j={{ jahr }}">Excel</a>
<a class="btn" href="jahr/excel?j={{ jahr }}&viertelstunden=1" title="Zusätzlich alle Viertelstunden des Jahres (grosse Datei)">Excel mit Viertelstunden</a></div>{% endif %}</div>
{% if not d %}<div class="msg warn">Keine Daten für {{ jahr }}{% if fehler %}: {{ fehler }}{% endif %}.</div>{% else %}
{% if d.vorlaeufig %}<div class="msg warn">Vorläufig: Lastgänge bis {{ d.daten_bis.strftime('%d.%m.%Y') }}{% if d.offen %}, noch nicht abgeschlossen: {{ d.offen|join(', ') }}{% endif %}.
Die Zahlen können sich bis zum Abschluss aller Monate ändern.</div>{% else %}<div class="msg ok">Alle Monate von {{ jahr }} sind abgeschlossen.</div>{% endif %}
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div class="t">Allgemeinstrom {{ jahr }}</div><div class="v">{{ d.k.allg|f2 }} <small>CHF</small></div><div class="s">für die Nebenkostenabrechnung</div></div>
 {% if d.mit_wp %}<div class="kpi"><div class="t">Heizung und Warmwasser</div><div class="v">{{ d.k.wp|f2 }} <small>CHF</small></div><div class="s">{{ d.k.wp_kwh|k0 }} kWh, für die Heizkostenabrechnung</div></div>{% endif %}
 <div class="kpi"><div class="t">Produktion</div><div class="v">{{ d.k.produktion|k0 }} <small>kWh</small></div><div class="s">Autarkie Haus {{ '%.1f'|format(d.k.autarkie) }} %</div></div>
 <div class="kpi"><div class="t">Rücklieferung</div><div class="v">{{ d.k.export|k0 }} <small>kWh</small></div><div class="s">{{ d.k.export_chf|f2 if d.k.export_chf is not none else '–' }} CHF{{ ', Tarif teilweise offen' if d.k.export_offen }}</div></div>
 <div class="kpi"><div class="t">Wertschöpfung</div><div class="v">{{ d.k.wert|f2 }} <small>CHF</small></div><div class="s">inkl. manuell erfasster Erträge</div></div>
</div>
<div class="card"><h2>Allgemeinstrom {{ d.von.strftime('%d.%m.') }}–{{ d.bis.strftime('%d.%m.%Y') }}</h2><div class="scroll"><table class="wide">
{% set sp = d.allg|sum(attribute='speicher') > 0.0005 %}{% set bo = d.allg|sum(attribute='bonus') > 0 %}
<tr><th>Monat</th><th>Solar kWh</th><th>Netz HT</th><th>Netz NT</th>{% if sp %}<th>Speicher NT</th>{% endif %}<th>Solar CHF</th><th>Netz CHF</th><th>Grundpreis</th>{% if bo %}<th>Bonus</th>{% endif %}<th>Total CHF</th></tr>
{% for r in d.allg %}<tr><td>{{ r.monat }}</td><td>{{ r.solar|f2 }}</td><td>{{ r.ht|f2 }}</td><td>{{ r.nt|f2 }}</td>{% if sp %}<td>{{ r.speicher|f2 }}</td>{% endif %}<td>{{ r.solar_chf|f2 }}</td><td>{{ (r.netz_chf + r.speicher_chf)|f2 }}</td><td>{{ r.grundpreis|f2 }}</td>{% if bo %}<td>–{{ r.bonus|f2 }}</td>{% endif %}<td><b>{{ r.total|f2 }}</b></td></tr>{% endfor %}
<tr class="sum"><td>Total</td><td>{{ d.allg|sum(attribute='solar')|f2 }}</td><td>{{ d.allg|sum(attribute='ht')|f2 }}</td><td>{{ d.allg|sum(attribute='nt')|f2 }}</td>{% if sp %}<td>{{ d.allg|sum(attribute='speicher')|f2 }}</td>{% endif %}
<td>{{ d.allg|sum(attribute='solar_chf')|f2 }}</td><td>{{ (d.allg|sum(attribute='netz_chf') + d.allg|sum(attribute='speicher_chf'))|f2 }}</td><td>{{ d.allg|sum(attribute='grundpreis')|f2 }}</td>{% if bo %}<td>–{{ d.allg|sum(attribute='bonus')|f2 }}</td>{% endif %}<td>{{ d.k.allg|f2 }}</td></tr>
</table></div><p class="muted">Ohne Ladestation{{ ' und Wärmepumpen' if d.mit_wp }}, inkl. Standby der PV-Anlage. Das PDF fasst diese Tabelle für die Nebenkostenabrechnung zusammen.</p></div>
{% if d.mit_wp %}<div class="card"><h2>Heizung und Warmwasser {{ d.von.strftime('%d.%m.') }}–{{ d.bis.strftime('%d.%m.%Y') }}</h2><div class="scroll"><table class="wide">
{% set namen = d.wp_einzeln.keys()|list %}
<tr><th>Monat</th>{% for n in namen %}<th>{{ n }} kWh</th>{% endfor %}<th>Solar kWh</th><th>Netz HT</th><th>Netz NT</th><th>Solar CHF</th><th>Netz CHF</th><th>Total CHF</th></tr>
{% for r in d.wp %}<tr><td>{{ r.monat }}</td>{% for n in namen %}<td>{{ d.wp_einzeln[n].get(r.periode, 0)|f2 }}</td>{% endfor %}<td>{{ r.solar|f2 }}</td><td>{{ r.ht|f2 }}</td><td>{{ r.nt|f2 }}</td>
<td>{{ r.solar_chf|f2 }}</td><td>{{ (r.netz_chf + r.speicher_chf)|f2 }}</td><td><b>{{ r.total|f2 }}</b></td></tr>{% endfor %}
<tr class="sum"><td>Total</td>{% for n in namen %}<td>{{ d.wp_einzeln[n].sum()|f2 }}</td>{% endfor %}<td>{{ d.wp|sum(attribute='solar')|f2 }}</td><td>{{ d.wp|sum(attribute='ht')|f2 }}</td><td>{{ d.wp|sum(attribute='nt')|f2 }}</td>
<td>{{ d.wp|sum(attribute='solar_chf')|f2 }}</td><td>{{ (d.wp|sum(attribute='netz_chf') + d.wp|sum(attribute='speicher_chf'))|f2 }}</td><td>{{ d.k.wp|f2 }}</td></tr>
</table></div><p class="muted">Gemessen über Home Assistant{% if d.wp_ab %} ab {{ d.wp_ab.strftime('%d.%m.%Y') }}; davor ist der Verbrauch der Wärmepumpen im Allgemeinstrom enthalten{% endif %}. Solaranteil wie bei allen Zählern pro Viertelstunde.</p>
{% if d.wp_jaz %}<p><b>Jahresarbeitszahl:</b> {% for n, j in d.wp_jaz.items() %}{{ n }} {{ '%.2f'|format(j.jaz) if j.jaz else '–' }} ({{ j.waerme|k0 }} kWh Wärme / {{ j.strom|k0 }} kWh Strom){{ ' · ' if not loop.last }}{% endfor %}</p>{% endif %}</div>{% endif %}
<div class="card"><h2>Mieter {{ jahr }}</h2><div class="scroll"><table>
<tr><th class="l">Mieter</th><th class="l">Zeitraum</th><th>Verbrauch kWh</th><th>davon Solar</th><th>Berechnet CHF</th><th>In Rechnung gestellt</th><th>Bezahlt</th><th class="l">Rechnungen</th></tr>
{% for m in d.mieter %}<tr><td class="l">{{ m.vorname }}</td><td class="l">{{ m.von.strftime('%d.%m.') }}–{{ m.bis.strftime('%d.%m.%Y') }}{{ ' (läuft)' if m.laufend }}</td>
<td>{{ m.kwh|f2 }}</td><td>{{ m.solar|f2 }}</td><td><b>{{ m.betrag|f2 }}</b></td><td>{{ m.gestellt|f2 }}</td><td>{{ m.bezahlt|f2 }}</td><td class="l muted">{{ m.rechnungen|join(', ') or '–' }}</td></tr>
{% else %}<tr><td class="l" colspan="8">Keine Mietverhältnisse in {{ jahr }}.</td></tr>{% endfor %}</table></div>
<p class="muted">«Berechnet» = aktueller Stand aus den Lastgängen inkl. Grundpreis; «In Rechnung gestellt» = Summe der erstellten Quartalsrechnungen. Unterschiede entstehen, solange Quartale noch offen sind oder Rechnungen vor einer Korrektur erstellt wurden.</p></div>
<div class="card"><h2>Zähler pro Monat</h2><div class="scroll"><table class="wide">
<tr><th>Monat</th>{% for k, l in zl %}<th>{{ l }} kWh</th><th>Solar</th>{% endfor %}</tr>
{% for p in d.perioden %}{% set m = d.monate.get(p, {}) %}<tr><td>{{ p.strftime('%m.%Y') }}</td>{% for k, l in zl %}{% set z = m.get(k) %}
<td>{{ (z.solar + z.ht + z.nt)|f2 if z is not none else '–' }}</td><td>{{ z.solar|f2 if z is not none else '–' }}</td>{% endfor %}</tr>{% endfor %}
</table></div></div>
<div class="card"><h2>Wertschöpfung {{ jahr }}</h2><div class="scroll"><table class="wide">
<tr><th>Monat</th><th>Rücklieferung</th><th>Verkauf Mieter</th><th>Eigenverbrauch</th><th>Übrige</th><th>Total CHF</th></tr>
{% for m, r in d.w.iterrows() %}<tr><td>{{ m.strftime('%m.%Y') }}</td><td>{{ r.export_chf|f2 }}</td><td>{{ r.mieter_chf|f2 }}</td><td>{{ r.eigen_chf|f2 }}</td><td>{{ r.uebrige_chf|f2 }}</td><td><b>{{ r.total_chf|f2 }}</b></td></tr>{% endfor %}
<tr class="sum"><td>Summe</td><td>{{ d.w.export_chf.sum()|f2 }}</td><td>{{ d.w.mieter_chf.sum()|f2 }}</td><td>{{ d.w.eigen_chf.sum()|f2 }}</td><td>{{ d.w.uebrige_chf.sum()|f2 }}</td><td>{{ d.w.total_chf.sum()|f2 }}</td></tr>
</table></div></div>{% endif %}"""


def _jahr_param(b, cfg):
    jahre = _jahre(b, cfg) if b.get("ok") else [date.today().year]
    try:
        j = int(request.args.get("j") or jahre[0])
    except ValueError:
        j = jahre[0]
    return j, jahre


def seite():
    b0 = S.berechnung() if any(S.PRIMEO.iterdir()) else {}
    j, jahre = _jahr_param(b0, b0.get("cfg") or S.config())
    b, d = daten(j)
    import uebersicht
    return S.page("Jahresabrechnung", render_template_string(SEITE, jahr=j, jahre=jahre, d=d, zl=uebersicht.zl(b.get("cfg") or S.config()),
                                                            fehler=b.get("fehler")))


def pdf():
    b0 = S.berechnung() if any(S.PRIMEO.iterdir()) else {}
    j, _ = _jahr_param(b0, b0.get("cfg") or S.config())
    b, d = daten(j)
    if not d:
        return redirect(f"jahr?j={j}&c=warn&msg=Keine Daten für {j}")
    ziel = S.RECHNUNGEN / "jahr"
    ziel.mkdir(parents=True, exist_ok=True)
    if request.args.get("teil") == "wp":
        if not d["mit_wp"]:
            return redirect(f"jahr?j={j}&c=warn&msg=Keine Wärmepumpen eingerichtet")
        titel, rows, name = "Heizung und Warmwasser", d["wp"], "Heizung_Warmwasser"
        hinweis = ("Wärmepumpe Heizung und Warmwasser, Unterzähler am Allgemeinzähler (Home Assistant)"
                   + (f", gemessen ab {d['wp_ab']:%d.%m.%Y}" if d["wp_ab"] is not None else "") + ". Zur Übernahme in die Heiz- und Nebenkostenabrechnung.")
    else:
        titel, rows, name, hinweis = "Allgemeinstrom", d["allg"], "Allgemeinstrom", None
    pfad = ziel / f"{name}_{j}{'_vorlaeufig' if d['vorlaeufig'] else ''}.pdf"
    total = invoices.render_jahr(pfad, d["cfg"], rows, j, d["von"], d["bis"], d["vorlaeufig"], titel=titel, hinweis=hinweis)
    S.log.info("Jahresaufstellung %s %s erstellt: CHF %.2f%s", titel, j, total, " (vorläufig)" if d["vorlaeufig"] else "")
    return send_file(pfad, mimetype="application/pdf", download_name=pfad.name)


def excel():
    b0 = S.berechnung() if any(S.PRIMEO.iterdir()) else {}
    j, _ = _jahr_param(b0, b0.get("cfg") or S.config())
    b, d = daten(j)
    if not d:
        return redirect(f"jahr?j={j}&c=warn&msg=Keine Daten für {j}")
    k = d["k"]
    blaetter = {
        "Übersicht": pd.DataFrame([
            ("Jahr", j), ("Zeitraum", f"{d['von']:%d.%m.%Y} – {d['bis']:%d.%m.%Y}"), ("Stand", "vorläufig" if d["vorlaeufig"] else "abgeschlossen"),
            ("Allgemeinstrom CHF", k["allg"]), ("Heizung und Warmwasser CHF", k["wp"] if d["mit_wp"] else None), ("Produktion kWh", round(k["produktion"], 2)),
            ("Autarkie Haus %", round(k["autarkie"], 1)), ("Rücklieferung kWh", round(k["export"], 2)),
            ("Rücklieferung CHF", None if k["export_chf"] is None else round(k["export_chf"], 2)),
            ("Wertschöpfung CHF", round(k["wert"], 2))], columns=["Kennzahl", "Wert"]),
        "Allgemeinstrom": pd.DataFrame([{"Monat": r["monat"], "Solar kWh": r["solar"], "Netz HT kWh": r["ht"], "Netz NT kWh": r["nt"],
                                         "Speicher NT kWh": r["speicher"], "Solar CHF": r["solar_chf"], "Netz CHF": r["netz_chf"],
                                         "Speicher CHF": r["speicher_chf"], "Grundpreis CHF": r["grundpreis"], "Bonus CHF": -r["bonus"],
                                         "Total CHF": r["total"]} for r in d["allg"]]),
        **({"Heizung und Warmwasser": pd.DataFrame([dict(
            {"Monat": r["monat"]}, **{f"{n} kWh": float(d["wp_einzeln"][n].get(r["periode"], 0)) for n in d["wp_einzeln"]},
            **{"Solar kWh": r["solar"], "Netz HT kWh": r["ht"], "Netz NT kWh": r["nt"], "Speicher NT kWh": r["speicher"],
               "Solar CHF": r["solar_chf"], "Netz CHF": r["netz_chf"], "Speicher CHF": r["speicher_chf"], "Bonus CHF": -r["bonus"],
               "Total CHF": r["total"]}) for r in d["wp"]])} if d["mit_wp"] else {}),
        "Mieter": pd.DataFrame([{"Mieter": m["name"], "Einheit": m["einheit"], "Von": m["von"], "Bis": m["bis"], "Verbrauch kWh": m["kwh"],
                                 "Solar kWh": m["solar"], "Berechnet CHF": m["betrag"], "In Rechnung gestellt CHF": m["gestellt"],
                                 "Bezahlt CHF": m["bezahlt"], "Rechnungen": ", ".join(m["rechnungen"])} for m in d["mieter"]]),
    }
    zeilen = []
    for p in d["perioden"]:
        for kk, label in ZL:
            z = d["monate"].get(p, {}).get(kk)
            if z is not None:
                zeilen.append({"Monat": p.strftime("%m.%Y"), "Zähler": label, "Solar kWh": z.solar, "Netz HT kWh": z.ht, "Netz NT kWh": z.nt,
                               "Speicher NT kWh": z.speicher, "Solar CHF": z.solar_chf, "Netz CHF": z.netz_chf,
                               "Speicher CHF": z.speicher_chf, "Bonus CHF": -z.bonus_chf})
    blaetter["Zähler pro Monat"] = pd.DataFrame(zeilen)
    w = d["w"].copy()
    w.index = [p.strftime("%m.%Y") for p in w.index]
    blaetter["Wertschöpfung"] = w.reset_index().rename(columns={"index": "Monat"})
    reg = [x for x in zahlungen.uebersicht()["zeilen"] if x["quartal"].startswith(str(j))]
    blaetter["Rechnungen"] = pd.DataFrame([{"Rechnung": x["nummer"], "Partei": x["partei"], "Datum": x["datum"], "Fällig": x["faellig"],
                                            "Betrag CHF": x["betrag"], "Bezahlt CHF": x["bezahlt"], "Offen CHF": x["offen"], "Status": x["stand"]}
                                           for x in reg])
    if request.args.get("viertelstunden"):
        spalten = [c for c in ["tarif", "Prod", "1OG", "2OG", "Allg", "PVA", "EV", "AllgC", "Export"] +
                   [f"{a}_{k}" for k, _ in ZL for a in ("S", "N", "P")] + ["price", "solarprice", "exprice", "occ_1OG"] if c in d["res"]]
        v = d["res"][spalten].copy()
        v.index.name = "Viertelstunde"
        blaetter["Viertelstunden"] = v.reset_index()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in blaetter.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                breite = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, breite + 2), 45)
            ws.freeze_panes = "B2"
    buf.seek(0)
    name = f"vZEV_{j}{'_mit_Viertelstunden' if request.args.get('viertelstunden') else ''}.xlsx"
    S.log.info("Excel-Export %s erstellt", name)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", download_name=name, as_attachment=True)


def register(app, server):
    global S
    S = server
    app.add_url_rule("/jahr", "jahr", seite)
    app.add_url_rule("/jahr/pdf", "jahr_pdf", pdf)
    app.add_url_rule("/jahr/excel", "jahr_excel", excel)
