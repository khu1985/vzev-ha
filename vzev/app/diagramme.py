"""Einfache SVG-Diagramme ohne externe Bibliotheken (die App läuft offline im Home Assistant).

Farben geprüft (Helligkeit, Farbsättigung, Farbsehschwäche): Rücklieferung #2E8B57, Solar #D4900A, Netz #2F6DB5.
Die Werte stehen zusätzlich in den Tabellen und im Tooltip.
"""
from html import escape

FARBEN = {"solar": "#D4900A", "rueck": "#2E8B57", "netz": "#2F6DB5", "uebrige": "#A0446E"}


def _ticks(maximum):
    if maximum <= 0:
        return [0, 1]
    roh = maximum / 4
    mag = 10 ** (len(str(int(roh))) - 1)
    schritt = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= roh)
    n = int(maximum // schritt) + 1
    return [round(i * schritt, 6) for i in range(n + 1)]


def _zahl(x, nachkomma=0):
    t = f"{x:,.{nachkomma}f}".replace(",", "'")
    return t


def saeulen(labels, reihen, einheit="kWh", vorlaeufig=(), hoehe=260, aktiv=None, links=None, summe=None):
    """Gestapelte Säulen. reihen = [(name, farbe, werte)], vorlaeufig = Indizes, die heller und mit * erscheinen."""
    n = len(labels)
    if not n:
        return '<p class="muted">Noch keine Daten.</p>'
    summen = [sum(max(0, (r[2][i] or 0)) for r in reihen) for i in range(n)]
    ticks = _ticks(max(summen) * 1.05)
    top = ticks[-1]
    links_rand, unten, oben = 52, 26, 10
    breite = max(1000, n * 56 + links_rand)
    band = (breite - links_rand) / n
    saeule = min(28, band * 0.6)
    ph = hoehe - unten - oben
    y = lambda v: oben + ph - v / top * ph
    teile = [f'<svg class="chart" viewBox="0 0 {breite} {hoehe}" role="img" aria-label="Diagramm" style="width:100%;min-width:{min(breite, 560)}px;height:auto">']
    for t in ticks:
        teile.append(f'<line x1="{links_rand}" x2="{breite}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>'
                     f'<text x="{links_rand - 8}" y="{y(t) + 4:.1f}" text-anchor="end" class="ax">{_zahl(t)}</text>')
    for i, lab in enumerate(labels):
        x = links_rand + band * i + (band - saeule) / 2
        basis = 0.0
        tip = [f"{lab}{' (vorläufig)' if i in vorlaeufig else ''}"]
        sichtbar = [(name, farbe, w[i] or 0) for name, farbe, w in reihen if (w[i] or 0) > 0]
        for j, (name, farbe, v) in enumerate(sichtbar):
            y0, y1 = y(basis), y(basis + v)
            h = max(0.0, y0 - y1 - (2 if j < len(sichtbar) - 1 else 0))
            r = 4 if j == len(sichtbar) - 1 else 0
            op = ' opacity="0.55"' if i in vorlaeufig else ""
            if r and h > r:
                d = (f"M{x:.1f},{y0:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + saeule - r:.1f} "
                     f"Q{x + saeule:.1f},{y1:.1f} {x + saeule:.1f},{y1 + r:.1f} V{y0:.1f} Z")
                teile.append(f'<path d="{d}" fill="{farbe}"{op}/>')
            else:
                teile.append(f'<rect x="{x:.1f}" y="{y0 - h:.1f}" width="{saeule:.1f}" height="{h:.1f}" fill="{farbe}"{op}/>')
            basis += v
        if summe:  # z. B. «Verbrauch gesamt»
            tip.append(f"{summe}: {_zahl(sum((w[i] or 0) for _, _, w in reihen), 1)} {einheit}")
        for name, _, w in reihen:
            tip.append(f"{name}: {_zahl(w[i] or 0, 1)} {einheit}")
        cls = "hit on" if aktiv == i else "hit"
        hit = (f'<rect class="{cls}" x="{links_rand + band * i:.1f}" y="{oben}" width="{band:.1f}" height="{ph:.1f}" '
               f'data-tip="{escape(chr(10).join(tip))}"/>')
        teile.append(f'<a href="{escape(links[i])}">{hit}</a>' if links else hit)
        teile.append(f'<text x="{links_rand + band * i + band / 2:.1f}" y="{hoehe - 8}" text-anchor="middle" class="ax{" b" if aktiv == i else ""}">'
                     f'{escape(lab)}{"*" if i in vorlaeufig else ""}</text>')
    teile.append("</svg>")
    legende = "".join(f'<span class="lg"><i style="background:{f}"></i>{escape(nm)}</span>' for nm, f, _ in reihen)
    return f'<div class="legende">{legende}</div><div class="scroll">{"".join(teile)}</div>'


STIL = """<style>
.chart .grid{stroke:#E6E8E4;stroke-width:1}.chart .ax{font-size:11px;fill:#5B6660}.chart .ax.b{font-weight:700;fill:#16201C}
.chart .hit{fill:transparent;cursor:pointer}.chart .hit:hover,.chart .hit.on{fill:rgba(22,32,28,.05)}
.legende{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 8px;font-size:12px;color:#3F4A44}.lg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
#tip{position:fixed;pointer-events:none;background:#16201C;color:#fff;font-size:12px;line-height:1.5;padding:8px 10px;border-radius:8px;white-space:pre;display:none;z-index:10}
</style><div id="tip"></div><script>
document.addEventListener('mousemove',function(e){var t=document.getElementById('tip');if(!t)return;var d=e.target.getAttribute&&e.target.getAttribute('data-tip');
if(d){t.textContent=d;t.style.display='block';var x=e.clientX+14,y=e.clientY+14;if(x+t.offsetWidth>innerWidth-8)x=e.clientX-t.offsetWidth-14;t.style.left=x+'px';t.style.top=y+'px'}else t.style.display='none'});
</script>"""


def tagesverlauf(reihen, einheit="Rp./kWh", hoehe=240):
    """Treppenlinien über einen Tag. reihen = [(name, farbe, [(minute_seit_mitternacht, wert), …])]."""
    werte = [w for _, _, pkt in reihen for _, w in pkt]
    if not werte:
        return '<p class="muted">Noch keine Preise.</p>'
    lo, hi = min(0, min(werte)), max(werte) * 1.08 or 1
    ticks = _ticks(hi)
    hi = ticks[-1]
    links, rechts, unten, oben, breite = 52, 12, 26, 10, 1000
    pw, ph = breite - links - rechts, hoehe - unten - oben
    x = lambda m: links + m / 1440 * pw
    y = lambda v: oben + ph - (v - lo) / (hi - lo) * ph
    t = [f'<svg class="chart" viewBox="0 0 {breite} {hoehe}" role="img" aria-label="Preisverlauf" style="width:100%;min-width:560px;height:auto">']
    for v in ticks:
        t.append(f'<line x1="{links}" x2="{breite - rechts}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{links - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="ax">{_zahl(v, 0 if hi >= 10 else 1)}</text>')
    for h in range(0, 25, 3):
        t.append(f'<text x="{x(h * 60):.1f}" y="{hoehe - 8}" text-anchor="middle" class="ax">{h:02d}</text>')
    for name, farbe, pkt in reihen:
        if not pkt:
            continue
        d = ""
        for i, (m, v) in enumerate(pkt):
            m2 = pkt[i + 1][0] if i + 1 < len(pkt) else m + 15
            d += (f"M{x(m):.1f},{y(v):.1f}" if i == 0 else f" V{y(v):.1f}") + f" H{x(m2):.1f}"
        t.append(f'<path d="{d}" fill="none" stroke="{farbe}" stroke-width="2" stroke-linejoin="round"/>')
        for i, (m, v) in enumerate(pkt):
            m2 = pkt[i + 1][0] if i + 1 < len(pkt) else m + 15
            t.append(f'<rect class="hit" x="{x(m):.1f}" y="{oben}" width="{max(1, x(m2) - x(m)):.1f}" height="{ph}" '
                     f'data-tip="{escape(name)} {m // 60:02d}:{m % 60:02d}&#10;{_zahl(v, 2)} {einheit}"/>')
    t.append("</svg>")
    legende = "".join(f'<span class="lg"><i style="background:{f}"></i>{escape(n)}</span>' for n, f, p in reihen if p)
    return f'<div class="legende">{legende}</div><div class="scroll">{"".join(t)}</div>'


def linie(labels, werte, name, farbe, einheit="CHF", hoehe=220, vorlaeufig=()):
    """Einfache Linie mit Punkten über Kategorien (z. B. Monate), mit Tooltip pro Punkt."""
    n = len(labels)
    if not n:
        return '<p class="muted">Noch keine Daten.</p>'
    hi = max(max(werte), 0) * 1.08 or 1
    ticks = _ticks(hi)
    hi = ticks[-1]
    links, unten, oben = 64, 26, 12
    breite = max(1000, n * 56 + links)
    band = (breite - links) / n
    ph = hoehe - unten - oben
    x = lambda i: links + band * i + band / 2
    y = lambda v: oben + ph - v / hi * ph
    t = [f'<svg class="chart" viewBox="0 0 {breite} {hoehe}" role="img" aria-label="{escape(name)}" style="width:100%;min-width:{min(breite, 560)}px;height:auto">']
    for v in ticks:
        t.append(f'<line x1="{links}" x2="{breite}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{links - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="ax">{_zahl(v)}</text>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(werte))
    t.append(f'<polyline points="{pts}" fill="none" stroke="{farbe}" stroke-width="2" stroke-linejoin="round"/>')
    for i, (lab, v) in enumerate(zip(labels, werte)):
        t.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="{farbe}" stroke="#fff" stroke-width="2"{" opacity=\"0.55\"" if i in vorlaeufig else ""}/>')
        t.append(f'<rect class="hit" x="{links + band * i:.1f}" y="{oben}" width="{band:.1f}" height="{ph}" data-tip="{escape(lab)}&#10;{escape(name)}: {_zahl(v, 2)} {einheit}"/>')
        t.append(f'<text x="{x(i):.1f}" y="{hoehe - 8}" text-anchor="middle" class="ax">{escape(lab)}{"*" if i in vorlaeufig else ""}</text>')
    t.append(f'<text x="{x(n - 1):.1f}" y="{y(werte[-1]) - 10:.1f}" text-anchor="end" class="ax b">{_zahl(werte[-1])} {einheit}</text>')
    t.append("</svg>")
    return f'<div class="scroll">{"".join(t)}</div>'


def balken_h(zeilen, einheit):
    """Horizontale Balken mit Beschriftung: zeilen = [(label, wert, farbe, notiz)]."""
    hi = max((w for _, w, _, _ in zeilen if w), default=1) or 1
    out = ['<div class="hbalken">']
    for label, w, farbe, notiz in zeilen:
        breite = 0 if not w else max(2, w / hi * 100)
        out.append(f'<div class="hb"><div class="hb-l">{escape(label)}</div><div class="hb-s"><i style="width:{breite:.1f}%;background:{farbe}"></i></div>'
                   f'<div class="hb-w">{"–" if w is None else _zahl(w, 3 if w < 1 else 2)} {einheit}</div><div class="hb-n muted">{escape(notiz)}</div></div>')
    out.append('</div><style>.hbalken{display:grid;gap:10px}.hb{display:grid;grid-template-columns:150px 1fr 120px;gap:4px 12px;align-items:center}'
               '.hb-s{background:#F1F3EF;border-radius:6px;height:14px;overflow:hidden}.hb-s i{display:block;height:100%;border-radius:6px}'
               '.hb-w{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}.hb-n{grid-column:2 / 4}'
               '@media (max-width:759px){.hb{grid-template-columns:1fr auto}.hb-s{grid-column:1 / 3;grid-row:2}.hb-n{grid-column:1 / 3}}</style>')
    return "".join(out)
