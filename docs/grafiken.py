"""Erzeugt die zwei handgezeichneten README-Grafiken: Architektur und Monatsprozess."""
import sys
from html import escape

OUT = sys.argv[1]
INK, MUTED, LINE = "#16201C", "#5B6660", "#C9CEC8"
FARBE = {
    "quelle": ("#EEF3FA", "#2F6DB5"),
    "app": ("#FDF3DF", "#D4900A"),
    "daten": ("#E3F1E8", "#2E8B57"),
    "aus": ("#F6F7F5", "#5B6660"),
}
FONT = "font-family='Helvetica, Arial, sans-serif'"


def box(x, y, w, h, titel, unter="", art="app", form="rect", nr=None):
    f, s = FARBE[art]
    out = []
    if form == "zyl":
        e = 7
        out.append(f"<path d='M{x},{y+e} v{h-2*e} a{w/2},{e} 0 0 0 {w},0 v{-(h-2*e)} a{w/2},{e} 0 0 0 {-w},0 z' fill='{f}' stroke='{s}' stroke-width='1.5'/>")
        out.append(f"<ellipse cx='{x+w/2}' cy='{y+e}' rx='{w/2}' ry='{e}' fill='{f}' stroke='{s}' stroke-width='1.5'/>")
        ty = y + e + 4
    elif form == "raute":
        cx, cy = x + w / 2, y + h / 2
        out.append(f"<path d='M{cx},{y} L{x+w},{cy} L{cx},{y+h} L{x},{cy} z' fill='{f}' stroke='{s}' stroke-width='1.5'/>")
        ty = y
    else:
        out.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='{f}' stroke='{s}' stroke-width='1.5'/>")
        ty = y
    zeilen = [(titel, 14, 700, INK)] + [(z, 12, 400, MUTED) for z in unter.split("\n") if z]
    hoehe = sum(z[1] + 4 for z in zeilen)
    yy = ty + (y + h - ty) / 2 - hoehe / 2 + 12
    for t, size, weight, col in zeilen:
        out.append(f"<text x='{x+w/2}' y='{yy:.1f}' text-anchor='middle' font-size='{size}' font-weight='{weight}' fill='{col}' {FONT}>{escape(t)}</text>")
        yy += size + 4
    if nr is not None:
        out.append(f"<circle cx='{x+4}' cy='{y+4}' r='13' fill='{INK}'/><text x='{x+4}' y='{y+8.5}' text-anchor='middle' font-size='12' font-weight='700' fill='#fff' {FONT}>{nr}</text>")
    return "".join(out)


def pfeil(x1, y1, x2, y2, text="", gestrichelt=False, kurve=0):
    dash = " stroke-dasharray='5 4'" if gestrichelt else ""
    if kurve:
        mx = (x1 + x2) / 2
        d = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
    else:
        d = f"M{x1},{y1} L{x2},{y2}"
    out = f"<path d='{d}' fill='none' stroke='{MUTED}' stroke-width='1.6'{dash} marker-end='url(#pf)'/>"
    if text:
        tx, ty = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        out += f"<text x='{tx}' y='{ty}' text-anchor='middle' font-size='11' fill='{MUTED}' {FONT}>{escape(text)}</text>"
    return out


def svg(w, h, inhalt, titel):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' width='{w}' height='{h}' role='img' aria-label='{escape(titel)}'>"
            f"<defs><marker id='pf' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
            f"<path d='M0,0 L10,5 L0,10 z' fill='{MUTED}'/></marker></defs>"
            f"<rect width='{w}' height='{h}' fill='#fff'/>{inhalt}</svg>")


# --- Architektur: Quellen → Erfassung → Speicher → Berechnung → Ausgabe --------
W, BW, BH = 1080, 176, 58
X = [20, 236, 452, 668, 884]
k = []
for x, t in zip(X, ["Quellen", "Erfassung", "Speicher", "Berechnung", "Ausgabe"]):
    k.append(f"<text x='{x+BW/2}' y='28' text-anchor='middle' font-size='13' font-weight='700' fill='{MUTED}' letter-spacing='1' {FONT}>{t.upper()}</text>")
    k.append(f"<line x1='{x-12}' y1='44' x2='{x-12}' y2='600' stroke='#EEF0EC'/>" if x > 20 else "")
