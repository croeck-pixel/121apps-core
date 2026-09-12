"""Selbsttest für die Sprach- und Länderkette.

Warum das ein Gate braucht: Der Fehlerfall ist geräuschlos. Wer die falsche
Sprache bekommt, sieht eine Seite, die für ihn schlicht fremdsprachig ist —
kein Log, keine Ausnahme, oft nicht einmal eine Beschwerde. Fünf Apps hatten
fünf verschiedene Fassungen dieser Kette, und niemandem ist es aufgefallen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from locale_resolver import (  # noqa: E402
    LAND_STANDARDSPRACHE,
    SPRACHE_HEIMATLAND,
    Sprachraum,
    bestimme_land,
    bestimme_sprache,
    heimatland,
    normalisiere_land,
    normalisiere_sprache,
    sprache_aus_accept_language,
)

FLOTTE = Sprachraum(
    sprachen=("de", "en", "fr", "it", "es", "nl", "pl", "sv", "da", "no", "pt"),
    standard_sprache="en",
    standard_land="GB",
)
#: Eine App, die bewusst weniger führt — der häufigere Fall.
KLEIN = Sprachraum(sprachen=("de", "en"), standard_sprache="de")


# ── Der Sprachraum selbst ───────────────────────────────────────────────────


def test_standardsprache_muss_gefuehrt_werden():
    """Sonst liefert die Kette am Ende eine Sprache, für die es keine Texte
    gibt — und das fällt erst dem Besucher auf."""
    with pytest.raises(ValueError):
        Sprachraum(sprachen=("de", "en"), standard_sprache="fr")


# ── Normalisieren ───────────────────────────────────────────────────────────


def test_regionale_kennung_faellt_weg():
    assert normalisiere_sprache("de-DE", raum=KLEIN) == "de"
    assert normalisiere_sprache("EN-gb", raum=KLEIN) == "en"


def test_ungefuehrte_sprache_gilt_als_kein_signal():
    """Nicht „irgendwas Ähnliches", sondern nichts — dann greift die nächste
    Stufe der Kette, sichtbar statt heimlich."""
    assert normalisiere_sprache("fr", raum=KLEIN) is None
    assert normalisiere_sprache("", raum=KLEIN) is None
    assert normalisiere_sprache(None, raum=KLEIN) is None


def test_land_wird_gross_geschrieben_und_geprueft():
    assert normalisiere_land("ch") == "CH"
    assert normalisiere_land("CHE") is None
    assert normalisiere_land("D1") is None
    assert normalisiere_land(None) is None


# ── Accept-Language ─────────────────────────────────────────────────────────


def test_hoechstes_gewicht_gewinnt():
    """Browser schicken die Zweitsprache regelmäßig zuerst, wenn die
    Erstsprache regional gekennzeichnet ist."""
    header = "en;q=0.8,de-DE;q=0.9"
    assert sprache_aus_accept_language(header, raum=KLEIN) == "de"


def test_bei_gleichstand_zaehlt_die_reihenfolge():
    assert sprache_aus_accept_language("en,de", raum=KLEIN) == "en"
    assert sprache_aus_accept_language("de,en", raum=KLEIN) == "de"


def test_unlesbares_gewicht_landet_hinten():
    """Nicht „egal", sondern ganz hinten: Ein kaputter Wert darf keine Sprache
    nach vorn schieben."""
    assert sprache_aus_accept_language("de;q=kaputt,en;q=0.5", raum=KLEIN) == "en"


def test_nur_ungefuehrte_sprachen_ergeben_nichts():
    assert sprache_aus_accept_language("fr,it", raum=KLEIN) is None
    assert sprache_aus_accept_language(None, raum=KLEIN) is None


# ── Die Sprachkette ─────────────────────────────────────────────────────────


def test_cookie_schlaegt_alles():
    """Das Cookie ist die Entscheidung des Besuchers — sie zu übergehen wäre
    die häufigste Beschwerde über mehrsprachige Seiten."""
    assert (
        bestimme_sprache(
            cookie="en",
            accept_language="de-DE,de;q=0.9",
            land_vom_proxy="DE",
            raum=KLEIN,
        )
        == "en"
    )


def test_ohne_cookie_entscheidet_der_browser():
    assert (
        bestimme_sprache(
            cookie=None, accept_language="de-AT,de;q=0.9", land_vom_proxy="US", raum=KLEIN
        )
        == "de"
    )


def test_ein_deutschsprachiger_in_zuerich_bekommt_deutsch():
    """Der Fall, für den Sprache und Land getrennt sind."""
    assert (
        bestimme_sprache(
            cookie=None, accept_language="de-DE", land_vom_proxy="CH", raum=FLOTTE
        )
        == "de"
    )


def test_ohne_browsersprache_entscheidet_das_land():
    assert (
        bestimme_sprache(
            cookie=None, accept_language=None, land_vom_proxy="FR", raum=FLOTTE
        )
        == "fr"
    )


def test_landessprache_die_die_app_nicht_fuehrt_wird_uebersprungen():
    """Sonst zeigte die Seite Schlüssel statt Text — der Fehler, den ein
    stiller Rückfall auf Deutsch monatelang verdeckt hätte."""
    assert (
        bestimme_sprache(
            cookie=None, accept_language=None, land_vom_proxy="FR", raum=KLEIN
        )
        == "de"
    )


def test_ganz_ohne_signal_gilt_der_standard():
    assert (
        bestimme_sprache(
            cookie=None, accept_language=None, land_vom_proxy=None, raum=FLOTTE
        )
        == "en"
    )


# ── Die Länderkette ─────────────────────────────────────────────────────────


def test_land_aus_dem_cookie_schlaegt_den_proxy():
    assert (
        bestimme_land(cookie="AT", land_vom_proxy="DE", sprache="de", raum=FLOTTE) == "AT"
    )


def test_ohne_cookie_gilt_das_land_vom_proxy():
    assert (
        bestimme_land(cookie=None, land_vom_proxy="ch", sprache="de", raum=FLOTTE) == "CH"
    )


def test_ohne_laendersignal_das_heimatland_der_sprache():
    """Nicht alphabetisch raten: Deutsch gehört nach DE, nicht nach AT."""
    assert (
        bestimme_land(cookie=None, land_vom_proxy=None, sprache="de", raum=FLOTTE) == "DE"
    )
    assert (
        bestimme_land(cookie=None, land_vom_proxy=None, sprache="fr", raum=FLOTTE) == "FR"
    )
    assert (
        bestimme_land(cookie=None, land_vom_proxy=None, sprache="en", raum=FLOTTE) == "GB"
    )


def test_ganz_ohne_signal_gilt_das_standardland():
    assert (
        bestimme_land(cookie=None, land_vom_proxy=None, sprache="xx", raum=FLOTTE) == "GB"
    )


def test_heimatland_einer_sprache():
    assert heimatland("it", raum=FLOTTE) == "IT"
    assert heimatland("de-DE", raum=FLOTTE) == "DE"
    # Ungeführte Sprache → Standard der App, nicht alphabetisch geraten.
    assert heimatland("fr", raum=KLEIN) == "DE"


# ── Die Tabellen ────────────────────────────────────────────────────────────


def test_jede_sprache_hat_ein_heimatland():
    """Fehlt eines, rutscht die Kette auf das Standardland durch — und ein
    Franzose landet im Vereinigten Königreich."""
    for sprache in FLOTTE.sprachen:
        assert sprache in SPRACHE_HEIMATLAND, sprache


def test_jede_landessprache_ist_eine_flottensprache():
    """Sonst verweist die Tabelle auf eine Sprache, die es nirgends gibt."""
    for land, sprache in LAND_STANDARDSPRACHE.items():
        assert sprache in FLOTTE.sprachen, f"{land} → {sprache}"


def test_die_zuordnungen_widersprechen_sich_nicht():
    """Heimatland → Sprache muss wieder dieselbe Sprache ergeben."""
    for sprache, land in SPRACHE_HEIMATLAND.items():
        assert LAND_STANDARDSPRACHE.get(land) == sprache, f"{sprache} ↔ {land}"
