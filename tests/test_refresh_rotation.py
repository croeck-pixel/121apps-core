"""Selbsttest für die Refresh-Rotations-Regel.

Warum das ein Gate braucht: der Fehler, den diese Regel verhindert, ist im
Betrieb unsichtbar. Nutzer melden „ich werde ständig ausgeloggt", die Logs
zeigen Token-Diebstahl, und niemand kommt auf die Idee, dass zwei Tabs genügen.
Wer die Regel später „vereinfacht", merkt es erst an den Beschwerden.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from refresh_rotation import (  # noqa: E402
    DEFAULT_GRACE_SECONDS,
    RefreshDecision,
    decide_refresh,
)


def test_aktueller_token_rotiert():
    e = decide_refresh(matches_current=True)
    assert e.decision is RefreshDecision.ROTATE
    assert e.is_ok


def test_aktuell_gewinnt_gegen_vorgaenger():
    """Ein Token, der zugleich als Vorgänger geführt wird, darf nicht in der
    Karenz landen — sonst rotiert die Sitzung nie weiter."""
    e = decide_refresh(matches_current=True, matches_previous=True, seconds_since_rotation=0)
    assert e.decision is RefreshDecision.ROTATE


@pytest.mark.parametrize("alter", [0, 1, 30, DEFAULT_GRACE_SECONDS])
def test_vorgaenger_innerhalb_der_karenz_wird_akzeptiert(alter):
    """Der Fall aus dem echten Vorfall: zwei Tabs, zweiter kommt Sekunden später."""
    e = decide_refresh(matches_current=False, matches_previous=True, seconds_since_rotation=alter)
    assert e.decision is RefreshDecision.ACCEPT_WITHIN_GRACE
    assert e.is_ok
    assert e.audit_code is None, "ein legitimer Aufruf darf keinen Alarm ins Audit schreiben"


@pytest.mark.parametrize("alter", [DEFAULT_GRACE_SECONDS + 1, 120, 3600])
def test_vorgaenger_nach_der_karenz_widerruft_nur_diese_sitzung(alter):
    e = decide_refresh(matches_current=False, matches_previous=True, seconds_since_rotation=alter)
    assert e.decision is RefreshDecision.REVOKE_THIS_SESSION
    assert e.audit_code == "refresh_token_reuse"
    assert not e.is_ok


def test_unbekannter_token_fasst_nichts_an():
    """Der Kern des Vorfalls: hier wurden früher ALLE Sitzungen widerrufen."""
    e = decide_refresh(matches_current=False, matches_previous=False)
    assert e.decision is RefreshDecision.REJECT_ONLY
    assert e.audit_code == "refresh_token_unknown"


def test_unbekanntes_alter_gilt_als_ausserhalb():
    """`None` heißt „weiß nicht" — dann lieber eine Sitzung widerrufen als einen
    gestohlenen Token unbegrenzt gelten lassen."""
    e = decide_refresh(matches_current=False, matches_previous=True, seconds_since_rotation=None)
    assert e.decision is RefreshDecision.REVOKE_THIS_SESSION


def test_negatives_alter_gilt_nicht_als_karenz():
    """Uhrensprung oder falsch berechnete Differenz darf die Karenz nicht öffnen."""
    e = decide_refresh(matches_current=False, matches_previous=True, seconds_since_rotation=-5)
    assert e.decision is RefreshDecision.REVOKE_THIS_SESSION


def test_app_ohne_vorgaenger_speicher_bekommt_trotzdem_keinen_massenwiderruf():
    """survey/support/aufträge führen nur einen aktuellen Wert. Sie übergeben
    matches_previous=False — dann gibt es keine Karenz, aber eben auch keine
    Entscheidung, die andere Geräte betrifft."""
    e = decide_refresh(matches_current=False, matches_previous=False)
    assert e.decision is RefreshDecision.REJECT_ONLY


def test_keine_entscheidung_widerruft_mehr_als_eine_sitzung():
    """Gegenprobe zur eigentlichen Regel: es gibt KEINEN Rückgabewert, der einen
    Massenwiderruf bedeutet. Kommt je einer dazu, schlägt dieser Test an."""
    erlaubt = {
        RefreshDecision.ROTATE,
        RefreshDecision.ACCEPT_WITHIN_GRACE,
        RefreshDecision.REVOKE_THIS_SESSION,
        RefreshDecision.REJECT_ONLY,
    }
    assert set(RefreshDecision) == erlaubt


def test_karenz_ist_kurz():
    """Eine großzügige Karenz macht einen gestohlenen Token länger nutzbar."""
    assert 0 < DEFAULT_GRACE_SECONDS <= 120


def test_eigene_karenz_wird_beachtet():
    e = decide_refresh(
        matches_current=False, matches_previous=True, seconds_since_rotation=90, grace_seconds=120
    )
    assert e.decision is RefreshDecision.ACCEPT_WITHIN_GRACE
