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
