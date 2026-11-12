"""Aufgaben-Assistent: führt durch die regelmässigen Arbeiten (monatlich, pro Quartal, jährlich).

Den Stand jedes Schritts erkennt die App selbst aus den Daten (Lastgänge, Ladevorgänge, Primeo-Rechnungen, Kontrollen,
Abschluss, Rechnungsregister, Jahres-PDF, Tarife). Nur «Rechnungen versendet» wird von Hand bestätigt
(gespeichert in aufgaben.json).
"""
import json
from datetime import date, datetime

import pandas as pd
from flask import redirect, render_template_string, request

import core

S = None
MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _datei():
    return S.DATA / "aufgaben.json"


def laden():
    try:
        return json.loads(_datei().read_text(encoding="utf-8"))
    except Exception:
        return {"versendet": {}}


def speichern(st):
    tmp = _datei().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_datei())


def _titel(p):
    return f"{MONATE[p.month]} {p.year}"


def offene_monate(b, abschluss, heute=None):
    """Vergangene Monate ab Beginn der Daten, die noch nicht abgeschlossen sind (der laufende Monat zählt nicht)."""
    heute = heute or date.today()
    if not b.get("ok"):
        return []
    start = b["res"].index.min().to_period("M")
    jetzt = pd.Period(heute, "M")
    out, p = [], start
    while p < jetzt:
        if str(p) not in abschluss["monate"]:
            out.append(p)
        p += 1
    return out


