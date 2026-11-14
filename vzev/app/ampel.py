"""Ampeln: grün / gelb / rot (grau = keine Daten) für alle Bereiche der App – wie in der Finanz-App.

Jede Ampel gehört zu einer Seite (Pfad wie in der Navigation). Die Navigation zeigt pro Eintrag die schlechteste Ampel
(nur gelb und rot), zugeklappte Gruppen ebenso; die Startseite zeigt alle als Kacheln.

Bewertet wird im Hintergrund und zwischengespeichert (höchstens alle 5 Minuten oder nach einer neuen Berechnung),
damit keine Seite darauf wartet. Fehler einer Bewertung ergeben «grau», nie einen Seitenfehler.
"""
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

S = None
GRUEN, GELB, ROT, GRAU = "gruen", "gelb", "rot", "grau"
RANG = {ROT: 3, GELB: 2, GRUEN: 1, GRAU: 0}
TEXT = {GRUEN: "in Ordnung", GELB: "prüfen", ROT: "handeln", GRAU: "keine Daten"}
GUELTIG_S = 300
_CACHE = {"zeit": 0.0, "key": None, "ampeln": [], "laeuft": False}
_SPERRE = threading.Lock()


@dataclass
class Ampel:
    bereich: str
    status: str
    text: str
    seite: str      # Pfad wie in der Navigation (z. B. "rechnungen", "./")
    link: str = ""  # genauer Link, falls abweichend (z. B. "einstellungen?tab=zaehler")

    @property
    def ziel(self):
        return self.link or self.seite


def schlechteste(stati):
    stati = [s for s in stati if s]
    return max(stati, key=lambda s: RANG[s]) if stati else GRAU


def alter_status(tage, gelb, rot):
    return GRUEN if tage <= gelb else GELB if tage <= rot else ROT


def _de(d):
    return d.strftime("%d.%m.%Y")


# ---------------------------------------------------------------- Einzelbewertungen

def _berechnung(b):
    if not b.get("ok"):
        return Ampel("Berechnung", ROT if b.get("fehler") else GRAU, (b.get("fehler") or "noch keine Lastgänge")[:120], "import")
    return None


def _primeo(res, heute):
    ende = res.index.max().date()
    tage = (heute - ende).days
    # Primeo liefert monatlich: bis ~6 Wochen alt ist normal
    return Ampel("Primeo-Lastgänge", alter_status(tage, 45, 75), f"bis {_de(ende)} ({tage} Tage)", "import")


def _aufgaben(heute):
    import aufgaben
    d, abschluss, zst, st, offen, mon = aufgaben.stand(heute)
    n = len(offen)
    if not n:
        return Ampel("Monatsabschluss", GRUEN, "alle vergangenen Monate abgeschlossen", "aufgaben"), d, offen, mon
    s = GELB if n == 1 else ROT
    return Ampel("Monatsabschluss", s, f"{n} Monat{'e' if n > 1 else ''} offen ({aufgaben._titel(offen[0])}" + (" …)" if n > 1 else ")"),
                 "aufgaben", f"aufgaben?m={offen[0]}"), d, offen, mon


def _kontrollen(d, offen, mon):
    """Kontrollen des ältesten offenen Monats, sonst des letzten vollständigen."""
    import uebersicht
    if mon is None or not len(mon):
        return None
    if offen:
        p = offen[0]
    else:
        fertig = [p for p in mon.index if not mon.loc[p, "vorlaeufig"]] if "vorlaeufig" in mon else list(mon.index)
        if not fertig:
            return None
        p = fertig[-1]
    kontrollen = uebersicht.kontrollen_fuer(d, mon, p)[0]
    falsch = [t for ok, t, _ in kontrollen if ok is False]
    import aufgaben
    monat = aufgaben._titel(p)
    link = f"uebersicht?j={p.year}&m={p}#monat"
    if not falsch:
        return Ampel("Kontrollen", GRUEN, f"{monat}: alle {sum(1 for k in kontrollen if k[0] is not None)} stimmen", "uebersicht", link)
    return Ampel("Kontrollen", GELB if len(falsch) <= 2 else ROT, f"{monat}: {', '.join(falsch[:2])}" + (" …" if len(falsch) > 2 else ""),
                 "uebersicht", link)


