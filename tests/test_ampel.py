"""Ampeln: schlechteste pro Seite, Navigation mit Gruppen."""
import ampel


def test_schlechteste_und_pro_seite():
    a = [ampel.Ampel("A", ampel.GRUEN, "", "rechnungen"), ampel.Ampel("B", ampel.GELB, "", "rechnungen"),
         ampel.Ampel("C", ampel.GRAU, "", "sammler"), ampel.Ampel("D", ampel.ROT, "", "aufgaben", "aufgaben?m=2026-10")]
    assert ampel.schlechteste([ampel.GRUEN, ampel.ROT, ampel.GELB]) == ampel.ROT
    assert ampel.schlechteste([]) == ampel.GRAU
    assert ampel.pro_seite(a) == {"rechnungen": ampel.GELB, "sammler": ampel.GRAU, "aufgaben": ampel.ROT}
    assert a[3].ziel == "aufgaben?m=2026-10" and a[0].ziel == "rechnungen"
    assert ampel.alter_status(10, 45, 75) == ampel.GRUEN and ampel.alter_status(60, 45, 75) == ampel.GELB
    html = ampel.karte(a)
    assert html.index("ampel-kachel rot") < html.index("ampel-kachel gelb") and "1 handeln" in html


def test_karte_gruene_aufklappbar():
    """Was zu tun ist, steht oben; was in Ordnung ist, aufklappbar (Handy: Energiefluss im ersten Bildschirm)."""
    import ampel as A
    amp = [A.Ampel("Kontrollen", A.GRUEN, "alle stimmen", "uebersicht"), A.Ampel("Zahlungen", A.GELB, "offen", "rechnungen"),
           A.Ampel("Tarife", A.GRUEN, "ok", "tarife"), A.Ampel("Prognose", A.GRAU, "nicht eingerichtet", "prognose")]
    h = A.karte(amp)
    oben, rest = h.split("<details", 1)
    assert "Zahlungen" in oben and "Kontrollen" not in oben
    assert "2 in Ordnung, 1 ohne Daten" in rest and "Kontrollen" in rest and " open" not in rest.split(">")[0]
    alles_gut = A.karte([a for a in amp if a.status != A.GELB])
    assert alles_gut.startswith('<details class="ampel-rest" open>')


def test_monate_text():
    import jahr
    assert jahr.monate_text(["2026-03", "2026-04", "2026-05", "2026-07"]) == "März bis Mai, Juli 2026"
    assert jahr.monate_text(["2026-12", "2027-01"]) == "Dezember 2026 bis Januar 2027"
    assert jahr.monate_text([]) == ""