def schritte_monat(d, mon, p, abschluss, zst, st):
    """Schritte für einen Monat (und, am Quartals-/Jahresende, die zugehörigen Arbeiten)."""
    import uebersicht
    b, cfg = d["b"], d["cfg"]
    res = b["res"] if b.get("ok") else None
    ende = p.end_time.floor("15min")
    sch = []

    # 1. Lastgänge
    bis = res.index.max() if res is not None else None
    ok = bis is not None and bis >= ende
    sch.append(dict(gruppe="Monat", titel="Primeo-Lastgänge importieren", ok=ok, link="import", knopf="Daten importieren",
                    text=(f"Lastgänge liegen bis {bis:%d.%m.%Y %H:%M} vor." if bis is not None else "Noch keine Lastgänge.")
                    + ("" if ok else f" Im Primeo-Kundenportal die fünf Lastgänge bis Ende {_titel(p)} herunterladen und hochladen.")))
    # 2. Ladestation
    lade = b.get("lade")
    letzte = None
    if lade is not None and len(lade):
        spalte = next((c for c in ("ende", "Ende", "end", "start", "Start") if c in lade), None)
        try:
            letzte = pd.to_datetime(lade[spalte]).max() if spalte else None
        except Exception:
            letzte = None
    datei = (b.get("files") or {}).get("Lade")
    # vollständig, wenn der letzte Ladevorgang höchstens eine Woche vor Monatsende liegt – oder die Datei nach Monatsende
    # exportiert wurde und der letzte Ladevorgang im selben Monat liegt (in der letzten Woche wurde einfach nicht geladen)
    ok = letzte is not None and (letzte >= ende - pd.Timedelta(days=7) or
                                 (datei is not None and _datei_neuer(datei, ende) and letzte >= p.start_time))
    sch.append(dict(gruppe="Monat", titel="Ladevorgänge der Wallbox importieren", ok=bool(ok), link="import", knopf="Daten importieren",
                    text=(f"Letzter Ladevorgang: {letzte:%d.%m.%Y}. " if letzte is not None else "")
                    + ("Der Export deckt den Monat ab." if ok else "Den Export der Ladevorgänge (go-e) mit dem ganzen Monat hochladen.")))
    # 3. Primeo-Rechnung
    rech = [r for r in cfg.get("primeo_rechnungen") or [] if pd.Timestamp(r["von"]) <= p.end_time and pd.Timestamp(r["bis"]) >= p.start_time]
    ok = any(pd.Timestamp(r["bis"]) >= p.end_time.normalize() for r in rech)
    sch.append(dict(gruppe="Monat", titel="Primeo-Rechnung erfassen", ok=ok, link="primeo", knopf="Primeo öffnen",
                    text=(f"Erfasst: Rechnung {', '.join(str(r['nr']) for r in rech)}." if rech else "Noch keine Primeo-Rechnung für diesen Monat.")
                    + ("" if ok else " Netzbezug HT/NT und Rücklieferung aus der Primeo-Rechnung eintragen – sie dient dem Abgleich."), optional=True))
    # 4. Kontrollen
    if p in mon.index:
        kontr, _, _, _ = uebersicht.kontrollen_fuer(d, mon, p)
        kontr = [k for k in kontr if k[1] not in ("Abgeschlossen und unverändert", "Rechnungen bezahlt")]
        falsch = [k for k in kontr if k[0] is False]
        sch.append(dict(gruppe="Monat", titel="Kontrollen prüfen", ok=not falsch, link=f"uebersicht?m={p}#monat", knopf="Kontrollen ansehen",
                        text=("Alle Kontrollen stimmen." if not falsch else "Zu prüfen:"), liste=[f"{t}: {x}" for _, t, x in falsch]))
    # 5. Abschluss
    ok = str(p) in abschluss["monate"]
    sch.append(dict(gruppe="Monat", titel=f"{_titel(p)} abschliessen", ok=ok, link="abschluss", knopf="Abschluss öffnen",
                    text="Abgeschlossen." if ok else "Hält die Werte fest; danach sind Tarife und Mieter für diesen Monat gesperrt. "
                    "Monate werden der Reihe nach abgeschlossen."))

    if p.month % 3 == 0:
        q = f"{p.year}-Q{p.month // 3}"
        reg = [z for z in zst["zeilen"] if z["quartal"] == q and z["stand"] != "ersetzt"]
        ok = bool(reg)
        sch.append(dict(gruppe=f"Quartal {p.month // 3}/{p.year}", titel="Quartalsrechnungen erstellen", ok=ok, link="rechnungen", knopf="Rechnungen öffnen",
                        text=(f"{len(reg)} Rechnungen erstellt." if ok else "Rechnungen für die Wohnungen (mit QR-Einzahlungsschein) und die Gesamtrechnungen erstellen.")))
        wohnungen = [z for z in reg if z["art"] == "wohnung"]
        vers = st["versendet"].get(q)
        sch.append(dict(gruppe=f"Quartal {p.month // 3}/{p.year}", titel="Rechnungen versenden", ok=bool(vers), manuell=q, link="rechnungen",
                        knopf="PDFs öffnen", text=(f"Versendet am {date.fromisoformat(vers[:10]):%d.%m.%Y}." if vers else
                                                   "PDFs an die Mieter senden und die Gesamtrechnungen für die Nebenkostenabrechnung ablegen.")
                        + ("" if vers or not wohnungen else " Stimmt das Rechnungsdatum nicht, unter «Rechnungen» → «Datum ändern» anpassen.")))
        offen = [z for z in wohnungen if z["stand"] in ("offen", "teilweise", "überfällig")]
        sch.append(dict(gruppe=f"Quartal {p.month // 3}/{p.year}", titel="Zahlungseingang erfassen", ok=bool(wohnungen) and not offen,
                        link="rechnungen", knopf="Zahlungen erfassen",
                        text=("Alle Rechnungen bezahlt." if wohnungen and not offen else "Eingegangene Zahlungen bei der Rechnung eintragen.")
                        + (" Offen: " + ", ".join(f"{core.vorname(cfg, z['partei'])} CHF {z['offen']:.2f}" + (" (überfällig)" if z["stand"] == "überfällig" else "") for z in offen) if offen else ""),
                        optional=True))
    if p.month == 12:
        pdf = S.RECHNUNGEN / "jahr" / f"Allgemeinstrom_{p.year}.pdf"
        sch.append(dict(gruppe=f"Jahr {p.year}", titel="Jahresabrechnung erstellen", ok=pdf.exists(), link=f"jahr?j={p.year}", knopf="Jahresabrechnung öffnen",
                        text=("PDF erstellt." if pdf.exists() else "PDF Allgemeinstrom (und Heizung und Warmwasser) für die Nebenkostenabrechnung erstellen, Excel-Export bei Bedarf.")))
    return sch


def _datei_neuer(info, ende):
    """Ladevorgänge-Datei (Name, Art, Text): nach Monatsende hochgeladen?"""
    try:
        return datetime.fromtimestamp((S.PRIMEO / info[0]).stat().st_mtime) > ende
    except Exception:
        return False


def stehende(cfg, zst, heute=None):
    """Aufgaben unabhängig vom Monat: Tarife fürs neue Jahr, überfällige Rechnungen."""
    heute = heute or date.today()
    out = []
    if heute.month >= 11:
        nj = date(heute.year + 1, 1, 1)
        tar = cfg.get("tarife") or {}
        fehlt = [n for k, n in (("netz", "Netz HT/NT"), ("solar", "Solarpreis"), ("grundpreis_zaehler", "Grundpreis"))
                 if not any(pd.Timestamp(str(t.get("ab"))) >= pd.Timestamp(nj) for t in tar.get(k) or [])]
        out.append(dict(gruppe="Vor dem Jahreswechsel", titel=f"Tarife ab 01.01.{nj.year} eintragen", ok=not fehlt, link="tarife", knopf="Tarife öffnen",
                        text=("Eingetragen." if not fehlt else "Fehlt: " + ", ".join(fehlt) + ". Primeo publiziert die Preise im Herbst (Preisblatt);"
                              " die Solarpreis-Kontrolle (80 %) prüft danach die Grenze.")))
    if zst["n_ueberfaellig"]:
        out.append(dict(gruppe="Laufend", titel="Überfällige Rechnungen", ok=False, link="rechnungen", knopf="Rechnungen öffnen",
                        text=f"{zst['n_ueberfaellig']} Rechnung(en) überfällig, CHF {zst['ueberfaellig']:.2f}. Zahlung erfassen oder erinnern."))
    return out


