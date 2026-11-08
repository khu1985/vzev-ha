"""Übersicht und Verlauf pro Zähler, mit Diagrammen und Vorschau aus Home Assistant."""
from datetime import date

import numpy as np
import pandas as pd
from flask import render_template_string, request

import core
import diagramme
import seiten
import vorschau

S = None
VIERTEL = pd.Timedelta(minutes=15)
ZL = [("1OG", "1. OG"), ("2OG", "2. OG"), ("AllgC", "Allgemein"), ("EV", "Ladestation")]
_vcache = {}


# =============================================================================
# Daten: Primeo-Berechnung + Vorschau zusammensetzen
# =============================================================================
def daten():
    """dict mit res (Primeo + Vorschau), cfg, b, info zur Vorschau und Monatsstatus."""
    b = S.berechnung() if any(S.PRIMEO.iterdir()) else {"ok": False, "fehler": "keine Dateien importiert"}
    cfg = b["cfg"] if b.get("ok") else S.config()
    res_p = b["res"] if b.get("ok") else None
    with S.collector._db() as c:
        letzter = c.execute("SELECT MAX(ts) FROM messwerte").fetchone()[0]
    key = (b.get("key"), letzter, S.files_key())
    if _vcache.get("key") != key:
        ab = (res_p.index.max() + VIERTEL) if res_p is not None else None
        try:
            res_v, info = vorschau.berechnen(S.collector._db, cfg, ab, res_p)
        except Exception as e:
            S.log.exception("Vorschau aus Home Assistant fehlgeschlagen")
            res_v, info = None, {"fehlend": [f"Fehler: {e}"]}
        if res_p is not None and res_v is not None and len(res_v):
            res = pd.concat([res_p.assign(quelle="primeo"), res_v.assign(quelle="ha")])
        elif res_p is not None:
            res = res_p.assign(quelle="primeo")
        elif res_v is not None and len(res_v):
            res = res_v.assign(quelle="ha")
        else:
            res = None
        vgl = []
        if res_p is not None:  # Kontrolle: Zeitraum, für den es Primeo-Lastgänge und Zählerstände gibt
            try:
                with S.collector._db() as c:
                    erster = c.execute("SELECT MIN(ts) FROM messwerte").fetchone()[0]
                if erster and pd.Timestamp(erster) < res_p.index.max():
                    res_k, _ = vorschau.berechnen(S.collector._db, cfg, None, res_p)
                    vgl = vorschau.vergleich(res_k, res_p)
            except Exception:
                S.log.exception("Vergleich Home Assistant / Primeo fehlgeschlagen")
        _vcache.update(key=key, res=res, info=info, vergleich=vgl)
    return dict(b=b, cfg=cfg, res=_vcache["res"], info=_vcache["info"], vergleich=_vcache["vergleich"])


def monate(res):
    """Monatswerte für Diagramm und Kennzahlen."""
    g = res["month"]
    solar = res[["S_1OG", "S_2OG", "S_AllgC", "S_EV"]].sum(axis=1)
    netz = res[["N_1OG", "N_2OG", "N_AllgC", "N_EV"]].sum(axis=1)
    m = pd.DataFrame({
        "produktion": res["Prod"].groupby(g).sum(), "export": res["Export"].groupby(g).sum(),
        "solar": solar.groupby(g).sum(), "netz": netz.groupby(g).sum(),
        "export_chf": (res["Export"] * res["exprice"]).groupby(g).sum(min_count=1),
        "tarif_offen": res["exprice"].isna().groupby(g).any(),
        "ha": (res["quelle"] == "ha").groupby(g).any(),
        "bis": res.index.to_series().groupby(g).max() + VIERTEL,
    })
    m["verbrauch"] = m["solar"] + m["netz"]
    m["autarkie"] = np.where(m["verbrauch"] > 0, m["solar"] / m["verbrauch"] * 100, np.nan)
    m["vorlaeufig"] = m["ha"] | (m["bis"] < pd.DatetimeIndex([p.end_time for p in m.index]).floor("15min") + VIERTEL)
    return m


