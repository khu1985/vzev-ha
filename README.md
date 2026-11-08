# vZEV Abrechnung – Home-Assistant-App

Abrechnung eines virtuellen Zusammenschlusses zum Eigenverbrauch (vZEV) in der Schweiz:
Primeo-Lastgänge, Ladestation, Wertschöpfung und Quartalsrechnungen mit QR-Einzahlungsschein.

## Installation

Home Assistant → Einstellungen → Apps → App-Store → ⋮ → Repositories →
`https://github.com/khu1985/vzev-ha` hinzufügen, dann «vZEV Abrechnung» installieren.

Persönliche Daten (Namen, IBAN, Messpunkte, Tarife) gehören nicht in dieses Repository,
sondern in die Konfiguration der App (Seite «Einstellungen»).

## Architektur

Die App läuft als Container im Home Assistant und erscheint über Ingress als Seite in der Seitenleiste.
Sie braucht kein Internet: Alle Daten liegen im Konfigurationsordner der App und sind damit im Home-Assistant-Backup enthalten.

```mermaid
flowchart LR
    subgraph Quellen
        P["Primeo-Kundenportal<br/>Lastgänge .xlsx (15 Min.)"]
        W["go-e Wallbox<br/>Ladevorgänge .csv"]
        HA["Home Assistant<br/>whatwatt, go-e, Solis, Kia"]
        E["evcc<br/>Ladevorgänge (REST)"]
    end

    subgraph App["vZEV-App (Container, Flask, Ingress)"]
        S["server.py<br/>Seiten, Import, Rechnungen, Protokoll"]
        C["core.py<br/>15-Minuten-Aufteilung, Tarife, Wertschöpfung, Abgleich"]
        V["vorschau.py<br/>Vorschau aus Zählerständen"]
        U["uebersicht.py<br/>Übersicht, Verlauf"]
        SE["seiten.py<br/>Mieter, Tarife, Primeo, Abschluss, Batterie, Einstellungen"]
        I["invoices.py<br/>PDF mit QR-Einzahlungsschein"]
        D["diagramme.py<br/>SVG-Diagramme"]
        CO["collector.py<br/>Datensammler alle 15 Min."]
    end

    subgraph Daten["Konfigurationsordner /addon_configs/…_vzev"]
        Y[("vzev.yaml<br/>Betreiber, Messpunkte, Tarife,<br/>Mieter, Regeln")]
        PR[("primeo/<br/>importierte Dateien + Zwischenspeicher")]
        DB[("messwerte.sqlite<br/>Zählerstände, evcc")]
        AB[("abschluss.json<br/>festgehaltene Monate, Korrekturen")]
        R[("rechnungen/<br/>PDFs, _alt/")]
        L[("vzev.log")]
    end

    P -- Upload --> S
    W -- Upload --> S
    S --> PR
    HA -- Supervisor-API --> CO
    E -- REST --> CO
    CO --> DB
    PR --> C
    Y --> C
    C --> U
    DB --> V --> U
    C --> SE
    SE <--> Y
    SE <--> AB
    C --> I --> R
    U --> D
    S --> L
```

| Datei | Aufgabe |
|---|---|
| `vzev/app/core.py` | Lastgänge einlesen (Messpunkt aus dem Dateikopf), Ladestation auf Viertelstunden verteilen, Solar/Netz pro Zähler aufteilen, Tarife mit Gültig-ab-Datum, Wertschöpfung, Abgleich mit Primeo-Rechnungen |
| `vzev/app/vorschau.py` | Gleiche Rechnung mit den gesammelten Zählerständen aus Home Assistant für die Zeit nach dem letzten Lastgang |
| `vzev/app/server.py` | Webserver, Navigation, Import, Rechnungen, Datensammler-Seite, Protokoll |
| `vzev/app/uebersicht.py` | Übersicht mit Kennzahlen, Kontrollen und Diagramm; Verlauf pro Zähler |
| `vzev/app/seiten.py` | Formulare für Mieter, Tarife, Primeo, Batterie und Einstellungen; Monatsabschluss und Sperre |
| `vzev/app/invoices.py` | Quartalsrechnungen als PDF: Wohnung mit QR-Einzahlungsschein, Allgemeinstrom als Gesamtrechnung |
| `vzev/app/collector.py` | Speichert alle 15 Minuten die Zählerstände aus Home Assistant und stündlich die evcc-Ladevorgänge |
| `vzev/app/diagramme.py` | Säulendiagramme als SVG ohne externe Bibliothek |
| `vzev/app/default_config.yaml` | Vorlage für `vzev.yaml` (ohne persönliche Daten) |

## Rechenmodell

Grundlage sind die Primeo-Lastgänge in 15-Minuten-Auflösung. Jede Viertelstunde wird einzeln gerechnet:

```mermaid
flowchart TD
    A["Lastgänge pro Viertelstunde<br/>1. OG, 2. OG, Allgemein, Produktion, Netzbezug PV-Anlage"] --> B
    LS["Wallbox-Ladevorgänge<br/>Start, Ende, kWh"] --> B
    B["Ladestation herausrechnen<br/>Energie jedes Ladevorgangs auf die Viertelstunden verteilen,<br/>in denen der Allgemeinzähler über der Grundlast liegt"] --> C
    C["Allgemeinstrom = Allgemein − Ladestation + Standby PV-Anlage"] --> D
    D["Solaranteil = min(Produktion ÷ Verbrauch aller Zähler, 1)<br/>gleicher Anteil für jeden Zähler"] --> E
    E["Pro Zähler: Solar kWh, Netz HT kWh, Netz NT kWh<br/>Rücklieferung = Produktion − Verbrauch (wenn positiv)"] --> F
    T[("Tarife mit Gültig-ab-Datum<br/>Solar, Netz HT/NT, Rücklieferung, Grundpreis")] --> F
    M[("Mietverhältnisse<br/>von – bis, Leerstand")] --> F
    F["Monatssummen und Beträge"] --> G["Rechnungen<br/>Wohnung pro Mietverhältnis,<br/>Allgemeinstrom gesamt"]
    F --> H["Wertschöpfung Betreiber<br/>Rücklieferung + Verkauf an Mieter + Eigenverbrauch"]
    F --> K["Abgleich mit Primeo-Rechnungen<br/>Netzbezug HT/NT, Rücklieferung"]
```

Regeln, die in `vzev.yaml` einstellbar sind:

- **Allgemeinstrom** wird als Gesamtrechnung gestellt (Weiterverrechnung in der Nebenkostenabrechnung). Nur für die Wertschöpfung gilt er zu einem einstellbaren Anteil (Standard 50 %) als an die Mieter verkauft.
- **Leerstand** zählt als Eigenverbrauch des Betreibers; der Grundpreis wird nach Miettagen aufgeteilt.
- **Ladestation** gehört dem Betreiber; ihr Solarstrom zählt als Eigenverbrauch.
- **Rücklieferung** ohne bekannten Tarif bleibt offen und wird in der Wertschöpfung nicht geschätzt.

## Prozess

### Laufend (automatisch)

```mermaid
flowchart LR
    A["alle 15 Min.<br/>Zählerstände aus Home Assistant speichern"] --> B["stündlich<br/>evcc-Ladevorgänge abrufen"]
    B --> C["Übersicht: laufender Monat<br/>als Vorschau (vorläufig)"]
```

### Monatlich / quartalsweise (von Hand)

```mermaid
flowchart TD
    A["Primeo-Kundenportal: Lastgänge aller 5 Zähler exportieren<br/>go-e: Ladevorgänge exportieren"] --> B["Daten importieren: Dateien hochladen<br/>Zuordnung über die Messpunkt-Nummer, alte Fassung wird ersetzt"]
    B --> C{"Übersicht: Kontrollen ok?<br/>Lücken, Ladestation, Abgleich"}
    C -- nein --> B
    C -- ja --> D["Primeo-Rechnung erfassen (Seite «Primeo»)<br/>Netzbezug HT/NT und Rücklieferung für den Abgleich"]
    D --> E["Tarife prüfen<br/>Rückliefertarif des Quartals eintragen, sobald publiziert"]
    E --> F["Abschluss: Monat abschliessen<br/>Werte werden festgehalten und gesperrt"]
    F --> G["Rechnungen: Quartal erstellen<br/>PDF pro Mietverhältnis + Allgemeinstrom"]
    G --> H["Rechnungen versenden<br/>Allgemeinstrom in die Nebenkostenabrechnung"]
```

### Korrekturen

```mermaid
flowchart LR
    A["Datei ersetzt oder Regel geändert"] --> B{"Betrifft einen<br/>abgeschlossenen Monat?"}
    B -- nein --> C["wird sofort neu gerechnet"]
    B -- "ja, Tarif / Mieter / Ertrag" --> D["wird abgelehnt<br/>Monat zuerst mit Begründung wieder öffnen"]
    B -- "ja, Datei / Regel" --> E["Übersicht und Abschluss melden «verändert»<br/>neue Werte mit Begründung übernehmen"]
    D --> F["Korrekturen-Liste<br/>Zeit, Monat, Was, Begründung"]
    E --> F
    E --> G["Rechnungen des Quartals neu erstellen<br/>nur mit Begründung, alte PDFs unter rechnungen/_alt"]
```

## Daten und Sicherung

| Datei / Ordner | Inhalt |
|---|---|
| `vzev.yaml` | Betreiber, Messpunkte, Tarife, Mietverhältnisse, Regeln, Home-Assistant-Sensoren; frühere Fassung als `vzev.yaml.bak` |
| `primeo/` | importierte Lastgänge und Wallbox-Export; ersetzte Dateien unter `primeo/_entfernt/` |
| `messwerte.sqlite` | Zählerstände aus Home Assistant und evcc-Ladevorgänge |
| `abschluss.json` | abgeschlossene Monate mit festgehaltenen Werten, Korrekturen |
| `rechnungen/` | erstellte PDFs; ersetzte Fassungen unter `rechnungen/_alt/` |
| `vzev.log` | Protokoll (auch in der App unter «Protokoll») |

Alles liegt im Konfigurationsordner der App und ist im Home-Assistant-Backup enthalten.

## Änderungen

Siehe [vzev/CHANGELOG.md](vzev/CHANGELOG.md).