def stand(heute=None):
    """Alles für die Seite und für den Hinweis auf der Startseite."""
    import seiten
    import uebersicht
    import zahlungen
    d = uebersicht.daten()
    abschluss = seiten.abschluss_laden()
    zst = zahlungen.uebersicht()
    st = laden()
    offen = offene_monate(d["b"], abschluss, heute)
    mon = uebersicht._memo("monate", lambda: uebersicht.monate(d["res"])) if d["res"] is not None else pd.DataFrame()
    return d, abschluss, zst, st, offen, mon


SEITE = """
<style>.schritt{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--line2)}.schritt:last-child{border-bottom:0}
.nr{flex:0 0 30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:2px solid var(--rand);color:var(--muted)}
.schritt.fertig .nr{background:var(--okbg);border-color:var(--okbg);color:var(--ok)}.schritt.jetzt .nr{background:var(--amber);border-color:var(--amber);color:#16201C}
.schritt .inhalt{flex:1;min-width:0}.schritt h3{font-size:15px;margin:4px 0 4px}.schritt.fertig h3{color:var(--muted);font-weight:600}
.schritt .knoepfe{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.schritt ul{margin:6px 0 0;padding-left:18px}.schritt li{margin:2px 0}
.gruppe{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600;margin:18px 0 0}
.fortschritt{height:8px;background:var(--line2);border-radius:99px;overflow:hidden;margin:6px 0 4px}.fortschritt i{display:block;height:100%;background:var(--ok)}</style>
{% if monate %}<div style="display:flex;gap:6px;flex-wrap:wrap;margin:-8px 0 16px">{% for m, l, n in monate %}
<a class="btn {{ 'primary' if m == sel }}" href="aufgaben?m={{ m }}">{{ l }}{% if n %} <span class="pill warn" style="margin-left:6px">{{ n }}</span>{% endif %}</a>{% endfor %}</div>{% endif %}
{% if not sel %}<div class="card"><h2>Alles erledigt</h2><p>Alle vergangenen Monate sind abgeschlossen{% if naechster %}. Der nächste Monat ({{ naechster }}) ist ab dem 1. des Folgemonats an der Reihe{% endif %}.</p></div>{% else %}
<div class="card"><h2>{{ titel }}</h2>
<div class="fortschritt" role="progressbar" aria-valuenow="{{ fertig }}" aria-valuemax="{{ schritte|length }}"><i style="width:{{ (fertig / schritte|length * 100)|round }}%"></i></div>
<p class="muted">{{ fertig }} von {{ schritte|length }} Schritten erledigt{% if offen_n > 1 %} · noch {{ offen_n }} Monate offen{% endif %}</p>
{% set g = namespace(alt='') %}
{% for s in schritte %}{% if s.gruppe != g.alt %}<div class="gruppe">{{ s.gruppe }}</div>{% set g.alt = s.gruppe %}{% endif %}
<div class="schritt {{ 'fertig' if s.ok else ('jetzt' if loop.index0 == aktiv else '') }}"><div class="nr">{{ '✓' if s.ok else loop.index }}</div>
<div class="inhalt"><h3>{{ s.titel }}{% if s.optional and not s.ok %} <span class="muted" style="font-weight:400">· empfohlen</span>{% endif %}</h3>
<div class="muted" style="font-size:13px">{{ s.text }}</div>{% if s.liste %}<ul class="muted">{% for x in s.liste %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
{% if not s.ok or s.manuell %}<div class="knoepfe">{% if not s.ok %}<a class="btn {{ 'primary' if loop.index0 == aktiv }}" href="{{ s.link }}" data-assistent="1">{{ s.knopf }} →</a>{% endif %}
{% if s.manuell %}<form method="post" action="aufgaben_erledigt" class="inline"><input type="hidden" name="q" value="{{ s.manuell }}"><input type="hidden" name="m" value="{{ sel }}">
<input type="hidden" name="wert" value="{{ '' if s.ok else '1' }}"><button>{{ 'Doch nicht versendet' if s.ok else 'Als versendet markieren' }}</button></form>{% endif %}</div>{% endif %}
</div></div>{% endfor %}</div>{% endif %}
{% if stehend %}<div class="card"><h2>Ausserdem</h2>{% for s in stehend %}<div class="schritt {{ 'fertig' if s.ok }}"><div class="nr">{{ '✓' if s.ok else '!' }}</div>
<div class="inhalt"><h3>{{ s.titel }}</h3><div class="muted" style="font-size:13px">{{ s.text }}</div>
{% if not s.ok %}<div class="knoepfe"><a class="btn" href="{{ s.link }}" data-assistent="1">{{ s.knopf }} →</a></div>{% endif %}</div></div>{% endfor %}</div>{% endif %}
<p class="muted">Der Assistent erkennt erledigte Schritte selbst. Über «→» öffnet sich die passende Seite; mit «Zurück zu den Aufgaben» unten links geht es weiter.</p>
<script>try{sessionStorage.removeItem('vzev-assistent')}catch(e){}
document.querySelectorAll('[data-assistent]').forEach(function(a){a.addEventListener('click',function(){try{sessionStorage.setItem('vzev-assistent',location.href)}catch(e){}})})</script>
"""


