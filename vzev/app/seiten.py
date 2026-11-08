"""Weitere Seiten der vZEV-App: Mieter, Tarife, Primeo, Abschluss, Batterie und Einstellungen in Formularen.

Die Formulare ändern jeweils nur ihren Abschnitt in vzev.yaml; Kommentare in den übrigen Abschnitten bleiben erhalten.
Abgeschlossene Monate sind gesperrt: Änderungen, die sie betreffen würden, werden abgelehnt, bis der Monat
mit Begründung wieder geöffnet wird.
"""
import json
import shutil
from datetime import date, datetime, timedelta

import pandas as pd
import yaml
from flask import redirect, render_template_string, request

import core

S = None  # server-Modul, wird in register() gesetzt


# =============================================================================
# vzev.yaml abschnittsweise speichern
# =============================================================================
def _flow(x):
    t = yaml.safe_dump(x, default_flow_style=True, allow_unicode=True, width=10 ** 6, sort_keys=False)
    return t.replace("\n...\n", "").strip()


def _emit(v, ind=""):
    out = []
    for k, x in v.items():
        key = _flow(k)
        if isinstance(x, list) and x and all(isinstance(i, (dict, list)) for i in x):
            out.append(f"{ind}{key}:")
            out += [f"{ind}  - {_flow(i)}" for i in x]
        elif isinstance(x, dict) and x:
            out.append(f"{ind}{key}:")
            out += _emit(x, ind + "  ")
        else:
            out.append(f"{ind}{key}: {_flow(x)}")
    return out


def abschnitt_speichern(name, wert, kommentar=None):
    """Ersetzt einen Abschnitt der obersten Ebene in vzev.yaml."""
    text = S.CFG.read_text(encoding="utf-8")
    zeilen = text.splitlines()
    neu = ([f"# {kommentar}"] if kommentar else []) + _emit({name: wert})
    start = next((i for i, z in enumerate(zeilen) if z.startswith(f"{name}:")), None)
    if start is None:
        zeilen += [""] + neu
    else:
        # nächster Abschnitt = nächste Zeile, die mit einem Schlüssel beginnt (Listen dürfen auch ganz links stehen)
        ende = next((i for i in range(start + 1, len(zeilen)) if zeilen[i][:1] not in ("", " ", "\t", "#", "-")), len(zeilen))
        while ende > start + 1 and (zeilen[ende - 1].startswith("#") or not zeilen[ende - 1].strip()):
            ende -= 1  # Kommentare direkt vor dem nächsten Abschnitt gehören zu diesem
        if kommentar and start > 0 and zeilen[start - 1].startswith("#"):
            start -= 1
        zeilen[start:ende] = neu + ([""] if ende < len(zeilen) else [])
    ergebnis = "\n".join(zeilen) + "\n"
    try:
        geprueft = yaml.safe_load(ergebnis)
    except yaml.YAMLError as e:
        raise ValueError(f"Speichern hätte vzev.yaml unlesbar gemacht – abgebrochen ({e.problem})")
    if _norm(geprueft.get(name)) != _norm(wert):
        raise ValueError("Speichern hätte die Datei verändert – abgebrochen")
    shutil.copy(S.CFG, S.CFG.with_suffix(".yaml.bak"))
    S.CFG.write_text(ergebnis, encoding="utf-8")


def _norm(x):
    return json.loads(json.dumps(x, default=str))


# =============================================================================
# Tabellen-Editor
# =============================================================================
EDITOR = """
<div class="scroll"><table class="edit" id="t-{{ p }}">
<tr>{% for f in felder %}<th class="l">{{ f.label }}</th>{% endfor %}<th class="l">Entfernen</th></tr>
{% for r in rows + [{}] %}<tr class="{{ 'neu' if loop.last }}">
{% for f in felder %}<td class="l">{% set v = r.get(f.key) %}
{% if f.typ == 'auswahl' %}<select name="{{ p }}.{{ f.key }}"><option value=""></option>
{% for o in f.opts %}<option value="{{ o[0] }}" {{ 'selected' if v is not none and o[0] == v|string }}>{{ o[1] }}</option>{% endfor %}</select>
{% else %}<input name="{{ p }}.{{ f.key }}" type="{{ 'date' if f.typ == 'datum' else 'text' }}" inputmode="{{ 'decimal' if f.typ == 'zahl' else 'text' }}"
 value="{{ '' if v is none else (v.isoformat() if f.typ == 'datum' and v.isoformat is defined else v) }}" placeholder="{{ f.hinweis or '' }}" style="width:{{ f.breite or 140 }}px">{% endif %}</td>{% endfor %}
<td class="l">{% if not loop.last %}<label><input type="checkbox" name="{{ p }}.__weg" value="{{ loop.index0 }}"> entfernen</label>{% else %}<span class="muted">neu</span>{% endif %}</td></tr>{% endfor %}
</table></div>
<p><button type="button" onclick="(function(t){var r=t.querySelector('tr.neu');var c=r.cloneNode(true);c.querySelectorAll('input,select').forEach(function(i){i.value=''});r.parentNode.appendChild(c)})(document.getElementById('t-{{ p }}'))">+ Zeile</button></p>"""


def editor(p, felder, rows):
    return render_template_string(EDITOR, p=p, felder=felder, rows=rows)


def _wert(f, roh):
    roh = (roh or "").strip()
    if not roh:
        return None
    if f["typ"] == "datum":
        return date.fromisoformat(roh)
    if f["typ"] == "zahl":
        return float(roh.replace("'", "").replace(",", "."))
    if f["typ"] == "ganz":
        return int(float(roh.replace("'", "")))
    return roh


def lesen(p, felder):
    spalten = {f["key"]: request.form.getlist(f"{p}.{f['key']}") for f in felder}
    n = max((len(v) for v in spalten.values()), default=0)
    weg = {int(i) for i in request.form.getlist(f"{p}.__weg")}
    out = []
    for i in range(n):
        if i in weg:
            continue
        roh = {k: (v[i] if i < len(v) else "") for k, v in spalten.items()}
        if not any(x.strip() for x in roh.values()):
            continue
        r = {}
        for f in felder:
            try:
                r[f["key"]] = _wert(f, roh[f["key"]])
            except ValueError:
                raise ValueError(f"Zeile {i + 1}, «{f['label']}»: «{roh[f['key']]}» ist kein gültiger Wert")
        out.append(r)
    return out


def _d(x):
    if x is None or x == "":
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


# =============================================================================
# Abschluss
# =============================================================================
def _abschluss_datei():
    return S.DATA / "abschluss.json"


def abschluss_laden():
    try:
        return json.loads(_abschluss_datei().read_text(encoding="utf-8"))
    except Exception:
        return {"monate": {}, "korrekturen": []}


def abschluss_speichern(a):
    _abschluss_datei().write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")


def gesperrt_bis():
    """Letzter Tag des letzten abgeschlossenen Monats oder None."""
    m = sorted(abschluss_laden()["monate"])
    return (pd.Period(m[-1], "M").end_time.date()) if m else None


def korrektur(monat, art, grund):
    a = abschluss_laden()
    a["korrekturen"].append({"zeit": datetime.now().strftime("%Y-%m-%d %H:%M"), "monat": monat, "art": art, "grund": grund})
    abschluss_speichern(a)
    S.log.warning("Korrektur %s: %s – %s", monat, art, grund)


ZL = [("1OG", "1. OG"), ("2OG", "2. OG"), ("AllgC", "Allgemein"), ("EV", "Ladestation")]


