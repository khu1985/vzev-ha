# Changelog

## 0.6.0

- Jahresabrechnung: neue Seite unter «Abrechnung» mit Allgemeinstrom fürs ganze Jahr (Monatstabelle und Total), Mietern (berechnet, in Rechnung gestellt, bezahlt), Zählern pro Monat und Wertschöpfung. Hinweis «vorläufig», solange nicht alle Monate abgeschlossen sind.
- Wertschöpfung: eigene Seite unter «Auswertung» mit Kennzahlen (Total, pro kWh Produktion, Anteil im Haus genutzt, Anteil Rücklieferung) und Diagrammen: Wertschöpfung pro Monat nach Quelle, kumuliert, wohin der Solarstrom geht und was eine kWh je Verwendung wert ist; filterbar nach Jahr.
- PDF Allgemeinstrom: Jahresaufstellung für die Nebenkostenabrechnung, gespeichert unter rechnungen/jahr.
- Excel-Export: alle Tabellen des Jahres als Excel-Datei, auf Wunsch mit allen Viertelstunden.
- Was ist neu: Ein Klick auf die Versionsnummer oben zeigt alle Änderungen; nach einem Update erscheint einmalig ein Hinweis.
- Dynamische Strompreise: jetzt auf der Seite «Tarife» statt «Primeo».
- Rechnungen: Die Tarife in der Fussnote kommen jetzt aus den Einstellungen statt fest aus dem Text (wichtig für neue Tarife 2027).

## 0.5.1

- Dynamische Strompreise jetzt auf der Seite «Primeo» (Verlauf, Jetzt abrufen, Schnittstelle einstellen).
- Regeln für Batterie und dynamischen Tarif jetzt unter «Einstellungen → Regeln». Die Seite «Batterie» zeigt nur noch die Speicherwerte.
- Statusanzeige: «Berechnung startet» blieb nach dem Speichern von Einstellungen stehen, bis eine Seite mit Berechnung geöffnet wurde. Die Berechnung startet jetzt sofort im Hintergrund.

## 0.5.0

- Dynamische Strompreise (Primeo Dynamisch / NetzDynamisch): Die App holt die Viertelstundenpreise über die Primeo-Schnittstelle, stündlich und zwischen 18 und 21 Uhr alle 15 Minuten (Veröffentlichung für den nächsten Tag bis 18 Uhr). Fehlende Tage werden nachgeladen, ab einem einstellbaren Datum (Standard 01.01.2027).
- Seite «Batterie»: Preisverlauf heute und morgen, Durchschnitt, Spanne und günstigste Stunde; «Jetzt abrufen»; Schnittstelle einstellbar (Adresse, Tarifname, Tariftyp, ab Datum, automatisch an/aus).
- Die Preise werden noch nicht für die Abrechnung verwendet; das folgt, wenn die offenen Fragen (Mieterpreis, Abgaben 2027, Batterie-Netzladung) geklärt sind.

## 0.4.1

- Rechnungen: «Datum ändern» pro Rechnung – Rechnungsdatum und Fälligkeit im Register anpassen (z. B. wenn die Rechnung früher verschickt wurde). Fällig leer = Datum + Zahlungsfrist. Jede Änderung wird festgehalten und ins Protokoll geschrieben; das PDF bleibt unverändert.

## 0.4.0

- Zahlungseingang: Jede erstellte Rechnung kommt ins Register (Betrag, Rechnungsdatum, Fälligkeit). Zahlungen lassen sich unter «Rechnungen» mit Datum und Betrag erfassen und wieder entfernen; Status offen, teilweise, überfällig, bezahlt oder überzahlt. Oben: offener und überfälliger Betrag.
- Bei einer Korrektur übernimmt die neue Rechnung die bereits erfassten Zahlungen; die alte Fassung bleibt als «ersetzt» sichtbar.
- Allgemeinstrom-Rechnungen gelten als «intern» (für die Nebenkostenabrechnung) und brauchen keine Zahlung.
- Rechnungen von vor diesem Update werden automatisch nachgetragen (Betrag aus der aktuellen Berechnung, Datum der Datei).
- Übersicht: neue Kontrolle «Rechnungen bezahlt», sobald etwas überfällig ist.

## 0.3.12

- Automatische Tests (44 Fälle) für Rechenkern, Rechnungen, Vorschau und Web-App; GitHub prüft jede Änderung im gleichen Debian-Image wie Home Assistant.
- Korrektur (von den Tests gefunden): Formulare konnten vzev.yaml beschädigen, wenn Listen in der Datei ganz links ohne Einrückung stehen. Ausserdem bricht das Speichern jetzt mit einer Meldung ab, statt eine unlesbare Datei zu schreiben.

