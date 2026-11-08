"""Energiefluss: animiertes Übersichtsdiagramm (Startseite der App).

Knoten: PV-Anlage, Netz, Speicher (falls Daten), Haus (Ring = Herkunft des Stroms) und darunter die Verbraucher.
Flüsse pro Zeitraum aus derselben 15-Minuten-Rechnung wie die Abrechnung (Primeo-Lastgänge, danach Vorschau aus
Home Assistant):
- PV → Haus: Solarstrom aller Zähler (S_…)
- PV → Netz: Rücklieferung
- Netz → Haus: Netzbezug aller Zähler (N_…, inkl. Standby der PV-Anlage)
- Netz → Speicher: Netzladung (ab dem eingestellten Datum), Speicher → Haus: «Speicher NT» (P_…)
- PV ↔ Speicher: geladen / entladen laut Wechselrichter (Solis-Tageswerte), nur zur Information
Punkte laufen umso schneller, je mehr Energie fliesst; bei «Bewegung reduzieren» stehen sie still.
"""
import math
from datetime import date, timedelta
from html import escape

import pandas as pd
from flask import render_template_string, request

import core
import diagramme

S = None
F = {"solar": diagramme.FARBEN["solar"], "netz": diagramme.FARBEN["netz"], "rueck": diagramme.FARBEN["rueck"],
     "speicher": diagramme.FARBEN["uebrige"], "linie": "#C9CEC8"}
MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _zahl(x):
    if x is None:
        return "–"
    return f"{x:,.0f}".replace(",", "'") if abs(x) >= 100 else f"{x:.1f}"


def solis(db, cfg, von, bis):
    """Speicher geladen/entladen (kWh) laut Solis-Tageszähler im Zeitraum, sonst None."""
    sol = (cfg.get("homeassistant") or {}).get("solis") or {}
    e = {"geladen": sol.get("batterie_geladen_heute"), "entladen": sol.get("batterie_entladen_heute")}
    if not all(e.values()):
        return None
    out = {}
    with db() as c:
        for k, ent in e.items():
            rows = c.execute("SELECT substr(ts, 1, 10), MAX(wert) FROM messwerte WHERE entity=? AND ts >= ? AND ts < ? GROUP BY 1",
                             (ent, von.isoformat(), (bis + timedelta(days=1)).isoformat())).fetchall()
            out[k] = sum(w or 0 for _, w in rows) if rows else None
    return out if any(v for v in out.values()) else None


def werte(res, cfg):
    """Flüsse und Verbraucher für einen Ausschnitt der Berechnung."""
    namen = core.wp_namen(cfg)
    zl = [x for x in core.ZL if x[0] != "WP" or namen]
    if len(namen) > 1 and all(f"S_{k}" in res for k, _ in namen):  # Heizung, Warmwasser … einzeln zeigen
        zl = [x for x in zl if x[0] != "WP"] + namen
    verbraucher = []
    for k, label in zl:
        s, n, p = (float(res[f"{a}_{k}"].sum()) for a in ("S", "N", "P"))  # Allgemein inkl. Standby der PV-Anlage
        verbraucher.append(dict(k=k, label=label, solar=s, netz=n, speicher=p, total=s + n + p))
    solar_haus = sum(v["solar"] for v in verbraucher)
    netz_haus = float(res[[f"N_{k}" for k, _ in zl]].sum().sum())
    speicher_haus = sum(v["speicher"] for v in verbraucher)
    return dict(prod=float(res["Prod"].sum()), export=float(res["Export"].sum()), solar_haus=solar_haus, netz_haus=netz_haus,
                laden=float(res["Laden"].sum()), speicher_haus=speicher_haus, verbraucher=verbraucher,
                haus=solar_haus + netz_haus + speicher_haus)


def _dauer(kwh, gross):
    """Sekunden für einen Punktdurchlauf: viel Energie = schnell (relativ zum grössten Fluss)."""
    if gross <= 0 or kwh <= 0:
        return None
    r = math.log1p(kwh) / math.log1p(gross)
    return round(4.5 - 2.8 * r, 2)


