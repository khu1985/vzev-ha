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
4. **Mieter:** Mietverhältnisse mit Vorname, Nachname und Von/Bis.
5. **Daten importieren:** Lastgänge aller Zähler aus dem Primeo-Kundenportal (.xlsx) und den Wallbox-Export (.csv) hochladen.

## Seiten

Die Navigation ist gruppiert wie in der Finanz-App: **Überblick** ist immer offen, die übrigen Gruppen klappen auf, wenn
sie die aktuelle Seite enthalten (Klick auf den Gruppennamen öffnet oder schliesst sie).

**Ampeln.** Für jeden Bereich gibt es eine Ampel – grün in Ordnung, gelb prüfen, rot handeln, grau keine Daten. Die
Startseite zeigt alle als Kacheln (Klick führt zur Seite); in der Navigation stehen gelbe und rote Punkte bei der Seite und
bei der zugeklappten Gruppe.

| Ampel | grün | gelb | rot |
|---|---|---|---|
| Primeo-Lastgänge | bis 45 Tage alt | bis 75 Tage | älter |
| Monatsabschluss | alle vergangenen Monate abgeschlossen | 1 Monat offen | 2 und mehr |
| Kontrollen | ältester offener (sonst letzter) Monat: alle stimmen | 1–2 stimmen nicht | mehr |
| Zahlungen | nichts überfällig | Quartalsrechnungen 3 Wochen nach Quartalsende nicht erstellt | Rechnung überfällig |
| Tarife | alle Monate mit Tarif | im Dezember Tarife des neuen Jahres fehlen, Rückliefertarif fehlt | – |
| Nebenkosten | Grundlagen vollständig | Angaben fehlen; Abrechnung 1 Monat nach Periodenende nicht erstellt | 3 Monate danach |
| Datensammler | letzte Ablesung bis 1 h | bis 6 h, Sensor ohne Wert | älter |
| PV-Prognose | Prognose für heute vorhanden | fehlt | – |
| Sensoren für HA | geschrieben | Fehler beim Schreiben | – |
| Protokoll | keine Fehler seit dem Start | 1–4 Fehler | 5 und mehr |
| Vorschläge | keine dringenden | Vorschlag mit hoher Priorität | – |

Die Ampeln werden im Hintergrund bewertet (höchstens alle 5 Minuten, nach jeder Änderung und neuen Berechnung) – keine
Seite wartet darauf.

**Überblick**
- **Energiefluss** (Startseite): oben die Ampeln, darunter animiertes Diagramm von PV-Anlage, Netz und Speicher zum Haus und zu den Verbrauchern, für heute, gestern, einen Monat oder ein Jahr. Die Ringe zeigen den Anteil Solar-, Speicher- und Netzstrom; Werte erscheinen per Maus oder Tippen. Speicherwerte stammen vom Wechselrichter, alles andere aus derselben Rechnung wie die Abrechnung.
- **Übersicht:** Jahr wählen; Produktion, Autarkie, Rücklieferung und Wertschöpfung des Jahres; Diagramm «Energiefluss pro Monat» – ein Klick auf einen Monat zeigt darunter dessen Kennzahlen, Kontrollen (Abgleich mit Primeo, Ladestation, Lücken, Rückliefertarif, 80-%-Grenze Solarpreis, dynamische Preise, Wärmepumpen, Netzladung gegen Wechselrichter, Abschluss, offene Rechnungen) und Verbraucher mit Betrag inkl. Grundpreis.
- **Aufgaben:** Assistent für den Monatsabschluss und wiederkehrende Aufgaben; erkennt erledigte Schritte selbst.

