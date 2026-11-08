"""Quartalsrechnungen als PDF: Wohnung pro Mietverhältnis (mit Swiss QR-Zahlteil) und Allgemeinstrom als Gesamtrechnung.

Aufruf: python -I invoices.py <datenordner> <jahr> <quartal> <ausgabeordner> [rechnungsdatum JJJJ-MM-TT]
"""
import calendar
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
INK, MUTED, LINE, AMBER, BLUE, SOFT = (HexColor(c) for c in
                                       ("#16201C", "#5B6660", "#D3D8D2", "#E8A21B", "#3B5B8C", "#F6F7F5"))


def chf(x):
    return f"{x:,.2f}".replace(",", "'")


def kwh(x):
    return f"{x:,.2f}".replace(",", "'")


def de(d):
    return d.strftime("%d.%m.%Y")


# --- Daten pro Rechnung ----------------------------------------------------
def quarter_range(year, q):
    start = date(year, 3 * q - 2, 1)
    end_month = 3 * q
    return start, date(year, end_month, calendar.monthrange(year, end_month)[1])


def grundpreis(cfg, d):
    gp = [e for e in cfg["tarife"]["grundpreis_zaehler"] if pd.Timestamp(e["ab"]) <= pd.Timestamp(d)]
    return gp[-1]["chf"] if gp else 0.0


def _werte_im_zeitraum(eintraege, von, bis, key):
    """Werte der Tarifeinträge, die zwischen von und bis gelten (in zeitlicher Reihenfolge, ohne Wiederholung)."""
    es = sorted(eintraege or [], key=lambda e: str(e["ab"]))
    out = []
    for i, e in enumerate(es):
        ab = pd.Timestamp(e["ab"]).date()
        ende = pd.Timestamp(es[i + 1]["ab"]).date() - timedelta(days=1) if i + 1 < len(es) else date.max
        if ab <= bis and ende >= von and e.get(key) is not None and e[key] not in out:
            out.append(e[key])
    return out


def tarif_hinweise(cfg, von, bis):
    """Fussnoten mit den im Zeitraum gültigen Tarifen (statt fester Zahlen)."""
    t = cfg["tarife"]
    rp = lambda xs: " bzw. ".join(f"{x * 100:.2f}" for x in xs) or "–"
    ht, nt = _werte_im_zeitraum(t.get("netz"), von, bis, "ht"), _werte_im_zeitraum(t.get("netz"), von, bis, "nt")
    gp = _werte_im_zeitraum(t.get("grundpreis_zaehler"), von, bis, "chf")
    return [f"Tarife: Solarstrom {rp(_werte_im_zeitraum(t.get('solar'), von, bis, 'chf'))} Rp./kWh · Netzstrom HT {rp(ht)} / NT {rp(nt)} Rp./kWh "
            "(Primeo, inkl. Abgaben und MWST).",
            "* Grundpreis Netznutzung anteilig, Messtarif, Konzessionsabgabe: "
            + (" bzw. ".join(f"{x:.2f}" for x in gp) or "–") + " CHF pro Zähler und Monat."]


