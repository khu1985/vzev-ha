"""Einfache SVG-Diagramme ohne externe Bibliotheken (die App läuft offline im Home Assistant).

Farben geprüft (Helligkeit, Farbsättigung, Farbsehschwäche): Rücklieferung #2E8B57, Solar #D4900A, Netz #2F6DB5.
Die Werte stehen zusätzlich in den Tabellen und im Tooltip.
"""
from html import escape

FARBEN = {"solar": "#D4900A", "rueck": "#2E8B57", "netz": "#2F6DB5"}


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