**Auswertung**
- **Verlauf:** pro Zähler Verbrauch, Solar/Netz und Kosten pro Monat, beim 1. OG nach Mietverhältnis gruppiert.
- **Wertschöpfung:** Ertrag des Betreibers pro Monat nach Quelle (Verkauf an Mieter, Eigenverbrauch, Rücklieferung, Gutschriften), kumuliert, Verwendung des Solarstroms und Wert pro kWh; filterbar nach Jahr.
- **Prognose:** PV-Prognose aus der Solcast-Integration (heute, morgen, folgende Tage) mit Bandbreite, gemessenem Ertrag, üblichem Verbrauch und dynamischem Strompreis; Zeitfenster «günstig aus dem Netz laden»; Trefferquote der Prognose vom Vortag.
- **Batterie:** Monatswerte des Speichers (geladen, entladen, Wirkungsgrad) aus den Solis-Daten. Für die Abrechnung zählt die Netzladung aus den Primeo-Lastgängen (siehe «Dynamische Strompreise»).

**Abrechnung**
- **Rechnungen:** Quartal und Rechnungsdatum wählen und erstellen – pro Mietverhältnis eine Rechnung mit QR-Einzahlungsschein, dazu eine Gesamtrechnung Allgemeinstrom für die Nebenkostenabrechnung. Ab 2027 zusätzlich die Spalte «Speicher NT» und die Zeile «Bonus dynamischer Stromtarif», sobald sie vorkommen. Darunter **Rechnungen und Zahlungen**: offene und überfällige Beträge, Zahlungen erfassen oder entfernen, Rechnungsdatum und Fälligkeit ändern.
- **Nebenkosten:** Nebenkostenabrechnung 1.7.–30.6. (siehe unten).
- **Jahresabrechnung:** Allgemeinstrom fürs ganze Jahr als PDF für die Nebenkostenabrechnung, Mieter, Wertschöpfung, Excel-Export (auf Wunsch mit allen Viertelstunden).
- **Abschluss:** Monate der Reihe nach abschliessen (mit Abschlussdatum). Danach sind Änderungen an Tarifen, Mietern und Erträgen für diesen Monat gesperrt.

**Daten**
- **Daten importieren:** Dateien hochladen, ersetzen oder entfernen. Die Zuordnung erfolgt über die Messpunkt-Nummer im Dateikopf, nicht über den Dateinamen. Oben steht, bis wann die Lastgänge reichen.
- **Primeo:** Primeo-Rechnungen für den Abgleich, manuelle Erträge.
- **Datensammler:** Zählerstände aus Home Assistant (alle 15 Minuten) mit letztem Wert und Status, evcc-Ladevorgänge im Detail.

**Stammdaten**
- **Mieter:** Mietverhältnisse mit Historie. In der App steht nur der Vorname; Rechnungen, Zahlungserinnerungen, Jahresabrechnung und Excel verwenden Vor- und Nachname.
- **Tarife:** Tarife mit Gültig-ab-Datum und **Dynamische Strompreise** (Verlauf heute/morgen, Schnittstelle einstellen).

**App**
- **Einstellungen:** Betreiber, Zähler, Regeln (Aufteilung sowie Speicher und Bonus dynamischer Tarif) die Datei `vzev.yaml` direkt sowie als Reiter **Protokoll** (Uploads, Rechnungen, Zahlungen, Korrekturen, Warnungen und Fehler) und **Änderungen**.
- **Vorschläge:** Vorschläge für die Weiterentwicklung und Leistung der App (siehe unten).

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

- Änderungen an Tarifen, Mietern oder Erträgen, die einen abgeschlossenen Monat betreffen, lehnt die App ab (ausgenommen die Korrektur eines Mieternamens). Zuerst den Monat unter **Abschluss** mit Begründung wieder öffnen (rückwärts, der Reihe nach).
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

Wärmepumpen für Heizung und Warmwasser, die am Allgemeinzähler hängen, werden unter **Einstellungen → Zähler → Wärmepumpen** mit ihrem Energie-Sensor eingetragen (Zählerstand in kWh oder Wh, z. B. Shelly-Energie oder Stromverbrauch der Wärmepumpe). Schätzt die Wärmepumpe ihren Stromverbrauch nur, gleicht ein **Faktor** die Abweichung aus. Pro Wärmepumpe eine Zeile: Strom als Energie-Sensor, erzeugte Wärme (z. B. Buderus «erzeugte Wärme gesamt») im Feld **Wärme-Sensor** derselben Zeile – nie als eigene Zeile.