def _status(m, abschluss):
    k = str(m)
    return "abgeschlossen" if k in abschluss["monate"] else "offen"


# =============================================================================
# Übersicht
# =============================================================================
UEBERSICHT = diagramme.STIL + """
{% if not res_ok %}<div class="msg warn">Noch keine Berechnung möglich: {{ fehler }}. <a href="import">Dateien importieren</a></div>
{% else %}
{% if abw %}<div class="msg warn">Abgeschlossene Monate haben sich verändert: {% for m, t in abw %}{{ m }} ({{ t }}){{ ', ' if not loop.last }}{% endfor %}. Details unter <a href="abschluss">Abschluss</a>.</div>{% endif %}
<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin:-8px 0 16px">
<form method="get" action="./"><select name="m" onchange="this.form.submit()">{% for k, l in auswahl %}<option value="{{ k }}" {{ 'selected' if k == sel }}>{{ l }}</option>{% endfor %}</select></form>
<span class="muted">Primeo-Lastgänge bis {{ primeo_bis }}{% if info.bis %} · Vorschau aus Home Assistant bis {{ info.bis.strftime('%d.%m.%Y %H:%M') }}{% endif %}</span></div>
{% if mon.vorlaeufig %}<div class="msg" style="background:var(--soft)">{{ titel }} ist vorläufig{% if mon.ha %}: ab {{ info.von.strftime('%d.%m. %H:%M') if info.von else '' }} aus den Zählerständen in Home Assistant gerechnet
(Abdeckung {{ '%.0f'|format(info.abdeckung * 100) }} % der Viertelstunden){% else %}: Daten bis {{ (mon.bis - viertel).strftime('%d.%m.%Y') }}{% endif %}. Für die Rechnungen zählen die Primeo-Lastgänge.</div>{% endif %}
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div class="t">Produktion</div><div class="v">{{ mon.produktion|k0 }} <small>kWh</small></div><div class="s">{% if vor is not none %}{{ vor_label }}: {{ vor.produktion|k0 }} kWh{% endif %}</div></div>
 <div class="kpi"><div class="t">Autarkie Haus</div><div class="v">{{ '%.1f'|format(mon.autarkie) }} <small>%</small></div><div class="s">{{ mon.solar|k0 }} von {{ mon.verbrauch|k0 }} kWh aus Solarstrom</div></div>
 <div class="kpi"><div class="t">Rücklieferung</div><div class="v">{{ mon.export|k0 }} <small>kWh</small></div><div class="s">{% if mon.tarif_offen %}Tarif noch offen{% else %}= {{ mon.export_chf|f2 }} CHF{% endif %}</div></div>
 <div class="kpi"><div class="t">Wertschöpfung</div><div class="v">{{ wert|f2 }} <small>CHF</small></div><div class="s">Rücklieferung, Verkauf Mieter, Eigenverbrauch</div></div>
</div>
<div class="card"><h2>Energiefluss pro Monat</h2>{{ chart|safe }}
<p class="muted">kWh. Solar im Haus = selbst verbrauchter Solarstrom aller Zähler; Netzbezug inkl. Standby PV-Anlage. * vorläufig. Klick auf einen Monat zeigt ihn oben.</p></div>
<div class="card"><h2>Kontrollen {{ titel }}</h2>
{% for ok, t, d in kontrollen %}<div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid #EEF0EC">
<span class="pill {{ 'ok' if ok == True else 'warn' if ok == False else '' }}" style="min-width:64px;text-align:center">{{ 'stimmt' if ok == True else 'prüfen' if ok == False else 'offen' }}</span>
<div><b>{{ t }}</b><div class="muted">{{ d }}</div></div></div>{% endfor %}</div>
<div class="card"><h2>Verbraucher {{ titel }}</h2><div class="scroll"><table>
<tr><th class="l">Zähler</th><th class="l"></th><th>Solar kWh</th><th>Netz HT</th><th>Netz NT</th><th>Autarkie</th><th>Betrag CHF</th><th class="l"></th></tr>
{% for r in verbraucher %}<tr><td class="l"><a href="verlauf?z={{ r.k }}">{{ r.label }}</a></td><td class="l muted">{{ r.partei }}</td><td>{{ r.solar|f2 }}</td><td>{{ r.ht|f2 }}</td><td>{{ r.nt|f2 }}</td>
<td>{{ '%.1f %%'|format(r.autarkie) if r.autarkie is not none else '–' }}</td><td>{{ r.betrag|f2 if r.betrag is not none else '' }}</td><td class="l muted">{{ r.hinweis }}</td></tr>{% endfor %}
</table></div><p class="muted">Beträge inkl. Grundpreis pro Zähler (Netznutzung anteilig, Messtarif, Konzessionsabgabe), beim 1. OG anteilig zur Mietdauer.</p></div>
{% if vergleich %}<div class="card"><h2>Kontrolle Home Assistant gegen Primeo</h2><div class="scroll"><table>
<tr><th class="l">Zähler</th><th>Home Assistant kWh</th><th>Primeo kWh</th><th>Differenz</th><th>%</th></tr>
{% for v in vergleich %}<tr><td class="l">{{ v.zaehler }}</td><td>{{ v.ha|f2 }}</td><td>{{ v.primeo|f2 }}</td><td>{{ v.diff|f2 }}</td><td>{{ '%.1f'|format(v.prozent) if v.prozent is not none else '–' }}</td></tr>{% endfor %}
</table></div><p class="muted">Zeitraum, in dem beides vorliegt. Zeigt, wie genau die Vorschau ist.</p></div>{% endif %}
<details class="card"><summary><b>Alle Monate pro Zähler</b></summary><div class="scroll" style="margin-top:12px"><table>
<tr><th>Monat</th>{% for z in zl %}<th>{{ z[1] }} Solar</th><th>Netz HT/NT</th><th>CHF*</th>{% endfor %}</tr>
{% for m, row in tab %}<tr><td>{{ m }}</td>{% for c in row %}<td>{{ c[0]|f2 }}</td><td>{{ c[1]|f2 }} / {{ c[2]|f2 }}</td><td>{{ c[3]|f2 }}</td>{% endfor %}</tr>{% endfor %}
</table></div><p class="muted">kWh. * Solar- plus Netzkosten ohne Grundpreis; Allgemein ohne Ladestation, inkl. Standby PV-Anlage.</p></details>
{% if abg is not none %}<details class="card"><summary><b>Abgleich mit Primeo-Rechnungen</b> <span class="pill {{ 'ok' if abg.ok.all() else 'warn' }}">{{ 'alles stimmt' if abg.ok.all() else 'Abweichung prüfen' }}</span></summary>
<div class="scroll" style="margin-top:12px"><table>
<tr><th>Rechnung</th><th class="l">Position</th><th>Primeo kWh</th><th>Berechnet kWh</th><th>Differenz</th><th></th></tr>
{% for r in abg.itertuples() %}<tr><td>{{ r.rechnung }}</td><td class="l">{{ r.position }}</td><td>{{ r.primeo_kwh }}</td><td>{{ r.berechnet_kwh|f2 }}</td><td>{{ r.diff|f2 }}</td>
<td><span class="pill {{ 'ok' if r.ok else 'warn' }}">{{ 'stimmt' if r.ok else 'prüfen' }}</span></td></tr>{% endfor %}</table></div></details>{% endif %}
<details class="card"><summary><b>Wertschöpfung Betreiber</b> {{ w.total_chf.sum()|f2 }} CHF</summary><div class="scroll" style="margin-top:12px"><table>
<tr><th>Monat</th><th>Rücklieferung</th><th>Verkauf Mieter</th><th>Eigenverbrauch</th><th>Übrige</th><th>Total CHF</th></tr>
{% for m, r in w.iterrows() %}<tr><td>{{ m.strftime('%m.%Y') }}{{ '*' if m in vorl }}</td><td>{{ r.export_chf|f2 }}</td><td>{{ r.mieter_chf|f2 }}</td><td>{{ r.eigen_chf|f2 }}</td><td>{{ r.uebrige_chf|f2 }}</td><td><b>{{ r.total_chf|f2 }}</b></td></tr>{% endfor %}
<tr class="sum"><td>Summe</td><td>{{ w.export_chf.sum()|f2 }}</td><td>{{ w.mieter_chf.sum()|f2 }}</td><td>{{ w.eigen_chf.sum()|f2 }}</td><td>{{ w.uebrige_chf.sum()|f2 }}</td><td>{{ w.total_chf.sum()|f2 }}</td></tr>
</table></div><p class="muted">Rücklieferung leer = Tarif noch nicht bekannt. Allgemeinstrom zu 50 % als verkauft gerechnet; Leerstand zählt als Eigenverbrauch. * vorläufig.</p></details>
{% endif %}"""


