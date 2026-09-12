"""Selbsttest für die Länder-Erkennung aus Proxy-Headern.

Warum das ein Gate braucht: der Fehlerfall ist geräuschlos. Liefert die Funktion
fälschlich ein Land, sieht die Seite für den Besucher schlicht nach dem falschen
Markt aus — kein Log, keine Ausnahme, keine Beschwerde. Genau so blieb in
paperball-news monatelang unbemerkt, dass jeder Besucher als Deutscher galt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from geo_country import COUNTRY_HEADERS, country_from_headers  # noqa: E402


class Header(dict):
    """Nachbau der Groß-/Kleinschreibung-unabhängigen Header von Starlette."""

    def get(self, key, default=None):  # noqa: D102
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def test_liest_den_header_unseres_nginx():
    assert country_from_headers(Header({"X-Country-Code": "CH"})) == "CH"


def test_gross_klein_egal():
    assert country_from_headers(Header({"x-country-code": "at"})) == "AT"


def test_ohne_header_kein_signal():
    """Kein Rückfall auf eine eigene Auflösung — die Kette geht weiter."""
    assert country_from_headers(Header({})) is None


@pytest.mark.parametrize("wert", ["", "   ", "XX", "T1", "DEU", "D", "12", "D3"])
def test_unbrauchbare_werte_sind_kein_signal(wert):
    assert country_from_headers(Header({"X-Country-Code": wert})) is None


def test_leerzeichen_werden_abgeschnitten():
    assert country_from_headers(Header({"X-Country-Code": " fr "})) == "FR"


def test_reihenfolge_cloudflare_vor_eigenem_header():
    kopf = Header({"CF-IPCountry": "PT", "X-Country-Code": "DE"})
    assert country_from_headers(kopf) == "PT"


def test_unbrauchbarer_erster_header_blockiert_den_zweiten_nicht():
    """Cloudflare schickt bei unbekannter IP „XX" — das darf den eigenen
    Header nicht verdecken, sonst verliert man das Signal ohne Grund."""
    kopf = Header({"CF-IPCountry": "XX", "X-Country-Code": "IT"})
    assert country_from_headers(kopf) == "IT"


def test_reihenfolge_ist_dokumentiert_und_vollstaendig():
    assert COUNTRY_HEADERS == ("cf-ipcountry", "x-country-code", "x-geo-country")
