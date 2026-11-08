# vZEV Abrechnung

Abrechnung eines vZEV direkt in Home Assistant.

## Was die App macht

- **Daten importieren:** Primeo-Lastgänge (.xlsx) und Wallbox-Export (.csv) hochladen, ersetzen oder entfernen. Die Zuordnung erfolgt über die Messpunkt-Nummer.
- **Übersicht und Verlauf:** Kennzahlen und Diagramme pro Monat und Zähler; Vorschau des laufenden Monats aus den Home-Assistant-Zählerständen.
- **Berechnung:** 15-Minuten-Aufteilung von Solar- und Netzstrom pro Zähler, Ladestation herausgerechnet, Abgleich mit den Primeo-Rechnungen, Wertschöpfung für den Betreiber.
- **Zahlungseingang:** Zahlungen pro Rechnung erfassen, offene und überfällige Beträge auf einen Blick.
- **Rechnungen:** Quartalsrechnungen als PDF – Wohnung mit QR-Einzahlungsschein, Allgemeinstrom als Gesamtrechnung für die Nebenkostenabrechnung.
- **Datensammler:** speichert alle 15 Minuten die Zählerstände von whatwatt, go-e, Solis und Kia sowie die evcc-Ladevorgänge.
- **Protokoll:** Uploads, Rechnungen, Warnungen und Fehler direkt in der App; zusätzlich als `vzev.log` im Konfigurationsordner.
- **Abschluss:** Monate abschliessen und sperren; Korrekturen nur mit Begründung, alles nachvollziehbar.
- **Mieter, Tarife, Primeo:** Mietverhältnisse mit Historie, Tarife mit Gültig-ab-Datum, Primeo-Rechnungen und manuelle Erträge in Formularen.
- **Batterie:** Monatswerte des Speichers aus den Solis-Daten und Regeln für die Netzladung ab dem dynamischen Tarif.
- **Einstellungen:** Betreiber, Zähler und Regeln in Formularen; alles liegt in der Datei `vzev.yaml`, die sich auch direkt bearbeiten lässt.

## Daten

Alles liegt im App-Konfigurationsordner (`/addon_configs/…_vzev/`) und ist damit im Home-Assistant-Backup enthalten:
`vzev.yaml`, `primeo/`, `rechnungen/`, `abschluss.json`, `messwerte.sqlite`, `vzev.log`.

## Optionen

- `evcc_passwort`: nur nötig, wenn evcc für die Ladevorgänge eine Anmeldung verlangt.