# Quellen
q = {"primeo": 60, "goe": 135, "ha": 245, "evcc": 320, "du": 430, "tarif": 530}
k.append(box(X[0], q["primeo"], BW, BH, "Primeo-Portal", "Lastgänge .xlsx, 15 Min.", "quelle"))
k.append(box(X[0], q["goe"], BW, BH, "go-e Wallbox", "Ladevorgänge .csv", "quelle"))
k.append(box(X[0], q["ha"], BW, BH, "Home Assistant", "whatwatt, go-e, Solis, Solcast", "quelle"))
k.append(box(X[0], q["evcc"], BW, BH, "evcc", "Ladevorgänge (REST)", "quelle"))
k.append(box(X[0], q["du"], BW, BH, "Betreiber", "Formulare in der App", "quelle"))
k.append(box(X[0], q["tarif"], BW, BH, "Primeo-Tarife", "Strompreise (Internet)", "quelle"))
# Erfassung
e = {"import": 97, "sammler": 282, "seiten": 430, "preise": 530}
k.append(box(X[1], e["import"], BW, BH, "Import", "server.py · Messpunkt erkennen", "app"))
k.append(box(X[1], e["sammler"], BW, BH, "Datensammler", "collector.py · alle 15 Min.", "app"))
k.append(box(X[1], e["seiten"], BW, BH, "Stammdaten, Abschluss", "seiten.py", "app"))
k.append(box(X[1], e["preise"], BW, BH, "Preisabruf", "preise.py · täglich ab 18 Uhr", "app"))
# Speicher
s = {"primeo": 70, "yaml": 165, "mess": 282, "abschl": 410}
k.append(box(X[2], s["primeo"], BW, BH, "primeo/", "Lastgänge + Zwischenspeicher", "daten", "zyl"))
k.append(box(X[2], s["yaml"], BW, BH, "vzev.yaml", "Tarife, Mieter, Regeln", "daten", "zyl"))
k.append(box(X[2], s["mess"], BW, BH, "messwerte.sqlite", "Zählerstände, evcc", "daten", "zyl"))
k.append(box(X[2], s["abschl"], BW, BH, "abschluss.json", "festgehaltene Monate", "daten", "zyl"))
# Berechnung
b = {"core": 118, "vorschau": 282}
k.append(box(X[3], b["core"], BW, BH, "Rechenkern", "core.py · Speicher, Bonus", "app"))
k.append(box(X[3], b["vorschau"], BW, BH, "Vorschau", "vorschau.py · laufender Monat", "app"))
# Ausgabe
a = {"ueb": 70, "rech": 165, "abs": 410, "prot": 282}
k.append(box(X[4], a["ueb"], BW, BH, "Übersicht, Wertschöpfung", "uebersicht.py · Kontrollen", "aus"))
k.append(box(X[4], a["rech"], BW, BH, "Rechnungen, Jahr", "invoices, jahr, zahlungen", "aus"))
k.append(box(X[4], a["prot"], BW, BH, "Sensoren, Status", "sensor.vzev_*, Protokoll", "aus"))
k.append(box(X[4], a["abs"], BW, BH, "Abschluss, Korrekturen", "Sperre, Begründungen", "aus"))
k.append(box(X[4], 530, BW, BH, "Energiefluss, Prognose", "Aufgaben, Ladefenster", "aus"))
m = BH / 2
R = lambda i: X[i] + BW
k += [
    pfeil(R(0), q["primeo"] + m, X[1], e["import"] + m - 10, kurve=1),
    pfeil(R(0), q["goe"] + m, X[1], e["import"] + m + 10, kurve=1),
    pfeil(R(0), q["ha"] + m, X[1], e["sammler"] + m - 10, kurve=1),
    pfeil(R(0), q["evcc"] + m, X[1], e["sammler"] + m + 10, kurve=1),
    pfeil(R(0), q["du"] + m, X[1], e["seiten"] + m),
    pfeil(R(1), e["import"] + m, X[2], s["primeo"] + m, kurve=1),
    pfeil(R(1), e["sammler"] + m, X[2], s["mess"] + m),
    pfeil(R(1), e["seiten"] + m - 10, X[2], s["yaml"] + m + 10, kurve=1),
    pfeil(R(1), e["seiten"] + m, X[2], s["abschl"] + m),
    pfeil(R(2), s["primeo"] + m, X[3], b["core"] + m - 10, kurve=1),
    pfeil(R(2), s["yaml"] + m, X[3], b["core"] + m + 10, kurve=1),
    pfeil(R(2), s["mess"] + m, X[3], b["vorschau"] + m),
    pfeil(X[3] + BW / 2, b["core"] + BH, X[3] + BW / 2, b["vorschau"], "HT/NT, Tarife", gestrichelt=True),
    pfeil(R(3), b["core"] + m - 12, X[4], a["ueb"] + m, kurve=1),
    pfeil(R(3), b["core"] + m + 4, X[4], a["rech"] + m, kurve=1),
    pfeil(R(3), b["core"] + m + 18, X[4], a["abs"] + m - 10, kurve=1),
    pfeil(R(3), b["vorschau"] + m - 10, X[4], a["ueb"] + m + 12, kurve=1),
    pfeil(R(2), s["abschl"] + m, X[4], a["abs"] + m + 10, kurve=1),
    pfeil(R(0), q["tarif"] + m, X[1], e["preise"] + m),
    pfeil(R(1), e["preise"] + m - 10, X[2], s["mess"] + m + 12, kurve=1),
    pfeil(R(2), s["mess"] + m + 14, X[4], 530 + m, kurve=1),
    pfeil(R(3), b["vorschau"] + m + 8, X[4], a["prot"] + m, kurve=1),
]
k.append(f"<text x='20' y='{620}' font-size='12' fill='{MUTED}' {FONT}>Alles läuft im Container der App; die Daten liegen im Konfigurationsordner und sind im Home-Assistant-Backup enthalten. Ins Internet geht nur der Preisabruf; die Sensoren gehen zurück an Home Assistant.</text>")
open(f"{OUT}/architektur.svg", "w").write(svg(W, 640, "".join(k), "Architektur der vZEV-App"))