def tabelle(c, L, R, hy, rows):
    """Monatstabelle (Rechnung und Jahresaufstellung). Spalte «Speicher NT» nur, wenn Netzstrom aus dem Speicher
    geliefert wurde; Bonus aus dem dynamischen Tarif als eigene Zeile vor dem Total. Gibt (y unter Total, Total) zurück."""
    speicher = any(r.get("speicher", 0) > 0.0005 for r in rows)
    bonus = round(sum(r.get("bonus", 0) for r in rows), 2)
    if speicher:
        cols = [("Monat", 0, "l"), ("Solar kWh", 46, "r"), ("HT kWh", 64, "r"), ("NT kWh", 81, "r"),
                ("Speicher NT", 100, "r"), ("Solar CHF", 117, "r"), ("Netz CHF", 135, "r"), ("Grundpreis*", 152, "r"),
                ("Total CHF", 168, "r")]
    else:
        cols = [("Monat", 0, "l"), ("Solar kWh", 52, "r"), ("Netz HT kWh", 74, "r"), ("Netz NT kWh", 96, "r"),
                ("Solar CHF", 116, "r"), ("Netz CHF", 134, "r"), ("Grundpreis*", 153, "r"), ("Total CHF", 170, "r")]

    def zeile(vals, y):
        for (name, x, al), v in zip(cols, vals):
            (c.drawString if al == "l" else c.drawRightString)(L + (2 if al == "l" else x) * mm, y, v)

    def werte(label, r, total):
        v = [label, kwh(r["solar"]), kwh(r["ht"]), kwh(r["nt"])]
        if speicher:
            v.append(kwh(r.get("speicher", 0)))
        # Netz CHF inkl. Netzstrom aus Speicher; Total ohne Bonus (der folgt als eigene Zeile)
        return v + [chf(r["solar_chf"]), chf(r["netz_chf"] + r.get("speicher_chf", 0)), chf(r["grundpreis"]), chf(total)]

    c.setFillColor(HexColor("#26313A"))
    c.rect(L, hy - 2.2 * mm, R - L, 7 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 7 if speicher else 7.5)
    zeile([n for n, _, _ in cols], hy)
    yy = hy - 7 * mm
    c.setFont("Helvetica", 8.5)
    keys = ("solar", "ht", "nt", "speicher", "solar_chf", "netz_chf", "speicher_chf", "grundpreis", "total")
    sums = dict.fromkeys(keys, 0)
    for r in rows:
        c.setFillColor(INK)
        zeile(werte(r["monat"], r, r["total"] + r.get("bonus", 0)), yy)
        for k in keys:
            sums[k] += r.get(k, 0)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        c.line(L, yy - 2.5 * mm, R, yy - 2.5 * mm)
        yy -= 6.5 * mm
    total = round(sums["total"], 2)
    if bonus:
        c.setFillColor(HexColor("#2E8B57"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L + 2 * mm, yy, "Bonus dynamischer Stromtarif (Gutschrift)")
        c.drawRightString(L + cols[-1][1] * mm, yy, "– " + chf(bonus))
        c.setStrokeColor(LINE)
        c.line(L, yy - 2.5 * mm, R, yy - 2.5 * mm)
        yy -= 6.5 * mm
    c.setFillColor(SOFT)
    c.rect(L, yy - 2.2 * mm, R - L, 6.5 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 8.5)
    zeile(werte("Total", sums, total), yy)
    return yy, total


def zusatz_hinweise(cfg, rows):
    """Fussnoten zu Speicher und Bonus, nur wenn sie vorkommen."""
    out = []
    if any(r.get("speicher", 0) > 0.0005 for r in rows):
        out.append("Speicher NT: Netzstrom, der nachts in den Batteriespeicher geladen und später im Haus verbraucht wurde, "
                   "zum vZEV-Preis; nicht als Solarstrom ausgewiesen.")
    if any(r.get("bonus", 0) for r in rows):
        fehlt = sum(r.get("dyn_fehlt", 0) for r in rows)
        out.append("Bonus: Differenz zwischen Standardtarif HT/NT und dem dynamischen Tarif von Primeo pro Viertelstunde, "
                   "voll gutgeschrieben" + (f" ({int(fehlt)} Viertelstunden ohne publizierten Preis ausgenommen)." if fehlt else "."))
    return out


def render_jahr(path, cfg, rows, jahr, von, bis, vorlaeufig):
    """Jahresaufstellung Allgemeinstrom für die Nebenkostenabrechnung."""
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"Allgemeinstrom {jahr}")
    b = cfg["betreiber"]
    L, R = 20 * mm, W - 20 * mm
    y = H - 20 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(L, y, b["name"])
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(L, y - 5 * mm, f"{b['strasse']} {b['hausnr']} · {b['plz']} {b['ort']}")
    c.setStrokeColor(AMBER)
    c.setLineWidth(1.5)
    c.line(L, y - 9 * mm, R, y - 9 * mm)
    c.setFont("Helvetica", 8.5)
    for i, (k, v) in enumerate([("Liegenschaft", f"{b['strasse']} {b['hausnr']}, {b['plz']} {b['ort']}"),
                                 ("Zeitraum", f"{de(von)} – {de(bis)}"), ("Erstellt", de(date.today()))]):
        c.setFillColor(MUTED)
        c.drawString(L, y - 20 * mm - i * 4.6 * mm, k)
        c.setFillColor(INK)
        c.drawString(L + 24 * mm, y - 20 * mm - i * 4.6 * mm, v)
    ty = y - 40 * mm
    c.setFont("Helvetica-Bold", 15)
    c.drawString(L, ty, f"Allgemeinstrom {jahr} · Aufstellung für die Nebenkostenabrechnung" if not vorlaeufig
                 else f"Allgemeinstrom {jahr} · Aufstellung (vorläufig)")
    hy = ty - 10 * mm
    yy, total = tabelle(c, L, R, hy, rows)
    ny = yy - 9 * mm
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    notes = tarif_hinweise(cfg, von, bis) + zusatz_hinweise(cfg, rows) + [
        "Ohne Ladestation (separat erfasst); inkl. Standby-Netzbezug der PV-Anlage. Grundlage: Primeo-Lastgänge in 15-Minuten-Auflösung."]
    if vorlaeufig:
        notes.append("Vorläufig: Nicht alle Monate des Zeitraums sind abgeschlossen oder es fehlen noch Lastgänge.")
    for i, n in enumerate(notes):
        c.drawString(L, ny - i * 3.6 * mm, n)
    by = ny - len(notes) * 3.6 * mm - 18 * mm
    c.setFillColor(HexColor("#FDF3DF"))
    c.roundRect(L, by, R - L, 13 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 8.5)
    c.drawString(L + 4 * mm, by + 5 * mm, "Betrag zur Übernahme in die Nebenkostenabrechnung.")
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(R - 4 * mm, by + 4.5 * mm, f"CHF {chf(total)}")
    c.showPage()
    c.save()
    return total


