"""vZEV Rechenkern: Daten laden, 15-Minuten-Aufteilung, Ladestation, Kosten, Abgleich, Wertschöpfung.

Aufruf: python -I core.py <datenordner> [config.yaml]
Die Lastgänge werden über die Messpunkt-Nummer erkannt, nicht über den Dateinamen.
"""
import sys
from pathlib import Path

import numpy as np
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


def read_lastgang(path):
    messpunkt, lieferstelle = read_header(path)
    df = pd.read_excel(path, sheet_name="Lastgang", skiprows=8)
    ts = pd.to_datetime(df["Datum"]).dt.normalize() + pd.to_timedelta(df["Uhrzeit"].astype(str))
    out = pd.DataFrame(
        {"kwh": pd.to_numeric(df["kWh"], errors="coerce").values, "tarif": df["Tarif"].values},
        index=pd.DatetimeIndex(ts.values),
    )
    # Lokalzeit: bei der Umstellung auf Winterzeit kommt 02:00–02:45 doppelt vor -> zusammenfassen
    if out.index.has_duplicates:
        out = out.groupby(level=0).agg({"kwh": "sum", "tarif": "first"})
    return out, messpunkt, lieferstelle


def load(datadir, cfg):
    datadir = Path(datadir)
    series, files = {}, {}
    for p in sorted(datadir.glob("*.xlsx")):
        try:
            s, mp, lieferstelle = read_lastgang(p)
        except Exception:
            continue
        key = cfg["messpunkte"].get(mp)
        if key:
            series[key], files[key] = s, (p.name, mp, lieferstelle)
    missing = {"1OG", "2OG", "Allg", "PVA", "Prod"} - set(series)
    if missing:
        raise SystemExit(f"Fehlende Lastgänge: {sorted(missing)}")
    idx = series["1OG"].index
    df = pd.DataFrame({k: s["kwh"].reindex(idx) for k, s in series.items()}, index=idx)
    df["tarif"] = series["1OG"]["tarif"]
    df = df[df.index >= pd.Timestamp(cfg["vzev_start"])]
    lade = None
    for p in datadir.glob("*.csv"):
        t = pd.read_csv(p, sep=";", decimal=",", dtype=str)
        if "Zaehlerstand Differenz [kWh]" in t.columns:
            t = t.dropna(subset=["Start"])
            t["Start"] = pd.to_datetime(t["Start"], format="%d.%m.%Y %H:%M")
            t["Ende"] = pd.to_datetime(t["Ende"], format="%d.%m.%Y %H:%M")
            t["kwh"] = t["Zaehlerstand Differenz [kWh]"].str.replace(",", ".").astype(float)
            lade, files["Lade"] = t, (p.name, "Wallbox", f"{len(t)} Ladevorgänge")
    if lade is None:
        raise SystemExit("Ladestation-Datei fehlt")
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


def compute(df, lade, cfg):
    df = df.copy()
    rules, tar = cfg["regeln"], cfg["tarife"]
    df["EV"] = np.minimum(distribute_ev(df, lade, rules["ladestation_grundlast_kwh"]), df["Allg"])
    df["AllgC"] = df["Allg"] - df["EV"]
    cons = df["1OG"] + df["2OG"] + df["AllgC"] + df["EV"]
    ratio = np.where(cons > 0, np.minimum(df["Prod"] / cons.replace(0, np.nan), 1.0), 0.0)
    for k in ["1OG", "2OG", "AllgC", "EV"]:
        df[f"S_{k}"] = df[k] * ratio
        df[f"N_{k}"] = df[k] - df[f"S_{k}"]
    df["N_AllgC"] += df["PVA"]
    df["Export"] = np.maximum(df["Prod"] - cons, 0)
    ht = tariff_series(df.index, tar["netz"], "ht")
    nt = tariff_series(df.index, tar["netz"], "nt")
    df["price"] = np.where(df["tarif"] == "HT", ht, nt)
    df["solarprice"] = tariff_series(df.index, tar["solar"], "chf")
    df["exprice"] = tariff_series(df.index, tar["ruecklieferung"], "chf")
    df["occ_1OG"] = occupied(df.index, cfg, "1OG")
    df["month"] = df.index.to_period("M")
    return df


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
        "ersparnis_chf": (r[f"S_{k}"] * r["price"]).groupby(g).sum(),
        "letzte_viertelstunde": r.index.to_series().groupby(g).max(),
    })


def wertschoepfung(res, cfg):
    share = cfg["regeln"]["allgemein_mieteranteil"]
    occ = res["occ_1OG"].astype(float)
    mieter_kwh = res["S_1OG"] * occ + res["S_AllgC"] * share * occ
    eigen_kwh = res["S_2OG"] + res["S_EV"] + res["S_1OG"] * (1 - occ) + res["S_AllgC"] * (1 - share * occ)
    g = res["month"]
    out = pd.DataFrame({
        "export_kwh": res["Export"].groupby(g).sum(),
        "export_chf": (res["Export"] * res["exprice"]).groupby(g).sum(min_count=1),
        "mieter_kwh": mieter_kwh.groupby(g).sum(),
        "mieter_chf": (mieter_kwh * res["solarprice"]).groupby(g).sum(),
        "eigen_kwh": eigen_kwh.groupby(g).sum(),
        "eigen_chf": (eigen_kwh * res["price"]).groupby(g).sum(),
    })
    man = cfg.get("manuell", {})
    ex = pd.Series({pd.Period(str(e["monat"]), "M"): e["chf"] for e in man.get("ruecklieferung_vor_start", [])}, dtype=float)
    ue = pd.Series({pd.Period(str(e["monat"]), "M"): e["chf"] for e in man.get("uebrige_ertraege", [])}, dtype=float)
    out = out.reindex(out.index.union(ex.index).union(ue.index))
    out.loc[ex.index, "export_chf"] = ex
    out["uebrige_chf"] = ue.reindex(out.index).fillna(0)
    out["total_chf"] = out[["export_chf", "mieter_chf", "eigen_chf", "uebrige_chf"]].sum(axis=1, min_count=1)
    return out


def abgleich(res, cfg):
    netz = res[["N_1OG", "N_2OG", "N_AllgC", "N_EV"]].sum(axis=1)
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


def run(datadir, config=None):
    cfg = load_config(config)
    df, lade, files = load(datadir, cfg)
    res = compute(df, lade, cfg)
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
