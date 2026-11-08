# vZEV Abrechnung

Abrechnung eines virtuellen Zusammenschlusses zum Eigenverbrauch (vZEV) direkt in Home Assistant:
Primeo-Lastgänge einlesen, Solar- und Netzstrom pro Viertelstunde aufteilen, Quartalsrechnungen mit
QR-Einzahlungsschein erstellen, Zahlungen verfolgen und Monate revisionssicher abschliessen.

## Erste Schritte

1. **Einstellungen → Betreiber und Rechnungen:** Name, Adresse, Bank und IBAN (erscheinen auf den Rechnungen und im QR-Einzahlungsschein), vZEV-Start, Zahlungsfrist.
2. **Einstellungen → Zähler:** die fünf Primeo-Messpunkte (1. OG, 2. OG, Allgemein, Netzbezug PV-Anlage, Produktion) und die Energie-Sensoren in Home Assistant.
3. **Tarife:** Solarpreis, Netzstrom HT/NT, Rücklieferung und Grundpreis, jeweils mit «Gültig ab».
4. **Mieter:** Mietverhältnisse mit Von/Bis.
5. **Daten importieren:** Lastgänge aller Zähler aus dem Primeo-Kundenportal (.xlsx) und den Wallbox-Export (.csv) hochladen.

## Seiten

**Auswertung**
- **Übersicht:** Monat wählen; Produktion, Autarkie, Rücklieferung, Wertschöpfung; Diagramm «Energiefluss pro Monat»; Kontrollen (Abgleich mit Primeo, Ladestation, Lücken, Rückliefertarif, Abschluss, offene Rechnungen); Verbraucher des Monats mit Betrag inkl. Grundpreis.
- **Verlauf:** pro Zähler Verbrauch, Solar/Netz und Kosten pro Monat, beim 1. OG nach Mietverhältnis gruppiert.

**Abrechnung**
- **Daten importieren:** Dateien hochladen, ersetzen oder entfernen. Die Zuordnung erfolgt über die Messpunkt-Nummer im Dateikopf, nicht über den Dateinamen. Oben steht, bis wann die Lastgänge reichen.
- **Rechnungen:** Quartal und Rechnungsdatum wählen und erstellen – pro Mietverhältnis eine Rechnung mit QR-Einzahlungsschein, dazu eine Gesamtrechnung Allgemeinstrom für die Nebenkostenabrechnung. Darunter **Rechnungen und Zahlungen**: offene und überfällige Beträge, Zahlungen erfassen oder entfernen, Rechnungsdatum und Fälligkeit ändern.
- **Abschluss:** Monate der Reihe nach abschliessen (mit Abschlussdatum). Danach sind Änderungen an Tarifen, Mietern und Erträgen für diesen Monat gesperrt.

**Stammdaten**
- **Mieter, Tarife:** Mietverhältnisse mit Historie, Tarife mit Gültig-ab-Datum.
- **Primeo:** **Dynamische Strompreise** (Verlauf heute/morgen, Schnittstelle einstellen), Primeo-Rechnungen für den Abgleich, manuelle Erträge.
- **Einstellungen:** Betreiber, Zähler, Regeln (Aufteilung sowie Batterie und dynamischer Tarif) und die Datei `vzev.yaml` direkt.

**Anlage**
- **Batterie:** Monatswerte des Speichers (geladen, entladen, Wirkungsgrad) aus den Solis-Daten.
- **Datensammler:** Zählerstände aus Home Assistant (alle 15 Minuten) mit letztem Wert und Status, evcc-Ladevorgänge im Detail.
- **Protokoll:** Uploads, Rechnungen, Zahlungen, Korrekturen, Warnungen und Fehler.

Oben neben der Version zeigt eine **Statusanzeige**, was im Hintergrund läuft (Berechnung, Abruf von Zählerständen, evcc oder Strompreisen). Seiten, die auf eine Berechnung warten, laden von selbst neu.

