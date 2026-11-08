"""Web-Oberfläche der vZEV-App (läuft über Home-Assistant-Ingress, daher nur relative Links)."""
import json
import logging
import os
import shutil
from logging.handlers import RotatingFileHandler
import traceback
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml
from flask import Flask, abort, redirect, render_template_string, request, send_file
from werkzeug.utils import secure_filename

import core
import invoices
from collector import Collector

DATA = Path(os.environ.get("VZEV_DIR", Path(__file__).parent / "data"))
PRIMEO = DATA / "primeo"
RECHNUNGEN = DATA / "rechnungen"
CFG = DATA / "vzev.yaml"
for d in (PRIMEO, RECHNUNGEN, PRIMEO / "_entfernt"):
    d.mkdir(parents=True, exist_ok=True)
if not CFG.exists():
    shutil.copy(Path(__file__).parent / "default_config.yaml", CFG)

# --- Protokoll ----------------------------------------------------------------
LOGFILE = DATA / "vzev.log"
START = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
log = logging.getLogger("vzev")


def _logging_einrichten():
    if getattr(log, "_eingerichtet", False):
        return
    fh = RotatingFileHandler(LOGFILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s", "%Y-%m-%d %H:%M:%S"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for h in (fh, sh):
        log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    wz = logging.getLogger("werkzeug")  # Zugriffe nur bei Problemen ins Protokoll
    wz.addHandler(fh)
    fh.addFilter(lambda r: r.name != "werkzeug" or r.levelno >= logging.WARNING)
    log._eingerichtet = True


_logging_einrichten()


def protokoll(n=500):
    zeilen = []
    for p in (Path(str(LOGFILE) + ".1"), LOGFILE):
        if p.exists():
            zeilen += p.read_text(encoding="utf-8", errors="replace").splitlines()
    eintraege, cur = [], None
    for z in zeilen:
        teile = z.split("\t", 2)
        if len(teile) == 3 and len(teile[0]) == 19 and teile[0][4] == "-":
            cur = {"zeit": teile[0], "stufe": teile[1], "text": teile[2]}
            eintraege.append(cur)
        elif cur is not None:  # Fortsetzung, z. B. Fehlerdetails
            cur["text"] += "\n" + z
    return eintraege[-n:][::-1]


def fehler_seit_start():
    return sum(1 for e in protokoll(300) if e["stufe"] in ("ERROR", "CRITICAL") and e["zeit"] >= START)


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def config():
    return core.load_config(CFG)


collector = Collector(str(DATA / "messwerte.sqlite"), config)

# --- Hilfen -------------------------------------------------------------------
_cache = {}


def files_key():
    fs = sorted(p for p in PRIMEO.iterdir() if p.is_file())
    return tuple((p.name, p.stat().st_mtime) for p in fs) + ((CFG.name, CFG.stat().st_mtime),)


def berechnung():
    key = files_key()
    if _cache.get("key") != key:
        try:
            cfg, res, files, lade, ev = core.run(PRIMEO, CFG)
            _cache.update(key=key, ok=True, cfg=cfg, res=res, files=files, ev=ev, fehler=None)
        except BaseException as e:  # SystemExit bei fehlenden Dateien
            _cache.update(key=key, ok=False, fehler=str(e) or traceback.format_exc(limit=1))
            log.warning("Berechnung nicht möglich: %s", _cache["fehler"])
    return _cache


INFO_DATEI = DATA / ".dateiinfo.json"
try:
    _info_cache = json.loads(INFO_DATEI.read_text(encoding="utf-8"))
except Exception:
    _info_cache = {}


def datei_info(p, cfg):
    """Infos zu einer importierten Datei; zwischengespeichert, damit die Import-Seite auch nach einem Neustart sofort lädt."""
    st = p.stat()
    key = [st.st_mtime, st.st_size]
    hit = _info_cache.get(p.name)
    if hit and hit[0] == key:
        info = dict(hit[1])
    else:
        info = _datei_info(p)
        _info_cache[p.name] = [key, info]
        for alt in [n for n in _info_cache if not (PRIMEO / n).is_file()]:
            _info_cache.pop(alt)
        try:
            INFO_DATEI.write_text(json.dumps(_info_cache), encoding="utf-8")
        except OSError:
            pass
    if info["art"] == "Lastgang":
        info["rolle"] = (cfg.get("messpunkte") or {}).get(info["messpunkt"]) or "unbekannt"
        info["ok"] = info["rolle"] != "unbekannt"
    return info


def _lastgang_zeitraum(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        von = bis = None
        for r in wb["Lastgang"].iter_rows(min_row=9, max_col=1, values_only=True):
            if isinstance(r[0], datetime):
                von = von or r[0]
                bis = r[0]
        return (von.date().isoformat() if von else None), (bis.date().isoformat() if bis else None)
    finally:
        wb.close()


def _datei_info(p):
    leer = dict(name=p.name, art="?", messpunkt="", rolle="unbekannt", lieferstelle="", von=None, bis=None, ok=False)
    try:
        if p.suffix.lower() == ".xlsx":
            mp, lst = core.read_header(p)
            von, bis = _lastgang_zeitraum(p)
            return dict(leer, art="Lastgang", messpunkt=mp, lieferstelle=lst, von=von, bis=bis)
        if p.suffix.lower() == ".csv":
            t = pd.read_csv(p, sep=";", dtype=str)
            if "Zaehlerstand Differenz [kWh]" in t.columns:
                n = len(t.dropna(subset=["Start"])) if "Start" in t.columns else len(t)
                return dict(leer, art="Wallbox", rolle="Ladestation", lieferstelle=f"{n} Ladevorgänge", ok=True)
            return dict(leer, art="CSV")
    except Exception as e:
        log.warning("Datei %s nicht lesbar: %s", p.name, e)
        return dict(leer, rolle="nicht lesbar", lieferstelle=str(e)[:80])
    return leer


ROLLEN = {"1OG": "Verbrauch 1. OG", "2OG": "Verbrauch 2. OG", "Allg": "Allgemein (inkl. Ladestation)",
          "PVA": "Netzbezug PV-Anlage", "Prod": "Produktion PV-Anlage", "Ladestation": "Ladevorgänge Wallbox"}


def f2(x):
    return "–" if x is None or pd.isna(x) else f"{x:,.2f}".replace(",", "'")


app.jinja_env.filters["f2"] = f2
app.jinja_env.filters["d"] = lambda t: "" if t is None else pd.Timestamp(t).strftime("%d.%m.%Y")

# --- Layout -------------------------------------------------------------------
BASE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>vZEV · {{ title }}</title><style>
:root{--ink:#16201C;--muted:#5B6660;--line:#E2E5E1;--bg:#F6F7F5;--amber:#E8A21B;--soft:#FDF3DF;--ok:#23603A;--okbg:#E3F1E8;--warn:#8A4307;--warnbg:#FCEBD9;--blue:#3B5B8C}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);font-size:14px}
header{background:#fff;border-bottom:1px solid var(--line);padding:12px 24px;display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center}
header b{font-size:16px;margin-right:12px}nav a{color:#3F4A44;text-decoration:none;padding:10px 12px;border-radius:8px;font-weight:500;display:inline-block}
nav a.on{background:var(--soft);color:var(--ink)}main{max-width:1180px;margin:0 auto;padding:24px}
h1{font-size:26px;margin:4px 0 16px}h2{font-size:16px;margin:0 0 12px}.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:20px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}th{font-size:12px;color:var(--muted);text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #EEF0EC;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}th:first-child,td:first-child,.l{text-align:left}
.sum td{font-weight:700;background:var(--bg)}.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}
.ok{background:var(--okbg);color:var(--ok)}.warn{background:var(--warnbg);color:var(--warn)}.muted{color:var(--muted);font-size:12px}
button,.btn{min-height:40px;padding:0 16px;border:1px solid #D3D8D2;border-radius:8px;background:#fff;font:inherit;font-weight:600;cursor:pointer;color:var(--ink);text-decoration:none;display:inline-flex;align-items:center}
.primary{background:var(--ink);color:#fff;border-color:var(--ink)}.danger{color:var(--warn);border-color:#E8C9B0}
input,select,textarea{font:inherit;padding:8px 10px;border:1px solid #D3D8D2;border-radius:8px}textarea{width:100%;font-family:ui-monospace,Menlo,monospace;font-size:12px}
.msg{padding:12px 16px;border-radius:10px;margin-bottom:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}.kpi div:first-child{color:var(--muted);font-size:13px}.kpi div:last-child{font-size:22px;font-weight:600;margin-top:4px}
form.inline{display:inline}</style></head><body>
<header><b>☀ vZEV {{ anlage }}</b><nav>
{% for href, label in [('./','Übersicht'),('import','Daten importieren'),('rechnungen','Rechnungen'),('sammler','Datensammler'),('einstellungen','Einstellungen'),('protokoll','Protokoll')] %}
<a href="{{ href }}" class="{{ 'on' if label == title else '' }}">{{ label }}{% if label == 'Protokoll' and nfehler %} <span class="pill warn">{{ nfehler }}</span>{% endif %}</a>{% endfor %}</nav></header>
<main><h1>{{ title }}</h1>{% if msg %}<div class="msg {{ msgclass or 'ok' }}">{{ msg }}</div>{% endif %}{{ body|safe }}</main></body></html>"""


def page(title, body, **kw):
    b = config().get("betreiber", {})
    return render_template_string(BASE, title=title, body=body, anlage=f"{b.get('strasse', '')} {b.get('hausnr', '')}".strip(), msg=request.args.get("msg"), msgclass=request.args.get("c"), nfehler=fehler_seit_start(), **kw)


# --- Übersicht ----------------------------------------------------------------
UEBERSICHT = """
{% if not b.ok %}<div class="msg warn">Noch keine vollständige Berechnung: {{ b.fehler }}. <a href="import">Dateien importieren</a></div>
{% else %}
<div class="grid" style="margin-bottom:20px">
 <div class="kpi"><div>Daten bis</div><div>{{ b.res.index.max()|d }}</div></div>
 <div class="kpi"><div>Ladestation verteilt</div><div>{{ 'stimmt' if b.ev < 0.01 else 'Abweichung %.2f kWh'|format(b.ev) }}</div></div>
 <div class="kpi"><div>Abgleich Primeo</div><div>{{ 'alles stimmt' if abg.ok.all() else 'Abweichung prüfen' }}</div></div>
 <div class="kpi"><div>Wertschöpfung gesamt</div><div>{{ w.total_chf.sum()|f2 }} CHF</div></div>
</div>
<div class="card"><h2>Pro Zähler und Monat</h2><div class="scroll"><table>
<tr><th>Monat</th>{% for z in zl %}<th>{{ z[1] }} Solar</th><th>Netz HT/NT</th><th>CHF*</th>{% endfor %}</tr>
{% for m, row in tab %}<tr><td>{{ m }}</td>{% for c in row %}<td>{{ c[0]|f2 }}</td><td>{{ c[1]|f2 }} / {{ c[2]|f2 }}</td><td>{{ c[3]|f2 }}</td>{% endfor %}</tr>{% endfor %}
</table></div><p class="muted">kWh. * Solar- plus Netzkosten ohne Grundpreis; Allgemein ohne Ladestation, inkl. Standby PV-Anlage.</p></div>
<div class="card"><h2>Abgleich mit Primeo-Rechnungen</h2><div class="scroll"><table>
<tr><th>Rechnung</th><th class="l">Position</th><th>Primeo kWh</th><th>Berechnet kWh</th><th>Differenz</th><th></th></tr>
{% for r in abg.itertuples() %}<tr><td>{{ r.rechnung }}</td><td class="l">{{ r.position }}</td><td>{{ r.primeo_kwh }}</td><td>{{ r.berechnet_kwh|f2 }}</td><td>{{ r.diff|f2 }}</td>
<td><span class="pill {{ 'ok' if r.ok else 'warn' }}">{{ 'stimmt' if r.ok else 'prüfen' }}</span></td></tr>{% endfor %}</table></div></div>
<div class="card"><h2>Wertschöpfung Betreiber</h2><div class="scroll"><table>
<tr><th>Monat</th><th>Rücklieferung</th><th>Verkauf Mieter</th><th>Eigenverbrauch</th><th>Übrige</th><th>Total CHF</th></tr>
{% for m, r in w.iterrows() %}<tr><td>{{ m.strftime('%m.%Y') }}</td><td>{{ r.export_chf|f2 }}</td><td>{{ r.mieter_chf|f2 }}</td><td>{{ r.eigen_chf|f2 }}</td><td>{{ r.uebrige_chf|f2 }}</td><td><b>{{ r.total_chf|f2 }}</b></td></tr>{% endfor %}
<tr class="sum"><td>Summe</td><td>{{ w.export_chf.sum()|f2 }}</td><td>{{ w.mieter_chf.sum()|f2 }}</td><td>{{ w.eigen_chf.sum()|f2 }}</td><td>{{ w.uebrige_chf.sum()|f2 }}</td><td>{{ w.total_chf.sum()|f2 }}</td></tr>
</table></div><p class="muted">Rücklieferung leer = Tarif noch nicht bekannt. Allgemeinstrom zu 50 % als verkauft gerechnet; Leerstand zählt als Eigenverbrauch.</p></div>
{% endif %}"""


@app.route("/")
def index():
    b = berechnung()
    ctx = dict(b=b)
    if b.get("ok"):
        res, cfg = b["res"], b["cfg"]
        zl = [("1OG", "1. OG"), ("2OG", "2. OG"), ("AllgC", "Allgemein"), ("EV", "Ladestation")]
        sums = {k: core.zaehler_summen(res, k) for k, _ in zl}
        months = sums["1OG"].index
        tab = [(m.strftime("%m.%Y"), [(sums[k].loc[m, "solar"], sums[k].loc[m, "ht"], sums[k].loc[m, "nt"],
                                       sums[k].loc[m, "solar_chf"] + sums[k].loc[m, "netz_chf"]) for k, _ in zl]) for m in months]
        ctx.update(zl=zl, tab=tab, abg=core.abgleich(res, cfg), w=core.wertschoepfung(res, cfg))
    return page("Übersicht", render_template_string(UEBERSICHT, **ctx))


# --- Import -------------------------------------------------------------------
IMPORT = """
<div class="card"><h2>Dateien hochladen</h2>
<form id="up" method="post" action="hochladen" enctype="multipart/form-data">
<input id="upfiles" type="file" name="dateien" multiple accept=".xlsx,.csv" required> <button class="primary" id="upbtn">Hochladen</button></form>
<ul id="upstatus" class="muted" style="padding-left:18px"></ul>
<script>
document.getElementById('up').addEventListener('submit', async function (ev) {
  ev.preventDefault();
  const files = Array.from(document.getElementById('upfiles').files);
  const list = document.getElementById('upstatus'); const btn = document.getElementById('upbtn');
  btn.disabled = true; list.innerHTML = '';
  let allOk = true;
  for (const f of files) {
    const li = document.createElement('li'); li.textContent = f.name + ' … wird hochgeladen'; list.appendChild(li);
    const fd = new FormData(); fd.append('dateien', f, f.name);
    try {
      const r = await fetch('hochladen', {method: 'POST', body: fd, headers: {'X-Requested-With': 'fetch'}, credentials: 'same-origin'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json(); li.textContent = j.msg; allOk = allOk && j.ok;
    } catch (e) { li.textContent = f.name + ': ' + e.message; allOk = false; }
  }
  btn.disabled = false;
  if (allOk) location.href = 'import?msg=' + encodeURIComponent(files.length + ' Datei(en) hochgeladen');
});
</script>
<p class="muted">Primeo-Lastgänge (.xlsx) und Wallbox-Export (.csv). Die Zuordnung erfolgt über die Messpunkt-Nummer. Eine neue Datei für denselben Messpunkt ersetzt die alte automatisch.</p></div>
<div class="card"><h2>Importierte Dateien</h2><div class="scroll"><table>
<tr><th class="l">Datei</th><th class="l">Zugeordnet als</th><th class="l">Messpunkt / Inhalt</th><th>Von</th><th>Bis</th><th class="l">Aktionen</th></tr>
{% for f in files %}<tr><td class="l">{{ f.name }}</td>
<td class="l"><span class="pill {{ 'ok' if f.ok else 'warn' }}">{{ rollen.get(f.rolle, f.rolle) }}</span></td>
<td class="l">{{ f.messpunkt[-6:] and '…' ~ f.messpunkt[-6:] }} <span class="muted">{{ f.lieferstelle }}</span></td>
<td>{{ f.von|d }}</td><td>{{ f.bis|d }}</td>
<td class="l"><form class="inline" method="post" action="ersetzen" enctype="multipart/form-data">
<input type="hidden" name="alt" value="{{ f.name }}"><label class="btn" style="padding:0 12px">Ersetzen<input type="file" name="datei" accept=".xlsx,.csv" style="display:none" onchange="this.form.submit()"></label></form>
<form class="inline" method="post" action="entfernen" onsubmit="return confirm('{{ f.name }} entfernen?')"><input type="hidden" name="name" value="{{ f.name }}"><button class="danger">Entfernen</button></form></td></tr>
{% else %}<tr><td class="l" colspan="6">Noch keine Dateien.</td></tr>{% endfor %}</table></div>
<p class="muted">Entfernte Dateien werden nicht gelöscht, sondern in den Unterordner «_entfernt» verschoben.</p></div>"""


def liste():
    cfg = config()
    return [datei_info(p, cfg) for p in sorted(PRIMEO.iterdir()) if p.is_file()]


def speichern(fs):
    name = secure_filename(fs.filename) or f"upload_{datetime.now():%Y%m%d%H%M%S}"
    ziel = PRIMEO / name
    fs.save(ziel)
    cfg = config()
    neu = datei_info(ziel, cfg)
    ersetzt = []
    if neu["ok"]:
        for p in PRIMEO.iterdir():
            if p.is_file() and p != ziel and datei_info(p, cfg)["rolle"] == neu["rolle"]:
                shutil.move(str(p), PRIMEO / "_entfernt" / f"{datetime.now():%Y%m%d%H%M%S}_{p.name}")
                ersetzt.append(p.name)
    return neu, ersetzt


@app.route("/import")
def import_page():
    return page("Daten importieren", render_template_string(IMPORT, files=liste(), rollen=ROLLEN))


@app.post("/hochladen")
def hochladen():
    teile, fehler = [], False
    dateien = [fs for fs in request.files.getlist("dateien") if fs and fs.filename]
    if not dateien:
        log.warning("Upload ohne Dateien (Content-Length %s)", request.content_length)
        teile.append("Keine Datei empfangen")
        fehler = True
    for fs in dateien:
        try:
            neu, ersetzt = speichern(fs)
            teile.append(f"{neu['name']} → {ROLLEN.get(neu['rolle'], neu['rolle'])}" + (f" (ersetzt {', '.join(ersetzt)})" if ersetzt else ""))
            fehler |= not neu["ok"]
            log.info("Hochgeladen: %s → %s", neu["name"], ROLLEN.get(neu["rolle"], neu["rolle"]))
        except Exception as e:
            log.exception("Upload %s fehlgeschlagen", fs.filename)
            teile.append(f"{fs.filename}: Fehler {e}")
            fehler = True
    msg = "; ".join(teile)
    if request.headers.get("X-Requested-With") == "fetch":
        return {"ok": not fehler, "msg": msg}
    return redirect("import?" + ("c=warn&" if fehler else "") + "msg=" + msg)


@app.post("/ersetzen")
def ersetzen():
    alt = PRIMEO / secure_filename(request.form["alt"])
    if alt.exists():
        shutil.move(str(alt), PRIMEO / "_entfernt" / f"{datetime.now():%Y%m%d%H%M%S}_{alt.name}")
    neu, _ = speichern(request.files["datei"])
    return redirect(f"import?msg={alt.name} ersetzt durch {neu['name']}")


@app.post("/entfernen")
def entfernen():
    p = PRIMEO / secure_filename(request.form["name"])
    if p.exists():
        shutil.move(str(p), PRIMEO / "_entfernt" / f"{datetime.now():%Y%m%d%H%M%S}_{p.name}")
    return redirect(f"import?msg={p.name} entfernt")


# --- Rechnungen ---------------------------------------------------------------
RECH = """
<div class="card"><h2>Quartalsrechnungen erstellen</h2>
<form method="post" action="rechnungen">Jahr <input name="jahr" type="number" value="{{ jahr }}" style="width:90px">
Quartal <select name="quartal">{% for q in [1,2,3,4] %}<option {{ 'selected' if q == quartal }}>{{ q }}</option>{% endfor %}</select>
Rechnungsdatum <input name="datum" type="date" value="{{ heute }}"> <button class="primary">Erstellen</button></form>
<p class="muted">Pro Mietverhältnis eine Rechnung für die Wohnung (mit QR-Einzahlungsschein) und eine Gesamtrechnung Allgemeinstrom für die Nebenkostenabrechnung. Ein erneutes Erstellen überschreibt die Dateien dieses Quartals.</p></div>
<div class="card"><h2>Erstellte Rechnungen</h2><table><tr><th class="l">Quartal</th><th class="l">Datei</th><th>Erstellt</th><th></th></tr>
{% for q, p, t in pdfs %}<tr><td class="l">{{ q }}</td><td class="l">{{ p }}</td><td>{{ t }}</td><td><a class="btn" href="datei?pfad={{ q }}/{{ p }}" target="_blank">Öffnen</a></td></tr>
{% else %}<tr><td class="l" colspan="4">Noch keine Rechnungen.</td></tr>{% endfor %}</table></div>"""


@app.route("/rechnungen", methods=["GET", "POST"])
def rechnungen():
    if request.method == "POST":
        j, q = int(request.form["jahr"]), int(request.form["quartal"])
        try:
            made = invoices.main(PRIMEO, j, q, RECHNUNGEN / f"{j}-Q{q}", request.form.get("datum") or None, CFG)
            txt = ", ".join(f"{n} (CHF {t:.2f})" for n, t, _ in made)
            log.info("Rechnungen %s Q%s erstellt: %s", j, q, txt)
            return redirect(f"rechnungen?msg=Erstellt: {txt}")
        except BaseException as e:
            log.exception("Rechnungen %s Q%s fehlgeschlagen", j, q)
            return redirect(f"rechnungen?c=warn&msg=Fehler: {e}")
    pdfs = sorted(((p.parent.name, p.name, datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M"))
                   for p in RECHNUNGEN.glob("*/*.pdf")), reverse=True)
    t = date.today()
    return page("Rechnungen", render_template_string(RECH, pdfs=pdfs, jahr=t.year, quartal=max(1, (t.month - 1) // 3), heute=t.isoformat()))


@app.route("/datei")
def datei():
    p = (RECHNUNGEN / request.args.get("pfad", "")).resolve()
    if RECHNUNGEN.resolve() not in p.parents or not p.is_file():
        abort(404)
    return send_file(p, mimetype="application/pdf")


# --- Datensammler -------------------------------------------------------------
SAMMLER = """
<div class="card"><h2>Zählerstände aus Home Assistant</h2>
<p>{{ s.anzahl }} Werte gespeichert{% if s.erster %}, von {{ s.erster.replace('T',' ') }} bis {{ s.letzter.replace('T',' ') }}{% endif %}. Abruf alle 15 Minuten.</p>
{% if s.fehler %}<div class="msg warn">{{ s.fehler }}</div>{% endif %}
<form method="post" action="sammler"><button>Jetzt abrufen</button></form>
<div class="scroll" style="margin-top:12px"><table><tr><th class="l">Zweck</th><th class="l">Entität</th><th>Letzter Wert</th><th>Gespeichert um</th><th>Werte</th><th class="l">Status</th></tr>
{% for z in s.zeilen %}<tr><td class="l">{{ z.zweck }}</td>
<td class="l">{{ z.name or z.entity }}{% if z.name %}<br><span class="muted">{{ z.entity }}</span>{% endif %}</td>
<td>{% if z.wert is not none %}<b>{{ '{:,.3f}'.format(z.wert).replace(',', "'") }}</b> {{ z.einheit }}{% else %}–{% endif %}</td>
<td>{{ z.zeit.replace('T',' ')[8:10] ~ '.' ~ z.zeit[5:7] ~ '. ' ~ z.zeit[11:16] if z.zeit else '–' }}</td><td>{{ z.anzahl }}</td>
<td class="l">{% if z.zustand is none %}<span class="pill warn">noch nicht abgefragt</span>{% elif z.ok %}<span class="pill ok">liefert Werte</span>{% else %}<span class="pill warn">{{ z.zustand }}</span>{% endif %}</td></tr>
{% endfor %}</table></div>
<p class="muted">Letzter Wert = Zählerstand beim letzten Abruf. «unavailable» heisst: Home Assistant hat den Sensor gerade nicht erreicht.</p></div>
<div class="card"><h2>Ladevorgänge aus evcc</h2><p>{{ s.evcc_status }} · {{ s.evcc_sessions }} Ladevorgänge gespeichert. Abruf stündlich.</p>
{% if monate %}<h2 style="margin-top:16px">Pro Monat</h2><div class="scroll"><table>
<tr><th>Monat</th><th>Ladevorgänge</th><th>kWh evcc</th><th>davon Solar kWh</th><th>Solaranteil</th><th>kWh Ladestation laut Abrechnung</th><th>Kosten evcc CHF</th></tr>
{% for m in monate %}<tr><td>{{ m.monat }}</td><td>{{ m.n }}</td><td>{{ m.kwh|f2 }}</td><td>{{ m.solar_kwh|f2 }}</td><td>{{ '%.0f %%'|format(m.solar_anteil) if m.solar_anteil is not none else '–' }}</td>
<td>{{ m.abrechnung|f2 }}</td><td>{{ m.preis|f2 }}</td></tr>{% endfor %}</table></div>
<p class="muted">«Laut Abrechnung» = Ladestation aus den Primeo-Lastgängen und dem Wallbox-Export, wie sie in den Rechnungen verwendet wird. Solaranteil und Kosten berechnet evcc selbst.</p>{% endif %}
{% if ladungen %}<h2 style="margin-top:16px">Einzelne Ladevorgänge</h2>
<form method="get" action="sammler" style="margin-bottom:8px">Monat <select name="monat" onchange="this.form.submit()"><option value="">alle</option>
{% for m in monate %}<option {{ 'selected' if m.monat == monat }}>{{ m.monat }}</option>{% endfor %}</select></form>
<div class="scroll"><table>
<tr><th class="l">Start</th><th>Ende</th><th>Dauer</th><th class="l">Ladepunkt</th><th class="l">Fahrzeug</th><th>kWh</th><th>Solar</th><th>CHF</th><th>Rp./kWh</th><th>km-Stand</th></tr>
{% for l in ladungen %}<tr><td class="l">{{ l.start.strftime('%d.%m.%Y %H:%M') }}</td><td>{{ l.ende.strftime('%d.%m. %H:%M') if l.ende else 'läuft' }}</td>
<td>{{ '%d:%02d h'|format(l.dauer_min // 60, l.dauer_min % 60) if l.dauer_min is not none else '–' }}</td>
<td class="l">{{ l.ladepunkt }}</td><td class="l">{{ l.fahrzeug }}</td><td>{{ l.kwh|f2 }}</td>
<td>{{ '%.0f %%'|format(l.solar) if l.solar is not none else '–' }}</td><td>{{ l.preis|f2 }}</td>
<td>{{ '%.1f'|format(l.preis_kwh * 100) if l.preis_kwh else '–' }}</td><td>{{ '{:,.0f}'.format(l.km).replace(',', "'") if l.km else '–' }}</td></tr>{% endfor %}
<tr class="sum"><td class="l">Summe</td><td></td><td></td><td></td><td></td><td>{{ ladungen|sum(attribute='kwh_s')|f2 }}</td><td></td><td>{{ ladungen|sum(attribute='preis_s')|f2 }}</td><td></td><td></td></tr>
</table></div>{% endif %}</div>"""


@app.route("/sammler", methods=["GET", "POST"])
def sammler():
    if request.method == "POST":
        try:
            n = collector.read_now()
            collector.fetch_evcc()
            return redirect(f"sammler?msg={n} Werte gespeichert")
        except Exception as e:
            return redirect(f"sammler?c=warn&msg=Fehler: {e}")
    alle = collector.sessions()
    for l in alle:
        l["monat"] = l["start"].strftime("%m.%Y")
        l["kwh_s"], l["preis_s"] = l["kwh"] or 0, l["preis"] or 0
    abr = {}
    b = berechnung() if any(PRIMEO.iterdir()) else {}
    if b.get("ok"):
        ev = core.zaehler_summen(b["res"], "EV")
        abr = {m.strftime("%m.%Y"): r.solar + r.ht + r.nt for m, r in ev.iterrows()}
    monate = []
    for m in sorted({l["monat"] for l in alle} | set(abr), key=lambda x: (x[3:], x[:2]), reverse=True):
        ls = [l for l in alle if l["monat"] == m]
        kwh = sum(l["kwh_s"] for l in ls)
        sk = sum(l["kwh_s"] * l["solar"] / 100 for l in ls if l["solar"] is not None)
        mit = sum(l["kwh_s"] for l in ls if l["solar"] is not None)
        monate.append(dict(monat=m, n=len(ls), kwh=kwh if ls else None, solar_kwh=sk if mit else None,
                           solar_anteil=(sk / mit * 100) if mit else None, abrechnung=abr.get(m),
                           preis=sum(l["preis_s"] for l in ls) if any(l["preis"] is not None for l in ls) else None))
    monat = request.args.get("monat", "")
    ladungen = [l for l in alle if not monat or l["monat"] == monat][:300]
    return page("Datensammler", render_template_string(SAMMLER, s=collector.status(), monate=monate, ladungen=ladungen, monat=monat))


# --- Einstellungen ------------------------------------------------------------
EINST = """
<div class="card"><h2>Konfiguration (vzev.yaml)</h2>
<form method="post" action="einstellungen"><textarea name="text" rows="40">{{ text }}</textarea>
<p><button class="primary">Speichern</button> <span class="muted">Wird vor dem Speichern geprüft; die vorherige Version bleibt als vzev.yaml.bak erhalten.</span></p></form></div>"""


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    if request.method == "POST":
        text = request.form["text"].replace("\r\n", "\n")
        try:
            data = yaml.safe_load(text)
            for k in ("betreiber", "messpunkte", "tarife", "mietverhaeltnisse", "regeln"):
                if k not in data:
                    raise ValueError(f"Abschnitt «{k}» fehlt")
        except Exception as e:
            return redirect(f"einstellungen?c=warn&msg=Nicht gespeichert: {e}")
        shutil.copy(CFG, CFG.with_suffix(".yaml.bak"))
        CFG.write_text(text, encoding="utf-8")
        return redirect("einstellungen?msg=Gespeichert")
    return page("Einstellungen", render_template_string(EINST, text=CFG.read_text(encoding="utf-8")))


# --- Protokoll ----------------------------------------------------------------
PROT = """
<div class="card"><form method="get" action="protokoll" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<select name="stufe" onchange="this.form.submit()">{% for k, v in [('', 'Alle Einträge'), ('WARNING', 'Warnungen und Fehler'), ('ERROR', 'Nur Fehler')] %}
<option value="{{ k }}" {{ 'selected' if k == stufe }}>{{ v }}</option>{% endfor %}</select>
<a class="btn" href="protokoll?stufe={{ stufe }}">Aktualisieren</a>
<span class="muted">App gestartet {{ start }} · {{ eintraege|length }} Einträge</span></form></div>
<div class="card"><div class="scroll"><table>
<tr><th class="l">Zeit</th><th class="l">Art</th><th class="l">Meldung</th></tr>
{% for e in eintraege %}<tr><td class="l" style="vertical-align:top">{{ e.zeit[8:10] }}.{{ e.zeit[5:7] }}. {{ e.zeit[11:] }}</td>
<td class="l" style="vertical-align:top"><span class="pill {{ 'warn' if e.stufe in ('WARNING','ERROR','CRITICAL') else 'ok' }}">{{ stufen.get(e.stufe, e.stufe) }}</span></td>
<td class="l" style="white-space:pre-wrap;word-break:break-word">{{ e.text }}</td></tr>
{% else %}<tr><td class="l" colspan="3">Keine Einträge.</td></tr>{% endfor %}</table></div>
<p class="muted">Das Protokoll liegt auch als Datei «vzev.log» im App-Konfigurationsordner.</p></div>"""


@app.route("/protokoll")
def protokoll_seite():
    stufe = request.args.get("stufe", "")
    rang = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 2}
    eintraege = [e for e in protokoll() if rang.get(e["stufe"], 0) >= rang.get(stufe, 0)]
    return page("Protokoll", render_template_string(PROT, eintraege=eintraege, stufe=stufe, start=START[8:10] + "." + START[5:7] + ". " + START[11:16],
                                                   stufen={"INFO": "Info", "WARNING": "Warnung", "ERROR": "Fehler", "CRITICAL": "Fehler"}))


@app.errorhandler(Exception)
def unerwartet(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    log.exception("Fehler auf Seite %s", request.path)
    return page("Fehler", f'<div class="msg warn">Da ist etwas schiefgelaufen: {e}. Details stehen im <a href="protokoll">Protokoll</a>.</div>'), 500


if __name__ == "__main__":
    if os.environ.get("SUPERVISOR_TOKEN") or config().get("homeassistant", {}).get("token"):
        collector.start()
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("App gestartet. Daten in %s, %d Dateien im Import", DATA, sum(1 for p in PRIMEO.iterdir() if p.is_file()))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8099)), threaded=True)
