# Changelog

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
