# vZEV Abrechnung

Abrechnung eines vZEV direkt in Home Assistant.

## Was die App macht

- **Daten importieren:** Primeo-Lastgänge (.xlsx) und Wallbox-Export (.csv) hochladen, ersetzen oder entfernen. Die Zuordnung erfolgt über die Messpunkt-Nummer.
- **Übersicht:** 15-Minuten-Aufteilung von Solar- und Netzstrom pro Zähler, Ladestation herausgerechnet, Abgleich mit den Primeo-Rechnungen, Wertschöpfung für den Betreiber.
- **Rechnungen:** Quartalsrechnungen als PDF – Wohnung mit QR-Einzahlungsschein, Allgemeinstrom als Gesamtrechnung für die Nebenkostenabrechnung.
- **Datensammler:** speichert alle 15 Minuten die Zählerstände von whatwatt, go-e, Solis und Kia sowie die evcc-Ladevorgänge.
- **Einstellungen:** Tarife, Mietverhältnisse und Regeln in der Datei `vzev.yaml`.

## Daten

Alles liegt im App-Konfigurationsordner (`/addon_configs/…_vzev/`) und ist damit im Home-Assistant-Backup enthalten:
`vzev.yaml`, `primeo/`, `rechnungen/`, `messwerte.sqlite`.

## Optionen

- `evcc_passwort`: nur nötig, wenn evcc für die Ladevorgänge eine Anmeldung verlangt.
