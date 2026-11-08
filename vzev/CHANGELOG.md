# Changelog

## 0.1.1

- Hochladen: Dateien werden einzeln hochgeladen, mit Status pro Datei.
- Hochladen: Die Zuordnung liest nur noch den Dateikopf (Messpunkt), das ist auf dem Raspberry Pi deutlich schneller.
- Hochladen: Leere oder unlesbare Dateien brechen den Import nicht mehr ab; der Fehler erscheint in der App und im Log.
- Winterzeit: Doppelte Viertelstunden bei der Zeitumstellung (z. B. 25.10. 02:00–02:45) werden zusammengezählt.

## 0.1.0

- Erste Version: Daten importieren, Übersicht mit 15-Minuten-Aufteilung, Abgleich mit den Primeo-Rechnungen, Wertschöpfung, Quartalsrechnungen mit QR-Einzahlungsschein, Datensammler für Home Assistant und evcc.
