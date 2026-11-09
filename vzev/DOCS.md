# vZEV Abrechnung

Abrechnung eines virtuellen Zusammenschlusses zum Eigenverbrauch (vZEV) direkt in Home Assistant:
Primeo-Lastgänge einlesen, Solar- und Netzstrom pro Viertelstunde aufteilen, Quartalsrechnungen mit
QR-Einzahlungsschein erstellen, Zahlungen verfolgen, Monate revisionssicher abschliessen und am Jahresende
den Allgemeinstrom für die Nebenkostenabrechnung ausgeben. Ab 2027 mit Bonus aus dem dynamischen Tarif
und getrennt ausgewiesenem Netzstrom aus dem Batteriespeicher.

## Erste Schritte

1. **Einstellungen → Betreiber und Rechnungen:** Name, Adresse, Bank und IBAN (erscheinen auf den Rechnungen und im QR-Einzahlungsschein), vZEV-Start, Zahlungsfrist.
2. **Einstellungen → Zähler:** die fünf Primeo-Messpunkte (1. OG, 2. OG, Allgemein, Netzbezug PV-Anlage, Produktion), die Energie-Sensoren in Home Assistant und – falls vorhanden – die Wärmepumpen am Allgemeinzähler.
3. **Tarife:** Solarpreis, Netzstrom HT/NT, Rücklieferung und Grundpreis, jeweils mit «Gültig ab». Neue Preise (z. B. ab 01.01.2027) als neue Zeile eintragen, die alten bleiben für frühere Monate gültig.
4. **Mieter:** Mietverhältnisse mit Von/Bis.
5. **Daten importieren:** Lastgänge aller Zähler aus dem Primeo-Kundenportal (.xlsx) und den Wallbox-Export (.csv) hochladen.

## Seiten

**Auswertung**
- **Energiefluss** (Startseite): animiertes Diagramm von PV-Anlage, Netz und Speicher zum Haus und zu den Verbrauchern, für heute, gestern, einen Monat oder ein Jahr. Die Ringe zeigen den Anteil Solar-, Speicher- und Netzstrom; Werte erscheinen per Maus oder Tippen. Speicherwerte stammen vom Wechselrichter, alles andere aus derselben Rechnung wie die Abrechnung.
- **Übersicht:** Jahr wählen; Produktion, Autarkie, Rücklieferung und Wertschöpfung des Jahres; Diagramm «Energiefluss pro Monat» – ein Klick auf einen Monat zeigt darunter dessen Kennzahlen, Kontrollen (Abgleich mit Primeo, Ladestation, Lücken, Rückliefertarif, 80-%-Grenze Solarpreis, dynamische Preise, Wärmepumpen, Netzladung gegen Wechselrichter, Abschluss, offene Rechnungen) und Verbraucher mit Betrag inkl. Grundpreis.
- **Wertschöpfung:** Ertrag des Betreibers pro Monat nach Quelle (Verkauf an Mieter, Eigenverbrauch, Rücklieferung, Gutschriften), kumuliert, Verwendung des Solarstroms und Wert pro kWh; filterbar nach Jahr.
- **Verlauf:** pro Zähler Verbrauch, Solar/Netz und Kosten pro Monat, beim 1. OG nach Mietverhältnis gruppiert.

**Abrechnung**
- **Daten importieren:** Dateien hochladen, ersetzen oder entfernen. Die Zuordnung erfolgt über die Messpunkt-Nummer im Dateikopf, nicht über den Dateinamen. Oben steht, bis wann die Lastgänge reichen.
- **Jahresabrechnung:** Allgemeinstrom fürs ganze Jahr als PDF für die Nebenkostenabrechnung, Mieter, Wertschöpfung, Excel-Export (auf Wunsch mit allen Viertelstunden).
- **Rechnungen:** Quartal und Rechnungsdatum wählen und erstellen – pro Mietverhältnis eine Rechnung mit QR-Einzahlungsschein, dazu eine Gesamtrechnung Allgemeinstrom für die Nebenkostenabrechnung. Ab 2027 zusätzlich die Spalte «Speicher NT» und die Zeile «Bonus dynamischer Stromtarif», sobald sie vorkommen. Darunter **Rechnungen und Zahlungen**: offene und überfällige Beträge, Zahlungen erfassen oder entfernen, Rechnungsdatum und Fälligkeit ändern.
- **Abschluss:** Monate der Reihe nach abschliessen (mit Abschlussdatum). Danach sind Änderungen an Tarifen, Mietern und Erträgen für diesen Monat gesperrt.