- Der Verbrauch wird pro Viertelstunde aus dem Allgemeinstrom herausgerechnet und bekommt den gleichen Solaranteil wie alle Zähler. Die Ladevorgänge der Ladestation (nur als Summe bekannt) werden auf den Allgemeinstrom ohne die gemessenen Wärmepumpen verteilt. Weil Home Assistant und Primeo einige Minuten versetzt messen, wird ein Überschuss bis eine Stunde davor oder danach eingepasst; nur was auch dort keinen Platz hat, bleibt im Allgemeinstrom (Kontrolle «herausgerechnet»).
- Pro Quartal entsteht eine zusätzliche Gesamtrechnung **Heizung und Warmwasser**, in der Jahresabrechnung ein eigenes PDF für die Heiz- und Nebenkostenabrechnung.
- Gemessen wird ab dem Tag, an dem der Datensammler die Sensoren speichert; davor bleibt der Verbrauch im Allgemeinstrom. Kurze Lücken (bis 4 Stunden) werden gleichmässig verteilt.
- Die Übersicht prüft, ob die Werte vollständig ankommen.
- **Rückwirkend:** Unter Einstellungen → Zähler → «Wärmepumpen rückwirkend» übernimmt die App die stündlichen Zählerstände aus der Langzeit-Statistik von Home Assistant für die Zeit vor ihrer ersten eigenen Ablesung. Vorgeschlagen ist der erste nicht abgeschlossene Monat; für abgeschlossene Monate meldet «Abschluss» danach eine Abweichung, weil sich der Allgemeinstrom ändert.
- **Jahresarbeitszahl:** Mit einem Wärme-Sensor (erzeugte Wärme in kWh, Wh, MWh oder GJ) zeigt der Verlauf die Arbeitszahl pro Monat, die Jahresabrechnung die des Jahres; dazu der Sensor `sensor.vzev_jaz_<name>`.

## Nebenkostenabrechnung

**Abrechnung → Nebenkosten** rechnet die Neben- und Betriebskosten nach Mietvertrag ab (Abrechnungsperiode 1.7.–30.6.).
Verrechnet werden dürfen nur die im Mietvertrag aufgeführten Kosten, zu den tatsächlichen Kosten (Art. 257a/b OR, VMWG).

- **Grundlagen** (einmal): Fläche jeder Wohnung, Personen bei selbst bewohnten Wohnungen, pro Mietverhältnis Personen und
  Akonto pro Monat (aus dem Mietvertrag), Grundanteil der Heizung (Standard 30 % nach m², Rest nach Wärmezähler) und
  Honorar für die Abrechnung (Standard 3 % der Nebenkosten, oder ein fester Betrag nach m²). Optional die Sensoren der
  Wärmezähler – der Datensammler liest sie dann mit.
- **Kosten** pro Periode: Strom der Wärmepumpen (Heizung, Warmwasser) und Allgemeinstrom kommen aus der App (einzeln
  abwählbar). Übrige Kosten mit Kategorie und Beleg erfassen, z. B. Wartung Heizung, Wasser/Abwasser, Kehricht,
  Hauswartung, Treppenhausreinigung, Antenne, Einstellplatz-Anteil aus der Abrechnung der Nachbarliegenschaft.
- **Wärmezähler**: Stand am 1.7. und 30.6. für den Gesamtzähler und die Wohnungen mit eigenem Zähler (von Hand oder aus
  Home Assistant). Wohnungen ohne eigenen Zähler teilen sich den Rest nach m².

| Kategorie | Verteilung |
|---|---|
| Heizung | Grundanteil nach m², Rest nach Wärmezähler |
| Warmwasser, Wasser/Abwasser | nach Personen × Tage |
| Übrige Neben- und Betriebskosten | nach m² |
| Direkt | ganz einer Wohnung |