## 0.3.11

- Handy, Lesbarkeit: Kennzahlen zweispaltig, grössere Abstände zwischen den Einträgen der Karten, erste Zeile jeder Karte hervorgehoben, Hinweistexte etwas grösser, mehr Zeilenabstand.
- Handy: Rechnungsformular mit Beschriftung über den Feldern und Knopf in voller Breite; Upload-Feld und Knopf mit Abstand.
- Handy: «entfernen» in den Eingabekarten bricht nicht mehr Buchstabe für Buchstabe um; Status im Abschluss nicht mehr eingeklemmt.

## 0.3.10

- Statusanzeige «Seite wird geladen …» mit Ladebalken oben bei jedem Seitenwechsel: Monat wählen, Klick ins Diagramm, Reiter im Verlauf und in den Einstellungen, Navigation, Filter im Protokoll und Datensammler. Der Inhalt wird bis zum Laden abgeblendet.
- Monats- und Reiterwechsel schneller: Monatswerte, Wertschöpfung und Abgleich werden zwischengespeichert, bis sich Daten oder Einstellungen ändern.

## 0.3.9

- Handy: Versionsnummer wieder in der Kopfzeile neben dem Namen. Der Name wird bei sehr schmalen Bildschirmen gekürzt, damit «Menü» in derselben Zeile bleibt; die Statusanzeige erscheint darunter.

## 0.3.8

- Statusanzeige oben neben der Version: «Berechnung läuft (12 s)», «Zählerstände abrufen», «evcc-Ladevorgänge abrufen» oder «bereit · gerechnet 13:03». Aktualisiert sich von selbst.
- Seiten mit Berechnung warten nicht mehr blind: Läuft die Berechnung länger als 1.5 s, erscheint eine Warteseite mit Fortschritt, die automatisch lädt, sobald alles fertig ist.
- Knöpfe zeigen beim Absenden, dass etwas läuft (z. B. «Rechnungen werden erstellt …», «Zählerstände und evcc werden abgerufen …») und lassen sich nicht doppelt drücken.
- Datensammler zeigt, wann der nächste Abruf der Zählerstände und von evcc kommt.

## 0.3.7