**Stammdaten**
- **Mieter:** Mietverhältnisse mit Historie.
- **Tarife:** Tarife mit Gültig-ab-Datum und **Dynamische Strompreise** (Verlauf heute/morgen, Schnittstelle einstellen).
- **Primeo:** Primeo-Rechnungen für den Abgleich, manuelle Erträge.
- **Einstellungen:** Betreiber, Zähler, Regeln (Aufteilung sowie Speicher und Bonus dynamischer Tarif) und die Datei `vzev.yaml` direkt.

**Anlage**
- **Prognose:** PV-Prognose aus der Solcast-Integration (heute, morgen, folgende Tage) mit Bandbreite, gemessenem Ertrag, üblichem Verbrauch und dynamischem Strompreis; Zeitfenster «günstig aus dem Netz laden»; Trefferquote der Prognose vom Vortag.
- **Batterie:** Monatswerte des Speichers (geladen, entladen, Wirkungsgrad) aus den Solis-Daten. Für die Abrechnung zählt die Netzladung aus den Primeo-Lastgängen (siehe «Dynamische Strompreise»).
- **Datensammler:** Zählerstände aus Home Assistant (alle 15 Minuten) mit letztem Wert und Status, evcc-Ladevorgänge im Detail.
- **Protokoll:** Uploads, Rechnungen, Zahlungen, Korrekturen, Warnungen und Fehler.

Ein Klick auf die **Versionsnummer** zeigt, was neu ist. Der Knopf daneben stellt die Darstellung um: **Auto** (wie das Gerät), **Hell** oder **Dunkel**. Daneben zeigt eine **Statusanzeige**, was im Hintergrund läuft (Berechnung, Abruf von Zählerständen, evcc oder Strompreisen). Seiten, die auf eine Berechnung warten, laden von selbst neu.

## Monatlicher Ablauf

Am einfachsten über **Abrechnung → Aufgaben**: Der Assistent zeigt für jeden offenen Monat die Schritte unten, erkennt erledigte selbst und öffnet mit «→» die passende Seite («Zurück zu den Aufgaben» unten links führt zurück). Die Startseite zeigt die nächste Aufgabe.

1. Lastgänge bei Primeo und Ladevorgänge der Wallbox exportieren und unter **Daten importieren** hochladen.
2. In der **Übersicht** die Kontrollen prüfen. Bei «prüfen» die betroffene Datei ansehen und neu hochladen.
3. Die Primeo-Rechnung unter **Primeo** erfassen (Netzbezug HT/NT, Rücklieferung) – damit läuft der Abgleich.
4. Unter **Tarife** den Rückliefertarif des Quartals eintragen, sobald Primeo ihn publiziert.
5. Unter **Abschluss** den Monat abschliessen.
6. Am Quartalsende unter **Rechnungen** die Rechnungen erstellen und versenden; eingehende Zahlungen dort erfassen.
7. Am Jahresende unter **Jahresabrechnung** das PDF Allgemeinstrom für die Nebenkostenabrechnung erstellen und bei Bedarf den Excel-Export herunterladen.

## Korrekturen

- Änderungen an Tarifen, Mietern oder Erträgen, die einen abgeschlossenen Monat betreffen, lehnt die App ab. Zuerst den Monat unter **Abschluss** mit Begründung wieder öffnen (rückwärts, der Reihe nach).
- Ändern sich abgeschlossene Monate durch eine ersetzte Datei oder eine geänderte Regel, warnen Übersicht und Abschluss. Mit **Neue Werte übernehmen** und Begründung wird der Monat neu festgehalten.
- Rechnungen eines Quartals mit abgeschlossenen Monaten lassen sich nur mit Begründung neu erstellen. Die alten PDFs bleiben unter `rechnungen/_alt`, bereits erfasste Zahlungen gehen auf die neue Rechnung über.
- Alle Korrekturen stehen unter **Abschluss → Korrekturen und Abschlüsse** und im **Protokoll**.

## Vorschau aus Home Assistant

Für die Zeit nach dem letzten Primeo-Lastgang rechnet die App mit den gesammelten Zählerständen (whatwatt, go-e, Solis). Diese Monate sind als «vorläufig» markiert; für die Rechnungen zählen ausschliesslich die Primeo-Lastgänge. Wo beides vorliegt, zeigt die Übersicht den Vergleich.

## Dynamische Strompreise

Die App holt die Viertelstundenpreise über die Primeo-Schnittstelle (Standard: `https://tarife.primeo-energie.ch/api/v1/tariffs`), stündlich und zwischen 18 und 21 Uhr alle 15 Minuten. Adresse, Tarifname, Tariftyp und Startdatum lassen sich unter **Tarife → Dynamische Strompreise → Schnittstelle einstellen** ändern. Die Preise enthalten keine kantonalen/kommunalen Abgaben und keine MWST.