Innerhalb einer Wohnung zählt jedes Mietverhältnis nach Tagen; Tage ohne Mieter (Leerstand, selbst bewohnt) trägt der
Vermieter. Die Tabelle «Verteilung» zeigt jederzeit den Stand. Nach dem 30.6. – sobald die Lastgänge bis Ende Juni da sind
und keine Hinweise offen – erstellt **Abrechnungen erstellen** je Mietverhältnis ein PDF mit Positionen, Schlüssel,
Honorar, Akonto und Saldo. Eine Nachzahlung kommt mit Einzahlungsschein ins Zahlungsregister (Rechnungen, Erinnerungen),
ein Guthaben steht als Hinweis auf der Abrechnung. «Vorschau als PDF» geht jederzeit. Alle Angaben, Beträge und Belege
liegen nur im Datenordner (`nebenkosten.json`, `nebenkosten/`).

## Vorschläge für die Weiterentwicklung

**Anlage → Vorschläge** zeigt, wo die App mit deinen Daten an Grenzen stösst – als Liste, die du anonymisiert an die
Entwicklung weitergeben kannst.

| Quelle | Beispiel | Wichtigkeit |
|---|---|---|
| Fehler im Protokoll seit dem Update (installierte Version; ohne Startzeile 30 Tage) | «ERROR: Seite ‹…› fehlgeschlagen – KeyError in uebersicht.py:index» | hoch |
| Kontrollen, die nicht stimmen (12 Monate) | «Abgleich mit Primeo» stimmt nicht (3×) | hoch bis tief |
| Import | Messpunkt nicht zugeordnet, Datei nicht lesbar, Ladevorgänge ohne Datum | mittel/hoch |
| Korrekturen | Monate wieder geöffnet, Rechnungen neu erstellt, Rechnungsdatum von Hand geändert | mittel/tief |
| Datensammler | Sensor ohne Werte (geprüft, aber nicht verfügbar) | mittel |
| Prognose | Solcast liegt im Mittel mehr als 20 % daneben | tief |
| Leistung (siehe unten) | Seite «verlauf» lädt langsam, «core.compute» ist langsamer geworden | mittel/hoch |
| eigene Ideen | frei formuliert | mittel |

Namen, Adressen, Messpunkte, Seriennummern in Sensor-IDs, IBAN, E-Mail, Zugangsdaten, Beträge und Daten werden ersetzt.
Nichts wird automatisch gesendet: Der Text zum Weitergeben lässt sich kopieren, als `vzev-vorschlaege.md`
herunterladen oder als Entwurf eines GitHub-Issues öffnen. Erledigtes lässt sich ausblenden oder als gemeldet markieren.

**Leistung.** Die App misst laufend, pro Version:

| Was | Beispiel |
|---|---|
| Ladezeit jeder Seite und Aktion | «verlauf» Ø 420 ms, längster 1,2 s |
| Rechenzeit der grossen Berechnungen | Berechnung aller Zähler (Laden, Rechnen), Übersicht und Kontrollen, Rechnungen, Jahresabrechnung, Wärmepumpen und JAZ, Prognose, Sensoren |
| Hintergrundaufgaben | Datensammler ablesen |
| System und Daten | Kerne, Last, freier Arbeitsspeicher, Speicher der App, Grösse von Datenbank, Dateien und Zwischenspeicher, Anzahl Messwerte, Preise und Prognosen |

Die Karte «Leistung» auf der Seite Vorschläge zeigt alles mit Ampel und dem Mittel der Vorversion. Daraus entstehen
Vorschläge im Bereich «Leistung»: Seiten oder Aktionen ab 1,5 s im Mittel, Berechnungen ab 0,8 s, alles, was gegenüber
der Vorversion deutlich langsamer wurde, eine Gesamtberechnung über einer Minute, Datenbank oder Zwischenspeicher über
200 MB, knapper Arbeitsspeicher oder hohe Last. Die Messwerte (nur Zeiten und Mengen, keine Inhalte) stehen im Text zum
Weitergeben und werden in `leistung.json` gespeichert (die letzten fünf Versionen).

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

Im Home Assistant beantwortet die App nur Anfragen des Ingress-Proxys (172.30.32.2); andere Apps im internen Netz
erhalten «403». Lokal zum Entwickeln (ohne `SUPERVISOR_TOKEN`) ist sie offen.
