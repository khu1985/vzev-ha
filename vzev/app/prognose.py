"""PV-Prognose aus der Solcast-Integration in Home Assistant.

Die Solcast-Sensoren (Prognose heute, morgen, Tag 3 …) haben das Attribut «detailedForecast»: eine Liste mit
period_start (ISO mit Zeitzone) und pv_estimate / pv_estimate10 / pv_estimate90 in kW (Mittel über die Periode,
meist 30 Minuten). Die App findet diese Sensoren selbst (oder nimmt die unter Einstellungen → Zähler eingetragenen)
und speichert:
- prognose: die neueste Prognose pro Periode
- prognose_vortag: die letzte Prognose, die vor dem jeweiligen Tag erstellt wurde (für die Trefferquote)
Solcast überschreibt seine Prognosen; ohne eigenes Speichern liesse sich die Treffsicherheit nicht prüfen.
"""
import logging
from datetime import date, datetime, timedelta

import requests

log = logging.getLogger("vzev")


def init(db):
    with db() as c:
        for t in ("prognose", "prognose_vortag"):
            c.execute(f"""CREATE TABLE IF NOT EXISTS {t} (periode TEXT PRIMARY KEY, minuten INTEGER,
                kw REAL, kw10 REAL, kw90 REAL, stand TEXT)""")


def _lokal(ts):
    """Zeitstempel mit Zeitzone → lokale Wanduhrzeit ohne Zeitzone (Home Assistant liefert Ortszeit)."""
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)


