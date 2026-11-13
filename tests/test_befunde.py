"""Befunde aus den «Vorschlägen» (0.16.2): Zeitstempel, Einpassen der Wärmepumpen."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vzev" / "app"))
import core  # noqa: E402


def test_zeiten_gemischt_mit_und_ohne_sekunden():
    z = core.zeiten(["2026-11-10T12:00", "2026-11-10T12:15:00", "2026-11-10 12:30", "kaputt"])
    assert list(z[:3]) == [pd.Timestamp("2026-11-10 12:00"), pd.Timestamp("2026-11-10 12:15"), pd.Timestamp("2026-11-10 12:30")]
    assert pd.isna(z[3])


def test_wp_einpassen_verschiebt_innerhalb_einer_stunde():
    wp = np.array([0, 0, 2.0, 0, 0, 0])
    platz = np.array([1, 1, 1, 0.5, 0, 0])
    ein = core.wp_einpassen(wp, platz)
    assert abs(ein.sum() - 2.0) < 1e-9
    assert (ein <= platz + 1e-12).all()
    assert ein[2] == 1.0 and ein[3] == 0.5  # zuerst die Viertelstunde danach


def test_wp_einpassen_nicht_weiter_als_eine_stunde():
    wp = np.zeros(12)
    wp[0] = 3.0
    platz = np.zeros(12)
    platz[0], platz[6] = 1.0, 5.0  # Platz erst nach 1,5 Stunden
    ein = core.wp_einpassen(wp, platz)
    assert abs(ein.sum() - 1.0) < 1e-9 and ein[6] == 0


def test_wp_einpassen_ohne_ueberschuss_unveraendert():
    wp = np.array([0.2, 0.3, 0.1])
    assert np.allclose(core.wp_einpassen(wp, np.array([1, 1, 1.0])), wp)


def test_namen_und_vorname():
    assert core.namen({"name": "Erika Muster"}) == ("Erika", "Muster")
    assert core.namen({"name": "Anna Maria Muster"}) == ("Anna Maria", "Muster")
    assert core.namen({"name": "Jan van Beispiel", "vorname": "Jan", "nachname": "van Beispiel"}) == ("Jan", "van Beispiel")
    cfg = {"mietverhaeltnisse": [{"name": "Erika Muster"}, {"name": "Jan van Beispiel", "vorname": "Jan", "nachname": "van Beispiel"}]}
    assert core.vorname(cfg, "Erika Muster") == "Erika"
    assert core.vorname(cfg, "Muster") == "Erika"           # Nachname aus dem Dateinamen der Rechnung
    assert core.vorname(cfg, "Jan van Beispiel") == "Jan"
    assert core.vorname(cfg, "Unbekannt") == "Unbekannt"


def test_verteilen_vektorisiert_wie_bisher():
    import vorschau
    rng = np.random.default_rng(1)
    t = pd.Timestamp("2026-01-01") + pd.to_timedelta(np.cumsum(rng.choice([1, 1, 1, 2, 3, 20], 400)) * 15, unit="min")
    stand = pd.Series(np.cumsum(rng.random(400)), index=pd.DatetimeIndex(t))
    stand.iloc[200] = 0  # Zählerwechsel
    neu = vorschau.verteilen(stand)
    # alte Fassung (Schleife)
    s = stand.sort_index()
    ti = s.index[:-1]
    n = np.maximum(1, np.round(np.asarray((s.index[1:] - ti) / vorschau.VIERTEL, dtype=float)).astype(int))
    diff = np.diff(s.to_numpy())
    ok = (diff >= 0) & (n <= 16)
    zeiten = np.concatenate([ti[i] + np.arange(n[i]) * vorschau.VIERTEL for i in np.flatnonzero(ok)])
    alt = pd.Series(np.repeat(diff[ok] / n[ok], n[ok]), index=pd.DatetimeIndex(zeiten)).groupby(level=0).sum()
    pd.testing.assert_series_equal(neu, alt, check_freq=False)


def test_tarifmuster_haeufigster_tarif():
    import vorschau
    idx = pd.date_range("2026-01-05", periods=96 * 21, freq="15min")  # drei Wochen: jeder Zeitpunkt dreimal
    t = pd.Series(np.where((idx.dayofweek < 5) & (idx.hour >= 7) & (idx.hour < 20), "HT", "NT"), index=idx)
    t.iloc[30] = "HT" if t.iloc[30] == "NT" else "NT"  # ein Ausreisser ändert das Muster nicht
    m = vorschau.tarifmuster(pd.DataFrame({"tarif": t}))
    assert m[(0, 7, 30)] == "HT" and m[(0, 6, 45)] == "NT" and m[(5, 12, 0)] == "NT" and len(m) == 7 * 96
