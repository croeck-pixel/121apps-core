"""Selbsttest für die Auth-Grenzen.

Warum das ein Gate braucht: die Regel entscheidet, wem der Zugang verwehrt
wird. Ein Fehler nach der einen Seite sperrt Leute aus ihrem eigenen Konto aus
und sieht dabei aus wie ein Serverfehler; ein Fehler nach der anderen Seite
lässt Brute-Force durch und sieht nach gar nichts aus. Beide Richtungen melden
sich nicht von selbst — deshalb Tests.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from rate_limit import (  # noqa: E402
    LIMITS,
    SCHLUESSEL_PRAEFIX,
    UNBEKANNTE_HERKUNFT,
    Regel,
    entscheide,
    regel_fuer,
    schluessel,
)

JETZT = 1_000_000.0


def entscheidung(treffer, aeltester=None, jetzt=JETZT, regel=Regel(3, 60)):
    return entscheide(
        treffer_im_fenster=treffer, aeltester_treffer=aeltester, jetzt=jetzt, regel=regel
    )


# ---------------------------------------------------------------- die Grenzen


def test_alle_auth_buckets_sind_belegt():
    """Wer einen Endpunkt absichert, findet den Bucket hier — oder merkt es."""
    assert set(LIMITS) == {
        "login",
        "register",
        "passwort_vergessen",
        "bestaetigung_erneut",
        "passwort_zuruecksetzen",
        "email_bestaetigen",
        "magic_login",
        "sso_start",
    }


def test_token_raten_ist_so_streng_wie_passwort_zuruecksetzen():
    """`magic_login` und `passwort_zuruecksetzen` raten beide an einem Token,
    und ein Treffer ist in beiden Faellen die volle Kontouebernahme. Wer die
    eine lockert, muss die andere mitdenken."""
    assert LIMITS["magic_login"] == LIMITS["passwort_zuruecksetzen"]


def test_sso_einstieg_ist_lockerer_als_anmelden_aber_begrenzt():
    """Ein SSO-Redirect ist billig, aber nicht gratis: er legt einen State in
    Redis an. Unbegrenzt darf er trotzdem nicht sein."""
    sso, login = LIMITS["sso_start"], LIMITS["login"]
    assert sso.limit > login.limit
    assert sso.limit <= 30


def test_mailversand_an_fremde_ist_am_striktesten():
    """Passwort-vergessen und Bestätigung-erneut verschicken Post an eine
    Adresse, die der Aufrufer nur behauptet. Sie müssen strenger sein als
    alles, was nur den eigenen Zugang betrifft."""
    fremdpost = [LIMITS["passwort_vergessen"], LIMITS["bestaetigung_erneut"]]
    for regel in fremdpost:
        assert regel.limit <= 3
        assert regel.fenster_sekunden >= 3600
    # ... und strenger als Anmelden, sonst ist die Reihenfolge verrutscht.
    for regel in fremdpost:
        pro_stunde = regel.limit * 3600 / regel.fenster_sekunden
        login_pro_stunde = LIMITS["login"].limit * 3600 / LIMITS["login"].fenster_sekunden
        assert pro_stunde < login_pro_stunde


def test_unsinnige_regeln_fliegen_beim_anlegen_auf():
    with pytest.raises(ValueError):
        Regel(limit=0, fenster_sekunden=60)
    with pytest.raises(ValueError):
        Regel(limit=5, fenster_sekunden=0)


def test_unbekannter_bucket_ist_ein_fehler_kein_freifahrtschein():
    """Ein Tippfehler im Bucket-Namen darf nicht lautlos zu „keine Grenze"
    werden — das fiele erst beim Vorfall auf (Regel #7)."""
    with pytest.raises(KeyError) as exc:
        regel_fuer("passwort_vergesen")
    assert "passwort_vergessen" in str(exc.value)  # nennt die bekannten Namen


# ------------------------------------------------------------- die Schlüssel


def test_schluessel_form_ist_flottenweit_gleich():
    assert schluessel("login", "203.0.113.9") == f"{SCHLUESSEL_PRAEFIX}:login:203.0.113.9"


def test_ohne_herkunft_teilen_sich_alle_ein_kontingent():
    """Kein IP ermittelbar heißt nicht „unbegrenzt durch"."""
    assert schluessel("login", "") == f"{SCHLUESSEL_PRAEFIX}:login:{UNBEKANNTE_HERKUNFT}"


def test_verschiedene_herkuenfte_stoeren_sich_nicht():
    assert schluessel("login", "a") != schluessel("login", "b")


def test_verschiedene_buckets_stoeren_sich_nicht():
    """Sonst frisst ein Anmeldeversuch das Kontingent fürs Zurücksetzen auf."""
    assert schluessel("login", "a") != schluessel("passwort_vergessen", "a")


# ---------------------------------------------------------- die Entscheidung


def test_leeres_fenster_laesst_durch():
    e = entscheidung(treffer=0)
    assert e.erlaubt and e.retry_after == 0


def test_verbleibend_zaehlt_den_laufenden_aufruf_mit():
    """Limit 3, noch kein Treffer: dieser Aufruf ist der erste, es bleiben
    zwei. Ein Off-by-one hier lässt die Grenze um einen zu hoch wirken."""
    assert entscheidung(treffer=0).verbleibend == 2
    assert entscheidung(treffer=1).verbleibend == 1
    assert entscheidung(treffer=2).verbleibend == 0


def test_der_letzte_erlaubte_kommt_noch_durch():
    e = entscheidung(treffer=2)
    assert e.erlaubt and e.verbleibend == 0


def test_einer_zu_viel_wird_abgewiesen():
    e = entscheidung(treffer=3, aeltester=JETZT - 10)
    assert not e.erlaubt and e.verbleibend == 0


def test_retry_after_zeigt_auf_das_freiwerden_des_aeltesten():
    """Ältester Treffer vor 10 s, Fenster 60 s -> in 50 s wird ein Platz frei."""
    assert entscheidung(treffer=3, aeltester=JETZT - 10).retry_after == 50


def test_retry_after_wird_aufgerundet():
    """Abrunden ergäbe einen Versuch, der garantiert wieder ins 429 läuft."""
    assert entscheidung(treffer=3, aeltester=JETZT - 10.5).retry_after == 50


def test_retry_after_ist_nie_null():
    """Ein „Retry-After: 0" liest sich als „sofort nochmal" — und läuft sofort
    wieder in die Sperre."""
    e = entscheidung(treffer=3, aeltester=JETZT - 60)
    assert e.retry_after >= 1


def test_retry_after_ohne_zeitstempel_nennt_das_ganze_fenster():
    """Lieber zu lange warten lassen als eine erfundene kurze Zahl nennen."""
    assert entscheidung(treffer=3, aeltester=None).retry_after == 60


def test_grenze_kippt_genau_am_limit_nicht_davor():
    """Der eigentliche Off-by-one-Test: bei limit=N ist der N-te Aufruf noch
    erlaubt und erst der N+1-te nicht."""
    for name, regel in LIMITS.items():
        letzter_erlaubter = entscheide(
            treffer_im_fenster=regel.limit - 1, aeltester_treffer=JETZT, jetzt=JETZT, regel=regel
        )
        erster_abgewiesener = entscheide(
            treffer_im_fenster=regel.limit, aeltester_treffer=JETZT, jetzt=JETZT, regel=regel
        )
        assert letzter_erlaubter.erlaubt, f"{name}: der {regel.limit}. Versuch muss durch"
        assert not erster_abgewiesener.erlaubt, f"{name}: der {regel.limit + 1}. darf nicht"


def test_gleitendes_fenster_hat_keinen_doppelschlag_an_der_grenze():
    """Der Grund, warum es kein festes Fenster (INCR + EXPIRE) ist.

    Festes Fenster: fünf Treffer kurz vor dem Wechsel, fünf direkt danach —
    zehn in einer Sekunde. Gleitend zählen die alten Treffer weiter, solange
    sie im Fenster liegen, und der elfte wird abgewiesen.
    """
    regel = Regel(limit=5, fenster_sekunden=60)
    # Fünf Treffer liegen 59 s zurück, sind also noch im Fenster.
    e = entscheide(
        treffer_im_fenster=5, aeltester_treffer=JETZT - 59, jetzt=JETZT, regel=regel
    )
    assert not e.erlaubt
    assert e.retry_after == 1  # in einer Sekunde fällt der älteste raus


def test_abgewiesener_versuch_verlaengert_die_sperre_nicht():
    """Zweimal abgewiesen bei gleichem Fensterinhalt heißt: dieselbe Wartezeit,
    nur um die vergangene Zeit kürzer. Wäre der abgewiesene Versuch mitgezählt
    worden, stünde der ältere Treffer später und die Sperre würde wandern.
    """
    erst = entscheidung(treffer=3, aeltester=JETZT - 10)
    spaeter = entscheidung(treffer=3, aeltester=JETZT - 10, jetzt=JETZT + 5)
    assert spaeter.retry_after == erst.retry_after - 5