def monatswerte(b):
    """Gerundete Werte pro Monat, die beim Abschluss festgehalten werden."""
    if not b.get("ok"):
        return {}
    if b.get("_mw_key") == b.get("key"):
        return b["_mw"]
    res, cfg = b["res"], b["cfg"]
    out = {}
    sums = {k: core.zaehler_summen(res, k) for k, _ in ZL}
    w = core.wertschoepfung(res, cfg)
    for m in sums["1OG"].index:
        d = {}
        for k, _ in ZL:
            r = sums[k].loc[m]
            d[k] = {"solar": round(r.solar, 3), "ht": round(r.ht, 3), "nt": round(r.nt, 3), "chf": round(r.solar_chf + r.netz_chf + r.speicher_chf - max(r.bonus_chf, 0), 2)}
        wr = w.loc[m] if m in w.index else None
        d["wertschoepfung"] = None if wr is None or pd.isna(wr.total_chf) else round(float(wr.total_chf), 2)
        d["rueck_offen"] = bool(wr is not None and pd.isna(wr.export_chf))
        lv = sums["1OG"].loc[m, "letzte_viertelstunde"]
        d["vollstaendig"] = bool(lv >= m.end_time.floor("15min")) and m.end_time.date() < date.today()
        out[str(m)] = d
    b["_mw"], b["_mw_key"] = out, b.get("key")
    return out


def abweichungen(b):
    """Abgeschlossene Monate, deren Werte sich seither geändert haben."""
    a, mw, out = abschluss_laden(), monatswerte(b), []
    for m, e in a["monate"].items():
        jetzt = mw.get(m)
        if jetzt is None:
            out.append((m, "Daten fehlen"))
            continue
        alt = e["werte"]
        diffs = []
        for k, label in ZL:
            dchf = jetzt[k]["chf"] - alt[k]["chf"]
            dkwh = sum(abs(jetzt[k][x] - alt[k][x]) for x in ("solar", "ht", "nt"))
            if abs(dchf) > 0.01 or dkwh > 0.01:
                diffs.append(f"{label} {dchf:+.2f} CHF")
        dw = (jetzt["wertschoepfung"] or 0) - (alt["wertschoepfung"] or 0)
        if abs(dw) > 0.01:
            diffs.append(f"Wertschöpfung {dw:+.2f} CHF")
        if diffs:
            out.append((m, ", ".join(diffs)))
    return sorted(out)


def _tage(bis, ab=None):
    d = ab or date(2000, 1, 1)
    while d <= bis:
        yield d
        d += timedelta(days=1)


def sperre_pruefen(alt_fn, neu_fn, start):
    """Vergleicht für jeden Tag bis zum Ende der Sperre; gibt den ersten betroffenen Tag zurück."""
    bis = gesperrt_bis()
    if not bis:
        return None
    for d in _tage(bis, start):
        if alt_fn(d) != neu_fn(d):
            return d
    return None


def _gueltig(entries, d, key):
    v = None
    for e in sorted(entries or [], key=lambda e: str(e["ab"])):
        if _d(e["ab"]) <= d:
            v = e.get(key)
    return v


def _vzev_start(cfg):
    return _d(cfg.get("vzev_start")) or date(2026, 1, 1)


def _sperrtext(d):
    m = d.strftime("%m.%Y")
    return f"Nicht gespeichert: Die Änderung betrifft den abgeschlossenen Monat {m}. Öffne ihn zuerst unter «Abschluss» mit Begründung wieder."


# =============================================================================
# Seiten
# =============================================================================
MIETER = """
<div class="card"><h2>Historie</h2>
{% for e, perioden in historie %}<p style="margin:12px 0 6px"><b>{{ einheiten.get(e, e) }}</b></p>
<div class="zeitachse">{% for p in perioden %}<div class="seg {{ 'leer' if p.leer }}" style="flex:{{ p.tage }}" title="{{ p.text }}">
<span>{{ p.name }}</span><small>{{ p.von.strftime('%d.%m.%Y') }} – {{ p.bis.strftime('%d.%m.%Y') if p.bis else 'offen' }}</small></div>{% endfor %}</div>
{% endfor %}
<p class="muted">Lücken zählen als Leerstand: Die Kosten trägt der Betreiber, der Solarstrom gilt in der Wertschöpfung als Eigenverbrauch.</p></div>
<form method="post" action="mieter" class="card"><h2>Mietverhältnisse</h2>
{{ tabelle|safe }}
<p class="muted">Bis leer = läuft noch. Adresse leer = Adresse der Liegenschaft. Jede Zeile ergibt eine eigene Rechnung pro Quartal.</p>
<button class="primary">Speichern</button></form>
<style>.zeitachse{display:flex;gap:3px;min-height:52px}@media (max-width:759px){.zeitachse{flex-direction:column}.seg{flex:none!important}}.seg{background:var(--okbg);color:var(--ok);border-radius:8px;padding:6px 8px;overflow:hidden;min-width:70px}
.seg span{display:block;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.seg small{font-size:11px;white-space:nowrap}
.seg.leer{background:var(--warnbg);color:var(--warn)}</style>"""


def _mieter_felder(cfg):
    einheiten = _einheiten(cfg)
    return [dict(key="einheit", label="Einheit", typ="auswahl", opts=list(einheiten.items())),
            dict(key="name", label="Mieter", typ="text", breite=220),
            dict(key="von", label="Von", typ="datum"), dict(key="bis", label="Bis", typ="datum"),
            dict(key="strasse", label="Strasse", typ="text", breite=150), dict(key="hausnr", label="Nr.", typ="text", breite=50),
            dict(key="plz", label="PLZ", typ="text", breite=60), dict(key="ort", label="Ort", typ="text", breite=110)]


def _einheiten(cfg):
    namen = {"1OG": "1. OG", "2OG": "2. OG", "EG": "EG", "UG": "UG", "DG": "DG"}
    keys = [v for v in (cfg.get("messpunkte") or {}).values() if v not in ("Allg", "PVA", "Prod")]
    keys += [m["einheit"] for m in cfg.get("mietverhaeltnisse") or [] if m.get("einheit") not in keys]
    return {k: namen.get(k, k) for k in keys}


def _mieter_am(liste, d):
    return sorted((m["einheit"], m["name"], m.get("strasse"), m.get("hausnr"), m.get("plz"), m.get("ort"))
                  for m in liste if _d(m["von"]) <= d and (not m.get("bis") or d <= _d(m["bis"])))


def _historie(cfg):
    start = min([_vzev_start(cfg)] + [_d(m["von"]) for m in cfg.get("mietverhaeltnisse") or []])
    ende = date.today()
    out = []
    for e in _einheiten(cfg):
        ms = sorted((m for m in cfg.get("mietverhaeltnisse") or [] if m["einheit"] == e), key=lambda m: str(m["von"]))
        if not ms:
            continue
        perioden, cur = [], start
        for m in ms:
            von, bis = _d(m["von"]), _d(m.get("bis"))
            if von > cur:
                perioden.append(dict(leer=True, name="Leerstand", von=cur, bis=von - timedelta(days=1)))
            perioden.append(dict(leer=False, name=m["name"], von=von, bis=bis))
            cur = (bis + timedelta(days=1)) if bis else None
            if cur is None:
                break
        if cur and cur <= ende:
            perioden.append(dict(leer=True, name="Leerstand", von=cur, bis=None))
        for p in perioden:
            p["tage"] = max(1, ((p["bis"] or ende) - p["von"]).days + 1)
            p["text"] = f"{p['name']}: {p['von']:%d.%m.%Y} – {p['bis'].strftime('%d.%m.%Y') if p['bis'] else 'offen'}"
        out.append((e, perioden))
    return out