- Handy: Werte in den Karten bleiben zusammen und rechtsbündig (z. B. «2'813.600 kWh», Name und Entität im Datensammler).
- Handy: Feld «Begründung der Korrektur» bei Rechnungen ragt nicht mehr über den Rand.

## 0.3.6

- Eigenes AppArmor-Profil: Die App darf nur noch in ihren Datenordner (/config), /data, /tmp und /run schreiben. Hebt die Sicherheitsbewertung in Home Assistant von 7 auf 8.

## 0.3.5

- Handy: Tabellen werden zu Karten mit Beschriftung pro Wert (Import, Abschluss, Verbraucher, Abgleich, Datensammler, Rechnungen, Protokoll).
- Handy: Eingabetabellen (Mieter, Tarife, Primeo, Zähler) als Karten pro Zeile mit vollbreiten Feldern; Formulare (Betreiber, Regeln, Batterie) mit Beschriftung über dem Feld. Nichts ragt mehr über den Bildschirmrand.
- Handy: Monatstabellen (Verlauf, Alle Monate, Wertschöpfung) scrollen seitlich mit fester Monatsspalte; Diagramme mit grösserer Beschriftung, beginnend bei den neuesten Monaten.
- Handy: Mieter-Historie untereinander statt nebeneinander.

## 0.3.4

- Verlauf: neue Spalte «Verbrauch kWh» (Solar + Netz HT + Netz NT) pro Monat und in der Summe, für alle Zähler. Im Diagramm zeigt der Tooltip zuerst den Verbrauch gesamt, dann Solar und Netz.

## 0.3.3

- Korrektur: Der Wallbox-Export mit Sekunden («11.05.2026 08:26:31») wurde in Home Assistant nicht gelesen. Die Ladestation war deshalb 0 und blieb im Allgemeinstrom. Das Datum wird jetzt unabhängig von der pandas-Version gelesen.
- Liest die App keinen einzigen Ladevorgang, bricht die Berechnung mit einer klaren Meldung ab, statt mit 0 weiterzurechnen.
- Kontrolle «Ladestation = Summe der Ladevorgänge» zeigt Anzahl Ladevorgänge und verteilte kWh und schlägt an, wenn nichts verteilt wurde.
- Abschluss: Hat sich ein abgeschlossener Monat verändert, lassen sich die neuen Werte mit Begründung übernehmen, ohne den Monat wieder zu öffnen. Steht unter «Korrekturen».

## 0.3.2

- Lastgänge robuster einlesen: Datum als Datum oder Text (TT.MM.JJJJ), Uhrzeit als Zeit oder Text, Summen- und Leerzeilen am Ende werden übersprungen. Wallbox-Export mit oder ohne Sekunden.
- Klare Fehlermeldung, wenn die Lastgänge nicht berechnet werden können: welche Datei nicht lesbar ist, welcher Messpunkt keinem Zähler zugeordnet ist oder ob zwei Dateien zum selben Zähler gehören. Die Meldung steht in der Übersicht, unter «Daten importieren» und im Protokoll.
- «Daten importieren» zeigt oben, von wann bis wann die Berechnung aus den Lastgängen reicht.

## 0.3.1

- Abschluss: Beim Abschliessen lässt sich das Abschlussdatum wählen (Standard heute); bei abgeschlossenen Monaten kann es nachträglich geändert werden, z. B. für Monate, die schon früher abgeschlossen wurden. Jede Änderung steht mit altem und neuem Datum unter «Korrekturen und Abschlüsse».
- Navigation nach Grösse des Bildschirms: Ab 1200 px Seitenleiste mit Gruppen (Auswertung, Abrechnung, Stammdaten, Anlage), auf Tablets eine Zeile zum Wischen, auf dem Handy ein Menü-Knopf mit allen Seiten in zwei Spalten.

## 0.3.0

- Version der App oben neben dem Namen.
- Übersicht neu: Monat wählen, Kennzahlen (Produktion, Autarkie, Rücklieferung, Wertschöpfung), Diagramm «Energiefluss pro Monat», Kontrollen und Verbraucher des Monats inkl. Grundpreis. Die bisherigen Tabellen sind aufklappbar darunter.
- Neue Seite «Verlauf»: pro Zähler Kennzahlen, Diagramm Solar/Netz pro Monat und Monatstabelle, beim 1. OG nach Mietverhältnis gruppiert.
- Vorschau aus Home Assistant: Für die Zeit nach dem letzten Primeo-Lastgang rechnet die App mit den gesammelten Zählerständen (whatwatt, go-e, Solis) und zeigt diese Monate als vorläufig. Wo Primeo-Lastgänge und Zählerstände beide vorliegen, zeigt die Übersicht den Vergleich.

## 0.2.1

- Schneller: Die eingelesenen Primeo-Lastgänge werden zwischengespeichert. Nach einem Neustart oder einer Änderung an Tarifen, Mietern oder Regeln wird nur noch neu gerechnet, nicht neu eingelesen (im Test 0.2 statt 3.4 Sekunden, auf dem Raspberry Pi entsprechend mehr).
- Nach dem Start und nach jedem Upload rechnet die App im Hintergrund, damit die nächste Seite nicht warten muss.
- Gleichzeitige Seitenaufrufe lösen nur noch eine Berechnung aus.

## 0.2.0

- Neue Seite «Mieter»: Mietverhältnisse als Tabelle bearbeiten, mit Historie pro Einheit inkl. Leerstand. Prüft Überschneidungen.
- Neue Seite «Tarife»: Solarstrom, Netzstrom HT/NT, Rücklieferung und Grundpreis mit Gültig-ab-Datum, plus die heute gültigen Werte.
- Neue Seite «Primeo»: Primeo-Rechnungen für den Abgleich, Einspeisevergütung vor dem vZEV-Start und übrige Erträge bearbeiten.
- Neue Seite «Abschluss»: Monate der Reihe nach abschliessen. Die Werte werden festgehalten; Änderungen an Tarifen, Mietern und Erträgen, die einen abgeschlossenen Monat betreffen, werden abgelehnt. Wieder öffnen nur mit Begründung. Verändern sich abgeschlossene Monate trotzdem (z. B. durch eine ersetzte Datei), warnen Übersicht und Abschluss.
- Rechnungen: Ein Quartal mit abgeschlossenen Monaten lässt sich nur mit Begründung neu erstellen; die alte Fassung bleibt unter rechnungen/_alt. Alles erscheint unter «Korrekturen».
- Neue Seite «Batterie»: geladen, entladen, Wirkungsgrad, PV-Ertrag, Netzbezug und Einspeisung pro Monat aus den Solis-Daten; Regeln für die Netzladung ab dem dynamischen Tarif.
- Einstellungen in Formularen: Betreiber und Rechnungen, Zähler (Messpunkte und Home-Assistant-Sensoren), Regeln. Die Datei vzev.yaml lässt sich weiterhin direkt bearbeiten.
- Formulare ändern nur ihren Abschnitt in vzev.yaml; die vorherige Fassung bleibt als vzev.yaml.bak.

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