def _rechnungen(heute):
    import zahlungen
    z = zahlungen.uebersicht()
    if z["n_ueberfaellig"]:
        return Ampel("Zahlungen", ROT, f"{z['n_ueberfaellig']} überfällig, CHF {z['ueberfaellig']:.2f}", "rechnungen")
    # Quartalsrechnungen: spätestens 3 Wochen nach Quartalsende erstellt?
    q_ende = date(heute.year, ((heute.month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)
    q = (q_ende.month - 1) // 3 + 1
    ordner = S.RECHNUNGEN / f"{q_ende.year}-Q{q}"
    start = S.config().get("vzev_start")
    if (heute - q_ende).days > 21 and not (start and str(start) > str(q_ende)) and not (ordner.exists() and any(ordner.glob("Rechnung_*.pdf"))):
        return Ampel("Zahlungen", GELB, f"Rechnungen Q{q} {q_ende.year} noch nicht erstellt", "rechnungen")
    return Ampel("Zahlungen", GRUEN, f"CHF {z['offen']:.2f} offen, nichts überfällig" if z["offen"] else "alles bezahlt", "rechnungen")


def _tarife(cfg, mon, heute):
    tar = cfg.get("tarife") or {}
    eintraege = [e for v in tar.values() if isinstance(v, list) for e in v if isinstance(e, dict) and e.get("ab")]
    hat = lambda jahr: any(str(e["ab"])[:4] == str(jahr) for e in eintraege)  # noqa: E731
    offen = int((mon["tarif_offen"] & ~mon["vorlaeufig"]).sum()) if mon is not None and "tarif_offen" in mon else 0
    if heute.month == 12 and not hat(heute.year + 1):
        return Ampel("Tarife", GELB, f"Tarife {heute.year + 1} noch nicht erfasst", "tarife")
    if heute.month <= 2 and not hat(heute.year):
        return Ampel("Tarife", GELB, f"Tarife {heute.year} noch nicht erfasst", "tarife")
    if offen:
        return Ampel("Tarife", GELB, f"Rückliefertarif fehlt für {offen} Monat{'e' if offen > 1 else ''}", "tarife")
    return Ampel("Tarife", GRUEN, "alle Monate mit Tarif", "tarife")


def _sammler(heute):
    st = S.collector.status()
    if not st["zeilen"]:
        return Ampel("Datensammler", GRAU, "keine Sensoren eingerichtet", "sammler")
    if not st["letzter"]:
        return Ampel("Datensammler", GELB, "noch keine Ablesung", "sammler")
    stunden = (datetime.now() - datetime.fromisoformat(str(st["letzter"])[:16])).total_seconds() / 3600
    defekt = [z["entity"] for z in st["zeilen"] if z.get("geprueft") and not z.get("ok")]
    s = GRUEN if stunden <= 1 else GELB if stunden <= 6 else ROT
    if defekt and s == GRUEN:
        s = GELB
    return Ampel("Datensammler", s, f"letzte Ablesung vor {stunden * 60:.0f} Min." if stunden < 2 else f"letzte Ablesung vor {stunden:.0f} h"
                 + (f", {len(defekt)} Sensor{'en' if len(defekt) > 1 else ''} ohne Wert" if defekt else ""), "sammler")


def _nebenkosten(cfg, res, heute):
    import nebenkosten as nk
    perioden = nk.perioden(cfg, heute)
    if not perioden:
        return None
    p = perioden[0]
    d = nk.laden()
    # Vorperiode vorbei: Abrechnung bis Ende September
    if len(perioden) > 1:
        vor = perioden[1]
        ordner = S.RECHNUNGEN / f"NK-{vor}"
        erstellt = ordner.exists() and any(ordner.glob("Rechnung_*.pdf"))
        # nur wenn die Periode in der App geführt wird (Kosten erfasst) – frühere Abrechnungen liefen evtl. ausserhalb
        gefuehrt = bool((d["perioden"].get(vor) or {}).get("positionen"))
        if gefuehrt and not erstellt:
            ende = nk.periode_grenzen(vor)[1]
            tage = (heute - ende).days
            if tage > 30:
                return Ampel("Nebenkosten", ROT if tage > 92 else GELB, f"Abrechnung {nk.periode_text(vor)} noch nicht erstellt",
                             "nebenkosten", f"nebenkosten?p={vor}")
    e = nk.abrechnen(cfg, res, p, d, heute)
    if not any(a.mieter for a in e["abschnitte"]):
        return Ampel("Nebenkosten", GRAU, "keine Mietverhältnisse in der Periode", "nebenkosten")
    grund = [h for h in e["hinweise"] if not h.startswith("Heizung vorläufig")]
    if grund:
        return Ampel("Nebenkosten", GELB, grund[0][:110], "nebenkosten", f"nebenkosten?p={p}")
    return Ampel("Nebenkosten", GRUEN, f"{nk.periode_text(p)}: {len(e['positionen'])} Positionen, CHF {e['kosten']:.0f}",
                 "nebenkosten", f"nebenkosten?p={p}")


def _einheiten(cfg):
    import seiten
    return seiten._einheiten(cfg)


def _prognose(cfg, heute):
    if not (cfg.get("homeassistant") or {}).get("solcast"):
        return Ampel("PV-Prognose", GRAU, "Solcast nicht eingerichtet", "prognose")
    import prognose
    h, m = prognose.kurz(S.collector._db)
    if h is None:
        return Ampel("PV-Prognose", GELB, "keine Prognose für heute – Solcast prüfen", "prognose")
    return Ampel("PV-Prognose", GRUEN, f"heute {h:.1f} kWh" + (f", morgen {m:.1f} kWh" if m is not None else ""), "prognose")


def _sensoren():
    import sensoren
    st = sensoren.status()
    if not st.get("zeit"):
        return None
    if st.get("fehler") == "ausgeschaltet":
        return Ampel("Sensoren für HA", GRAU, "ausgeschaltet", "einstellungen", "einstellungen?tab=zaehler")
    if st.get("fehler"):
        return Ampel("Sensoren für HA", GELB, f"nicht geschrieben: {st['fehler'][:80]}", "einstellungen", "einstellungen?tab=zaehler")
    return Ampel("Sensoren für HA", GRUEN, f"{st.get('anzahl', 0)} Sensoren aktuell", "einstellungen", "einstellungen?tab=zaehler")


def _protokoll():
    n = S.fehler_seit_start()
    s = GRUEN if not n else GELB if n < 5 else ROT
    return Ampel("Protokoll", s, f"{n} Fehler seit dem Start" if n else "keine Fehler seit dem Start", "einstellungen", "protokoll?stufe=ERROR" if n else "protokoll")


def _vorschlaege():
    import vorschlaege
    st = vorschlaege.laden()["status"]
    liste = [v for v in vorschlaege.sammeln() if v.schluessel not in st]
    hoch = [v for v in liste if v.gewicht >= 3]
    if hoch:
        return Ampel("Vorschläge", GELB, f"{len(hoch)} mit hoher Priorität: {hoch[0].titel[:70]}", "vorschlaege")
    return Ampel("Vorschläge", GRUEN, f"{len(liste)} offen, keine dringenden" if liste else "keine offenen", "vorschlaege")


# ---------------------------------------------------------------- Gesamt

def bewerten(heute=None):
    heute = heute or date.today()
    erg = []

    def versuch(name, fn, seite):
        try:
            a = fn()
            if a:
                erg.append(a)
        except Exception as e:  # noqa: BLE001 – eine Ampel darf nie eine Seite verhindern
            S.log.debug("Ampel %s: %s", name, e)
            erg.append(Ampel(name, GRAU, "nicht bewertbar", seite))
    b = S._cache if S._cache.get("key") else {}
    cfg = S.config()
    a = _berechnung(b) if b else Ampel("Berechnung", GRAU, "läuft noch", "import")
    if a:
        erg.append(a)
    res = b.get("res") if b.get("ok") else None
    ctx = {"d": None, "offen": [], "mon": None}
    if res is not None:
        versuch("Primeo-Lastgänge", lambda: _primeo(res, heute), "import")

        def auf():
            amp, ctx["d"], ctx["offen"], ctx["mon"] = _aufgaben(heute)
            return amp
        versuch("Monatsabschluss", auf, "aufgaben")
        if ctx["d"] is not None:
            versuch("Kontrollen", lambda: _kontrollen(ctx["d"], ctx["offen"], ctx["mon"]), "uebersicht")
        versuch("Tarife", lambda: _tarife(cfg, ctx["mon"], heute), "tarife")
    versuch("Zahlungen", lambda: _rechnungen(heute), "rechnungen")
    versuch("Nebenkosten", lambda: _nebenkosten(cfg, res, heute), "nebenkosten")
    versuch("Datensammler", lambda: _sammler(heute), "sammler")
    versuch("PV-Prognose", lambda: _prognose(cfg, heute), "prognose")
    versuch("Sensoren für HA", _sensoren, "einstellungen")
    versuch("Protokoll", _protokoll, "einstellungen")
    versuch("Vorschläge", _vorschlaege, "vorschlaege")
    return erg


def pro_seite(ampeln):
    """Schlechteste Ampel pro Seite (für die Navigation)."""
    seiten = {}
    for a in ampeln:
        seiten.setdefault(a.seite, []).append(a.status)
    return {s: schlechteste(v) for s, v in seiten.items()}


def _neu_bewerten():
    try:
        amp = bewerten()
        with _SPERRE:
            _CACHE.update(ampeln=amp, zeit=time.time())
    except Exception as e:  # noqa: BLE001
        S.log.debug("Ampeln: %s", e)
    finally:
        _CACHE["laeuft"] = False


def aktuell(warten=False):
    """Zwischengespeicherte Ampeln; veraltet → im Hintergrund neu (die Seite wartet nicht, ausser warten=True)."""
    key = S._cache.get("key")
    alt = time.time() - _CACHE["zeit"] > GUELTIG_S or _CACHE["key"] != key
    if alt and not _CACHE["laeuft"] and not S.RECHNEN.get("aktiv"):
        _CACHE.update(laeuft=True, key=key)
        if warten:
            _neu_bewerten()
        else:
            threading.Thread(target=_neu_bewerten, name="ampeln", daemon=True).start()
    return list(_CACHE["ampeln"])


def zuruecksetzen():
    """Nach einer Änderung (Speichern, Zahlung, Abschluss): beim nächsten Seitenaufruf neu bewerten."""
    _CACHE["zeit"] = 0.0


def karte(ampeln):
    """Kacheln für die Startseite."""
    from markupsafe import escape
    if not ampeln:
        return ""
    reihen = sorted(ampeln, key=lambda a: -RANG[a.status])
    kacheln = "".join(f'<a class="ampel-kachel {a.status}" href="{escape(a.ziel)}">{licht(a.status)}<div><b>{escape(a.bereich)}</b>'
                      f'<span>{escape(a.text)}</span></div></a>' for a in reihen)
    z = {s: sum(1 for a in ampeln if a.status == s) for s in (ROT, GELB, GRUEN)}
    legende = (f'<div class="ampel-legende"><span>{licht(ROT)}{z[ROT]} handeln</span><span>{licht(GELB)}{z[GELB]} prüfen</span>'
               f'<span>{licht(GRUEN)}{z[GRUEN]} in Ordnung</span></div>')
    return f'<div class="ampeln">{kacheln}</div>{legende}'


def licht(status, titel=""):
    t = titel or TEXT.get(status, "")
    return f'<span class="ampel {status}" title="{t}" role="img" aria-label="Ampel {TEXT.get(status, "")}"></span>'


CSS = """
.ampel{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px;flex:none;background:var(--rand);opacity:.6}
.ampel.gruen{background:#2fa35b;opacity:1;box-shadow:0 0 0 3px color-mix(in srgb,#2fa35b 20%,transparent)}
.ampel.gelb{background:#e6a817;opacity:1;box-shadow:0 0 0 3px color-mix(in srgb,#e6a817 22%,transparent)}
.ampel.rot{background:#d93b30;opacity:1;box-shadow:0 0 0 3px color-mix(in srgb,#d93b30 20%,transparent)}
nav .ampel{width:8px;height:8px;margin:0 0 0 6px;box-shadow:none;vertical-align:middle}
.ampeln{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));margin-bottom:10px}
.ampel-kachel{display:flex;gap:10px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;
 text-decoration:none;color:var(--ink)}.ampel-kachel:hover{border-color:var(--rand)}
.ampel-kachel .ampel{margin-top:5px}.ampel-kachel b{display:block;font-size:14px}.ampel-kachel span{color:var(--muted);font-size:12px}
.ampel-kachel.rot{border-color:color-mix(in srgb,#d93b30 45%,var(--line))}.ampel-kachel.gelb{border-color:color-mix(in srgb,#e6a817 45%,var(--line))}
.ampel-legende{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:0 0 18px}
"""


def register(app, server):
    global S
    S = server