def mieter():
    cfg = S.config()
    felder = _mieter_felder(cfg)
    if request.method == "POST":
        try:
            neu = lesen("m", felder)
            b = cfg.get("betreiber", {})
            for i, m in enumerate(neu, 1):
                if not (m["einheit"] and m["name"] and m["von"]):
                    raise ValueError(f"Zeile {i}: Einheit, Mieter und Von sind nötig")
                if m["bis"] and m["bis"] < m["von"]:
                    raise ValueError(f"Zeile {i}: «Bis» liegt vor «Von»")
                for k in ("strasse", "hausnr", "plz", "ort"):
                    m[k] = m[k] or b.get(k)
            neu.sort(key=lambda m: (m["einheit"], m["von"]))
            for a, c in zip(neu, neu[1:]):
                if a["einheit"] == c["einheit"] and (a["bis"] is None or a["bis"] >= c["von"]):
                    raise ValueError(f"{a['name']} und {c['name']} überschneiden sich in {_einheiten(cfg).get(a['einheit'])}")
            alt = cfg.get("mietverhaeltnisse") or []
            d = sperre_pruefen(lambda t: _mieter_am(alt, t), lambda t: _mieter_am(neu, t), _vzev_start(cfg))
            if d:
                return redirect("mieter?c=warn&msg=" + _sperrtext(d))
            abschnitt_speichern("mietverhaeltnisse", neu, "Mietverhältnisse – bearbeitet in der App, Bis leer = läuft noch")
            S.log.info("Mietverhältnisse gespeichert (%d Einträge)", len(neu))
            return redirect("mieter?msg=Gespeichert")
        except ValueError as e:
            return redirect(f"mieter?c=warn&msg=Nicht gespeichert: {e}")
    rows = [dict(m, von=_d(m["von"]), bis=_d(m.get("bis"))) for m in cfg.get("mietverhaeltnisse") or []]
    return S.page("Mieter", render_template_string(MIETER, historie=_historie(cfg), einheiten=_einheiten(cfg),
                                                   tabelle=editor("m", felder, rows)))


# --- Tarife -------------------------------------------------------------------
TARIF_ARTEN = [
    ("solar", "Solarstrom (vZEV-Preis)", [("chf", "CHF/kWh")], "Interner Preis, den die Mieter für Solarstrom zahlen."),
    ("netz", "Netzstrom Primeo", [("ht", "HT CHF/kWh"), ("nt", "NT CHF/kWh")], "Inkl. Netznutzung, Abgaben, Konzession und MWST."),
    ("ruecklieferung", "Rücklieferung", [("chf", "CHF/kWh")], "Inkl. HKN. Leer = noch nicht bekannt (wird in der Wertschöpfung offen gelassen)."),
    ("grundpreis_zaehler", "Grundpreis pro Zähler", [("chf", "CHF/Monat")], "Grundpreis Netznutzung anteilig, Messtarif, Konzessionsabgabe."),
]

TARIFE = """
<div class="grid" style="margin-bottom:20px">{% for k, label, felder, _ in arten %}<div class="kpi"><div>{{ label }} heute</div>
<div>{% for f in felder %}{{ heute[k][f[0]] if heute[k][f[0]] is not none else 'offen' }}{{ ' / ' if not loop.last }}{% endfor %}</div></div>{% endfor %}</div>
{{ preiskarte|safe }}
<form method="post" action="tarife">
{% for k, label, felder, hilfe in arten %}<div class="card"><h2>{{ label }}</h2>{{ tabellen[k]|safe }}<p class="muted">{{ hilfe }} Jeder Eintrag gilt ab dem Datum bis zum nächsten.</p></div>{% endfor %}
<p><button class="primary">Alle Tarife speichern</button> <span class="muted">Gesperrt bis: {{ sperre.strftime('%d.%m.%Y') if sperre else 'kein Monat abgeschlossen' }}</span></p></form>"""