def lines_for(res, cfg, zaehler, von, bis):
    """Monatszeilen für einen Zähler zwischen von und bis (inkl.), Grundpreis anteilig nach Tagen."""
    mask = (res.index >= pd.Timestamp(von)) & (res.index < pd.Timestamp(bis) + pd.Timedelta(days=1))
    s = core.zaehler_summen(res, zaehler, mask)
    rows = []
    for per, r in s.iterrows():
        m0 = max(per.start_time.date(), von)
        m1 = min(per.end_time.date(), bis)
        days, dim = (m1 - m0).days + 1, calendar.monthrange(per.year, per.month)[1]
        gp = round(grundpreis(cfg, m0) * days / dim, 2)
        solar_chf, netz_chf, speicher_chf = round(r.solar_chf, 2), round(r.netz_chf, 2), round(r.speicher_chf, 2)
        bonus = max(round(r.bonus_chf, 2), 0.0)  # der Mieter hat nie einen Nachteil
        total_kwh = r.solar + r.ht + r.nt + r.speicher
        rows.append(dict(
            monat=MONATE[per.month] + ("" if days == dim else f" ({m0.day}.–{m1.day}.)"),
            solar=r.solar, ht=r.ht, nt=r.nt, solar_chf=solar_chf, netz_chf=netz_chf, grundpreis=gp,
            speicher=r.speicher, speicher_chf=speicher_chf, bonus=bonus, dyn_fehlt=int(r.dyn_fehlt),
            total=round(solar_chf + netz_chf + speicher_chf + gp - bonus, 2),
            autarkie=100 * r.solar / total_kwh if total_kwh else 100.0,
            letzte=r.letzte_viertelstunde, monatsende=per.end_time.floor("15min"),
        ))
    return rows


