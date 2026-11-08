"""vZEV Rechenkern: Daten laden, 15-Minuten-Aufteilung, Ladestation, Kosten, Abgleich, Wertschöpfung.

Aufruf: python -I core.py <datenordner> [config.yaml]
Die Lastgänge werden über die Messpunkt-Nummer erkannt, nicht über den Dateinamen.
"""
import sys
from pathlib import Path

import numpy as np
from datetime import datetime
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent


# --- Konfiguration --------------------------------------------------------
def load_config(path=None):
    with open(path or HERE / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def tariff_series(index, entries, key):
    """Zeitreihe eines Tarifs: jeder Eintrag gilt ab 'ab' bis zum nächsten."""
    s = pd.Series(np.nan, index=index)
    for e in sorted(entries, key=lambda e: str(e["ab"])):
        v = e[key]
        s[index >= pd.Timestamp(e["ab"])] = np.nan if v is None else v
    return s


def occupied(index, cfg, einheit):
    """True, wo die Einheit vermietet ist."""
    occ = pd.Series(False, index=index)
    for m in cfg["mietverhaeltnisse"]:
        if m["einheit"] != einheit:
            continue
        von = pd.Timestamp(m["von"])
        bis = pd.Timestamp(m["bis"]) + pd.Timedelta(days=1) if m.get("bis") else pd.Timestamp.max
        occ |= (index >= von) & (index < bis)
    return occ


# --- Daten laden ----------------------------------------------------------
def read_header(path):
    """Messpunkt und Lieferstelle aus dem Kopf eines Primeo-Lastgangs, ohne die ganze Datei zu laden."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Lastgang"]
        rows = [r for _, r in zip(range(5), ws.iter_rows(values_only=True))]
    finally:
        wb.close()
    cell = lambda r: str(rows[r][2]).strip() if len(rows) > r and len(rows[r]) > 2 and rows[r][2] is not None else ""
    return cell(3), cell(4)


def _als_datum(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime)):
        return pd.Timestamp(v).normalize()
    t = str(v).strip()
    for f in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(datetime.strptime(t, f)).normalize()
        except ValueError:
            continue
    return pd.NaT


def _als_zeitpunkt(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    t = str(v).strip()
    for f in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return pd.Timestamp(datetime.strptime(t, f))
        except ValueError:
            continue
    return pd.NaT


def _als_zeit(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    if hasattr(v, "hour"):  # time oder datetime
        return pd.Timedelta(hours=v.hour, minutes=v.minute)
    try:
        h, m = str(v).strip().split(":")[:2]
        return pd.Timedelta(hours=int(h), minutes=int(m))
    except ValueError:
        return pd.NaT


def read_lastgang(path):
    messpunkt, lieferstelle = read_header(path)
    df = pd.read_excel(path, sheet_name="Lastgang", skiprows=8)
    fehlt = [c for c in ("Datum", "Uhrzeit", "kWh") if c not in df.columns]
    if fehlt:
        raise ValueError(f"Spalten {fehlt} fehlen in Zeile 9 (gefunden: {list(df.columns)[:6]})")
    if "Tarif" not in df.columns:
        df["Tarif"] = None
    # Datum als Datum oder Text (TT.MM.JJJJ); Summen- oder Leerzeilen am Ende werden übersprungen
    datum = df["Datum"].map(_als_datum)
    zeit = df["Uhrzeit"].map(_als_zeit)
    gueltig = datum.notna() & zeit.notna()
    if not gueltig.any():
        raise ValueError("keine Zeile mit gültigem Datum und Uhrzeit")
    df, ts = df[gueltig], (datum[gueltig] + zeit[gueltig])
    out = pd.DataFrame(
        {"kwh": pd.to_numeric(df["kWh"], errors="coerce").values, "tarif": df["Tarif"].values},
        index=pd.DatetimeIndex(ts.values),
    ).sort_index()
    # Lokalzeit: bei der Umstellung auf Winterzeit kommt 02:00–02:45 doppelt vor -> zusammenfassen
    if out.index.has_duplicates:
        out = out.groupby(level=0).agg({"kwh": "sum", "tarif": "first"})
    return out, messpunkt, lieferstelle


def read_lastgang_cached(path, cache_dir=None):
    """Wie read_lastgang, merkt sich das Ergebnis aber pro Datei (Name, Grösse, Änderungszeit).

    Das Einlesen der Excel-Dateien ist der langsamste Schritt; mit dem Zwischenspeicher wird nach einer
    Änderung an Tarifen oder Mietern nur noch neu gerechnet, nicht neu eingelesen.
    """
    if cache_dir is None:
        return read_lastgang(path)
    import pickle
    st = Path(path).stat()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ziel = cache_dir / f"{Path(path).name}.{st.st_size}.{int(st.st_mtime)}.pkl"
    if ziel.exists():
        try:
            with open(ziel, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    out = read_lastgang(path)
    for alt in cache_dir.glob(f"{Path(path).name}.*.pkl"):
        alt.unlink(missing_ok=True)
    with open(ziel, "wb") as f:
        pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def load(datadir, cfg, cache_dir=None):
    datadir = Path(datadir)
    series, files = {}, {}
    namen = set()
    probleme = []
    for p in sorted(datadir.glob("*.xlsx")):
        namen.add(p.name)
        try:
            s, mp, lieferstelle = read_lastgang_cached(p, cache_dir)
        except Exception as e:
            probleme.append(f"{p.name} nicht lesbar: {e}")
            continue
        key = cfg["messpunkte"].get(mp)
        if not key:
            probleme.append(f"{p.name}: Messpunkt «{mp}» ist keinem Zähler zugeordnet")
        elif key in series:
            probleme.append(f"{p.name} und {files[key][0]} gehören beide zu {key}; verwendet wird {files[key][0]}")
        else:
            series[key], files[key] = s, (p.name, mp, lieferstelle)
    missing = {"1OG", "2OG", "Allg", "PVA", "Prod"} - set(series)
    if missing:
        raise ValueError(f"Lastgang fehlt für {', '.join(sorted(missing))}" + (". " + "; ".join(probleme) if probleme else ""))
    idx = series["1OG"].index
    df = pd.DataFrame({k: s["kwh"].reindex(idx) for k, s in series.items()}, index=idx)
    df["tarif"] = series["1OG"]["tarif"]
    df = df[df.index >= pd.Timestamp(cfg["vzev_start"])]
    lade = None
    for p in sorted(datadir.glob("*.csv")):
        t = pd.read_csv(p, sep=";", decimal=",", dtype=str)
        if "Zaehlerstand Differenz [kWh]" in t.columns:
            t = t.dropna(subset=["Start"])
            zeilen = len(t)
            # Zeitpunkte mit oder ohne Sekunden; bewusst ohne pandas-Sonderformate, damit es mit
            # jeder pandas-Version gleich funktioniert (Home Assistant nutzt eine ältere als die Entwicklung)
            t["Start"] = pd.to_datetime(t["Start"].map(_als_zeitpunkt))
            t["Ende"] = pd.to_datetime(t["Ende"].map(_als_zeitpunkt))
            t["kwh"] = pd.to_numeric(t["Zaehlerstand Differenz [kWh]"].str.replace(",", "."), errors="coerce")
            t = t.dropna(subset=["Start", "Ende", "kwh"])
            if zeilen and t.empty:
                raise ValueError(f"{p.name}: keiner der {zeilen} Ladevorgänge hat ein lesbares Start-/Enddatum")
            if len(t) < zeilen:
                probleme.append(f"{p.name}: {zeilen - len(t)} Ladevorgänge ohne lesbares Datum übersprungen")
            lade, files["Lade"] = t, (p.name, "Wallbox", f"{len(t)} Ladevorgänge")
    if cache_dir is not None and Path(cache_dir).exists():  # Zwischenspeicher entfernter Dateien aufräumen
        for c in Path(cache_dir).glob("*.pkl"):
            if c.name.rsplit(".", 3)[0] not in namen:
                c.unlink(missing_ok=True)
    if lade is None:
        raise ValueError("Wallbox-Export (CSV mit «Zaehlerstand Differenz [kWh]») fehlt")
    return df, lade, files


# --- Berechnung -----------------------------------------------------------
def distribute_ev(df, lade, baseline):
    """Verteilt jeden Ladevorgang auf die Viertelstunden, in denen Allgemein über der Grundlast liegt."""
    ev = pd.Series(0.0, index=df.index)
    for _, r in lade.iterrows():
        m = (df.index >= r["Start"].floor("15min")) & (df.index <= r["Ende"])
        sub = df.loc[m, "Allg"]
        if len(sub) == 0:
            continue
        w = np.maximum(0, sub - baseline)
        alloc = w / w.sum() * r["kwh"] if w.sum() > 0 else pd.Series(r["kwh"] / len(sub), index=sub.index)
        ev.loc[sub.index] += alloc
    return ev


ZAEHLER = ["1OG", "2OG", "AllgC", "EV", "WP"]
ZL = [("1OG", "1. OG"), ("2OG", "2. OG"), ("AllgC", "Allgemein"), ("EV", "Ladestation"), ("WP", "Wärmepumpen")]
SPEICHER_STANDARD = {"speicher_ab": "2027-01-01", "pva_standby_max_kwh": 0.05, "speicher_wirkungsgrad": 0.9}
DYN_STANDARD = {"bonus": True, "bonus_ab": "2027-01-01", "konzession_prozent": 4.1, "mwst_prozent": 8.1}


def speicher_regeln(cfg):
    r = dict(SPEICHER_STANDARD)
    r.update({k: v for k, v in (cfg.get("regeln") or {}).items() if k in SPEICHER_STANDARD and v not in (None, "")})
    return r


def dyn_regeln(cfg):
    r = dict(DYN_STANDARD)
    r.update({k: v for k, v in (cfg.get("dynamisch") or {}).items() if k in DYN_STANDARD and v not in (None, "")})
    return r


def speicher_fifo(laden, intern, eta):
    """Netzstrom im Speicher: Netzladung (× Wirkungsgrad) kommt in einen Vorrat; was danach aus der Anlage im Haus
    verbraucht wird, stammt zuerst aus diesem Vorrat (first in, first out). Gibt die kWh pro Viertelstunde zurück."""
    out = np.zeros(len(laden))
    vorrat = 0.0
    for i, (l, v) in enumerate(zip(laden, intern)):
        vorrat += l * eta
        if vorrat > 0 and v > 0:
            x = min(vorrat, v)
            out[i] = x
            vorrat -= x
    return out


def compute(df, lade, cfg, ev=None, dyn=None, wp=None):
    """ev: gemessene Ladestation pro Viertelstunde (Vorschau aus Home Assistant); sonst aus den Ladevorgängen verteilt.
    dyn: dynamische Preise pro Viertelstunde (Spalten integrated, grid_usage in CHF/kWh exkl. MWST) für den Bonus.
    wp: Wärmepumpen (Heizung, Warmwasser) am Allgemeinzähler in kWh pro Viertelstunde aus Home Assistant; wo Werte
    fehlen, bleibt ihr Verbrauch im Allgemeinstrom.

    Ab «speicher_ab»: Netzbezug am Zähler der PV-Anlage über «pva_standby_max_kwh» pro Viertelstunde ist Laden des
    Speichers aus dem Netz (Kosten Betreiber, Spalte «Laden»); nur der Standby geht in den Allgemeinstrom. Strom, der
    später aus diesem Vorrat im Haus verbraucht wird, ist «Netzstrom aus Speicher» (P_…) statt Solarstrom (S_…)."""
    df = df.copy()
    rules, tar = cfg["regeln"], cfg["tarife"]
    if ev is None:
        ev = distribute_ev(df, lade, rules["ladestation_grundlast_kwh"])
    df["EV"] = np.minimum(ev, df["Allg"])
    einzeln = None
    if isinstance(wp, pd.DataFrame):  # je Wärmepumpe eine Spalte (Name) → Summe, Aufteilung unten
        einzeln = wp.reindex(df.index).fillna(0.0).clip(lower=0)
        wp = einzeln.sum(axis=1)
    wp = pd.Series(0.0, index=df.index) if wp is None else wp.reindex(df.index).fillna(0.0).clip(lower=0)
    df["WP_gemessen"] = wp
    df["WP"] = np.minimum(wp, df["Allg"] - df["EV"])
    df["AllgC"] = df["Allg"] - df["EV"] - df["WP"]
    cons = df["1OG"] + df["2OG"] + df["AllgC"] + df["EV"] + df["WP"]
    ratio = np.where(cons > 0, np.minimum(df["Prod"] / cons.replace(0, np.nan), 1.0), 0.0)
    sp = speicher_regeln(cfg)
    ab = df.index >= pd.Timestamp(str(sp["speicher_ab"]))
    standby = np.where(ab, np.minimum(df["PVA"], float(sp["pva_standby_max_kwh"])), df["PVA"])
    df["Laden"] = df["PVA"] - standby
    intern = np.minimum(df["Prod"], cons)
    speicher = speicher_fifo(df["Laden"].to_numpy(), intern.to_numpy(), float(sp["speicher_wirkungsgrad"]))
    anteil = np.where(intern > 0, speicher / intern.replace(0, np.nan), 0.0)
    for k in ZAEHLER:
        s = df[k] * ratio
        df[f"P_{k}"] = s * anteil
        df[f"S_{k}"] = s - df[f"P_{k}"]
        df[f"N_{k}"] = df[k] - s
    df["N_AllgC"] += standby
    df["Export"] = np.maximum(df["Prod"] - cons, 0)
    ht = tariff_series(df.index, tar["netz"], "ht")
    nt = tariff_series(df.index, tar["netz"], "nt")
    df["price"] = np.where(df["tarif"] == "HT", ht, nt)
    df["solarprice"] = tariff_series(df.index, tar["solar"], "chf")
    df["speicherprice"] = tariff_series(df.index, tar.get("speicher") or tar["solar"], "chf")
    df["exprice"] = tariff_series(df.index, tar["ruecklieferung"], "chf")
    df["occ_1OG"] = occupied(df.index, cfg, "1OG")
    df["month"] = df.index.to_period("M")
    dynamisch(df, cfg, dyn)
    # Einzelne Wärmepumpen (WP1, WP2 …): Anteil an der gemessenen Summe pro Viertelstunde, gleicher Solaranteil
    for i, (key, name) in enumerate(wp_namen(cfg), 1):
        anteil = (einzeln[name] / df["WP_gemessen"].where(df["WP_gemessen"] > 0)).fillna(0.0) \
            if einzeln is not None and name in einzeln else pd.Series(0.0, index=df.index)
        for a in ("S", "N", "P", "B"):
            df[f"{a}_{key}"] = df[f"{a}_WP"] * anteil
        df[key] = df["WP"] * anteil
    return df


def wp_namen(cfg):
    """[(WP1, Heizung), (WP2, Warmwasser) …] in der Reihenfolge der Einstellungen."""
    out = []
    for i, w in enumerate((cfg.get("homeassistant") or {}).get("waermepumpen") or [], 1):
        if isinstance(w, dict) and w.get("entity"):
            out.append((f"WP{i}", w.get("name") or w["entity"]))
    return out


def dynamisch(df, cfg, dyn):
    """Bonus aus dem dynamischen Tarif: pro Viertelstunde Standardtarif HT/NT minus dynamischer Preis
    (integrated + Konzessionsabgabe auf die Netznutzung, plus MWST), mal Netzbezug. Ohne Preis kein Bonus."""
    r = dyn_regeln(cfg)
    df["dynprice"] = np.nan
    if dyn is not None and len(dyn) and "integrated" in dyn:
        d = dyn.reindex(df.index)
        netz = d["grid_usage"].fillna(0.0) if "grid_usage" in d else 0.0
        df["dynprice"] = (d["integrated"] + float(r["konzession_prozent"]) / 100 * netz) * (1 + float(r["mwst_prozent"]) / 100)
    df["bonus_zeit"] = bool(r["bonus"]) & (df.index >= pd.Timestamp(str(r["bonus_ab"])))
    vorteil = (df["price"] - df["dynprice"]).where(df["bonus_zeit"]).fillna(0.0)
    for k in ZAEHLER:
        df[f"B_{k}"] = df[f"N_{k}"] * vorteil


def zaehler_summen(res, k, mask=None):
    """kWh und CHF eines Zählers (1OG, 2OG, AllgC, EV) pro Monat, optional nur innerhalb mask."""
    r = res if mask is None else res[mask]
    g = r["month"]
    ht = r[f"N_{k}"].where(r["tarif"] == "HT", 0)
    nt = r[f"N_{k}"].where(r["tarif"] == "NT", 0)
    return pd.DataFrame({
        "solar": r[f"S_{k}"].groupby(g).sum(),
        "ht": ht.groupby(g).sum(),
        "nt": nt.groupby(g).sum(),
        "solar_chf": (r[f"S_{k}"] * r["solarprice"]).groupby(g).sum(),
        "netz_chf": (r[f"N_{k}"] * r["price"]).groupby(g).sum(),
        "speicher": r[f"P_{k}"].groupby(g).sum(),
        "speicher_chf": (r[f"P_{k}"] * r["speicherprice"]).groupby(g).sum(),
        "bonus_chf": r[f"B_{k}"].groupby(g).sum(),
        "dyn_fehlt": (r["bonus_zeit"] & r["dynprice"].isna() & (r[f"N_{k}"] > 0)).groupby(g).sum(),
        "ersparnis_chf": (r[f"S_{k}"] * r["price"]).groupby(g).sum(),
        "letzte_viertelstunde": r.index.to_series().groupby(g).max(),
    })


def wertschoepfung(res, cfg):
    share = cfg["regeln"]["allgemein_mieteranteil"]
    occ = res["occ_1OG"].astype(float)
    neben = lambda a: res[f"{a}_AllgC"] + res[f"{a}_WP"]  # Allgemeinstrom und Wärmepumpen: Nebenkosten des ganzen Hauses
    mieter_kwh = res["S_1OG"] * occ + neben("S") * share * occ
    eigen_kwh = res["S_2OG"] + res["S_EV"] + res["S_1OG"] * (1 - occ) + neben("S") * (1 - share * occ)
    sp_mieter = res["P_1OG"] * occ + neben("P") * share * occ
    sp_eigen = res["P_2OG"] + res["P_EV"] + res["P_1OG"] * (1 - occ) + neben("P") * (1 - share * occ)
    ladepreis = res["dynprice"].fillna(res["price"])
    g = res["month"]
    out = pd.DataFrame({
        "export_kwh": res["Export"].groupby(g).sum(),
        "export_chf": (res["Export"] * res["exprice"]).groupby(g).sum(min_count=1),
        "mieter_kwh": mieter_kwh.groupby(g).sum(),
        "mieter_chf": (mieter_kwh * res["solarprice"]).groupby(g).sum(),
        "eigen_kwh": eigen_kwh.groupby(g).sum(),
        "eigen_chf": (eigen_kwh * res["price"]).groupby(g).sum(),
        # Speicher: Verkauf/Eigennutzung von Netzstrom aus dem Speicher minus Kosten der Netzladung
        "speicher_chf": (sp_mieter * res["speicherprice"] + sp_eigen * res["price"] - res["Laden"] * ladepreis).groupby(g).sum(),
        "laden_kwh": res["Laden"].groupby(g).sum(),
    })
    man = cfg.get("manuell", {})
    ex = pd.Series({pd.Period(str(e["monat"]), "M"): e["chf"] for e in man.get("ruecklieferung_vor_start", [])}, dtype=float)
    ue = pd.Series({pd.Period(str(e["monat"]), "M"): e["chf"] for e in man.get("uebrige_ertraege", [])}, dtype=float)
    out = out.reindex(out.index.union(ex.index).union(ue.index))
    out.loc[ex.index, "export_chf"] = ex
    out["uebrige_chf"] = ue.reindex(out.index).fillna(0)
    out["total_chf"] = out[["export_chf", "mieter_chf", "eigen_chf", "uebrige_chf", "speicher_chf"]].sum(axis=1, min_count=1)
    return out


def abgleich(res, cfg):
    netz = res[["N_1OG", "N_2OG", "N_AllgC", "N_EV", "N_WP", "Laden"]].sum(axis=1)
    rows = []
    end = lambda d: pd.Timestamp(d) + pd.Timedelta(days=1)
    for r in cfg["primeo_rechnungen"]:
        m = (res.index >= pd.Timestamp(r["von"])) & (res.index < end(r["bis"]))
        rows.append((r["nr"], "Netzbezug HT", r["netz_ht"], netz[m & (res["tarif"] == "HT")].sum()))
        rows.append((r["nr"], "Netzbezug NT", r["netz_nt"], netz[m & (res["tarif"] == "NT")].sum()))
        for von, bis, kwh in r["ruecklieferung"]:
            mm = (res.index >= pd.Timestamp(von)) & (res.index < end(bis))
            rows.append((r["nr"], f"Rücklieferung {von}–{bis}", kwh, res.loc[mm, "Export"].sum()))
    out = pd.DataFrame(rows, columns=["rechnung", "position", "primeo_kwh", "berechnet_kwh"])
    out["diff"] = out["berechnet_kwh"] - out["primeo_kwh"]
    out["ok"] = out["diff"].abs() <= 1.0
    return out


def run(datadir, config=None, cache_dir=None, dyn=None, wp=None):
    cfg = load_config(config)
    df, lade, files = load(datadir, cfg, cache_dir)
    res = compute(df, lade, cfg, dyn=dyn, wp=wp(cfg) if callable(wp) else wp)
    ev_check = abs(res["EV"].sum() - lade["kwh"].sum())
    return cfg, res, files, lade, ev_check


if __name__ == "__main__":
    cfg, res, files, lade, ev_check = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    pd.set_option("display.width", 220, "display.max_columns", 40)
    for k, v in files.items():
        print(f"{k:5} {v[0]:28} {v[1]}  {v[2]}")
    print(f"Ladestation verteilt vs. Wallbox: Differenz {ev_check:.4f} kWh")
    print(abgleich(res, cfg).round(2).to_string(index=False))
    w = wertschoepfung(res, cfg)
    print(w.round(2).to_string())
    print("Total Wertschöpfung:", round(w["total_chf"].sum(), 2))