def _ml(p):
    return ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"][p.month - 1]


def _titel(p):
    return ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"][p.month - 1] + f" {p.year}"


def _parteien(cfg, p):
    von, bis = p.start_time.date(), p.end_time.date()
    namen = []
    for m in cfg.get("mietverhaeltnisse") or []:
        if m["einheit"] != "1OG":
            continue
        mv, mb = seiten._d(m["von"]), seiten._d(m.get("bis"))
        if mv <= bis and (mb is None or mb >= von):
            namen.append(m["name"] + (f" (ab {mv:%d.%m.})" if mv > von else "") + (f" (bis {mb:%d.%m.})" if mb and mb < bis else ""))
    return ", ".join(namen) or "Leerstand – Kosten trägt der Betreiber"


def index():
    d = daten()
    res, cfg, b = d["res"], d["cfg"], d["b"]
    if res is None:
        return S.page("Übersicht", render_template_string(UEBERSICHT, res_ok=False, fehler=b.get("fehler") or ", ".join(d["info"].get("fehlend", []))))
    mon = monate(res)
    perioden = list(mon.index)
    voll = [p for p in perioden if not mon.loc[p, "vorlaeufig"]]
    sel = request.args.get("m") or str((voll or perioden)[-1])
    p = pd.Period(sel, "M") if sel in [str(x) for x in perioden] else (voll or perioden)[-1]
    sel = str(p)
    i = perioden.index(p)
    vor = mon.iloc[i - 1] if i > 0 else None
    w = core.wertschoepfung(res, cfg)
    wert = w.loc[p, "total_chf"] if p in w.index else None

    vorl = {j for j, x in enumerate(perioden) if mon.loc[x, "vorlaeufig"]}
    chart = diagramme.saeulen([_ml(x) + (f" {str(x.year)[2:]}" if x.month == 1 or j == 0 else "") for j, x in enumerate(perioden)],
                              [("Solar im Haus", diagramme.FARBEN["solar"], list(mon["solar"])),
                               ("Rücklieferung", diagramme.FARBEN["rueck"], list(mon["export"])),
                               ("Netzbezug", diagramme.FARBEN["netz"], list(mon["netz"]))],
                              vorlaeufig=vorl, aktiv=i, links=[f"?m={x}" for x in perioden])

    # Kontrollen
    rm = res[res["month"] == p]
    kontrollen = []
    abg = core.abgleich(b["res"], b["cfg"]) if b.get("ok") else None
    if abg is not None:
        def in_monat(pos_von, pos_bis):
            return pd.Timestamp(pos_von) <= p.end_time and pd.Timestamp(pos_bis) >= p.start_time
        betroffen = []
        for r in cfg.get("primeo_rechnungen") or []:
            if in_monat(r["von"], r["bis"]):
                betroffen.append(str(r["nr"]))
        a = abg[abg["rechnung"].astype(str).isin(betroffen)]
        if len(a):
            rl, nb = a[a.position.str.startswith("Rück")], a[a.position.str.startswith("Netz")]
            kontrollen.append((bool(rl.ok.all()), "Rücklieferung = Primeo-Abrechnung", f"Rechnung {', '.join(betroffen)}: Differenz {rl['diff'].sum():.2f} kWh"))
            kontrollen.append((bool(nb.ok.all()), "Netzbezug = Primeo-Abrechnung", f"HT und NT inkl. Standby PV-Anlage, Differenz {nb['diff'].sum():.2f} kWh"))
        else:
            kontrollen.append((None, "Abgleich mit Primeo", "Für diesen Monat ist noch keine Primeo-Rechnung erfasst (Seite «Primeo»)."))
    if (rm["quelle"] == "primeo").any() and b.get("ok"):
        lade = b["files"].get("Lade")
        kontrollen.append((b["ev"] < 0.01, "Ladestation = Summe der Ladevorgänge", f"Wallbox-Export {lade[0] if lade else ''}: Differenz {b['ev']:.2f} kWh über alle Monate"))
        luecken = int(rm[rm["quelle"] == "primeo"][["1OG", "2OG", "Allg", "PVA", "Prod"]].isna().any(axis=1).sum())
        kontrollen.append((luecken == 0, "Alle Primeo-Zähler liefern Daten", "keine Lücke im 15-Minuten-Raster" if not luecken else f"{luecken} Viertelstunden ohne Wert"))
    if (rm["quelle"] == "ha").any():
        ab = d["info"].get("abdeckung", 0)
        kontrollen.append((ab > 0.95, "Zählerstände aus Home Assistant vollständig", f"{ab * 100:.0f} % der Viertelstunden haben Werte aller Zähler"))
    kontrollen.append((not mon.loc[p, "tarif_offen"], "Rückliefertarif vorhanden", "in «Tarife» erfasst" if not mon.loc[p, "tarif_offen"] else "In «Tarife» ergänzen, sobald Primeo ihn publiziert"))
    a = seiten.abschluss_laden()
    abw = seiten.abweichungen(b) if b.get("ok") else []
    if sel in a["monate"]:
        kontrollen.append((sel not in dict(abw), "Abgeschlossen und unverändert", f"abgeschlossen per {seiten._abschlussdatum(a['monate'][sel]):%d.%m.%Y}"))

    # Verbraucher
    import invoices
    gp = invoices.grundpreis(cfg, p.start_time)
    occ = float(rm["occ_1OG"].mean()) if len(rm) else 0
    verbraucher = []
    for k, label in ZL:
        s = core.zaehler_summen(rm, k)
        r = s.iloc[0] if len(s) else None
        if r is None:
            continue
        tot = r.solar + r.ht + r.nt
        aut = r.solar / tot * 100 if tot else None
        if k == "1OG":
            partei, betrag, hinw = _parteien(cfg, p), r.solar_chf + r.netz_chf + gp * occ, ("verrechnet" if occ > 0.99 else "anteilig vermietet" if occ > 0 else "Betreiber")
        elif k == "2OG":
            partei, betrag, hinw = "Betreiber", None, "Eigenverbrauch"
        elif k == "AllgC":
            partei, betrag, hinw = "ohne Ladestation, Gesamtrechnung", r.solar_chf + r.netz_chf + gp, "für Nebenkostenabrechnung"
        else:
            partei, betrag, hinw = "Betreiber", None, f"Ersparnis {r.ersparnis_chf:.2f} CHF ggü. Netz"
        verbraucher.append(dict(k=k, label=label, partei=partei, solar=r.solar, ht=r.ht, nt=r.nt, autarkie=aut, betrag=betrag, hinweis=hinw))

    sums = {k: core.zaehler_summen(res, k) for k, _ in ZL}
    tab = [(m.strftime("%m.%Y") + ("*" if mon.loc[m, "vorlaeufig"] else ""), [(sums[k].loc[m, "solar"], sums[k].loc[m, "ht"], sums[k].loc[m, "nt"],
                                     sums[k].loc[m, "solar_chf"] + sums[k].loc[m, "netz_chf"]) for k, _ in ZL]) for m in perioden]
    auswahl = [(str(x), _titel(x) + (" (vorläufig)" if mon.loc[x, "vorlaeufig"] else "")) for x in reversed(perioden)]
    return S.page("Übersicht", render_template_string(
        UEBERSICHT, res_ok=True, abw=abw, auswahl=auswahl, sel=sel, titel=_titel(p), mon=mon.loc[p], vor=vor,
        vor_label=_titel(perioden[i - 1]) if i > 0 else "", wert=wert, chart=chart, kontrollen=kontrollen, verbraucher=verbraucher,
        info=d["info"], viertel=VIERTEL, primeo_bis=(b["res"].index.max().strftime("%d.%m.%Y") if b.get("ok") else "–"),
        zl=ZL, tab=tab, abg=abg, w=w, vorl={x for x in perioden if mon.loc[x, "vorlaeufig"]},
        vergleich=d["vergleich"]))