def seite():
    d, abschluss, zst, st, offen, mon = stand()
    if d["res"] is None:
        return S.page("Aufgaben", '<div class="card"><h2>Erste Schritte</h2><p>Noch keine Daten. Zuerst unter '
                      '<a href="einstellungen?tab=zaehler">Einstellungen → Zähler</a> die Messpunkte eintragen und unter '
                      '<a href="import">Daten importieren</a> die Primeo-Lastgänge hochladen.</p></div>')
    cfg = d["cfg"]
    alle = {str(p): schritte_monat(d, mon, p, abschluss, zst, st) for p in offen}
    # zuletzt abgeschlossenes Quartals-/Jahresende mit offenen Arbeiten (Rechnungen, Zahlungen, Jahres-PDF) ebenfalls zeigen
    for m in sorted(abschluss["monate"], reverse=True)[:3]:
        p = pd.Period(m, "M")
        if p.month % 3 == 0 and m not in alle:
            sch = schritte_monat(d, mon, p, abschluss, zst, st)
            if any(not s["ok"] and not s.get("optional") for s in sch):
                alle[m] = sch
    monate = sorted(alle)
    sel = request.args.get("m")
    if sel not in alle:
        sel = monate[0] if monate else None
    stehend = stehende(cfg, zst)
    naechster = _titel(pd.Period(date.today(), "M"))
    if not sel:
        return S.page("Aufgaben", render_template_string(SEITE, monate=[], sel=None, stehend=stehend, naechster=naechster))
    schritte = alle[sel]
    aktiv = next((i for i, s in enumerate(schritte) if not s["ok"] and not s.get("optional")),
                 next((i for i, s in enumerate(schritte) if not s["ok"]), -1))
    p = pd.Period(sel, "M")
    titel = _titel(p) + (f" · Quartal {p.month // 3}" if p.month % 3 == 0 else "") + (" · Jahresende" if p.month == 12 else "")
    lab = [(m, _titel(pd.Period(m, "M")), sum(1 for s in alle[m] if not s["ok"] and not s.get("optional"))) for m in monate]
    return S.page("Aufgaben", render_template_string(
        SEITE, monate=lab, sel=sel, titel=titel, schritte=schritte, aktiv=aktiv, fertig=sum(1 for s in schritte if s["ok"]),
        offen_n=len(offen), stehend=stehend, naechster=naechster))


def erledigt():
    st = laden()
    q = request.form.get("q", "")
    if request.form.get("wert"):
        st["versendet"][q] = datetime.now().isoformat(timespec="minutes")
        S.log.info("Aufgaben: Rechnungen %s als versendet markiert", q)
    else:
        st["versendet"].pop(q, None)
    speichern(st)
    return redirect(f"aufgaben?m={request.form.get('m', '')}")


def naechste():
    """Für die Startseite: (Text, Link) der nächsten Aufgabe oder None."""
    try:
        d, abschluss, zst, st, offen, mon = stand()
        if d["res"] is None:
            return None
        if offen:
            sch = schritte_monat(d, mon, offen[0], abschluss, zst, st)
            s = next((s for s in sch if not s["ok"] and not s.get("optional")), None)
            if s:
                return (f"{_titel(offen[0])}: {s['titel']}" + (f" (noch {len(offen)} Monate offen)" if len(offen) > 1 else ""), f"aufgaben?m={offen[0]}")
        for s in stehende(d["cfg"], zst):
            if not s["ok"]:
                return (s["titel"], "aufgaben")
    except Exception:
        S.log.exception("Aufgaben nicht bestimmbar")
    return None


def register(app, server):
    global S
    S = server
    app.add_url_rule("/aufgaben", "aufgaben", seite)
    app.add_url_rule("/aufgaben_erledigt", "aufgaben_erledigt", erledigt, methods=["POST"])
