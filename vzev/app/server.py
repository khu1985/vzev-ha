"""Web-Oberfläche der vZEV-App (läuft über Home-Assistant-Ingress, daher nur relative Links)."""
import json
import logging
import os
import shutil
import sys
import threading
import time
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
import seiten
import uebersicht
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


def _version():
    for p in (Path(__file__).parent / "addon.yaml", Path(__file__).parent.parent / "config.yaml"):
        try:
            return str(yaml.safe_load(p.read_text(encoding="utf-8"))["version"])
        except Exception:
            continue
    return "?"


VERSION = _version()
NAVIGATION = [
    ("Auswertung", [("./", "Übersicht"), ("verlauf", "Verlauf")]),
    ("Abrechnung", [("import", "Daten importieren"), ("rechnungen", "Rechnungen"), ("abschluss", "Abschluss")]),
    ("Stammdaten", [("mieter", "Mieter"), ("tarife", "Tarife"), ("primeo", "Primeo"), ("einstellungen", "Einstellungen")]),
    ("Anlage", [("batterie", "Batterie"), ("sammler", "Datensammler"), ("protokoll", "Protokoll")]),
]

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


_rechnen = threading.Lock()
RECHNEN = {"aktiv": False, "start": None, "ende": None, "dauer": None, "grund": "", "fehler": None}


def veraltet():
    """True, wenn es Dateien gibt und die gespeicherte Berechnung nicht mehr zu Dateien/Einstellungen passt."""
    try:
        return any(p.is_file() for p in PRIMEO.iterdir()) and _cache.get("key") != files_key()
    except OSError:
        return False


def berechnung(grund="Seitenaufruf"):
    key = files_key()
    if _cache.get("key") == key:
        return _cache
    with _rechnen:  # nur eine Berechnung gleichzeitig; wer wartet, bekommt das fertige Ergebnis
        key = files_key()
        if _cache.get("key") == key:
            return _cache
        t0 = time.time()
        RECHNEN.update(aktiv=True, start=t0, grund=grund)
        try:
            cfg, res, files, lade, ev = core.run(PRIMEO, CFG, DATA / ".cache")
            _cache.update(key=key, ok=True, cfg=cfg, res=res, files=files, ev=ev, fehler=None)
        except BaseException as e:  # SystemExit bei fehlenden Dateien
            _cache.update(key=key, ok=False, fehler=str(e) or traceback.format_exc(limit=1))
            log.warning("Berechnung nicht möglich: %s", _cache["fehler"])
        else:
            if time.time() - t0 > 5:
                log.info("Berechnung neu erstellt in %.0f s", time.time() - t0)
        finally:
            RECHNEN.update(aktiv=False, ende=time.time(), dauer=time.time() - t0, fehler=_cache.get("fehler"))
    return _cache


