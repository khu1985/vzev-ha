# Changelog

## 0.1.4

- Datensammler: Ladevorgänge aus evcc im Detail – Start, Ende, Dauer, Ladepunkt, Fahrzeug, kWh, Solaranteil, Kosten, Preis pro kWh und km-Stand, filterbar nach Monat.
- Monatsübersicht der Ladevorgänge mit Vergleich zur Ladestation laut Abrechnung (Primeo-Lastgänge und Wallbox-Export).

## 0.1.3

- Datensammler: Die Tabelle zeigt jetzt den letzten Zählerstand mit Einheit, den Zeitpunkt, den Namen aus Home Assistant, den Zweck (z. B. «zaehler · 1og») und ob der Sensor Werte liefert oder «unavailable» ist. Zähler stehen zuoberst, dann Solis und Kia.

## 0.1.2

- Neue Seite «Protokoll»: zeigt Uploads, erstellte Rechnungen, Warnungen und Fehler direkt in der App, filterbar nach Art. Fehler seit dem Start erscheinen als Zahl in der Menüleiste.
- Datensammler und evcc schreiben Probleme ins Protokoll (nur bei Änderungen, nicht alle 15 Minuten).
- Unerwartete Fehler zeigen eine Fehlerseite mit Verweis aufs Protokoll statt einer leeren Seite.
- «Daten importieren» lädt auch nach einem Neustart sofort: Dateiinfos werden dauerhaft zwischengespeichert, der Zeitraum wird ohne vollständiges Einlesen ermittelt.

## 0.1.1

- Hochladen: Dateien werden einzeln hochgeladen, mit Status pro Datei.
- Hochladen: Die Zuordnung liest nur noch den Dateikopf (Messpunkt), das ist auf dem Raspberry Pi deutlich schneller.
- Hochladen: Leere oder unlesbare Dateien brechen den Import nicht mehr ab; der Fehler erscheint in der App und im Log.
- Winterzeit: Doppelte Viertelstunden bei der Zeitumstellung (z. B. 25.10. 02:00–02:45) werden zusammengezählt.

## 0.1.0

- Erste Version: Daten importieren, Übersicht mit 15-Minuten-Aufteilung, Abgleich mit den Primeo-Rechnungen, Wertschöpfung, Quartalsrechnungen mit QR-Einzahlungsschein, Datensammler für Home Assistant und evcc.