**Bonus (ab 2027):** Die Rechnung bleibt bei HT/NT. Pro Viertelstunde rechnet die App Standardtarif minus dynamischen Preis (Typ `integrated` plus Konzessionsabgabe auf `grid_usage`, plus MWST) mal Netzbezug und schreibt die Summe als Zeile «Bonus dynamischer Stromtarif» gut – pro Monat nie negativ. Fehlt ein Preis, gibt es für diese Viertelstunde keinen Bonus (Kontrolle in der Übersicht). Einstellungen unter **Einstellungen → Regeln**.

**Speicher (ab 2027):** Netzbezug am Zähler der PV-Anlage über der Standby-Grenze ist Laden der Batterie aus dem Netz und geht auf den Betreiber. Strom, der aus diesem Vorrat später im Haus verbraucht wird (zuerst geladen, zuerst verbraucht, abzüglich Wirkungsgrad), erscheint als «Speicher NT» zum vZEV-Preis und nicht als Solarstrom.

**80-%-Grenze:** Die Übersicht prüft pro Monat, ob der Solarpreis höchstens 80 % des Standardprodukts beträgt (gewichtet nach HT/NT des Solarverbrauchs). Voraussetzung: Solar- und Netztarife auf der gleichen Basis (inkl. MWST).

## Wärmepumpen

Wärmepumpen für Heizung und Warmwasser, die am Allgemeinzähler hängen, werden unter **Einstellungen → Zähler → Wärmepumpen** mit ihrem Energie-Sensor eingetragen (Zählerstand in kWh oder Wh, z. B. Shelly-Energie oder Stromverbrauch der Wärmepumpe). Schätzt die Wärmepumpe ihren Stromverbrauch nur, gleicht ein **Faktor** die Abweichung aus.

- Der Verbrauch wird pro Viertelstunde aus dem Allgemeinstrom herausgerechnet und bekommt den gleichen Solaranteil wie alle Zähler.
- Pro Quartal entsteht eine zusätzliche Gesamtrechnung **Heizung und Warmwasser**, in der Jahresabrechnung ein eigenes PDF für die Heiz- und Nebenkostenabrechnung.
- Gemessen wird ab dem Tag, an dem der Datensammler die Sensoren speichert; davor bleibt der Verbrauch im Allgemeinstrom. Kurze Lücken (bis 4 Stunden) werden gleichmässig verteilt.
- Die Übersicht prüft, ob die Werte vollständig ankommen.
- **Rückwirkend:** Unter Einstellungen → Zähler → «Wärmepumpen rückwirkend» übernimmt die App die stündlichen Zählerstände aus der Langzeit-Statistik von Home Assistant für die Zeit vor ihrer ersten eigenen Ablesung. Vorgeschlagen ist der erste nicht abgeschlossene Monat; für abgeschlossene Monate meldet «Abschluss» danach eine Abweichung, weil sich der Allgemeinstrom ändert.
- **Jahresarbeitszahl:** Mit einem Wärme-Sensor (erzeugte Wärme in kWh, Wh, MWh oder GJ) zeigt der Verlauf die Arbeitszahl pro Monat, die Jahresabrechnung die des Jahres; dazu der Sensor `sensor.vzev_jaz_<name>`.

## Sensoren in Home Assistant

Die App liefert ihre Kennzahlen als Sensoren an Home Assistant – für Dashboards, Verlauf und Automationen. Ein- und
ausschalten sowie das Präfix (Standard `vzev`) unter **Einstellungen → Zähler → Sensoren für Home Assistant**; dort steht
auch, was zuletzt geschrieben wurde. Die App schreibt sie beim Start, alle 15 Minuten und nach jeder neuen Berechnung.