def im_hintergrund_rechnen(grund="Hintergrund"):
    """Nach Start oder Upload schon rechnen, damit die nächste Seite nicht warten muss."""
    def lauf():
        try:
            if any(p.is_file() for p in PRIMEO.iterdir()):
                liste()  # Dateiinfos für «Daten importieren»
                berechnung(grund)
        except Exception:
            log.exception("Berechnung im Hintergrund fehlgeschlagen")
    threading.Thread(target=lauf, daemon=True).start()


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
            d = core._als_datum(r[0])
            if not pd.isna(d):
                von = von or d
                bis = d
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
main{max-width:1180px;margin:0 auto;padding:24px;min-width:0;width:100%}
.side{background:#fff}.top{display:flex;align-items:center;gap:10px}.brand{font-size:16px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}.ver{color:var(--muted);font-size:12px;font-weight:500}
nav a{color:#3F4A44;text-decoration:none;padding:8px 10px;border-radius:8px;font-weight:500;white-space:nowrap}nav a.on{background:var(--soft);color:var(--ink)}nav a:hover{background:var(--bg)}
nav .gl{display:none;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
#menu{display:none;min-height:40px;margin-left:auto;flex-shrink:0}
@media (min-width:1200px){.app{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:100vh}
 .side{position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid var(--line);padding:20px 12px}
 .top{padding:0 10px;flex-wrap:wrap;gap:4px 8px}.brand{white-space:normal}nav .gl{display:block;margin:18px 10px 4px}nav a{display:block}}
@media (max-width:1199px){.side{position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);padding:10px 16px 0}
 nav{display:flex;overflow-x:auto;scrollbar-width:none;padding:6px 0 8px}nav::-webkit-scrollbar{display:none}
 nav .grp{display:flex;flex-shrink:0}nav .grp+.grp{border-left:1px solid var(--line);margin-left:6px;padding-left:6px}}
@media (max-width:759px){ #menu{display:inline-flex}.ver{flex-shrink:0}.brand{flex:1 1 0}nav{display:none}
 .side{padding:10px 16px}.side.offen nav{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;padding:8px 0 12px;max-height:calc(100vh - 70px);overflow-y:auto}
 .side.offen nav .grp{display:block;border:0;margin:0;padding:0}.side.offen nav .gl{display:block;margin:10px 10px 2px}.side.offen nav a{display:block}
 main{padding:16px}h1{font-size:22px}.card{padding:16px}}
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
.kpi .v{font-size:24px;font-weight:600;margin-top:4px}.kpi .v small{font-size:13px;font-weight:500;color:var(--muted)}.kpi div.s{font-size:12px;font-weight:400;color:var(--muted);margin-top:4px}
form.inline{display:inline}
/* Tabellen auf dem Handy: Zeilen als Karten mit Beschriftung, breite Monatstabellen scrollen mit fester erster Spalte */
@media (max-width:759px){
 .scroll>table:not(.wide),table.form{min-width:0}
 table:not(.wide) tr:has(>th){display:none}
 table:not(.wide),table:not(.wide) tbody,table:not(.wide) tr,table:not(.wide) td{display:block;width:100%}
 table:not(.wide) tr{border-bottom:1px solid var(--line);padding:8px 0}
 table:not(.wide) td{border:0;padding:5px 0;text-align:right;white-space:normal;min-height:0;overflow-wrap:anywhere}
 table:not(.wide) td[data-label]::before{content:attr(data-label);float:left;color:var(--muted);font-size:13px;font-weight:500;text-align:left;margin-right:12px;max-width:45%}
 table:not(.wide) td::after{content:"";display:block;clear:both}
 table:not(.wide) td.l{text-align:right}
 table:not(.wide) td:empty{display:none}
 table:not(.wide) td>*:not(.pill){max-width:100%}
 table.edit tr{border:1px solid var(--line);border-radius:12px;padding:8px 12px;margin-bottom:8px}
 table.edit td{display:grid;grid-template-columns:110px 1fr;text-align:left;align-items:center}
 table.edit td::before{float:none!important;margin:0}table.edit td::after{display:none}
 table.edit td::before{max-width:none!important}
 table.edit input,table.edit select,table.form input,table.form select{width:100%!important;min-width:0}
 table.form tr{padding:8px 0}table.form td{display:block!important;text-align:left;padding:2px 0}
 table.form td:first-child{color:var(--muted);font-size:13px}
 table.wide th:first-child,table.wide td:first-child{position:sticky;left:0;background:#fff;z-index:1}
 td.akt{min-width:0!important}
 table.edit td label{display:inline-flex;align-items:center;gap:6px;justify-self:start}
 .chart .ax{font-size:19px!important}
 form.datum,td.akt form{justify-content:flex-end}
 main input:not([type=checkbox]):not([type=file]),main select,main textarea{max-width:100%}
 main input[name=grund]{width:100%!important}
}
.bg{font-size:12px;color:var(--muted);display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.bg.an{color:var(--warn);background:var(--warnbg);padding:3px 10px;border-radius:999px;font-weight:600}
.spin{width:12px;height:12px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;display:inline-block;animation:dreh .8s linear infinite;flex-shrink:0}
@keyframes dreh{to{transform:rotate(360deg)}}
button[disabled]{opacity:.75;cursor:progress}
@media (max-width:759px){ .bg.an{font-size:11px;padding:2px 8px;order:5;flex-basis:100%;justify-content:center}.bg:not(.an){display:none}.top{flex-wrap:wrap}}
</style></head><body>
<div class="app"><aside class="side" id="side"><div class="top"><span class="brand">☀ vZEV {{ anlage }}</span><span class="ver" title="Version der App">v{{ version }}</span><span id="bg" class="bg" role="status" aria-live="polite"></span>
<button id="menu" type="button" aria-expanded="false" aria-controls="nav" onclick="var s=document.getElementById('side');var o=s.classList.toggle('offen');this.setAttribute('aria-expanded',o);this.textContent=o?'Schliessen':'Menü'">Menü</button></div>
<nav id="nav">{% for gruppe, eintraege in navigation %}<div class="grp"><span class="gl">{{ gruppe }}</span>{% for href, label in eintraege %}
<a href="{{ href }}" class="{{ 'on' if label == title else '' }}"{% if label == title %} aria-current="page"{% endif %}>{{ label }}{% if label == 'Protokoll' and nfehler %} <span class="pill warn">{{ nfehler }}</span>{% endif %}</a>{% endfor %}</div>{% endfor %}</nav></aside>
<script>(function(){var a=document.querySelector('nav a.on');if(a&&innerWidth<1200&&innerWidth>=760)a.scrollIntoView({block:'nearest',inline:'center'})})()</script>
<main><h1>{{ title }}</h1>{% if msg %}<div class="msg {{ msgclass or 'ok' }}">{{ msg }}</div>{% endif %}{{ body|safe }}</main></div><script>
(function(){
 var el=document.getElementById('bg'),warten=document.getElementById('warten');
 function zeit(s){return s<60?Math.round(s)+' s':Math.round(s/60)+' min'}
 function poll(){fetch('status',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.json()}).then(function(s){
  var t=[];if(s.rechnen.aktiv)t.push('Berechnung läuft ('+zeit(s.rechnen.seit)+')');else if(s.rechnen.veraltet)t.push('Berechnung startet');
  if(s.sammler.aktiv)t.push(s.sammler.aktiv);
  if(t.length){el.className='bg an';el.innerHTML='<span class="spin"></span>'+t.join(' · ')}
  else{el.className='bg';el.textContent='● bereit'+(s.rechnen.letzte?' · gerechnet '+s.rechnen.letzte:'');el.title=s.sammler.naechster?'Nächster Abruf Zählerstände '+s.sammler.naechster:''}
  if(warten&&!s.rechnen.aktiv&&!s.rechnen.veraltet){location.reload();return}
  if(warten&&s.rechnen.aktiv){var w=document.getElementById('wartezeit');if(w)w.textContent=zeit(s.rechnen.seit)}
  setTimeout(poll,(t.length||warten)?1500:15000)}).catch(function(){setTimeout(poll,15000)})}
 poll();
 document.addEventListener('submit',function(e){var f=e.target;if(e.defaultPrevented||f.method.toLowerCase()!=='post'||f.id==='up')return;
  var b=e.submitter||f.querySelector('button');if(!b)return;setTimeout(function(){b.disabled=true;b.innerHTML='<span class="spin"></span> '+(f.dataset.busy||'läuft …')},0);
  el.className='bg an';el.innerHTML='<span class="spin"></span>'+(f.dataset.busy||'wird ausgeführt …')});
})();
</script><script>if(innerWidth<760)document.querySelectorAll('.scroll').forEach(function(d){if(d.querySelector('svg.chart'))d.scrollLeft=d.scrollWidth});
document.querySelectorAll('table').forEach(function(t){var h=null;t.querySelectorAll('tr').forEach(function(r){var th=r.querySelectorAll(':scope>th');if(th.length){h=Array.from(th).map(function(x){return x.textContent.trim()});return}
if(!h)return;var i=0;r.querySelectorAll(':scope>td').forEach(function(td){var n=td.colSpan||1;if(n==1&&h[i]&&!td.hasAttribute('data-label'))td.setAttribute('data-label',h[i]);i+=n})})})</script></body></html>"""


def page(title, body, **kw):
    b = config().get("betreiber", {})
    return render_template_string(BASE, title=title, body=body, anlage=f"{b.get('strasse', '')} {b.get('hausnr', '')}".strip(), msg=request.args.get("msg"), msgclass=request.args.get("c"), nfehler=fehler_seit_start(), version=VERSION, navigation=NAVIGATION, **kw)


# --- Import -------------------------------------------------------------------
IMPORT = """
{% if status %}<div class="msg {{ 'ok' if status.ok else 'warn' }}">{% if status.ok %}Berechnung aus den Lastgängen: {{ status.von }} bis {{ status.bis }}.
{% else %}<b>Berechnung nicht möglich:</b> {{ status.fehler }}{% endif %}</div>{% endif %}
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
    status = None
    if any(p.is_file() for p in PRIMEO.iterdir()):
        b = berechnung()
        status = {"ok": True, "von": b["res"].index.min().strftime("%d.%m.%Y"), "bis": b["res"].index.max().strftime("%d.%m.%Y")} if b.get("ok") \
            else {"ok": False, "fehler": b.get("fehler")}
    return page("Daten importieren", render_template_string(IMPORT, files=liste(), rollen=ROLLEN, status=status))


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
    im_hintergrund_rechnen("neue Datei")
    if request.headers.get("X-Requested-With") == "fetch":
        return {"ok": not fehler, "msg": msg}
    return redirect("import?" + ("c=warn&" if fehler else "") + "msg=" + msg)


@app.post("/ersetzen")
def ersetzen():
    alt = PRIMEO / secure_filename(request.form["alt"])
    if alt.exists():
        shutil.move(str(alt), PRIMEO / "_entfernt" / f"{datetime.now():%Y%m%d%H%M%S}_{alt.name}")
    neu, _ = speichern(request.files["datei"])
    im_hintergrund_rechnen("Datei ersetzt")
    return redirect(f"import?msg={alt.name} ersetzt durch {neu['name']}")


@app.post("/entfernen")
def entfernen():
    p = PRIMEO / secure_filename(request.form["name"])
    if p.exists():
        shutil.move(str(p), PRIMEO / "_entfernt" / f"{datetime.now():%Y%m%d%H%M%S}_{p.name}")
    im_hintergrund_rechnen("Datei entfernt")
    return redirect(f"import?msg={p.name} entfernt")


# --- Rechnungen ---------------------------------------------------------------
RECH = """
<div class="card"><h2>Quartalsrechnungen erstellen</h2>
<form method="post" action="rechnungen" data-busy="Rechnungen werden erstellt …">Jahr <input name="jahr" type="number" value="{{ jahr }}" style="width:90px">
Quartal <select name="quartal">{% for q in [1,2,3,4] %}<option {{ 'selected' if q == quartal }}>{{ q }}</option>{% endfor %}</select>
Rechnungsdatum <input name="datum" type="date" value="{{ heute }}">
{% if korr %}<br><br>Begründung der Korrektur <input name="grund" style="width:420px" required placeholder="z. B. Lastgang Primeo korrigiert">{% endif %}
<button class="primary">{{ 'Korrektur erstellen' if korr else 'Erstellen' }}</button></form>
<p class="muted">Pro Mietverhältnis eine Rechnung für die Wohnung (mit QR-Einzahlungsschein) und eine Gesamtrechnung Allgemeinstrom für die Nebenkostenabrechnung. Ein erneutes Erstellen überschreibt die Dateien dieses Quartals.</p></div>
<div class="card"><h2>Erstellte Rechnungen</h2><div class="scroll"><table><tr><th class="l">Quartal</th><th class="l">Datei</th><th>Erstellt</th><th></th></tr>
{% for q, p, t in pdfs %}<tr><td class="l">{{ q }}</td><td class="l">{{ p }}</td><td>{{ t }}</td><td><a class="btn" href="datei?pfad={{ q }}/{{ p }}" target="_blank">Öffnen</a></td></tr>
{% else %}<tr><td class="l" colspan="4">Noch keine Rechnungen.</td></tr>{% endfor %}</table></div></div>"""


@app.route("/rechnungen", methods=["GET", "POST"])
def rechnungen():
    if request.method == "POST":
        j, q = int(request.form["jahr"]), int(request.form["quartal"])
        ziel = RECHNUNGEN / f"{j}-Q{q}"
        zu = seiten.quartal_gesperrt(j, q)
        if zu and ziel.exists() and any(ziel.glob("*.pdf")):
            grund = (request.form.get("grund") or "").strip()
            if not grund:
                return redirect(f"rechnungen?c=warn&msg=Q{q} {j} enthält abgeschlossene Monate ({', '.join(zu)}) und hat schon Rechnungen. Für eine Korrektur eine Begründung angeben.&korr={j}-{q}")
            alt = RECHNUNGEN / "_alt" / f"{datetime.now():%Y%m%d%H%M%S}_{j}-Q{q}"
            alt.parent.mkdir(exist_ok=True)
            shutil.move(str(ziel), alt)
            seiten.korrektur(f"{j}-Q{q}", "Rechnungen neu erstellt (alte Fassung unter rechnungen/_alt)", grund)
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
    jahr, quartal = t.year, max(1, (t.month - 1) // 3)
    korr = request.args.get("korr")
    if korr:
        jahr, quartal = (int(x) for x in korr.split("-"))
    pdfs = [p for p in pdfs if p[0] != "_alt"]
    return page("Rechnungen", render_template_string(RECH, pdfs=pdfs, jahr=jahr, quartal=quartal, heute=t.isoformat(), korr=korr))


@app.route("/datei")
def datei():
    p = (RECHNUNGEN / request.args.get("pfad", "")).resolve()
    if RECHNUNGEN.resolve() not in p.parents or not p.is_file():
        abort(404)
    return send_file(p, mimetype="application/pdf")


# --- Datensammler -------------------------------------------------------------
SAMMLER = """
<div class="card"><h2>Zählerstände aus Home Assistant</h2>
<p>{{ s.anzahl }} Werte gespeichert{% if s.erster %}, von {{ s.erster.replace('T',' ') }} bis {{ s.letzter.replace('T',' ') }}{% endif %}. Abruf alle 15 Minuten{% if naechster %}, nächster um {{ naechster }}{% endif %}.</p>
{% if s.fehler %}<div class="msg warn">{{ s.fehler }}</div>{% endif %}
<form method="post" action="sammler" data-busy="Zählerstände und evcc werden abgerufen …"><button>Jetzt abrufen</button></form>
<div class="scroll" style="margin-top:12px"><table><tr><th class="l">Zweck</th><th class="l">Entität</th><th>Letzter Wert</th><th>Gespeichert um</th><th>Werte</th><th class="l">Status</th></tr>
{% for z in s.zeilen %}<tr><td class="l">{{ z.zweck }}</td>
<td class="l">{{ z.name or z.entity }}{% if z.name %}<br><span class="muted">{{ z.entity }}</span>{% endif %}</td>
<td>{% if z.wert is not none %}<b>{{ '{:,.3f}'.format(z.wert).replace(',', "'") }}</b> {{ z.einheit }}{% else %}–{% endif %}</td>
<td>{{ z.zeit.replace('T',' ')[8:10] ~ '.' ~ z.zeit[5:7] ~ '. ' ~ z.zeit[11:16] if z.zeit else '–' }}</td><td>{{ z.anzahl }}</td>
<td class="l">{% if z.zustand is none %}<span class="pill warn">noch nicht abgefragt</span>{% elif z.ok %}<span class="pill ok">liefert Werte</span>{% else %}<span class="pill warn">{{ z.zustand }}</span>{% endif %}</td></tr>
{% endfor %}</table></div>
<p class="muted">Letzter Wert = Zählerstand beim letzten Abruf. «unavailable» heisst: Home Assistant hat den Sensor gerade nicht erreicht.</p></div>
<div class="card"><h2>Ladevorgänge aus evcc</h2><p>{{ s.evcc_status }} · {{ s.evcc_sessions }} Ladevorgänge gespeichert. Abruf stündlich{% if evcc_naechster %}, nächster um {{ evcc_naechster }}{% endif %}.</p>
{% if monate %}<h2 style="margin-top:16px">Pro Monat</h2><div class="scroll"><table class="wide">
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
    return page("Datensammler", render_template_string(SAMMLER, s=collector.status(), monate=monate, ladungen=ladungen, monat=monat,
                                                           naechster=collector.naechster.strftime("%H:%M") if collector.naechster else None,
                                                           evcc_naechster=collector.evcc_naechster.strftime("%H:%M") if collector.evcc_naechster else None))


# --- Einstellungen ------------------------------------------------------------
EINST = """
<div class="card"><h2>Konfiguration (vzev.yaml)</h2>
<form method="post" action="einstellungen?tab=datei"><textarea name="text" rows="40">{{ text }}</textarea>
<p><button class="primary">Speichern</button> <span class="muted">Wird vor dem Speichern geprüft; die vorherige Version bleibt als vzev.yaml.bak erhalten.</span></p></form></div>"""


@app.route("/einstellungen", methods=["GET", "POST"])
def einstellungen():
    tab = request.args.get("tab", "betreiber")
    if tab != "datei":
        return seiten.einstellungen_formulare(tab)
    if request.method == "POST":
        text = request.form["text"].replace("\r\n", "\n")
        try:
            data = yaml.safe_load(text)
            for k in ("betreiber", "messpunkte", "tarife", "mietverhaeltnisse", "regeln"):
                if k not in data:
                    raise ValueError(f"Abschnitt «{k}» fehlt")
        except Exception as e:
            return redirect(f"einstellungen?tab=datei&c=warn&msg=Nicht gespeichert: {e}")
        shutil.copy(CFG, CFG.with_suffix(".yaml.bak"))
        CFG.write_text(text, encoding="utf-8")
        log.info("vzev.yaml direkt bearbeitet")
        return redirect("einstellungen?tab=datei&msg=Gespeichert")
    return page("Einstellungen", render_template_string(seiten.EINST_TABS, tab="datei") + render_template_string(EINST, text=CFG.read_text(encoding="utf-8")))


# --- Status und Warteseite ------------------------------------------------------
BRAUCHT_BERECHNUNG = {"index", "verlauf", "abschluss", "primeo", "sammler", "import_page"}


@app.get("/status")
def status():
    jetzt = time.time()
    hm = lambda t: datetime.fromtimestamp(t).strftime("%H:%M") if t else None
    return {
        "rechnen": {"aktiv": RECHNEN["aktiv"], "seit": (jetzt - RECHNEN["start"]) if RECHNEN["aktiv"] else 0,
                    "grund": RECHNEN["grund"], "letzte": hm(RECHNEN["ende"]), "dauer": RECHNEN["dauer"],
                    "fehler": RECHNEN["fehler"], "veraltet": veraltet()},
        "sammler": {"aktiv": collector.aktiv, "naechster": collector.naechster.strftime("%H:%M") if collector.naechster else None,
                    "evcc_naechster": collector.evcc_naechster.strftime("%H:%M") if collector.evcc_naechster else None},
    }


WARTEN = """<div class="card" id="warten" style="text-align:center;padding:40px 20px">
<div class="spin" style="width:28px;height:28px;border-width:3px;color:var(--amber)"></div>
<h2 style="margin-top:16px">Berechnung läuft</h2>
<p class="muted">{{ grund }} – die Primeo-Lastgänge werden neu eingelesen und gerechnet (<span id="wartezeit">0 s</span>).<br>
Die Seite lädt automatisch, sobald alles fertig ist.</p></div>"""


@app.before_request
def auf_berechnung_warten():
    """Seiten mit Berechnung blockieren nicht: kurz warten, sonst Warteseite mit Fortschritt zeigen."""
    if request.method != "GET" or request.endpoint not in BRAUCHT_BERECHNUNG or not veraltet():
        return None
    if not _rechnen.locked():
        im_hintergrund_rechnen("Dateien oder Einstellungen geändert")
    ende = time.time() + 1.5
    while time.time() < ende:
        time.sleep(0.1)
        if not veraltet() and not _rechnen.locked():
            return None
    return page("Bitte warten", render_template_string(WARTEN, grund=RECHNEN.get("grund") or "Neu rechnen"))


seiten.register(app, sys.modules[__name__])
uebersicht.register(app, sys.modules[__name__])

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
    log.info("App gestartet (Version %s). Daten in %s, %d Dateien im Import", VERSION, DATA, sum(1 for p in PRIMEO.iterdir() if p.is_file()))
    im_hintergrund_rechnen("App-Start")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8099)), threaded=True)