def tarife():
    cfg = S.config()
    if request.method == "POST" and request.args.get("teil") == "dynamisch":
        url = (request.form.get("api_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return redirect("tarife?c=warn&msg=Nicht gespeichert: Die Adresse muss mit http:// oder https:// beginnen")
        try:
            ab = _d(request.form.get("abrufen_ab") or "2027-01-01")
        except ValueError:
            return redirect("tarife?c=warn&msg=Nicht gespeichert: ungültiges Datum")
        neu = dict(cfg.get("dynamisch") or {})  # Bonus-Einstellungen behalten
        neu.update({"api_url": url, "tarif_name": (request.form.get("tarif_name") or "NetzDynamisch").strip(),
                    "tarif_typ": request.form.get("tarif_typ") or "", "abrufen_ab": ab, "aktiv": bool(request.form.get("aktiv"))})
        abschnitt_speichern("dynamisch", neu, "Dynamische Strompreise – bearbeitet in der App")
        S.log.info("Preis-Schnittstelle gespeichert: %s (%s, %s)", url, neu["tarif_name"], neu["tarif_typ"] or "alle")
        return redirect("tarife?msg=Gespeichert")
    tar = cfg.get("tarife") or {}
    felder = {k: [dict(key="ab", label="Gültig ab", typ="datum")] + [dict(key=f, label=l, typ="zahl", breite=110) for f, l in fs]
              for k, _, fs, _ in TARIF_ARTEN}
    if request.method == "POST":
        try:
            neu = {}
            for k, label, fs, _ in TARIF_ARTEN:
                rows = lesen(k, felder[k])
                if any(r["ab"] is None for r in rows):
                    raise ValueError(f"{label}: Jede Zeile braucht ein «Gültig ab»")
                if len({r["ab"] for r in rows}) != len(rows):
                    raise ValueError(f"{label}: Ein Datum kommt doppelt vor")
                if not rows and k != "ruecklieferung":
                    raise ValueError(f"{label}: mindestens ein Eintrag nötig")
                neu[k] = sorted(rows, key=lambda r: r["ab"])
            schluessel = [(k, f) for k, _, fs, _ in TARIF_ARTEN for f, _ in fs]
            werte = lambda t: lambda d: tuple(_gueltig(t.get(k), d, f) for k, f in schluessel)
            d = sperre_pruefen(werte(tar), werte(neu), _vzev_start(cfg))
            if d:
                return redirect("tarife?c=warn&msg=" + _sperrtext(d))
            rest = {k: v for k, v in tar.items() if k not in neu}
            abschnitt_speichern("tarife", {**neu, **rest}, "Tarife – bearbeitet in der App, jeder Eintrag gilt ab dem Datum bis zum nächsten")
            S.log.info("Tarife gespeichert")
            return redirect("tarife?msg=Gespeichert")
        except ValueError as e:
            return redirect(f"tarife?c=warn&msg=Nicht gespeichert: {e}")
    heute = {k: {f: _gueltig(tar.get(k), date.today(), f) for f, _ in fs} for k, _, fs, _ in TARIF_ARTEN}
    tabellen = {k: editor(k, felder[k], [dict(r, ab=_d(r["ab"])) for r in tar.get(k) or []]) for k, _, _, _ in TARIF_ARTEN}
    return S.page("Tarife", render_template_string(TARIFE, preiskarte=render_template_string(PREISKARTE, p=preis_infos()), arten=TARIF_ARTEN, heute=heute, tabellen=tabellen, sperre=gesperrt_bis()))


# --- Primeo -------------------------------------------------------------------
PRIMEO = """
<form method="post" action="primeo">
<div class="card"><h2>Primeo-Rechnungen für den Abgleich</h2>{{ t_rech|safe }}
<h2 style="margin-top:16px">Rücklieferung laut Primeo-Rechnung</h2>{{ t_rueck|safe }}
<p class="muted">Primeo rechnet in ganzen kWh. Die Übersicht vergleicht diese Werte mit den Lastgängen (Toleranz 1 kWh).</p></div>
<div class="card"><h2>Einspeisevergütung vor dem vZEV-Start</h2>{{ t_vor|safe }}
<p class="muted">Monat als JJJJ-MM. Ersetzt die berechnete Rücklieferung in der Wertschöpfung.</p></div>
<div class="card"><h2>Übrige Erträge und Gutschriften</h2>{{ t_ue|safe }}
<p class="muted">Monat als JJJJ-MM, Betrag in CHF (Gutschrift positiv). Fliesst in die Wertschöpfung.</p></div>
<p><button class="primary">Speichern</button></p></form>
{% if abg is not none %}<div class="card"><h2>Abgleich</h2><div class="scroll"><table>
<tr><th>Rechnung</th><th class="l">Position</th><th>Primeo kWh</th><th>Berechnet kWh</th><th>Differenz</th><th></th></tr>
{% for r in abg.itertuples() %}<tr><td>{{ r.rechnung }}</td><td class="l">{{ r.position }}</td><td>{{ r.primeo_kwh }}</td><td>{{ r.berechnet_kwh|f2 }}</td><td>{{ r.diff|f2 }}</td>
<td><span class="pill {{ 'ok' if r.ok else 'warn' }}">{{ 'stimmt' if r.ok else 'prüfen' }}</span></td></tr>{% endfor %}</table></div></div>{% endif %}"""

F_RECH = [dict(key="nr", label="Rechnungsnr.", typ="text"), dict(key="von", label="Von", typ="datum"), dict(key="bis", label="Bis", typ="datum"),
          dict(key="netz_ht", label="Netzbezug HT kWh", typ="ganz", breite=90), dict(key="netz_nt", label="Netzbezug NT kWh", typ="ganz", breite=90)]
F_RUECK = [dict(key="nr", label="Rechnungsnr.", typ="text"), dict(key="von", label="Von", typ="datum"), dict(key="bis", label="Bis", typ="datum"),
           dict(key="kwh", label="kWh", typ="ganz", breite=90)]
F_VOR = [dict(key="monat", label="Monat", typ="text", breite=90, hinweis="2026-01"), dict(key="chf", label="CHF", typ="zahl", breite=90)]
F_UE = F_VOR + [dict(key="text", label="Beschreibung", typ="text", breite=360)]


def _monat(x, i):
    try:
        return str(pd.Period(str(x), "M"))
    except Exception:
        raise ValueError(f"Zeile {i}: «{x}» ist kein Monat (JJJJ-MM)")


def primeo():
    cfg = S.config()
    if request.method == "POST":
        try:
            rech, rueck = lesen("r", F_RECH), lesen("rl", F_RUECK)
            for i, r in enumerate(rech, 1):
                if not (r["nr"] and r["von"] and r["bis"]):
                    raise ValueError(f"Rechnung Zeile {i}: Nummer, Von und Bis sind nötig")
            nrn = {r["nr"] for r in rech}
            for i, r in enumerate(rueck, 1):
                if r["nr"] not in nrn:
                    raise ValueError(f"Rücklieferung Zeile {i}: Rechnung «{r['nr']}» gibt es oben nicht")
                if not (r["von"] and r["bis"] and r["kwh"] is not None):
                    raise ValueError(f"Rücklieferung Zeile {i}: Von, Bis und kWh sind nötig")
            neu_rech = [dict(nr=r["nr"], von=r["von"], bis=r["bis"], netz_ht=r["netz_ht"] or 0, netz_nt=r["netz_nt"] or 0,
                             ruecklieferung=[[x["von"], x["bis"], x["kwh"]] for x in rueck if x["nr"] == r["nr"]]) for r in rech]
            vor = [dict(monat=_monat(r["monat"], i), chf=r["chf"]) for i, r in enumerate(lesen("v", F_VOR), 1)]
            ue = [dict(monat=_monat(r["monat"], i), chf=r["chf"], text=r["text"]) for i, r in enumerate(lesen("u", F_UE), 1)]
            man = cfg.get("manuell") or {}
            bis = gesperrt_bis()
            if bis:
                gesperrt = lambda liste: sorted(json.dumps(_norm(e), sort_keys=True) for e in liste if pd.Period(str(e["monat"]), "M").end_time.date() <= bis)
                if gesperrt(vor) != gesperrt(man.get("ruecklieferung_vor_start") or []) or gesperrt(ue) != gesperrt(man.get("uebrige_ertraege") or []):
                    return redirect("primeo?c=warn&msg=Nicht gespeichert: Ein Eintrag betrifft einen abgeschlossenen Monat. Öffne ihn zuerst unter «Abschluss» wieder.")
            abschnitt_speichern("manuell", {**man, "ruecklieferung_vor_start": vor, "uebrige_ertraege": ue}, "Manuelle Erträge – bearbeitet in der App")
            abschnitt_speichern("primeo_rechnungen", neu_rech, "Primeo-Rechnungen für den Abgleich – bearbeitet in der App")
            S.log.info("Primeo-Angaben gespeichert (%d Rechnungen)", len(neu_rech))
            return redirect("primeo?msg=Gespeichert")
        except ValueError as e:
            return redirect(f"primeo?c=warn&msg=Nicht gespeichert: {e}")
    rech = cfg.get("primeo_rechnungen") or []
    rows_r = [dict(nr=str(r["nr"]), von=_d(r["von"]), bis=_d(r["bis"]), netz_ht=r.get("netz_ht"), netz_nt=r.get("netz_nt")) for r in rech]
    rows_rl = [dict(nr=str(r["nr"]), von=_d(v), bis=_d(b), kwh=k) for r in rech for v, b, k in r.get("ruecklieferung") or []]
    man = cfg.get("manuell") or {}
    b = S.berechnung() if any(S.PRIMEO.iterdir()) else {}
    abg = core.abgleich(b["res"], b["cfg"]) if b.get("ok") else None
    return S.page("Primeo", render_template_string(PRIMEO, abg=abg, t_rech=editor("r", F_RECH, rows_r), t_rueck=editor("rl", F_RUECK, rows_rl),
                                                   t_vor=editor("v", F_VOR, [dict(e, monat=str(e["monat"])) for e in man.get("ruecklieferung_vor_start") or []]),
                                                   t_ue=editor("u", F_UE, [dict(e, monat=str(e["monat"])) for e in man.get("uebrige_ertraege") or []])))


# --- Abschluss ----------------------------------------------------------------
ABSCHLUSS = """
{% if not b.ok %}<div class="msg warn">Noch keine vollständige Berechnung: {{ b.fehler }}</div>{% endif %}
{% if abw %}<div class="msg warn"><b>Abgeschlossene Monate haben sich verändert:</b> {% for m, t in abw %}{{ m }}: {{ t }}{{ '; ' if not loop.last }}{% endfor %}.
Prüfe, ob eine Datei ersetzt wurde. Ist die Änderung gewollt, übernimm die neuen Werte mit Begründung – das steht dann unter «Korrekturen».</div>{% endif %}
<div class="card"><h2>Monate</h2><div class="scroll"><table>
<tr><th class="l">Monat</th><th class="l">Status</th><th>1. OG CHF</th><th>Allgemein CHF</th><th>Ladestation kWh</th><th>Wertschöpfung CHF</th><th class="l">Aktion</th></tr>
{% for m in monate %}<tr><td class="l">{{ m.label }}</td>
<td class="l" style="white-space:normal;max-width:220px">{% if m.zu %}<span class="pill ok" title="abgeschlossen per {{ m.datum.strftime('%d.%m.%Y') }}">abgeschlossen</span>{% if m.abw %} <span class="pill warn">verändert</span>{% endif %}
{% elif not m.w.vollstaendig %}<span class="pill warn">Daten unvollständig</span>{% else %}<span class="muted">offen</span>{% endif %}
{% if m.w.rueck_offen %} <span class="pill warn">Rücklieferungstarif offen</span>{% endif %}</td>
<td>{{ m.w['1OG'].chf|f2 }}</td><td>{{ m.w['AllgC'].chf|f2 }}</td><td>{{ (m.w['EV'].solar + m.w['EV'].ht + m.w['EV'].nt)|f2 }}</td><td>{{ m.w.wertschoepfung|f2 }}</td>
<td class="l akt">{% if m.zu %}<form class="inline datum" method="post" action="abschluss"><input type="hidden" name="monat" value="{{ m.key }}"><input type="hidden" name="aktion" value="datum">
<input type="date" name="datum" value="{{ m.datum.isoformat() }}" min="{{ m.min }}" max="{{ heute }}" aria-label="Abschlussdatum {{ m.label }}"> <button title="Abschlussdatum ändern">Ändern</button></form>
{% if m.abw %}<form class="inline" method="post" action="abschluss" onsubmit="var g=prompt('{{ m.label }} hat sich verändert ({{ m.abw_text }}). Neue Werte festhalten – Begründung:');if(!g)return false;this.grund.value=g">
<input type="hidden" name="monat" value="{{ m.key }}"><input type="hidden" name="aktion" value="uebernehmen"><input type="hidden" name="grund"><button class="primary">Neue Werte übernehmen</button></form>{% endif %}
{% if m.letzter %}<form class="inline" method="post" action="abschluss" onsubmit="var g=prompt('Begründung für das Wiederöffnen von {{ m.label }}:');if(!g)return false;this.grund.value=g">
<input type="hidden" name="monat" value="{{ m.key }}"><input type="hidden" name="aktion" value="oeffnen"><input type="hidden" name="grund"><button class="danger">Wieder öffnen</button></form>{% endif %}
{% elif m.naechster and m.w.vollstaendig %}<form class="inline datum" method="post" action="abschluss"><input type="hidden" name="monat" value="{{ m.key }}"><input type="hidden" name="aktion" value="schliessen">
<input type="date" name="datum" value="{{ heute }}" min="{{ m.min }}" max="{{ heute }}" aria-label="Abschlussdatum {{ m.label }}"> <button class="primary">Abschliessen</button></form>{% endif %}</td></tr>
{% endfor %}</table></div>
<p class="muted">Beim Abschluss werden die Werte des Monats festgehalten. Danach lehnt die App Änderungen an Tarifen, Mietern und Erträgen ab, die diesen Monat betreffen,
und Rechnungen eines Quartals mit abgeschlossenen Monaten lassen sich nur mit Begründung neu erstellen. Monate werden der Reihe nach abgeschlossen und rückwärts wieder geöffnet.
Das Abschlussdatum lässt sich nachträglich ändern, etwa wenn ein Monat schon früher ausserhalb der App abgeschlossen wurde; jede Änderung steht unten in der Liste.</p></div>
<style>form.datum input[type=date]{padding:6px 8px}form.datum button,td.akt button{min-height:34px;padding:0 10px}
td.akt{white-space:normal;min-width:300px}td.akt form{display:inline-flex;gap:6px;flex-wrap:wrap;align-items:center;margin:2px 0}</style>
<div class="card"><h2>Korrekturen und Abschlüsse</h2><div class="scroll"><table><tr><th class="l">Erfasst</th><th class="l">Monat</th><th class="l">Was</th><th class="l">Begründung</th></tr>
{% for k in korrekturen %}<tr><td class="l">{{ k.zeit }}</td><td class="l">{{ k.monat }}</td><td class="l">{{ k.art }}</td><td class="l" style="white-space:normal">{{ k.grund }}</td></tr>
{% else %}<tr><td class="l" colspan="4">Noch keine Einträge.</td></tr>{% endfor %}</table></div></div>"""


def abschluss():
    b = S.berechnung() if any(S.PRIMEO.iterdir()) else {"ok": False, "fehler": "keine Dateien importiert"}
    mw = monatswerte(b)
    a = abschluss_laden()
    if request.method == "POST":
        m, aktion = request.form["monat"], request.form["aktion"]
        zu = sorted(a["monate"])
        jetzt = datetime.now().strftime("%Y-%m-%d %H:%M")
        if aktion in ("schliessen", "datum"):
            try:
                datum = date.fromisoformat(request.form.get("datum") or date.today().isoformat())
            except ValueError:
                return redirect("abschluss?c=warn&msg=Ungültiges Abschlussdatum.")
            if datum <= pd.Period(m, "M").end_time.date() or datum > date.today():
                return redirect(f"abschluss?c=warn&msg=Das Abschlussdatum für {m} muss nach dem Monatsende und spätestens heute sein.")
        if aktion == "schliessen":
            offen = [k for k in sorted(mw) if k not in a["monate"]]
            if not offen or offen[0] != m or not mw[m]["vollstaendig"]:
                return redirect("abschluss?c=warn&msg=Monate werden der Reihe nach abgeschlossen, und nur mit vollständigen Daten.")
            a["monate"][m] = {"zeit": jetzt, "datum": datum.isoformat(), "werte": mw[m]}
            a["korrekturen"].append({"zeit": jetzt, "monat": m, "art": f"abgeschlossen per {datum:%d.%m.%Y}", "grund": ""})
            abschluss_speichern(a)
            S.log.info("Monat %s abgeschlossen per %s", m, datum)
            return redirect(f"abschluss?msg={m} abgeschlossen per {datum:%d.%m.%Y}")
        if aktion == "datum":
            if m not in a["monate"]:
                return redirect("abschluss?c=warn&msg=Der Monat ist nicht abgeschlossen.")
            alt = _abschlussdatum(a["monate"][m])
            if alt == datum:
                return redirect("abschluss")
            a["monate"][m]["datum"] = datum.isoformat()
            a["korrekturen"].append({"zeit": jetzt, "monat": m, "art": f"Abschlussdatum geändert: {alt:%d.%m.%Y} → {datum:%d.%m.%Y}", "grund": ""})
            abschluss_speichern(a)
            S.log.info("Abschlussdatum %s geändert: %s -> %s", m, alt, datum)
            return redirect(f"abschluss?msg=Abschlussdatum {m} auf {datum:%d.%m.%Y} geändert")
        grund = (request.form.get("grund") or "").strip()
        if aktion == "uebernehmen":
            abw = dict(abweichungen(b)) if b.get("ok") else {}
            if m not in a["monate"] or m not in abw or m not in mw or not grund:
                return redirect("abschluss?c=warn&msg=Nur veränderte abgeschlossene Monate, und nur mit Begründung.")
            a["monate"][m]["werte"] = mw[m]
            a["korrekturen"].append({"zeit": jetzt, "monat": m, "art": f"neue Werte übernommen ({abw[m]})", "grund": grund})
            abschluss_speichern(a)
            S.log.warning("Abschluss %s: neue Werte übernommen (%s) – %s", m, abw[m], grund)
            return redirect(f"abschluss?msg=Neue Werte für {m} übernommen")
        if not zu or zu[-1] != m or not grund:
            return redirect("abschluss?c=warn&msg=Nur der zuletzt abgeschlossene Monat kann wieder geöffnet werden, und nur mit Begründung.")
        a["monate"].pop(m)
        abschluss_speichern(a)
        korrektur(m, "wieder geöffnet", grund)
        return redirect(f"abschluss?msg={m} wieder geöffnet")
    abw = dict(abweichungen(b)) if b.get("ok") else {}
    zu = sorted(a["monate"])
    offen = [k for k in sorted(mw) if k not in a["monate"]]
    monate = []
    for k in sorted(set(mw) | set(a["monate"]), reverse=True):
        w = mw.get(k) or a["monate"][k]["werte"]
        zu_k = a["monate"].get(k)
        monate.append(dict(key=k, label=pd.Period(k, "M").strftime("%m.%Y"), w=w, zu=zu_k, abw=k in abw, abw_text=abw.get(k, "").replace("'", ""),
                           datum=_abschlussdatum(zu_k) if zu_k else None, min=(pd.Period(k, "M").end_time.date() + timedelta(days=1)).isoformat(),
                           letzter=bool(zu) and zu[-1] == k, naechster=bool(offen) and offen[0] == k))
    return S.page("Abschluss", render_template_string(ABSCHLUSS, b=b, monate=monate, abw=sorted(abw.items()), heute=date.today().isoformat(),
                                                      korrekturen=list(reversed(a["korrekturen"]))))


def _abschlussdatum(e):
    return date.fromisoformat(e.get("datum") or e["zeit"][:10])


def quartal_gesperrt(jahr, q):
    a = abschluss_laden()
    return [m for m in (f"{jahr}-{q * 3 - 2 + i:02d}" for i in range(3)) if m in a["monate"]]


# --- Batterie -----------------------------------------------------------------
BATTERIE = """
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div>Ladestand</div><div>{{ '%.0f %%'|format(soc) if soc is not none else '–' }}</div></div>
 <div class="kpi"><div>Geladen {{ monat }}</div><div>{{ akt.geladen|f2 }} kWh</div></div>
 <div class="kpi"><div>Entladen {{ monat }}</div><div>{{ akt.entladen|f2 }} kWh</div></div>
 <div class="kpi"><div>Wirkungsgrad {{ monat }}</div><div>{{ '%.0f %%'|format(akt.entladen / akt.geladen * 100) if akt.geladen else '–' }}</div></div>
</div>
<div class="card"><h2>Pro Monat</h2><div class="scroll"><table class="wide">
<tr><th>Monat</th><th>Tage mit Daten</th><th>Geladen kWh</th><th>Entladen kWh</th><th>Wirkungsgrad</th><th>PV-Ertrag kWh</th><th>Netzbezug kWh</th><th>Einspeisung kWh</th></tr>
{% for m in monate %}<tr><td>{{ m.monat }}</td><td>{{ m.tage }}</td><td>{{ m.geladen|f2 }}</td><td>{{ m.entladen|f2 }}</td>
<td>{{ '%.0f %%'|format(m.entladen / m.geladen * 100) if m.geladen else '–' }}</td><td>{{ m.pv|f2 }}</td><td>{{ m.bezug|f2 }}</td><td>{{ m.einspeisung|f2 }}</td></tr>
{% else %}<tr><td colspan="8" class="l">Noch keine Daten vom Wechselrichter. Der Datensammler speichert sie alle 15 Minuten.</td></tr>{% endfor %}</table></div>
<p class="muted">Tageswerte des Solis-Wechselrichters (Höchstwert pro Tag), gesammelt vom Datensammler. Für die Abrechnung zählen weiterhin die Primeo-Lastgänge.</p></div>
<p class="muted">Dynamische Strompreise: Seite <a href="tarife">Tarife</a>. Speicher und Bonus: <a href="einstellungen?tab=regeln">Einstellungen → Regeln</a>.</p>"""


def batterie():
    cfg = S.config()
    r = cfg.get("batterie") or {}
    r = {"netzladung_zahlt": "betreiber", "entladung_netzanteil": "offen", "dynamisch_ab": "2027-01-01", **r}
    sol = (cfg.get("homeassistant") or {}).get("solis") or {}
    spalten = {"geladen": sol.get("batterie_geladen_heute"), "entladen": sol.get("batterie_entladen_heute"), "pv": sol.get("pv_heute"),
               "bezug": sol.get("netz_bezug_heute"), "einspeisung": sol.get("netz_einspeisung_heute")}
    with S.collector._db() as c:
        df = pd.read_sql_query("SELECT ts, entity, wert FROM messwerte WHERE entity IN (%s)" % ",".join("?" * len(spalten)), c,
                               params=[v or "" for v in spalten.values()])
        soc_row = c.execute("SELECT wert FROM messwerte WHERE entity=? ORDER BY ts DESC LIMIT 1", (sol.get("batterie_soc") or "",)).fetchone()
    monate = []
    if len(df):
        df["tag"] = pd.to_datetime(df["ts"]).dt.date
        tag = df.groupby(["tag", "entity"])["wert"].max().unstack()
        tag = tag.rename(columns={v: k for k, v in spalten.items() if v})
        tag.index = pd.to_datetime(tag.index)
        for m, g in tag.groupby(tag.index.to_period("M")):
            monate.append(dict(monat=m.strftime("%m.%Y"), tage=len(g), **{k: (g[k].sum() if k in g else None) for k in spalten}))
        monate.reverse()
    akt = monate[0] if monate and monate[0]["monat"] == date.today().strftime("%m.%Y") else dict(geladen=None, entladen=None)
    return S.page("Batterie", render_template_string(BATTERIE, r=r, monate=monate, akt=akt, monat=date.today().strftime("%m.%Y"), p=preis_infos(),
                                                     soc=soc_row[0] if soc_row else None))


def preis_infos():
    import diagramme
    import preise
    pa = S.preisabruf
    e = preise.einstellungen(S.config())
    vorhanden = preise.typen_vorhanden(pa.db)
    typ = e["tarif_typ"] or next((t for t in preise.TYPEN if t in vorhanden), None)
    tage, reihen = [], []
    heute = date.today()
    for d, label, farbe in [(heute, "Heute", diagramme.FARBEN["netz"]), (heute + timedelta(days=1), "Morgen", diagramme.FARBEN["solar"])]:
        rows = preise.tag(pa.db, d, typ) if typ else []
        if not rows:
            continue
        pkt = [(int(s[11:13]) * 60 + int(s[14:16]), v * 100) for s, v in rows]
        w = [v for _, v in pkt]
        stunden = {}
        for m, v in pkt:
            stunden.setdefault(m // 60, []).append(v)
        guenstig = min(stunden, key=lambda h: sum(stunden[h]) / len(stunden[h]))
        tage.append(dict(label=f"{label}, {d:%d.%m.}", mittel=sum(w) / len(w), min=min(w), max=max(w), guenstig=f"{guenstig:02d}:00"))
        reihen.append((f"{label} {d:%d.%m.}", farbe, pkt))
    naechster = S.collector.naechster.strftime("%H:%M") if getattr(S.collector, "naechster", None) else None
    return dict(e=e, status=pa.status, fehler=pa.fehler, letzter=pa.letzter.strftime("%d.%m. %H:%M") if pa.letzter else None,
                naechster=naechster, tage=tage, typ=typ, chart=(diagramme.STIL + diagramme.tagesverlauf(reihen)) if reihen else "")


# --- Einstellungen ------------------------------------------------------------
EINST_TABS = """<div style="display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap">{% for k, v in [('betreiber','Betreiber und Rechnungen'),('zaehler','Zähler'),('regeln','Regeln'),('datei','Datei vzev.yaml')] %}
<a class="btn {{ 'primary' if k == tab }}" href="einstellungen?tab={{ k }}">{{ v }}</a>{% endfor %}</div>"""

BETREIBER = """<form method="post" action="einstellungen?tab=betreiber" class="card"><h2>Betreiber</h2><table class="form">
{% for k, l in felder %}<tr><td class="l">{{ l }}</td><td class="l"><input name="b.{{ k }}" value="{{ b.get(k) or '' }}" style="width:320px"></td></tr>{% endfor %}
<tr><td class="l">vZEV-Start</td><td class="l"><input type="date" name="vzev_start" value="{{ start }}"></td></tr>
<tr><td class="l">Zahlungsfrist (Tage)</td><td class="l"><input name="frist" value="{{ r.zahlungsfrist_tage }}" style="width:80px"></td></tr>
<tr><td class="l">Rechnungsnummer</td><td class="l"><input name="nummer" value="{{ r.nummer }}" style="width:320px"> <span class="muted">Platzhalter {jahr}, {quartal}, {einheit}</span></td></tr></table>
<p><button class="primary">Speichern</button> <span class="muted">Name, Adresse und IBAN erscheinen auf den Rechnungen und im QR-Einzahlungsschein.</span></p></form>"""

ZAEHLER = """<form method="post" action="einstellungen?tab=zaehler"><div class="card"><h2>Primeo-Messpunkte</h2>{{ t_mp|safe }}
<p class="muted">Über die Messpunkt-Nummer erkennt die App beim Import, welche Datei zu welchem Zähler gehört.</p></div>
<div class="card"><h2>Zähler in Home Assistant</h2>{{ t_ha|safe }}
<p class="muted">Energie-Sensoren in kWh (total_increasing). Der Datensammler speichert sie alle 15 Minuten.</p></div>
<div class="card"><h2>PV-Prognose (Solcast)</h2><table class="form"><tr><td class="l">Sensoren</td><td class="l">
<input name="solcast" value="{{ solcast }}" style="width:100%;max-width:520px" placeholder="leer = automatisch finden"></td></tr></table>
<p class="muted">Leer lassen: Die App nimmt alle Sensoren mit Halbstunden-Prognose («detailedForecast»). Sonst Sensoren mit Komma getrennt, z. B. Prognose heute und morgen.</p></div>
<p><button class="primary">Speichern</button></p></form>"""

PREISKARTE = """<div class="card"><h2>Dynamische Strompreise</h2>
<p>{{ p.status }}{% if p.letzter %} · zuletzt {{ p.letzter }}{% endif %}{% if p.naechster %} · nächster Abruf {{ p.naechster }}{% endif %}</p>
{% if p.fehler %}<div class="msg warn">Abruf fehlgeschlagen: {{ p.fehler }}</div>{% endif %}
{% if p.tage %}<div class="grid" style="margin:12px 0">{% for t in p.tage %}<div class="kpi"><div class="t">{{ t.label }}</div>
<div class="v">{{ '%.1f'|format(t.mittel) }} <small>Rp./kWh Ø</small></div><div class="s">{{ '%.1f'|format(t.min) }} – {{ '%.1f'|format(t.max) }} Rp., günstigste Stunde ab {{ t.guenstig }}</div></div>{% endfor %}</div>
{{ p.chart|safe }}<p class="muted">Typ «{{ p.typ }}», ohne kantonale/kommunale Abgaben und MWST.</p>{% endif %}
<form method="post" action="preise_abrufen" data-busy="Strompreise werden abgerufen …" style="margin-top:8px"><button>Jetzt abrufen</button></form>
<details style="margin-top:12px"><summary class="muted">Schnittstelle einstellen</summary>
<form method="post" action="tarife?teil=dynamisch"><table class="form">
<tr><td class="l">Adresse (URL)</td><td class="l"><input name="api_url" value="{{ p.e.api_url }}" style="width:420px" required></td></tr>
<tr><td class="l">Tarifname</td><td class="l"><input name="tarif_name" value="{{ p.e.tarif_name }}" style="width:200px"> <span class="muted">NetzDynamisch, NetzDynamischAVAG, NetzDynamischELAG</span></td></tr>
<tr><td class="l">Tariftyp</td><td class="l"><select name="tarif_typ">{% for k, v in [('', 'alle'), ('integrated', 'integrated – Netz + Energie'), ('electricity', 'electricity – Energie'), ('grid', 'grid – Netz inkl. nationale Abgaben'), ('grid_usage', 'grid_usage – nur Netznutzung')] %}<option value="{{ k }}" {{ 'selected' if k == p.e.tarif_typ }}>{{ v }}</option>{% endfor %}</select></td></tr>
<tr><td class="l">Abrufen ab</td><td class="l"><input type="date" name="abrufen_ab" value="{{ p.e.abrufen_ab }}"></td></tr>
<tr><td class="l">Automatisch abrufen</td><td class="l"><label><input type="checkbox" name="aktiv" value="1" {{ 'checked' if p.e.aktiv }}> stündlich, zwischen 18 und 21 Uhr alle 15 Minuten</label></td></tr>
</table><p><button class="primary">Speichern</button> <span class="muted">Standard laut Primeo-Merkblatt: https://tarife.primeo-energie.ch/api/v1/tariffs</span></p></form></details></div>
"""

BATTERIE_REGELN = """<form method="post" action="einstellungen?tab=batterie" class="card"><h2>Speicher und dynamischer Tarif</h2>
<table class="form">
<tr><td class="l">Gilt ab</td><td class="l"><input type="date" name="speicher_ab" value="{{ sp.speicher_ab }}"></td></tr>
<tr><td class="l">Standby PV-Anlage bis</td><td class="l"><input name="pva_standby_max_kwh" value="{{ sp.pva_standby_max_kwh }}" style="width:80px"> kWh pro 15 Min.
<span class="muted">mehr Netzbezug am Zähler der PV-Anlage = Laden des Speichers aus dem Netz</span></td></tr>
<tr><td class="l">Wirkungsgrad Speicher</td><td class="l"><input name="speicher_wirkungsgrad" value="{{ (sp.speicher_wirkungsgrad * 100)|round(0)|int }}" style="width:80px"> %</td></tr>
<tr><td class="l">Bonus dynamischer Tarif</td><td class="l"><label><input type="checkbox" name="bonus" value="1" {{ 'checked' if dy.bonus }}> Vorteil gegenüber HT/NT gutschreiben</label> ab <input type="date" name="bonus_ab" value="{{ dy.bonus_ab }}"></td></tr>
<tr><td class="l">Konzessionsabgabe</td><td class="l"><input name="konzession_prozent" value="{{ dy.konzession_prozent }}" style="width:80px"> % auf die Netznutzung <span class="muted">(fehlt in den Preisen der Schnittstelle)</span></td></tr>
<tr><td class="l">MWST</td><td class="l"><input name="mwst_prozent" value="{{ dy.mwst_prozent }}" style="width:80px"> %</td></tr>
</table>
<p><button class="primary">Speichern</button></p>
<p class="muted">Laden aus dem Netz bezahlt der Betreiber; nur der Standby bleibt im Allgemeinstrom. Wird dieser Netzstrom später im Haus verbraucht,
steht er auf der Rechnung als «Speicher NT» zum vZEV-Preis und nicht als Solarstrom (zuerst geladen, zuerst verbraucht).
Bonus: pro Viertelstunde Standardtarif HT/NT minus dynamischer Preis (integrated + Konzessionsabgabe auf grid_usage, plus MWST), mal Netzbezug;
pro Monat nie negativ. Grundpreis und Messung sind in beiden Tarifen gleich und zählen nicht.</p></form>"""

REGELN = """<form method="post" action="einstellungen?tab=regeln" class="card"><h2>Regeln der Aufteilung</h2><table class="form">
<tr><td class="l">Netzbezug PV-Anlage (Standby) geht auf</td><td class="l"><select name="pva_standby_auf">{% for k, v in [('Allg','Allgemeinstrom')] %}<option value="{{ k }}" selected>{{ v }}</option>{% endfor %}</select></td></tr>
<tr><td class="l">Allgemeinstrom</td><td class="l"><select name="allgemein_rechnung"><option value="gesamt" selected>Gesamtrechnung für die Nebenkostenabrechnung</option></select></td></tr>
<tr><td class="l">Mieteranteil Allgemeinstrom (nur Wertschöpfung)</td><td class="l"><input name="allgemein_mieteranteil" value="{{ (r.allgemein_mieteranteil * 100)|round(1) }}" style="width:80px"> %</td></tr>
<tr><td class="l">Grundlast Allgemein für Ladestation-Verteilung</td><td class="l"><input name="ladestation_grundlast_kwh" value="{{ r.ladestation_grundlast_kwh }}" style="width:80px"> kWh pro 15 Min.</td></tr></table>
<p><button class="primary">Speichern</button></p>
<p class="muted">Diese Regeln wirken auf alle Monate. Ist ein Monat abgeschlossen, zeigt «Abschluss» danach eine Abweichung an.</p></form>"""

B_FELDER = [("name", "Name"), ("strasse", "Strasse"), ("hausnr", "Hausnummer"), ("plz", "PLZ"), ("ort", "Ort"), ("bank", "Bank"), ("iban", "IBAN")]
F_MP = [dict(key="mp", label="Messpunkt-Nummer", typ="text", breite=330),
        dict(key="z", label="Zähler", typ="auswahl", opts=[("1OG", "Verbrauch 1. OG"), ("2OG", "Verbrauch 2. OG"), ("Allg", "Allgemein (inkl. Ladestation)"),
                                                          ("PVA", "Netzbezug PV-Anlage"), ("Prod", "Produktion PV-Anlage")])]
F_HA = [dict(key="z", label="Zähler", typ="text", breite=120), dict(key="e", label="Entität", typ="text", breite=360)]


def einstellungen_formulare(tab):
    cfg = S.config()
    if request.method == "POST":
        try:
            if tab == "betreiber":
                b = dict(cfg.get("betreiber") or {})
                for k, _ in B_FELDER:
                    b[k] = (request.form.get(f"b.{k}") or "").strip() or None
                if b.get("iban"):
                    b["iban"] = b["iban"].replace(" ", "").upper()
                    if not (b["iban"].startswith(("CH", "LI")) and len(b["iban"]) == 21):
                        raise ValueError("IBAN muss eine Schweizer IBAN mit 21 Zeichen sein")
                r = dict(cfg.get("rechnungen") or {})
                r["zahlungsfrist_tage"] = int(request.form.get("frist") or 30)
                r["nummer"] = request.form.get("nummer") or "{jahr}-Q{quartal}-{einheit}"
                r["nummer"].format(jahr=2026, quartal=1, einheit="1OG")
                start = _d(request.form.get("vzev_start"))
                if start != _d(cfg.get("vzev_start")) and gesperrt_bis():
                    raise ValueError("Der vZEV-Start lässt sich nicht ändern, solange Monate abgeschlossen sind")
                abschnitt_speichern("betreiber", b)
                abschnitt_speichern("vzev_start", start)
                abschnitt_speichern("rechnungen", r)
            elif tab == "zaehler":
                mp = lesen("mp", F_MP)
                if len({r["z"] for r in mp}) != len(mp) or any(not r["mp"] or not r["z"] for r in mp):
                    raise ValueError("Jeder Zähler braucht genau eine Messpunkt-Nummer")
                ha = dict(cfg.get("homeassistant") or {})
                ha["zaehler"] = {r["z"]: r["e"] for r in lesen("ha", F_HA) if r["z"] and r["e"]}
                sc = [x.strip() for x in (request.form.get("solcast") or "").split(",") if x.strip()]
                if sc or ha.get("solcast"):
                    ha["solcast"] = sc
                abschnitt_speichern("messpunkte", {r["mp"]: r["z"] for r in mp})
                abschnitt_speichern("homeassistant", ha)
            elif tab == "batterie":
                f = lambda k: float((request.form.get(k) or "0").replace(",", "."))
                sp = {"speicher_ab": _d(request.form.get("speicher_ab") or "2027-01-01"),
                      "pva_standby_max_kwh": f("pva_standby_max_kwh"), "speicher_wirkungsgrad": round(f("speicher_wirkungsgrad") / 100, 4)}
                if not 0.5 <= sp["speicher_wirkungsgrad"] <= 1 or sp["pva_standby_max_kwh"] < 0:
                    raise ValueError("Wirkungsgrad zwischen 50 und 100 %, Standby nicht negativ")
                dy = {"bonus": bool(request.form.get("bonus")), "bonus_ab": _d(request.form.get("bonus_ab") or "2027-01-01"),
                      "konzession_prozent": f("konzession_prozent"), "mwst_prozent": f("mwst_prozent")}

                def uebernehmen(abschnitt, neu, aktuell, notiz=None):
                    """Nur schreiben, was sich gegenüber dem wirksamen Wert ändert (Standardwerte bleiben unsichtbar)."""
                    alt = dict(cfg.get(abschnitt) or {})
                    geaendert = {k: v for k, v in neu.items() if k in alt or str(v) != str(aktuell[k])}
                    if any(alt.get(k) != v for k, v in geaendert.items()):
                        alt.update(geaendert)
                        abschnitt_speichern(abschnitt, alt, *([notiz] if notiz else []))
                uebernehmen("regeln", sp, core.speicher_regeln(cfg))
                uebernehmen("dynamisch", dy, core.dyn_regeln(cfg), "Dynamische Strompreise – bearbeitet in der App")
                tab = "regeln"
            elif tab == "regeln":
                r = dict(cfg.get("regeln") or {})
                r["allgemein_mieteranteil"] = float(request.form["allgemein_mieteranteil"].replace(",", ".")) / 100
                r["ladestation_grundlast_kwh"] = float(request.form["ladestation_grundlast_kwh"].replace(",", "."))
                if not 0 <= r["allgemein_mieteranteil"] <= 1:
                    raise ValueError("Mieteranteil muss zwischen 0 und 100 % liegen")
                abschnitt_speichern("regeln", r)
            S.log.info("Einstellungen gespeichert (%s)", tab)
            return redirect(f"einstellungen?tab={tab}&msg=Gespeichert")
        except (ValueError, KeyError, IndexError) as e:
            return redirect(f"einstellungen?tab={tab}&c=warn&msg=Nicht gespeichert: {e}")
    kopf = render_template_string(EINST_TABS, tab=tab)
    if tab == "betreiber":
        body = render_template_string(BETREIBER, b=cfg.get("betreiber") or {}, felder=B_FELDER, start=_d(cfg.get("vzev_start")) or "",
                                      r=cfg.get("rechnungen") or {"zahlungsfrist_tage": 30, "nummer": "{jahr}-Q{quartal}-{einheit}"})
    elif tab == "zaehler":
        body = render_template_string(ZAEHLER, t_mp=editor("mp", F_MP, [dict(mp=k, z=v) for k, v in (cfg.get("messpunkte") or {}).items()]),
                                      t_ha=editor("ha", F_HA, [dict(z=k, e=v) for k, v in ((cfg.get("homeassistant") or {}).get("zaehler") or {}).items()]),
                                      solcast=", ".join((cfg.get("homeassistant") or {}).get("solcast") or []))
    else:
        body = render_template_string(REGELN, r=cfg.get("regeln") or {}) + render_template_string(
            BATTERIE_REGELN, sp=core.speicher_regeln(cfg), dy=core.dyn_regeln(cfg))
    return S.page("Einstellungen", kopf + body)


# =============================================================================
def register(app, server):
    global S
    S = server
    app.add_url_rule("/mieter", "mieter", mieter, methods=["GET", "POST"])
    app.add_url_rule("/tarife", "tarife", tarife, methods=["GET", "POST"])
    app.add_url_rule("/primeo", "primeo", primeo, methods=["GET", "POST"])
    app.add_url_rule("/abschluss", "abschluss", abschluss, methods=["GET", "POST"])
    app.add_url_rule("/batterie", "batterie", batterie, methods=["GET", "POST"])
    app.add_url_rule("/preise_abrufen", "preise_abrufen", preise_abrufen, methods=["POST"])


def preise_abrufen():
    S.collector.aktiv = "Strompreise abrufen"
    try:
        n = S.preisabruf.abrufen()
    finally:
        S.collector.aktiv = None
    pa = S.preisabruf
    if pa.fehler:
        return redirect(f"tarife?c=warn&msg=Abruf fehlgeschlagen: {pa.fehler}")
    return redirect(f"tarife?msg={pa.status}")