def _fluss(pfad, kwh, gross, farbe, punkte=None, tip=""):
    """Linie mit wandernden Punkten; ohne Energie nur eine blasse Linie."""
    breite = 1.4 + 2.2 * (math.log1p(kwh) / math.log1p(gross) if gross > 0 and kwh > 0 else 0)
    t = [f'<path d="{pfad}" fill="none" stroke="{farbe if kwh > 0.005 else F["linie"]}" stroke-width="{breite:.1f}" '
         f'stroke-linecap="round" opacity="{0.55 if kwh > 0.005 else 0.6}"/>']
    d = _dauer(kwh, gross)
    if d:
        farben = punkte or [farbe] * 3
        for i, f in enumerate(farben):
            t.append(f'<circle r="4.2" fill="{f}"><animateMotion dur="{d}s" begin="{-d * i / len(farben):.2f}s" '
                     f'repeatCount="indefinite" path="{pfad}"/></circle>')
    if tip:
        t.append(f'<path d="{pfad}" fill="none" stroke="transparent" stroke-width="16" class="hitl" data-tip="{escape(tip)}"/>')
    return "".join(t)


def _knoten(x, y, r, farbe, titel, zeilen, oben=True, ring=None, tip=""):
    t = [f'<g class="kn" data-tip="{escape(tip)}">']
    if ring:  # Herkunft des Stroms als Ring (Solar, Speicher, Netz)
        umfang, start = 2 * math.pi * r, 0.0
        t.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" stroke="{F["linie"]}" stroke-width="4"/>')
        for anteil, f in ring:
            if anteil > 0.001:
                t.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{f}" stroke-width="5" '
                         f'stroke-dasharray="{anteil * umfang:.1f} {umfang:.1f}" stroke-dashoffset="{-start * umfang:.1f}" '
                         f'transform="rotate(-90 {x} {y})"/>')
                start += anteil
    else:
        t.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" stroke="{farbe}" stroke-width="3"/>')
    hoehen = [19 if gross else 15 for _, _, gross in zeilen]
    yy = y - sum(hoehen) / 2
    for (txt, f, gross), h in zip(zeilen, hoehen):
        yy += h
        t.append(f'<text x="{x}" y="{yy - 4:.1f}" text-anchor="middle" class="{"kv" if gross else "ks"}" fill="{f}">{escape(txt)}</text>')
    ty = y - r - 9 if oben else y + r + 17
    if titel:
        t.append(f'<text x="{x}" y="{ty}" text-anchor="middle" class="kt">{escape(titel)}</text>')
    t.append("</g>")
    return "".join(t)


