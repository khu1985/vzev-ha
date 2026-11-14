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