# =============================================================================
# Verlauf pro Zähler
# =============================================================================
VERLAUF = diagramme.STIL + """
<div style="display:flex;gap:6px;margin:-8px 0 16px;flex-wrap:wrap">{% for k, l in zl %}<a class="btn {{ 'primary' if k == z }}" href="verlauf?z={{ k }}">{{ l }}</a>{% endfor %}</div>
{% if not ok %}<div class="msg warn">Noch keine Daten: {{ fehler }}</div>{% else %}
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div>Verbrauch gesamt</div><div>{{ tot.verbrauch|k0 }} <small>kWh</small></div></div>
 <div class="kpi"><div>davon Solar</div><div>{{ tot.solar|k0 }} <small>kWh</small></div></div>
 <div class="kpi"><div>Autarkie</div><div>{{ '%.1f'|format(tot.autarkie) }} <small>%</small></div></div>
 <div class="kpi"><div>{{ 'Ersparnis ggü. Netz' if z == 'EV' else 'Eigenverbrauch' if z == '2OG' else 'Verrechnet' }}</div><div>{{ tot.betrag|f2 }} <small>CHF</small></div></div>
</div>
<div class="card"><h2>Pro Monat</h2>{{ chart|safe }}<p class="muted">kWh. * vorläufig.</p></div>
<div class="card"><div class="scroll"><table>
<tr><th class="l">Monat</th><th>Solar kWh</th><th>Netz HT</th><th>Netz NT</th><th>Solar CHF</th><th>Netz CHF</th>{% if gp %}<th>Grundpreis*</th>{% endif %}<th>Total CHF</th><th>Autarkie</th><th class="l">Status</th></tr>
{% for r in zeilen %}{% if r.gruppe %}<tr><td class="l" colspan="10" style="background:var(--bg);font-weight:600">{{ r.gruppe }}</td></tr>{% endif %}
<tr><td class="l">{{ r.label }}</td><td>{{ r.solar|f2 }}</td><td>{{ r.ht|f2 }}</td><td>{{ r.nt|f2 }}</td><td>{{ r.solar_chf|f2 }}</td><td>{{ r.netz_chf|f2 }}</td>
{% if gp %}<td>{{ r.gp|f2 }}</td>{% endif %}<td><b>{{ r.total|f2 }}</b></td><td>{{ '%.1f %%'|format(r.autarkie) if r.autarkie is not none else '–' }}</td>
<td class="l"><span class="pill {{ 'ok' if r.status == 'abgeschlossen' else 'warn' if r.status == 'vorläufig' else '' }}">{{ r.status }}</span></td></tr>{% endfor %}
<tr class="sum"><td class="l">Summe</td><td>{{ tot.solar|f2 }}</td><td>{{ tot.ht|f2 }}</td><td>{{ tot.nt|f2 }}</td><td>{{ tot.solar_chf|f2 }}</td><td>{{ tot.netz_chf|f2 }}</td>{% if gp %}<td>{{ tot.gp|f2 }}</td>{% endif %}<td>{{ tot.total|f2 }}</td><td>{{ '%.1f %%'|format(tot.autarkie) }}</td><td></td></tr>
</table></div>{% if gp %}<p class="muted">* Grundpreis Netznutzung anteilig, Messtarif, Konzessionsabgabe{{ ', beim 1. OG anteilig zur Mietdauer' if z == '1OG' }}.</p>{% endif %}
{% if z == 'EV' %}<p class="muted">Total = was der Solarstrom zum Netztarif gekostet hätte (Ersparnis); Netz CHF = tatsächliche Netzkosten der Ladestation.</p>{% endif %}</div>
{% endif %}"""