def diagramm(w, speicher=None):
    """SVG mit allen Knoten und animierten Flüssen."""
    gross = max([w["prod"], w["netz_haus"] + w["laden"], w["haus"], w["export"], 0.1])
    mit_speicher = speicher is not None or w["laden"] > 0.005 or w["speicher_haus"] > 0.005
    W, H = 420, 470
    t = [f'<svg class="fluss" viewBox="0 0 {W} {H}" role="img" aria-label="Energiefluss" style="width:100%;max-width:560px;height:auto;display:block;margin:0 auto">']
    sx, sy, nx, ny, hx, hy, bx, by = 210, 72, 62, 215, 210, 215, 358, 215
    # Flüsse (unter den Knoten)
    t.append(_fluss(f"M{sx},{sy + 46} L{hx},{hy - 54}", w["solar_haus"], gross, F["solar"], tip=f"PV → Haus: {_zahl(w['solar_haus'])} kWh"))
    t.append(_fluss(f"M{sx - 32},{sy + 33} C{sx - 75},{sy + 70} {nx + 10},{ny - 90} {nx + 4},{ny - 46}", w["export"], gross, F["rueck"],
                    tip=f"Rücklieferung ins Netz: {_zahl(w['export'])} kWh"))
    t.append(_fluss(f"M{nx + 46},{ny} L{hx - 54},{hy}", w["netz_haus"], gross, F["netz"], tip=f"Netz → Haus: {_zahl(w['netz_haus'])} kWh"))
    if mit_speicher and w["laden"] > 0.005:
        t.append(_fluss(f"M{nx + 30},{ny + 35} C{nx + 90},{ny + 95} {bx - 90},{by + 95} {bx - 30},{by + 35}", w["laden"], gross, F["netz"],
                        tip=f"Netz → Speicher (Netzladung): {_zahl(w['laden'])} kWh"))
    if mit_speicher:
        t.append(_fluss(f"M{bx - 46},{by} L{hx + 54},{hy}", w["speicher_haus"], gross, F["speicher"],
                        tip=f"Speicher NT → Haus: {_zahl(w['speicher_haus'])} kWh"))
        if speicher:
            g, e = speicher.get("geladen") or 0, speicher.get("entladen") or 0
            t.append(_fluss(f"M{sx + 32},{sy + 33} C{sx + 75},{sy + 70} {bx - 10},{by - 90} {bx - 4},{by - 46}", max(g, e), gross,
                            F["solar"], punkte=[F["solar"], F["speicher"], F["solar"]],
                            tip=f"PV ↔ Speicher laut Wechselrichter: geladen {_zahl(g)} kWh, entladen {_zahl(e)} kWh"))
    vb = w["verbraucher"]
    abstand = min(84, (W - 24) / max(len(vb), 1))
    xs = [W / 2 + (i - (len(vb) - 1) / 2) * abstand for i in range(len(vb))]
    rv = min(31, abstand / 2 - 4)  # bei vielen Verbrauchern kleinere Kreise
    for v, x in zip(vb, xs):
        tot = v["total"]
        pkt = []
        if tot > 0:  # drei Punkte, nach Herkunft eingefärbt
            for i in range(3):
                q = (i + 0.5) / 3
                pkt.append(F["solar"] if q < v["solar"] / tot else F["speicher"] if q < (v["solar"] + v["speicher"]) / tot else F["netz"])
        t.append(_fluss(f"M{hx},{hy + 54} C{hx},{hy + 110} {x:.1f},{hy + 100} {x:.1f},{392 - rv:.1f}", tot, gross, "#5B6660", punkte=pkt,
                        tip=f"Haus → {v['label']}: {_zahl(tot)} kWh"))
    # Knoten
    t.append(_knoten(sx, sy, 46, F["solar"], "PV-Anlage", [(f"{_zahl(w['prod'])} kWh", "#16201C", True)],
                     tip=f"Produktion {_zahl(w['prod'])} kWh, davon im Haus {_zahl(w['solar_haus'])} kWh, ins Netz {_zahl(w['export'])} kWh"))
    t.append(_knoten(nx, ny, 46, F["netz"], "Netz", [(f"↓ {_zahl(w['netz_haus'] + w['laden'])} kWh", F["netz"], False),
                                                    (f"↑ {_zahl(w['export'])} kWh", F["rueck"], False)], oben=False,
                     tip=f"Bezug {_zahl(w['netz_haus'] + w['laden'])} kWh, Rücklieferung {_zahl(w['export'])} kWh"))
    haus = w["haus"] or 1
    aut = w["solar_haus"] / haus * 100 if w["haus"] else 0
    t.append(_knoten(hx, hy, 52, None, "", [("Haus", "#5B6660", False), (f"{_zahl(w['haus'])} kWh", "#16201C", True), (f"{aut:.0f} % Solar", F["solar"], False)],
                     oben=False, ring=[(w["solar_haus"] / haus, F["solar"]), (w["speicher_haus"] / haus, F["speicher"]), (w["netz_haus"] / haus, F["netz"])],
                     tip=f"Verbrauch {_zahl(w['haus'])} kWh: Solar {_zahl(w['solar_haus'])}, Speicher NT {_zahl(w['speicher_haus'])}, Netz {_zahl(w['netz_haus'])} kWh"))
    if mit_speicher:
        zeilen = []
        if speicher:
            zeilen += [(f"↓ {_zahl(speicher.get('geladen'))} kWh", F["speicher"], False), (f"↑ {_zahl(speicher.get('entladen'))} kWh", F["rueck"], False)]
        else:
            zeilen += [(f"{_zahl(w['laden'])} kWh", F["speicher"], False)]
        t.append(_knoten(bx, by, 46, F["speicher"], "Speicher", zeilen, oben=False,
                         tip=(f"Wechselrichter: geladen {_zahl(speicher.get('geladen'))}, entladen {_zahl(speicher.get('entladen'))} kWh. " if speicher else "")
                         + f"Netzladung {_zahl(w['laden'])} kWh, davon als Speicher NT im Haus {_zahl(w['speicher_haus'])} kWh"))
    for v, x in zip(vb, xs):
        a = v["solar"] / v["total"] if v["total"] else 0
        t.append(_knoten(round(x, 1), 392, rv, None, v["label"], [(_zahl(v["total"]), "#16201C", True)], oben=False,
                         ring=[(a, F["solar"]), (v["speicher"] / v["total"] if v["total"] else 0, F["speicher"]),
                               (v["netz"] / v["total"] if v["total"] else 0, F["netz"])],
                         tip=f"{v['label']}: {_zahl(v['total'])} kWh, {a * 100:.0f} % Solar"))
    t.append("</svg>")
    return "".join(t)