def invoices_for_quarter(res, cfg, year, q):
    qs, qe = quarter_range(year, q)
    data_end = res.index.max().date()
    out = []
    for m in cfg["mietverhaeltnisse"]:
        von = max(pd.Timestamp(m["von"]).date(), qs, pd.Timestamp(cfg["vzev_start"]).date())
        bis = min(pd.Timestamp(m["bis"]).date() if m.get("bis") else qe, qe)
        if von > bis:
            continue
        rows = lines_for(res, cfg, m["einheit"], von, bis)
        out.append(dict(art="wohnung", partei=m, einheit=m["einheit"], von=von, bis=bis, rows=rows,
                        vorlaeufig=data_end < bis))
    rows = lines_for(res, cfg, "AllgC", qs, qe)
    out.append(dict(art="allgemein", partei=None, einheit="ALLG", von=qs, bis=qe, rows=rows, vorlaeufig=data_end < qe))
    return out


# --- Grafik -----------------------------------------------------------------
def donuts_png(rows):
    n = len(rows)
    fig, axes = plt.subplots(1, n, figsize=(1.6 * n, 1.75), dpi=220)
    axes = [axes] if n == 1 else axes
    for ax, r in zip(axes, rows):
        netz = r["ht"] + r["nt"] + r.get("speicher", 0)
        ax.pie([r["solar"], max(netz, 1e-6)], colors=["#E8A21B", "#3B5B8C"], startangle=90, counterclock=False,
               wedgeprops=dict(width=0.32, edgecolor="white", linewidth=1.5))
        ax.text(0, 0.06, f"{r['autarkie']:.1f}%", ha="center", va="center", fontsize=10, fontweight="bold", color="#16201C")
        ax.text(0, -0.24, "Solar", ha="center", va="center", fontsize=7, color="#5B6660")
        ax.set_title(r["monat"].split(" (")[0], fontsize=9.5, color="#16201C", pad=3)
        ax.set_aspect("equal")
    plt.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return ImageReader(buf)


# --- Swiss QR ---------------------------------------------------------------
def qr_payload(cfg, inv, amount, nummer):
    b, p = cfg["betreiber"], inv["partei"]
    lines = ["SPC", "0200", "1", b["iban"].replace(" ", ""),
             "S", b["name"], b["strasse"], b["hausnr"], b["plz"], b["ort"], "CH",
             "", "", "", "", "", "", "",
             f"{amount:.2f}", "CHF",
             "S", p["name"], p["strasse"], p["hausnr"], p["plz"], p["ort"], "CH",
             "NON", "", f"Stromabrechnung {nummer}", "EPD"]
    return "\r\n".join(lines)


def iban_fmt(iban):
    i = iban.replace(" ", "")
    return " ".join(i[k:k + 4] for k in range(0, len(i), 4))