def zerlegen(attr):
    """Attribute eines Solcast-Sensors → [(periode, minuten, kw, kw10, kw90)]."""
    liste = attr.get("detailedForecast") or attr.get("detailed_forecast") or []
    pkt = []
    for e in liste:
        try:
            pkt.append((_lokal(e["period_start"]), float(e["pv_estimate"]),
                        float(e.get("pv_estimate10", e["pv_estimate"])), float(e.get("pv_estimate90", e["pv_estimate"]))))
        except (KeyError, TypeError, ValueError):
            continue
    pkt.sort()
    out = []
    for i, (t, kw, k10, k90) in enumerate(pkt):
        dauer = int((pkt[i + 1][0] - t).total_seconds() // 60) if i + 1 < len(pkt) else (out[-1][1] if out else 30)
        out.append((t, dauer if 0 < dauer <= 60 else 30, kw, k10, k90))
    return out


def speichern(db, zeilen, jetzt=None):
    jetzt = jetzt or datetime.now()
    stand = jetzt.isoformat(timespec="minutes")
    werte = [(t.isoformat(timespec="minutes"), m, kw, k10, k90, stand) for t, m, kw, k10, k90 in zeilen]
    vortag = [w for w, (t, *_ ) in zip(werte, zeilen) if t.date() > jetzt.date()]
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO prognose VALUES (?, ?, ?, ?, ?, ?)", werte)
        c.executemany("INSERT OR REPLACE INTO prognose_vortag VALUES (?, ?, ?, ?, ?, ?)", vortag)
    return len(werte)


def tag(db, d, tabelle="prognose"):
    """Prognose eines Tages: [(zeit, minuten, kw, kw10, kw90)]."""
    with db() as c:
        rows = c.execute(f"SELECT periode, minuten, kw, kw10, kw90 FROM {tabelle} WHERE periode >= ? AND periode < ? ORDER BY periode",
                         (d.isoformat(), (d + timedelta(days=1)).isoformat())).fetchall()
    return [(datetime.fromisoformat(p), m, kw, k10, k90) for p, m, kw, k10, k90 in rows]


def tagessummen(db, von, bis, tabelle="prognose"):
    """kWh pro Tag (P50, P10, P90)."""
    with db() as c:
        rows = c.execute(f"""SELECT substr(periode, 1, 10), SUM(kw * minuten / 60.0), SUM(kw10 * minuten / 60.0), SUM(kw90 * minuten / 60.0)
                             FROM {tabelle} WHERE periode >= ? AND periode < ? GROUP BY 1""",
                         (von.isoformat(), (bis + timedelta(days=1)).isoformat())).fetchall()
    return {date.fromisoformat(d): (p50, p10, p90) for d, p50, p10, p90 in rows}


class Prognose:
    def __init__(self, collector, get_config):
        self.collector = collector
        self.get_config = get_config
        self.status = "noch nicht abgerufen"
        self.fehler = None
        self.entitaeten = []
        init(collector._db)

    def eingestellt(self):
        s = (self.get_config().get("homeassistant") or {}).get("solcast")
        if isinstance(s, str):
            s = [x.strip() for x in s.split(",")]
        return [x for x in (s or []) if x]

    def finden(self, base, token):
        """Alle Sensoren mit Halbstunden-Prognose (Solcast: Prognose heute, morgen, Tag 3 …)."""
        r = requests.get(f"{base}/states", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        r.raise_for_status()
        return sorted(s["entity_id"] for s in r.json()
                      if isinstance((s.get("attributes") or {}).get("detailedForecast"), list))

    def abrufen(self):
        base, token = self.collector._ha()
        if not token:
            self.status = "kein Zugang zu Home Assistant"
            return 0
        ids = self.eingestellt()
        if not ids or any(not x.startswith("sensor.") for x in ids):
            gefunden = self.finden(base, token)
            if ids:  # Kurznamen wie «prognose_heute» → passenden Solcast-Sensor nehmen
                ids = [x if x.startswith("sensor.") else next((g for g in gefunden if g.endswith(x)), None) for x in ids]
                ids = [x for x in ids if x]
            ids = ids or gefunden
        self.entitaeten = ids
        if not ids:
            self.status = "keine Solcast-Sensoren gefunden"
            return 0
        zeilen = []
        for eid in ids:
            r = requests.get(f"{base}/states/{eid}", headers={"Authorization": f"Bearer {token}"}, timeout=15)
            if r.status_code == 200:
                zeilen += zerlegen(r.json().get("attributes") or {})
        n = speichern(self.collector._db, zeilen)
        tage = sorted({t.date() for t, *_ in zeilen})
        neu = f"{n} Perioden aus {len(ids)} Sensor(en), bis {tage[-1]:%d.%m.%Y}" if tage else "Sensoren ohne Prognosedaten"
        if not self.status[:1].isdigit():  # erster Abruf oder nach einem Problem
            log.info("PV-Prognose: %s", neu)
        self.status = f"{neu} · {datetime.now():%H:%M}"
        self.fehler = None
        return n


# =============================================================================
# Seite «Prognose»
# =============================================================================
S = None

SEITE = """
<div style="display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap">{% for k, lab in tage %}<a class="btn {{ 'primary' if k == d_key }}" href="prognose?d={{ k }}">{{ lab }}</a>{% endfor %}</div>
<div class="grid">
{% for k in kpis %}<div class="kpi"><div class="t">{{ k.t }}</div><div class="v">{{ k.v }} <small>{{ k.e }}</small></div><div class="s">{{ k.s }}</div></div>{% endfor %}
</div>
<div class="card"><h2>{{ titel }}</h2>{{ chart|safe }}
<p class="muted">Prognose von Solcast in Halbstunden, gestrichelt mit Bandbreite (10 % / 90 %). Gemessen: PV-Ertrag des Wechselrichters.
Üblicher Verbrauch: Mittel der letzten 4 Wochen zur gleichen Uhrzeit (1. OG, 2. OG, Allgemein ohne Ladestation).</p></div>
{% if preis_info %}<div class="card"><h2>Günstig aus dem Netz laden</h2>
{% if fenster %}<table><tr><th class="l">Zeitfenster</th><th>Ø Preis Rp./kWh</th><th>Fehlt aus PV kWh</th></tr>
{% for f in fenster %}<tr><td class="l">{{ f.von }}–{{ f.bis }}</td><td>{{ '%.1f'|format(f.preis) }}</td><td>{{ '%.1f'|format(f.fehlt) }}</td></tr>{% endfor %}</table>
<p class="muted">Viertelstunden, deren Preis im untersten Viertel zwischen Tiefst- und Höchstpreis liegt und in denen die Solarprognose den üblichen Verbrauch nicht deckt. Nur Anzeige – die App steuert weder Batterie noch Wallbox.</p>
{% else %}<p>{{ preis_info }}</p>{% endif %}</div>{% endif %}
<div class="card"><h2>Trefferquote (Prognose vom Vortag)</h2>
{% if treffer %}<div class="grid" style="margin-bottom:12px">
<div class="kpi"><div class="t">Abweichung Ø</div><div class="v">{{ '%+.0f'|format(tq.mittel) }} <small>%</small></div><div class="s">{{ 'Solcast schätzt eher zu hoch' if tq.mittel > 5 else 'Solcast schätzt eher zu tief' if tq.mittel < -5 else 'ohne deutliche Tendenz' }}</div></div>
<div class="kpi"><div class="t">Im Band 10–90 %</div><div class="v">{{ tq.im_band }} <small>von {{ tq.n }} Tagen</small></div><div class="s">ideal sind rund 80 %</div></div>
</div>
<div class="scroll"><table class="wide"><tr><th class="l">Tag</th><th>Prognose kWh</th><th>Band kWh</th><th>Gemessen kWh</th><th>Abweichung</th></tr>
{% for r in treffer[:14] %}<tr><td class="l">{{ wt[r.tag.weekday()][:2] }} {{ r.tag.strftime('%d.%m.') }}</td><td>{{ '%.1f'|format(r.p50) }}</td><td>{{ '%.1f'|format(r.p10) }}–{{ '%.1f'|format(r.p90) }}</td>
<td>{{ '%.1f'|format(r.ist) }}</td><td>{{ '%+.0f %%'|format(r.abw) if r.abw is not none else '–' }}{{ ' ✓' if r.im_band }}</td></tr>{% endfor %}</table></div>
<p class="muted">{% if treffer|length > 14 %}Letzte 14 Tage; die Kennzahlen oben gelten für {{ treffer|length }} Tage. {% endif %}Abweichung = Prognose gegenüber gemessenem PV-Ertrag. Liegt sie dauerhaft daneben, in Solcast Ausrichtung, Neigung oder Leistung der Anlage prüfen.</p>
{% else %}<p class="muted">Erscheint, sobald die App für ganze Tage eine Prognose vom Vortag und gemessene Werte hat (frühestens übermorgen).</p>{% endif %}</div>
<div class="card"><h2>Quelle</h2><p>{{ st.status }}{% if st.fehler %} · <b>Fehler:</b> {{ st.fehler }}{% endif %}</p>
<p class="muted">Sensoren: {{ st.entitaeten|join(', ') if st.entitaeten else 'automatisch (alle mit «detailedForecast»)' }} – ändern unter <a href="einstellungen?tab=zaehler">Einstellungen → Zähler</a>. Abruf stündlich.</p>
<form method="post" action="prognose_abrufen" data-busy="PV-Prognose wird abgerufen …"><button>Jetzt abrufen</button></form></div>
"""

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _messreihe(db, entity, von, bis, taeglich):
    """kWh pro Viertelstunde aus gespeicherten Zählerständen (Index = Beginn der Viertelstunde)."""
    import pandas as pd
    import vorschau
    if not entity:
        return pd.Series(dtype=float)
    with db() as c:
        roh = c.execute("SELECT ts, wert FROM messwerte WHERE entity=? AND ts >= ? AND ts <= ? ORDER BY ts",
                        (entity, von.isoformat(), bis.isoformat())).fetchall()
    if not roh:
        return pd.Series(dtype=float)
    s = pd.Series([w for _, w in roh], index=pd.to_datetime([t for t, _ in roh]))
    return vorschau._deltas(s[~s.index.duplicated(keep="last")], taeglich)


def ueblicher_verbrauch(db, cfg, heute):
    """kW nach Uhrzeit (Minute → kW), Mittel der letzten 28 Tage, ohne Ladestation."""
    import pandas as pd
    z = (cfg.get("homeassistant") or {}).get("zaehler") or {}
    von, bis = datetime.combine(heute - timedelta(days=28), datetime.min.time()), datetime.combine(heute, datetime.min.time())
    teile = [_messreihe(db, z.get(k), von, bis, False) for k in ("1OG", "2OG", "Allg")]
    if any(t.empty for t in teile):
        return []
    haus = sum(teile[1:], teile[0]).dropna()
    ev = _messreihe(db, z.get("ladestation"), von, bis, False)
    if not ev.empty:
        haus = (haus - ev.reindex(haus.index).fillna(0)).clip(lower=0)
    if len(haus) < 96:
        return []
    m = haus.groupby(haus.index.hour * 60 + haus.index.minute).mean() * 4
    return [(int(k), float(v)) for k, v in m.items()]


def preise_tag(db, cfg, d):
    """Dynamischer Preis inkl. Konzessionsabgabe und MWST in Rp./kWh: [(minute, rp)]."""
    import core
    r = core.dyn_regeln(cfg)
    with db() as c:
        rows = c.execute("SELECT start_lokal, typ, chf_kwh FROM preise WHERE start_lokal >= ? AND start_lokal < ?",
                         (d.isoformat(), (d + timedelta(days=1)).isoformat())).fetchall()
    w = {}
    for t, typ, chf in rows:
        w.setdefault(t[:16], {})[typ] = chf
    out = []
    for t in sorted(w):
        if "integrated" in w[t]:
            p = (w[t]["integrated"] + float(r["konzession_prozent"]) / 100 * w[t].get("grid_usage", 0)) * (1 + float(r["mwst_prozent"]) / 100)
            zt = datetime.fromisoformat(t)
            out.append((zt.hour * 60 + zt.minute, p * 100))
    return out


def ladefenster(pv, verbrauch, preis, anteil=0.25):
    """Zusammenhängende Viertelstunden, deren Preis im untersten Viertel der Tagesspanne liegt und in denen
    PV (P50) den üblichen Verbrauch nicht deckt."""
    if not preis or not verbrauch:
        return []
    pvq = {}
    for m, d, k50, _, _ in pv:
        for q in range(int(m), int(m + d), 15):
            pvq[q] = k50
    vq = dict(verbrauch)
    lo, hi = min(v for _, v in preis), max(v for _, v in preis)
    if hi - lo < 0.5:  # praktisch gleicher Preis den ganzen Tag: kein Zeitfenster ist günstiger
        return []
    grenze = lo + anteil * (hi - lo)
    gut = [(m, v, vq.get(m, 0) - pvq.get(m, 0)) for m, v in preis if v <= grenze and vq.get(m, 0) - pvq.get(m, 0) > 0.1]
    out = []
    for m, v, fehlt in gut:
        if out and out[-1]["bis_m"] == m:
            f = out[-1]
            f["bis_m"], f["summe"], f["n"], f["fehlt"] = m + 15, f["summe"] + v, f["n"] + 1, f["fehlt"] + fehlt / 4
        else:
            out.append(dict(von_m=m, bis_m=m + 15, summe=v, n=1, fehlt=fehlt / 4))
    for f in out:
        f.update(von=f"{f['von_m'] // 60:02d}:{f['von_m'] % 60:02d}", bis=f"{f['bis_m'] // 60:02d}:{f['bis_m'] % 60:02d}", preis=f["summe"] / f["n"])
    return out


def pv_ist_tage(db, cfg, von, bis):
    """Gemessener PV-Ertrag pro Tag (Höchstwert des Solis-Tageszählers)."""
    e = ((cfg.get("homeassistant") or {}).get("solis") or {}).get("pv_heute")
    if not e:
        return {}
    with db() as c:
        rows = c.execute("SELECT substr(ts, 1, 10), MAX(wert), MIN(ts) FROM messwerte WHERE entity=? AND ts >= ? AND ts < ? GROUP BY 1",
                         (e, von.isoformat(), (bis + timedelta(days=1)).isoformat())).fetchall()
    # nur Tage, an denen ab Mitternacht gesammelt wurde (sonst fehlt der Morgen nicht, aber der Tag ist unsicher)
    return {date.fromisoformat(d): w for d, w, erst in rows if erst[11:16] <= "06:00"}


def treffer(db, cfg, heute, tage=30):
    vortag = tagessummen(db, heute - timedelta(days=tage), heute - timedelta(days=1), "prognose_vortag")
    ist = pv_ist_tage(db, cfg, heute - timedelta(days=tage), heute - timedelta(days=1))
    out = []
    for d in sorted(set(vortag) & set(ist), reverse=True):
        p50, p10, p90 = vortag[d]
        i = ist[d]
        out.append(dict(tag=d, p50=p50, p10=p10, p90=p90, ist=i, abw=(p50 - i) / i * 100 if i > 0.5 else None,
                        im_band=p10 - 0.05 <= i <= p90 + 0.05))
    return out


def seite():
    from flask import render_template_string, request
    import diagramme
    cfg = S.config()
    db = S.collector._db
    heute = date.today()
    verfuegbar = sorted(tagessummen(db, heute, heute + timedelta(days=6)))
    tage = [("heute", "Heute"), ("morgen", "Morgen")] + [
        (d.isoformat(), WOCHENTAG[d.weekday()]) for d in verfuegbar if d > heute + timedelta(days=1)]
    d_key = request.args.get("d") or "heute"
    d = heute if d_key == "heute" else heute + timedelta(days=1) if d_key == "morgen" else date.fromisoformat(d_key)
    pv = [((t.hour * 60 + t.minute), m, k50, k10, k90) for t, m, k50, k10, k90 in tag(db, d)]
    sol = ((cfg.get("homeassistant") or {}).get("solis") or {}).get("pv_heute")
    gem = _messreihe(db, sol, datetime.combine(d, datetime.min.time()), datetime.combine(d + timedelta(days=1), datetime.min.time()), True)
    gem = gem[gem.index.date == d] if len(gem) else gem
    gemessen = [(t.hour * 60 + t.minute, float(v) * 4) for t, v in gem.items()]
    verbrauch = ueblicher_verbrauch(db, cfg, heute)
    preis = preise_tag(db, cfg, d)
    fenster = ladefenster(pv, verbrauch, preis)
    jetzt = datetime.now()
    chart = diagramme.prognose_tag(pv, gemessen, verbrauch, preis, [(f["von_m"], f["bis_m"]) for f in fenster],
                                   jetzt=(jetzt.hour * 60 + jetzt.minute) if d == heute else None)
    summen = tagessummen(db, heute, heute + timedelta(days=2))
    kpis = []
    for dd, lab in [(heute, "Prognose heute"), (heute + timedelta(days=1), "Prognose morgen"), (heute + timedelta(days=2), "Übermorgen")]:
        if dd in summen:
            p50, p10, p90 = summen[dd]
            kpis.append(dict(t=lab, v=f"{p50:.1f}", e="kWh", s=f"Band {p10:.1f}–{p90:.1f} kWh"))
    ist_heute = pv_ist_tage(db, cfg, heute, heute).get(heute)
    if d == heute and len(gem):
        kpis.insert(1, dict(t="Gemessen heute", v=f"{float(gem.sum()):.1f}", e="kWh", s=f"bis {gem.index.max() + timedelta(minutes=15):%H:%M}"))
    elif ist_heute is not None:
        kpis.insert(1, dict(t="Gemessen heute", v=f"{ist_heute:.1f}", e="kWh", s="Tageszähler Wechselrichter"))
    if not preis:
        preis_info = ("Strompreise für diesen Tag sind noch nicht publiziert (Primeo ab 18 Uhr für den nächsten Tag)."
                      if d > heute else "Für diesen Tag sind keine dynamischen Strompreise gespeichert (Abruf ab dem unter «Tarife» eingestellten Datum).")
    else:
        preis_info = "Heute lohnt sich kein Laden aus dem Netz: Die Sonne deckt den Verbrauch in den günstigen Viertelstunden." if not fenster else "ok"
    tr = treffer(db, cfg, heute)
    gueltig = [r["abw"] for r in tr if r["abw"] is not None]
    tq = dict(mittel=sum(gueltig) / len(gueltig) if gueltig else 0, im_band=sum(r["im_band"] for r in tr), n=len(tr))
    titel = {"heute": "Heute", "morgen": "Morgen"}.get(d_key, WOCHENTAG[d.weekday()]) + f", {d:%d.%m.%Y}"
    st = S.pvprognose
    return S.page("Prognose", diagramme.STIL + render_template_string(
        SEITE, tage=tage, d_key=d_key, kpis=kpis, chart=chart, titel=titel, fenster=fenster, preis_info=preis_info,
        treffer=tr, tq=tq, wt=WOCHENTAG, st=dict(status=st.status, fehler=st.fehler, entitaeten=st.entitaeten or st.eingestellt())))


def abrufen_seite():
    from flask import redirect
    try:
        n = S.pvprognose.abrufen()
        return redirect(f"prognose?msg={S.pvprognose.status if n else 'Keine Prognose: ' + S.pvprognose.status}" + ("" if n else "&c=warn"))
    except Exception as e:
        S.pvprognose.fehler = str(e)
        return redirect(f"prognose?c=warn&msg=Abruf fehlgeschlagen: {e}")


def kurz(db):
    """Für die Übersicht: (heute, morgen) in kWh oder None."""
    heute = date.today()
    s = tagessummen(db, heute, heute + timedelta(days=1))
    return (s.get(heute, (None,))[0], s.get(heute + timedelta(days=1), (None,))[0])


def register(app, server):
    global S
    S = server
    app.add_url_rule("/prognose", "prognose", seite)
    app.add_url_rule("/prognose_abrufen", "prognose_abrufen", abrufen_seite, methods=["POST"])