SEITE = diagramme.STIL + """
<style>.fluss .kv{font-size:15px;font-weight:700}.fluss .ks{font-size:12.5px;font-weight:600}.fluss .kt{font-size:13px;fill:#5B6660}
.fluss .hitl{cursor:help}.fluss .kn{cursor:help}
.fl-wahl{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:-8px 0 16px}.fl-wahl select{min-height:38px}</style>
<div class="fl-wahl">{% for k, l in tabs %}<a class="btn {{ 'primary' if k == sel }}" href="?p={{ k }}">{{ l }}</a>{% endfor %}
<form method="get" action="./"><input type="hidden" name="p" value="monat"><select name="m" onchange="this.form.submit()" aria-label="Monat">
{% for k, l in monate %}<option value="{{ k }}" {{ 'selected' if sel == 'monat' and k == m }}>{{ l }}</option>{% endfor %}</select></form>
<form method="get" action="./"><input type="hidden" name="p" value="jahr"><select name="j" onchange="this.form.submit()" aria-label="Jahr">
{% for y in jahre %}<option {{ 'selected' if sel == 'jahr' and y == j }}>{{ y }}</option>{% endfor %}</select></form></div>
{% if not w %}<div class="msg warn">{{ fehler }}</div>{% else %}
<div class="card"><h2>{{ titel }}{% if vorlaeufig %} <span class="pill">vorläufig</span>{% endif %}</h2>
{{ svg|safe }}
<div class="legende" style="justify-content:center;margin-top:10px"><span class="lg"><i style="background:{{ F.solar }}"></i>Solar</span>
<span class="lg"><i style="background:{{ F.netz }}"></i>Netz</span><span class="lg"><i style="background:{{ F.rueck }}"></i>Rücklieferung</span>
<span class="lg"><i style="background:{{ F.speicher }}"></i>Speicher</span></div>
<p class="muted" style="text-align:center">{{ quelle }} Ringe zeigen die Herkunft des Stroms. Mit der Maus (oder Tippen) auf Kreise und Linien erscheinen die Werte.</p></div>
<div class="grid">
 <div class="kpi"><div class="t">Autarkie Haus</div><div class="v">{{ '%.0f'|format(k.autarkie) }} <small>%</small></div><div class="s">Anteil Solarstrom am Verbrauch</div></div>
 <div class="kpi"><div class="t">Eigenverbrauch</div><div class="v">{{ '%.0f'|format(k.eigen) }} <small>%</small></div><div class="s">der Produktion im Haus genutzt</div></div>
 <div class="kpi"><div class="t">Netzbezug</div><div class="v">{{ k.netz }} <small>kWh</small></div><div class="s">inkl. Standby PV-Anlage{{ ' und Netzladung' if k.laden }}</div></div>
 <div class="kpi"><div class="t">Rücklieferung</div><div class="v">{{ k.export }} <small>kWh</small></div><div class="s"><a href="uebersicht{{ link_m }}">Details in der Übersicht</a></div></div>
</div>{% endif %}
<script>(function(){if(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)document.querySelectorAll('svg.fluss').forEach(function(s){s.pauseAnimations&&s.pauseAnimations()});
document.querySelectorAll('svg.fluss [data-tip]').forEach(function(e){e.addEventListener('click',function(ev){var t=document.getElementById('tip');if(!t)return;
t.textContent=e.getAttribute('data-tip');t.style.display='block';t.style.left=Math.min(ev.clientX+10,innerWidth-t.offsetWidth-8)+'px';t.style.top=(ev.clientY+14)+'px'})})})();</script>
"""