# --- Monatsprozess: zwei Reihen ------------------------------------------------
W, BW, BH = 1080, 210, 84
xs = [30, 300, 570, 840]
y1, y2 = 70, 310
k = [f"<text x='30' y='34' font-size='13' font-weight='700' fill='{MUTED}' letter-spacing='1' {FONT}>MONATLICH</text>",
     f"<text x='30' y='{y2-54}' font-size='13' font-weight='700' fill='{MUTED}' letter-spacing='1' {FONT}>ABSCHLUSS UND RECHNUNG</text>"]
k.append(box(xs[0], y1, BW, BH, "Exportieren", "Primeo: Lastgänge 5 Zähler\ngo-e: Ladevorgänge", "quelle", nr=1))
k.append(box(xs[1], y1, BW, BH, "Daten importieren", "Zuordnung über Messpunkt,\nalte Fassung wird ersetzt", "app", nr=2))
k.append(box(xs[2], y1 - 8, BW, BH + 16, "Kontrollen ok?", "Lücken, Ladestation,\nAbgleich", "app", "raute", nr=3))
k.append(box(xs[3], y1, BW, BH, "Primeo-Rechnung erfassen", "Netzbezug HT/NT und\nRücklieferung (Seite Primeo)", "app", nr=4))
k.append(box(xs[0], y2, BW, BH, "Tarife prüfen", "Rückliefertarif eintragen,\nsobald publiziert", "app", nr=5))
k.append(box(xs[1], y2, BW, BH, "Monat abschliessen", "Werte festhalten,\nÄnderungen gesperrt", "daten", nr=6))
k.append(box(xs[2], y2, BW, BH, "Rechnungen erstellen", "pro Quartal: Wohnung mit QR,\nAllgemeinstrom, Heizung gesamt", "aus", nr=7))
k.append(box(xs[3], y2, BW, BH, "Versenden, Zahlungen", "Gesamtrechnungen in die NK-Abr.;\nZahlungen, Erinnerung", "quelle", nr=8))
my1, my2 = y1 + BH / 2, y2 + BH / 2
k += [pfeil(xs[0] + BW, my1, xs[1], my1), pfeil(xs[1] + BW, my1, xs[2], my1),
      pfeil(xs[2] + BW, my1, xs[3], my1, "ja"),
      f"<path d='M{xs[2]+BW/2},{y1+BH+8} C{xs[2]+BW/2},{y1+BH+50} {xs[1]+BW/2},{y1+BH+50} {xs[1]+BW/2},{y1+BH}' fill='none' stroke='#B4541A' stroke-width='1.6' marker-end='url(#pf)'/>",
      f"<text x='{(xs[1]+xs[2])/2+BW/2}' y='{y1+BH+64}' text-anchor='middle' font-size='11' fill='#B4541A' {FONT}>nein: Datei prüfen, neu hochladen</text>",
      f"<path d='M{xs[3]+BW/2},{y1+BH} V{y2-40} H{xs[0]+BW/2} V{y2}' fill='none' stroke='{MUTED}' stroke-width='1.6' stroke-linejoin='round' marker-end='url(#pf)'/>",
      pfeil(xs[0] + BW, my2, xs[1], my2), pfeil(xs[1] + BW, my2, xs[2], my2, "Quartalsende"), pfeil(xs[2] + BW, my2, xs[3], my2)]
k.append(f"<text x='30' y='{y2+BH+40}' font-size='12' fill='{MUTED}' {FONT}>Der Aufgaben-Assistent zeigt pro Monat den nächsten Schritt. Jährlich: Jahresabrechnung (Allgemeinstrom- und Heizungs-PDF, Excel).</text>")
open(f"{OUT}/prozess-monatlich.svg", "w").write(svg(W, y2 + BH + 60, "".join(k), "Monatlicher Ablauf"))
print("ok")
