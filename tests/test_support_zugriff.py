"""Selbsttest für den Support-Zugriff-Kanon (docs/FLEET_SUPPORT_ZUGRIFF_SPEC.md).

Die Fehler dieser Klasse sind still: eine Impersonation ohne Einwilligung
funktioniert, eine Sitzung, die ihre Freigabe überlebt, funktioniert auch, und
eine erteilte Zeile ohne Frist sieht aus wie „unbegrenzt erteilt“. Jede
Entscheidung hat deshalb ihre Gegenprobe.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from support_zugriff import (  # noqa: E402
    ANFRAGE_GUELTIG,
    AUDIT_AKTIONEN,
    DAUERN,
    Fehler,
    Status,
    Verlaufsstatus,
    anfrage_offen,
    darf_ablehnen,
    darf_anfragen,
    darf_impersonieren,
    darf_widerrufen,
    frist_bis,
    laeuft,
    sitzungsende,
    verlaufsstatus,
)

JETZT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


# --- Entscheidung 1: ohne laufende Freigabe keine Impersonation --------------


def test_ohne_freigabe_keine_impersonation():
    assert darf_impersonieren(freigabe_laeuft=False) is Fehler.NO_CONSENT


def test_gegenprobe_mit_freigabe_impersonation():
    assert darf_impersonieren(freigabe_laeuft=True) is None


# --- laeuft ------------------------------------------------------------------


def test_erteilt_und_in_der_frist_laeuft():
    assert laeuft(status="granted", gueltig_bis=JETZT + timedelta(minutes=1), jetzt=JETZT)


def test_abgelaufene_freigabe_laeuft_nicht():
    assert not laeuft(status="granted", gueltig_bis=JETZT, jetzt=JETZT)
    assert not laeuft(status="granted", gueltig_bis=JETZT - timedelta(seconds=1), jetzt=JETZT)


def test_erteilt_ohne_frist_gilt_nicht():
    """Entscheidung 5 — ein NULL darf keinen unbefristeten Zugang erzeugen."""
    assert not laeuft(status="granted", gueltig_bis=None, jetzt=JETZT)


@pytest.mark.parametrize("status", ["requested", "declined", "revoked", "GRANTED", "erteilt"])
def test_nur_granted_laeuft(status):
    """Auch der alte finance-Wert „erteilt“ zählt nicht — der Kanon heißt `granted`."""
    assert not laeuft(status=status, gueltig_bis=JETZT + timedelta(days=1), jetzt=JETZT)


def test_naive_zeit_wirft():
    with pytest.raises(ValueError):
        laeuft(status="granted", gueltig_bis=JETZT, jetzt=JETZT.replace(tzinfo=None))
    with pytest.raises(ValueError):
        laeuft(status="granted", gueltig_bis=JETZT.replace(tzinfo=None), jetzt=JETZT)


# --- anfrage_offen -----------------------------------------------------------


def test_frische_anfrage_ist_offen():
    assert anfrage_offen(status="requested", angefragt_am=JETZT - timedelta(days=6), jetzt=JETZT)


def test_anfrage_verfaellt_nach_sieben_tagen():
    assert ANFRAGE_GUELTIG == timedelta(days=7)
    assert not anfrage_offen(status="requested", angefragt_am=JETZT - ANFRAGE_GUELTIG, jetzt=JETZT)


def test_anfrage_ohne_zeitpunkt_ist_nicht_offen():
    assert not anfrage_offen(status="requested", angefragt_am=None, jetzt=JETZT)


def test_beantwortete_anfrage_ist_nicht_offen():
    for status in ("granted", "declined", "revoked"):
        assert not anfrage_offen(status=status, angefragt_am=JETZT, jetzt=JETZT)


# --- Entscheidung 2: höchstens eine offene Anfrage ODER laufende Freigabe ----


def test_anfragen_neben_laufender_freigabe_abgelehnt():
    assert darf_anfragen(freigabe_laeuft=True, anfrage_offen=False) is Fehler.ACCESS_ALREADY_GRANTED


def test_zweite_anfrage_abgelehnt():
    assert darf_anfragen(freigabe_laeuft=False, anfrage_offen=True) is Fehler.REQUEST_ALREADY_OPEN


def test_laufende_freigabe_geht_vor_offener_anfrage():
    """Der Zustand „beides“ darf nicht entstehen; tritt er in Altdaten auf,
    nennt die Absage den stärkeren Grund."""
    assert darf_anfragen(freigabe_laeuft=True, anfrage_offen=True) is Fehler.ACCESS_ALREADY_GRANTED


def test_gegenprobe_anfragen_erlaubt():
    assert darf_anfragen(freigabe_laeuft=False, anfrage_offen=False) is None


# --- Ablehnen und Widerrufen -------------------------------------------------


def test_ablehnen_nur_die_offene_anfrage():
    assert darf_ablehnen(offene_anfrage_id=7, anfrage_id=7) is None
    assert darf_ablehnen(offene_anfrage_id=7, anfrage_id=6) is Fehler.REQUEST_NOT_FOUND
    assert darf_ablehnen(offene_anfrage_id=None, anfrage_id=7) is Fehler.REQUEST_NOT_FOUND


def test_ablehnen_mit_uuid_kennungen():
    kennung = "3f2c7c1e-0000-4000-8000-000000000001"
    assert darf_ablehnen(offene_anfrage_id=kennung, anfrage_id=kennung) is None


def test_widerrufen_ohne_freigabe_ist_fehler():
    assert darf_widerrufen(freigabe_laeuft=False) is Fehler.NO_ACTIVE_ACCESS
    assert darf_widerrufen(freigabe_laeuft=True) is None


# --- Fristen -----------------------------------------------------------------


def test_die_drei_fristen():
    assert set(DAUERN) == {"1h", "24h", "7d"}
    assert frist_bis("1h", jetzt=JETZT) == JETZT + timedelta(hours=1)
    assert frist_bis("24h", jetzt=JETZT) == JETZT + timedelta(hours=24)
    assert frist_bis("7d", jetzt=JETZT) == JETZT + timedelta(days=7)


@pytest.mark.parametrize("dauer", ["", "unbegrenzt", "30d", "0h", None])
def test_unbekannte_frist_wirft(dauer):
    with pytest.raises(ValueError):
        frist_bis(dauer, jetzt=JETZT)


# --- Entscheidung 3: die Sitzung endet spätestens mit der Freigabe -----------


def test_sitzung_endet_mit_der_freigabe():
    bis = JETZT + timedelta(minutes=10)
    assert sitzungsende(gueltig_bis=bis, gewuenscht=JETZT + timedelta(minutes=30)) == bis


def test_gegenprobe_kurze_sitzung_bleibt_kurz():
    gewuenscht = JETZT + timedelta(minutes=30)
    assert sitzungsende(gueltig_bis=JETZT + timedelta(days=1), gewuenscht=gewuenscht) == gewuenscht


def test_sitzung_ohne_frist_wirft():
    with pytest.raises(ValueError):
        sitzungsende(gueltig_bis=None, gewuenscht=JETZT)


# --- Verlauf -----------------------------------------------------------------


def test_verlaufsstatus_je_zustand():
    assert verlaufsstatus("granted") is Verlaufsstatus.EXPIRED
    assert verlaufsstatus("requested") is Verlaufsstatus.LAPSED
    assert verlaufsstatus("declined") is Verlaufsstatus.DECLINED
    assert verlaufsstatus("revoked") is Verlaufsstatus.REVOKED


def test_jeder_status_hat_einen_verlaufsstatus():
    """Wer einen fünften Zustand ergänzt, muss ihm eine Beschriftung geben."""
    for status in Status:
        verlaufsstatus(status.value)


def test_unbekannter_status_wirft():
    with pytest.raises(ValueError):
        verlaufsstatus("erteilt")


# --- Codes und Audit ---------------------------------------------------------


def test_fehler_sind_maschinencodes():
    """Regel #23: snake_case, keine Leerzeichen — übersetzt wird in der App."""
    for fehler in Fehler:
        assert fehler.value.replace("_", "").isalpha() and fehler.value.islower()


def test_audit_aktionen_folgen_der_punktnotation():
    for aktion in AUDIT_AKTIONEN:
        teile = aktion.split(".")
        assert len(teile) >= 2 and all(t and t.replace("_", "").isalpha() and t.islower() for t in teile), aktion


def test_jede_nutzerhandlung_hat_eine_audit_aktion():
    for verb in ("grant", "decline", "revoke"):
        assert f"user.support_access.{verb}" in AUDIT_AKTIONEN
    assert "admin.support_access.request" in AUDIT_AKTIONEN
    assert "impersonate.denied" in AUDIT_AKTIONEN