def seite():
    import uebersicht
    d = uebersicht.daten()
    res, cfg = d["res"], d["cfg"]
    if res is None:
        return S.page("Energiefluss", render_template_string(SEITE, w=None, tabs=[], monate=[], jahre=[], sel="", F=F,
                                                             fehler="Noch keine Daten. Zuerst unter «Daten importieren» die Lastgänge hochladen."))
    heute = date.today()
    letzter = res.index.max().date()
    perioden = sorted(set(res["month"]))
    jahre = sorted({p.year for p in perioden}, reverse=True)
    sel = request.args.get("p") or ("heute" if letzter >= heute else "monat")
    m = request.args.get("m") or str(perioden[-1])
    j = int(request.args.get("j") or jahre[0])
    if sel in ("heute", "gestern"):
        tag = heute if sel == "heute" else heute - timedelta(days=1)
        von = bis = tag
        titel = ("Heute, " if sel == "heute" else "Gestern, ") + f"{tag:%d.%m.%Y}"
    elif sel == "jahr":
        von, bis = date(j, 1, 1), date(j, 12, 31)
        titel = f"Jahr {j}"
    else:
        sel = "monat"
        p = pd.Period(m, "M") if m in [str(x) for x in perioden] else perioden[-1]
        m = str(p)
        von, bis = p.start_time.date(), p.end_time.date()
        titel = f"{MONATE[p.month]} {p.year}"
    r = res[(res.index >= pd.Timestamp(von)) & (res.index < pd.Timestamp(bis) + pd.Timedelta(days=1))]
    tabs = [("heute", "Heute"), ("gestern", "Gestern")]
    mon = [(str(x), f"{MONATE[x.month]} {x.year}") for x in reversed(perioden)]
    if r.empty:
        return S.page("Energiefluss", render_template_string(SEITE, w=None, tabs=tabs, monate=mon, jahre=jahre, sel=sel, m=m, j=j, F=F,
                                                             fehler=f"Für {titel} gibt es noch keine Daten (Lastgänge bis {letzter:%d.%m.%Y})."))
    w = werte(r, cfg)
    sp = solis(S.collector._db, cfg, von, bis)
    ha = "quelle" in r and (r["quelle"] == "ha").any()
    quelle = ("Aus den Primeo-Lastgängen" + (" und der Vorschau aus Home Assistant" if ha else "") + "." if (r.get("quelle", pd.Series(["primeo"])) == "primeo").any()
              else "Vorschau aus den Zählerständen in Home Assistant.")
    if sp:
        quelle += " Speicher: Werte des Wechselrichters."
    k = dict(autarkie=w["solar_haus"] / w["haus"] * 100 if w["haus"] else 0, eigen=w["solar_haus"] / w["prod"] * 100 if w["prod"] else 0,
             netz=_zahl(w["netz_haus"] + w["laden"]), export=_zahl(w["export"]), laden=w["laden"] > 0.005)
    link_m = f"?m={str(pd.Period(von, 'M'))}" if sel != "jahr" else ""
    return S.page("Energiefluss", render_template_string(
        SEITE, w=w, svg=diagramm(w, sp), titel=titel, tabs=tabs, monate=mon, jahre=jahre, sel=sel, m=m, j=j, F=F, k=k,
        quelle=quelle, vorlaeufig=ha or bis >= heute, link_m=link_m))


def register(app, server):
    global S
    S = server
    app.add_url_rule("/", "index", seite)