## Monatlicher Ablauf

1. Lastgänge bei Primeo und Ladevorgänge der Wallbox exportieren und unter **Daten importieren** hochladen.
2. In der **Übersicht** die Kontrollen prüfen. Bei «prüfen» die betroffene Datei ansehen und neu hochladen.
3. Die Primeo-Rechnung unter **Primeo** erfassen (Netzbezug HT/NT, Rücklieferung) – damit läuft der Abgleich.
4. Unter **Tarife** den Rückliefertarif des Quartals eintragen, sobald Primeo ihn publiziert.
5. Unter **Abschluss** den Monat abschliessen.
6. Am Quartalsende unter **Rechnungen** die Rechnungen erstellen und versenden; eingehende Zahlungen dort erfassen.

## Korrekturen

- Änderungen an Tarifen, Mietern oder Erträgen, die einen abgeschlossenen Monat betreffen, lehnt die App ab. Zuerst den Monat unter **Abschluss** mit Begründung wieder öffnen (rückwärts, der Reihe nach).
- Ändern sich abgeschlossene Monate durch eine ersetzte Datei oder eine geänderte Regel, warnen Übersicht und Abschluss. Mit **Neue Werte übernehmen** und Begründung wird der Monat neu festgehalten.
- Rechnungen eines Quartals mit abgeschlossenen Monaten lassen sich nur mit Begründung neu erstellen. Die alten PDFs bleiben unter `rechnungen/_alt`, bereits erfasste Zahlungen gehen auf die neue Rechnung über.
- Alle Korrekturen stehen unter **Abschluss → Korrekturen und Abschlüsse** und im **Protokoll**.

## Vorschau aus Home Assistant

Für die Zeit nach dem letzten Primeo-Lastgang rechnet die App mit den gesammelten Zählerständen (whatwatt, go-e, Solis). Diese Monate sind als «vorläufig» markiert; für die Rechnungen zählen ausschliesslich die Primeo-Lastgänge. Wo beides vorliegt, zeigt die Übersicht den Vergleich.

## Dynamische Strompreise

Die App holt die Viertelstundenpreise über die Primeo-Schnittstelle (Standard: `https://tarife.primeo-energie.ch/api/v1/tariffs`), stündlich und zwischen 18 und 21 Uhr alle 15 Minuten. Adresse, Tarifname, Tariftyp und Startdatum lassen sich unter **Primeo → Dynamische Strompreise → Schnittstelle einstellen** ändern. Die Preise enthalten keine kantonalen/kommunalen Abgaben und keine MWST. Für die Abrechnung werden sie noch nicht verwendet.

## Daten und Sicherung

Alles liegt im Konfigurationsordner der App (`/addon_configs/…_vzev/`) und ist damit im Home-Assistant-Backup enthalten:

| Datei / Ordner | Inhalt |
|---|---|
| `vzev.yaml` | Betreiber, Messpunkte, Tarife, Mieter, Regeln, Sensoren, Preis-Schnittstelle; vorherige Fassung als `vzev.yaml.bak` |
| `primeo/` | importierte Lastgänge und Wallbox-Export; ersetzte Dateien unter `primeo/_entfernt/` |
| `rechnungen/` | PDFs, `register.json` (Rechnungen und Zahlungen), alte Fassungen unter `_alt/` |
| `abschluss.json` | abgeschlossene Monate mit festgehaltenen Werten, Korrekturen |
| `messwerte.sqlite` | Zählerstände, evcc-Ladevorgänge, dynamische Strompreise |
| `vzev.log` | Protokoll |

## Optionen

- `evcc_passwort`: nur nötig, wenn evcc für die Ladevorgänge eine Anmeldung verlangt.

## Netzwerk

Die App verbindet sich nur mit Home Assistant, evcc (im lokalen Netz) und der eingestellten Preis-Schnittstelle von Primeo.