| Sensor | Inhalt |
|---|---|
| `sensor.vzev_produktion_monat`, `_produktion_jahr` | PV-Produktion in kWh (laufender Monat, Jahr bisher) |
| `sensor.vzev_autarkie_monat`, `_autarkie_jahr` | Anteil Solarstrom am Verbrauch in % |
| `sensor.vzev_ruecklieferung_monat`, `_ruecklieferung_jahr` | Rücklieferung in kWh |
| `sensor.vzev_wertschoepfung_monat`, `_wertschoepfung_jahr` | Wertschöpfung in CHF (Aufteilung als Attribute) |
| `sensor.vzev_offene_rechnungen`, `_ueberfaellig` | offener Betrag in CHF (Liste als Attribut), Anzahl überfällig |
| `sensor.vzev_naechste_aufgabe`, `_offene_monate` | nächster Schritt aus dem Aufgaben-Assistenten, Anzahl offener Monate |
| `sensor.vzev_pv_prognose_heute`, `_pv_prognose_morgen` | Solcast-Prognose in kWh |
| `sensor.vzev_jaz_<name>` | Jahresarbeitszahl der Wärmepumpe im laufenden Jahr (mit Wärme-Sensor) |
| `sensor.vzev_strompreis` | dynamischer Preis jetzt in Rp./kWh inkl. Konzessionsabgabe und MWST (Tief/Hoch des Tages als Attribute) |
| `binary_sensor.vzev_guenstig_laden` | «an», solange ein günstiges Ladefenster läuft (wie auf der Seite «Prognose») |
| `sensor.vzev_naechstes_ladefenster` | Beginn des nächsten Ladefensters (Ende, Preis, fehlende kWh als Attribute) |

Beispiel für eine Automation: Boiler oder Batterie laden, solange `binary_sensor.vzev_guenstig_laden` an ist.
Preis und Ladefenster gibt es erst, wenn dynamische Preise abgerufen werden.

## Zahlungserinnerung

Bei überfälligen Rechnungen erstellt **Rechnungen → Erinnerung (PDF)** ein Schreiben mit Aufstellung (Rechnung, Zahlungen,
offener Betrag), neuer Frist (Standard 14 Tage, `rechnungen.erinnerung_frist_tage`) und Einzahlungsschein über den offenen
Betrag. Jede Erinnerung wird bei der Rechnung vermerkt; weitere zählen als 2., 3. Erinnerung.

## PV-Prognose

Voraussetzung ist die Solcast-Integration in Home Assistant (HACS «Solcast PV Forecast»). Die App sucht stündlich alle Sensoren mit Halbstunden-Prognose (Attribut `detailedForecast`) und speichert sie in `messwerte.sqlite`. Sollen nur bestimmte Sensoren zählen, unter **Einstellungen → Zähler → PV-Prognose** eintragen.

- **Gemessen** ist der Tageszähler PV-Ertrag des Wechselrichters (Solis), **üblicher Verbrauch** das Mittel der letzten vier Wochen zur gleichen Uhrzeit (1. OG, 2. OG, Allgemein ohne Ladestation).
- **Günstig aus dem Netz laden:** Viertelstunden, deren Preis im untersten Viertel zwischen Tiefst- und Höchstpreis des Tages liegt und in denen die Prognose den üblichen Verbrauch nicht deckt. Die App steuert nichts.
- **Trefferquote:** Für jeden Tag zählt die letzte Prognose, die am Vortag gespeichert wurde. Liegt Solcast dauerhaft daneben, dort Ausrichtung, Neigung oder Leistung der Anlage prüfen.

## Daten und Sicherung

Alles liegt im Konfigurationsordner der App (`/addon_configs/…_vzev/`) und ist damit im Home-Assistant-Backup enthalten:

| Datei / Ordner | Inhalt |
|---|---|
| `vzev.yaml` | Betreiber, Messpunkte, Tarife, Mieter, Regeln, Sensoren, Preis-Schnittstelle; vorherige Fassung als `vzev.yaml.bak` |
| `primeo/` | importierte Lastgänge und Wallbox-Export; ersetzte Dateien unter `primeo/_entfernt/` |
| `rechnungen/` | PDFs, `register.json` (Rechnungen und Zahlungen), alte Fassungen unter `_alt/` |
| `abschluss.json` | abgeschlossene Monate mit festgehaltenen Werten, Korrekturen |
| `messwerte.sqlite` | Zählerstände, evcc-Ladevorgänge, dynamische Strompreise, PV-Prognosen |
| `aufgaben.json` | im Assistenten als versendet markierte Rechnungen |
| `vzev.log` | Protokoll |

Das Backup läuft im laufenden Betrieb (`backup: hot`); Zwischenspeicher (`.cache/`) sind ausgenommen. Zusätzlich lädt
**Einstellungen → Datei vzev.yaml → Sicherung herunterladen** alles als ZIP herunter (die Datenbank als konsistente Kopie).
Wiederherstellen: Inhalt in den Konfigurationsordner der App kopieren und die App neu starten.

## Optionen

- `evcc_passwort`: nur nötig, wenn evcc für die Ladevorgänge eine Anmeldung verlangt.

## Netzwerk

Die App verbindet sich nur mit Home Assistant, evcc (im lokalen Netz) und der eingestellten Preis-Schnittstelle von Primeo.