def draw_qr_bill(c, cfg, inv, amount, nummer):
    W = A4[0]
    top = 105 * mm
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.setDash(2, 2)
    c.line(0, top, W, top)
    c.line(62 * mm, 0, 62 * mm, top)
    c.setDash()
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawCentredString(W / 2, top + 2 * mm, "Vor der Einzahlung abzutrennen")
    b, p = cfg["betreiber"], inv["partei"]
    cred = [iban_fmt(b["iban"]), b["name"], f"{b['strasse']} {b['hausnr']}", f"{b['plz']} {b['ort']}"]
    debt = [p["name"], f"{p['strasse']} {p['hausnr']}", f"{p['plz']} {p['ort']}"]

    def block(x, y, head, lines, hs, vs, lead):
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", hs)
        c.drawString(x, y, head)
        y -= lead
        c.setFont("Helvetica", vs)
        for ln in lines:
            c.drawString(x, y, ln)
            y -= lead
        return y - lead * 0.6

    # Empfangsschein
    x, y = 5 * mm, top - 5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(black)
    c.drawString(x, y - 4 * mm, "Empfangsschein")
    y = block(x, y - 11 * mm, "Konto / Zahlbar an", cred, 6, 8, 9)
    y = block(x, y, "Zahlbar durch", debt, 6, 8, 9)
    c.setFont("Helvetica-Bold", 6)
    c.drawString(x, 37 * mm, "Währung")
    c.drawString(x + 14 * mm, 37 * mm, "Betrag")
    c.setFont("Helvetica", 8)
    c.drawString(x, 33 * mm, "CHF")
    c.drawString(x + 14 * mm, 33 * mm, chf(amount))
    c.setFont("Helvetica-Bold", 6)
    c.drawRightString(57 * mm, 18 * mm, "Annahmestelle")

    # Zahlteil
    x0 = 67 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x0, top - 9 * mm, "Zahlteil")
    size = 46 * mm
    qx, qy = x0, top - 17 * mm - size
    w = QrCodeWidget(qr_payload(cfg, inv, amount, nummer), barLevel="M")
    bx = w.getBounds()
    d = Drawing(size, size, transform=[size / (bx[2] - bx[0]), 0, 0, size / (bx[3] - bx[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, qx, qy)
    cs = 7 * mm
    cx, cy = qx + size / 2 - cs / 2, qy + size / 2 - cs / 2
    c.setFillColor(white)
    c.rect(cx - 0.5 * mm, cy - 0.5 * mm, cs + 1 * mm, cs + 1 * mm, stroke=0, fill=1)
    c.setFillColor(black)
    c.rect(cx, cy, cs, cs, stroke=0, fill=1)
    c.setFillColor(white)
    c.rect(cx + cs * 0.42, cy + cs * 0.19, cs * 0.16, cs * 0.62, stroke=0, fill=1)
    c.rect(cx + cs * 0.19, cy + cs * 0.42, cs * 0.62, cs * 0.16, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x0, 37 * mm, "Währung")
    c.drawString(x0 + 16 * mm, 37 * mm, "Betrag")
    c.setFont("Helvetica", 10)
    c.drawString(x0, 32 * mm, "CHF")
    c.drawString(x0 + 16 * mm, 32 * mm, chf(amount))
    x1 = 118 * mm
    y = top - 5 * mm
    y = block(x1, y - 4 * mm, "Konto / Zahlbar an", cred, 8, 10, 11)
    y = block(x1, y, "Zusätzliche Informationen", [f"Stromabrechnung {nummer}"], 8, 10, 11)
    block(x1, y, "Zahlbar durch", debt, 8, 10, 11)


# --- Seite ------------------------------------------------------------------
def render(path, cfg, inv, nummer, rechnungsdatum, quartal_label):
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"Stromabrechnung {nummer}")
    b = cfg["betreiber"]
    L, R = 20 * mm, W - 20 * mm
    rows = inv["rows"]
    total = round(sum(r["total"] for r in rows), 2)
    wohnung = inv["art"] == "wohnung"

    # Briefkopf
    y = H - 20 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(L, y, b["name"])
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(L, y - 5 * mm, f"{b['strasse']} {b['hausnr']} · {b['plz']} {b['ort']}")
    c.drawString(L, y - 9 * mm, f"{b['bank']} · IBAN {iban_fmt(b['iban'])}")
    c.setStrokeColor(AMBER)
    c.setLineWidth(1.5)
    c.line(L, y - 13 * mm, R, y - 13 * mm)

    # Empfänger (Fensterposition rechts)
    ry = H - 52 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica", 10)
    if wohnung:
        p = inv["partei"]
        rec = [p["name"], "Wohnung 1. OG", f"{p['strasse']} {p['hausnr']}", f"{p['plz']} {p['ort']}"]
    else:
        rec = ["Nebenkostenabrechnung", f"Liegenschaft {b['strasse']} {b['hausnr']}", f"{b['plz']} {b['ort']}"]
    for i, ln in enumerate(rec):
        c.drawString(118 * mm, ry - i * 4.6 * mm, ln)

    # Meta links
    c.setFont("Helvetica", 8.5)
    meta = [("Rechnung", nummer), ("Datum", de(rechnungsdatum)), ("Zeitraum", f"{de(inv['von'])} – {de(inv['bis'])}")]
    for i, (k, v) in enumerate(meta):
        c.setFillColor(MUTED)
        c.drawString(L, ry - i * 4.6 * mm, k)
        c.setFillColor(INK)
        c.drawString(L + 20 * mm, ry - i * 4.6 * mm, v)

    # Titel
    ty = H - 82 * mm
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(INK)
    title = "Stromabrechnung vZEV" if wohnung else "Allgemeinstrom vZEV · Gesamtrechnung"
    c.drawString(L, ty, f"{title} · {quartal_label}" + (" (vorläufig)" if inv["vorlaeufig"] else ""))

    # Tabelle
    hy = ty - 9 * mm
    yy, total = tabelle(c, L, R, hy, rows)
    ny = yy - 8 * mm
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    notes = tarif_hinweise(cfg, inv["von"], inv["bis"]) + zusatz_hinweise(cfg, rows)
    if not wohnung:
        notes.append("Ohne Ladestation (separat erfasst); inkl. Standby-Netzbezug der PV-Anlage. Zur Übernahme in die Nebenkostenabrechnung.")
    for i, n in enumerate(notes):
        c.drawString(L, ny - i * 3.6 * mm, n)

    # Diagramme
    gy = ny - len(notes) * 3.6 * mm - 4 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(INK)
    c.drawString(L, gy, "Anteil Solarstrom (Autarkie) pro Monat")
    img = donuts_png(rows)
    by_fest = 113 * mm if wohnung else None
    ih = 39 * mm if by_fest is None else max(22 * mm, min(39 * mm, gy - by_fest - 17 * mm))  # nicht in den Betrag hinein
    iw = 36 * mm * len(rows) * ih / (39 * mm)
    c.drawImage(img, L, gy - ih - 1 * mm, iw, ih, mask="auto")
    lx = L + iw + 6 * mm
    for i, (col, lab) in enumerate([(AMBER, "Solarstrom"), (BLUE, "Netzstrom")]):
        c.setFillColor(col)
        c.rect(lx, gy - 8 * mm - i * 5 * mm, 3 * mm, 3 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8)
        c.drawString(lx + 5 * mm, gy - 7.5 * mm - i * 5 * mm, lab)

    # Betrag
    by = 113 * mm if wohnung else gy - ih - 16 * mm
    c.setFillColor(HexColor("#FDF3DF"))
    c.roundRect(L, by, R - L, 13 * mm, 2 * mm, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 8.5)
    frist = rechnungsdatum + timedelta(days=cfg["rechnungen"]["zahlungsfrist_tage"])
    c.drawString(L + 4 * mm, by + 5 * mm,
                 f"Zahlbar bis {de(frist)} mit dem Einzahlungsschein unten." if wohnung else "Betrag zur Übernahme in die Nebenkostenabrechnung.")
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(R - 4 * mm, by + 4.5 * mm, f"CHF {chf(total)}")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(R - 4 * mm - c.stringWidth(f"CHF {chf(total)}", "Helvetica-Bold", 14) - 3 * mm, by + 5 * mm,
                      "Gesamtbetrag")

    if wohnung:
        draw_qr_bill(c, cfg, inv, total, nummer)
    c.showPage()
    c.save()
    return total


def main(datadir, year, q, outdir, rdate=None, config=None):
    cfg, res, files, lade, ev = core.run(datadir, config)
    rechnungsdatum = date.fromisoformat(rdate) if rdate else date.today()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    label = f"Q{q} {year}"
    made = []
    for inv in invoices_for_quarter(res, cfg, year, q):
        nummer = cfg["rechnungen"]["nummer"].format(jahr=year, quartal=q, einheit=inv["einheit"])
        name = inv["partei"]["name"].split(" ")[-1] if inv["partei"] else "Allgemeinstrom"
        path = outdir / f"Rechnung_{nummer}_{name}.pdf"
        total = render(path, cfg, inv, nummer, rechnungsdatum, label)
        made.append((path.name, total, [(r["monat"], r["total"]) for r in inv["rows"]]))
    return made


if __name__ == "__main__":
    a = sys.argv
    for name, total, rows in main(a[1], int(a[2]), int(a[3]), a[4], a[5] if len(a) > 5 else None):
        print(f"{name}: CHF {total:.2f}  {rows}")