def verlauf():
    z = request.args.get("z", "1OG")
    if z not in dict(ZL):
        z = "1OG"
    d = daten()
    res, cfg = d["res"], d["cfg"]
    if res is None:
        return S.page("Verlauf", render_template_string(VERLAUF, ok=False, zl=ZL, z=z, fehler=d["b"].get("fehler")))
    import invoices
    mon = monate(res)
    s = core.zaehler_summen(res, z)
    occ = res["occ_1OG"].groupby(res["month"]).mean()
    a = seiten.abschluss_laden()
    zeilen, gruppe_alt = [], None
    for p, r in s.iterrows():
        gp = 0.0
        if z in ("1OG", "AllgC"):
            gp = invoices.grundpreis(cfg, p.start_time) * (occ.get(p, 0) if z == "1OG" else 1)
        tot = r.solar + r.ht + r.nt
        total = (r.ersparnis_chf if z == "EV" else r.solar_chf + r.netz_chf + gp)
        status = "abgeschlossen" if str(p) in a["monate"] else ("vorläufig" if mon.loc[p, "vorlaeufig"] else "offen")
        gruppe = _parteien(cfg, p) if z == "1OG" else None
        zeilen.append(dict(gruppe=gruppe if gruppe != gruppe_alt else None, label=_titel(p) + ("*" if mon.loc[p, "vorlaeufig"] else ""),
                           solar=r.solar, ht=r.ht, nt=r.nt, solar_chf=r.solar_chf, netz_chf=r.netz_chf, gp=gp, total=total,
                           autarkie=r.solar / tot * 100 if tot else None, status=status))
        gruppe_alt = gruppe
    tot = {k: sum(x[k] for x in zeilen) for k in ("solar", "ht", "nt", "solar_chf", "netz_chf", "gp", "total")}
    tot["verbrauch"] = tot["solar"] + tot["ht"] + tot["nt"]
    tot["autarkie"] = tot["solar"] / tot["verbrauch"] * 100 if tot["verbrauch"] else 0
    tot["betrag"] = tot["total"]
    perioden = list(s.index)
    vorl = {j for j, p in enumerate(perioden) if mon.loc[p, "vorlaeufig"]}
    chart = diagramme.saeulen([_ml(p) for p in perioden],
                              [("Solar", diagramme.FARBEN["solar"], list(s["solar"])), ("Netz", diagramme.FARBEN["netz"], list(s["ht"] + s["nt"]))],
                              vorlaeufig=vorl, hoehe=220)
    return S.page("Verlauf", render_template_string(VERLAUF, ok=True, zl=ZL, z=z, zeilen=zeilen, tot=tot, chart=chart, gp=z in ("1OG", "AllgC")))


def register(app, server):
    global S
    S = server
    app.jinja_env.filters["k0"] = lambda x: "–" if x is None or pd.isna(x) else f"{x:,.0f}".replace(",", "'")
    app.add_url_rule("/", "index", index)
    app.add_url_rule("/verlauf", "verlauf", verlauf)
