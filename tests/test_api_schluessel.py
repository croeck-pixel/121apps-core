"""Selbsttest für den Schlüssel-Kanon.

Warum das ein Gate braucht: Die Fehler dieser Klasse sind still und teuer. Ein
Geltungsbereich, der zu viel erlaubt, sieht aus wie einer, der funktioniert.
Ein Schlüssel, der nach dem Rollenverlust weiterläuft, fällt niemandem auf —
der Zugang bleibt einfach offen. Und ein rotierter Vorgänger, der sofort
stirbt, bricht Clients zu einem Zeitpunkt, an dem noch niemand tauschen
konnte.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from api_schluessel import (  # noqa: E402
    GRACE_HOECHSTENS,
    SAMMEL_LESESCOPE,
    SchluesselFehler,
    erzeugen,
    grace_ende,
    hashen,
    ist_gueltig,
    passt,
    praefix_aus,
    scope_erfuellt,
)

JETZT = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


# ── Format ─────────────────────────────────────────────────────────────────


def test_ein_schluessel_traegt_die_app_im_namen():
    """Damit Secret-Scanning greift und der Support weiß, wohin er gehört."""
    s = erzeugen("pba")
    assert s.klartext.startswith("sk_pba_")
    assert s.praefix.startswith("sk_pba_")
    assert praefix_aus(s.klartext) == s.praefix


def test_der_praefix_ist_kurz_genug_fuer_eine_anzeigespalte():
    s = erzeugen("pba")
    assert len(s.praefix) <= 20


def test_zwei_schluessel_sind_verschieden():
    """Klingt trivial und ist die Zusage, an der alles hängt."""
    a, b = erzeugen("pba"), erzeugen("pba")
    assert a.klartext != b.klartext
    assert a.hash != b.hash


def test_der_klartext_steckt_nicht_im_hash():
    s = erzeugen("pba")
    assert s.klartext not in s.hash
    assert len(s.hash) == 64


@pytest.mark.parametrize("app", ["", "P", "zu-lang-fuer-ein-kuerzel", "AB", "a1"])
def test_unsinnige_app_kuerzel_werden_abgewiesen(app):
    with pytest.raises(SchluesselFehler):
        erzeugen(app)


@pytest.mark.parametrize(
    "eingabe",
    [
        "",
        "sk_pba_zukurz",
        "pba_a1b2c3d4_" + "x" * 32,
        "sk_pba_A1B2C3D4_" + "x" * 32,  # Präfix muss klein sein
        "sk_pba_a1b2c3d4_kurz",
    ],
)
def test_kaputte_schluessel_haben_kein_praefix(eingabe):
    with pytest.raises(SchluesselFehler):
        praefix_aus(eingabe)


# ── Vergleich ──────────────────────────────────────────────────────────────


def test_der_richtige_schluessel_passt():
    s = erzeugen("pba")
    assert passt(s.klartext, s.hash)


def test_ein_fremder_schluessel_passt_nicht():
    a, b = erzeugen("pba"), erzeugen("pba")
    assert not passt(a.klartext, b.hash)


def test_ein_um_ein_zeichen_abweichender_schluessel_passt_nicht():
    s = erzeugen("pba")
    verdreht = s.klartext[:-1] + ("a" if s.klartext[-1] != "a" else "b")
    assert not passt(verdreht, s.hash)


def test_hashen_ist_wiederholbar():
    assert hashen("sk_pba_a1b2c3d4_xyz") == hashen("sk_pba_a1b2c3d4_xyz")


# ── Geltungsbereiche ───────────────────────────────────────────────────────


def test_wer_den_bereich_hat_darf():
    assert scope_erfuellt("documents:write", {"documents:write"})


def test_wer_ihn_nicht_hat_darf_nicht():
    assert not scope_erfuellt("documents:write", {"chats:read"})


def test_der_sammelscope_deckt_lesendes_ab():
    assert scope_erfuellt("documents:read", {SAMMEL_LESESCOPE})
    assert scope_erfuellt("chats:read", {SAMMEL_LESESCOPE})


def test_der_sammelscope_deckt_kein_schreiben_ab():
    """Der Fehler, der aus einem Lese-Zugang unbemerkt einen Vollzugriff macht."""
    assert not scope_erfuellt("documents:write", {SAMMEL_LESESCOPE})
    assert not scope_erfuellt("documents:delete", {SAMMEL_LESESCOPE})


def test_kein_praefix_vergleich():
    """`documents:` zu haben darf nicht `documents:write` bedeuten."""
    assert not scope_erfuellt("documents:write", {"documents:"})
    assert not scope_erfuellt("documents:write", {"documents"})


def test_ohne_bereiche_darf_nichts():
    assert not scope_erfuellt("documents:read", set())


# ── Gültigkeit ─────────────────────────────────────────────────────────────


def _gueltig(**abweichend):
    argumente = dict(
        jetzt=JETZT, expires_at=None, revoked_at=None, ersteller_aktiv=True
    )
    argumente.update(abweichend)
    return ist_gueltig(**argumente)


def test_ein_frischer_schluessel_traegt():
    assert _gueltig()


def test_ein_gesperrter_traegt_nicht():
    assert not _gueltig(revoked_at=JETZT - timedelta(seconds=1))


def test_eine_sperrung_in_der_zukunft_wirkt_noch_nicht():
    assert _gueltig(revoked_at=JETZT + timedelta(hours=1))


def test_ein_abgelaufener_traegt_nicht():
    assert not _gueltig(expires_at=JETZT - timedelta(seconds=1))


def test_genau_im_ablaufmoment_traegt_er_nicht_mehr():
    """Die Grenze gehört auf die sichere Seite."""
    assert not _gueltig(expires_at=JETZT)


def test_ein_schluessel_kann_nie_mehr_als_sein_ersteller():
    """Der Punkt, den vier von fünf Apps nicht hatten.

    Wird jemand deaktiviert oder verliert die Rolle, hört sein Schlüssel auf
    zu wirken — sonst überlebt ein Zugang den Zugang.
    """
    assert not _gueltig(ersteller_aktiv=False)
    # Und zwar auch dann, wenn sonst alles stimmt.
    assert not _gueltig(ersteller_aktiv=False, expires_at=JETZT + timedelta(days=365))


# ── Rotation ───────────────────────────────────────────────────────────────


def test_der_vorgaenger_traegt_die_karenz_ueber():
    """Ohne Karenz bricht eine Rotation jeden Client in dem Moment, in dem der
    neue Schlüssel entsteht — bevor ihn jemand einsetzen konnte."""
    ende = grace_ende(JETZT)
    assert ende > JETZT
    assert ende == JETZT + timedelta(hours=24)


def test_eine_eigene_karenz_wird_genommen():
    assert grace_ende(JETZT, timedelta(hours=1)) == JETZT + timedelta(hours=1)


def test_eine_zu_lange_karenz_wird_abgewiesen():
    """Wochenlang ist kein Übergang mehr, sondern ein zweiter gültiger
    Schlüssel, von dem niemand weiß."""
    with pytest.raises(SchluesselFehler, match="Obergrenze"):
        grace_ende(JETZT, GRACE_HOECHSTENS + timedelta(seconds=1))


@pytest.mark.parametrize("dauer", [timedelta(0), timedelta(seconds=-1)])
def test_eine_unsinnige_karenz_wird_abgewiesen(dauer):
    with pytest.raises(SchluesselFehler, match="positiv"):
        grace_ende(JETZT, dauer)


def test_ein_zeitstempel_ohne_zone_wird_abgewiesen():
    """Er würde später gegen einen zonenbewussten verglichen und dort werfen —
    an einer Stelle, die mit der Rotation nichts mehr zu tun hat."""
    with pytest.raises(SchluesselFehler, match="Zeitzone"):
        grace_ende(datetime(2026, 8, 11, 12, 0))
