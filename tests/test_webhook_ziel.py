"""Selbsttest für die Zielprüfung ausgehender Webhooks.

Diese Fehlerklasse hat dieselbe unangenehme Eigenschaft wie die OAuth-Regeln:
Sie ist im Betrieb unsichtbar. Eine Prüfung, die `169.254.169.254` durchlässt,
funktioniert für jeden ehrlichen Kunden tadellos — sie fällt erst auf, wenn
jemand sie ausnutzt, und dann stehen die Zugangsdaten des Hosters in einem
fremden Empfänger-Log.

Deshalb prüft dieser Test vor allem, dass die Absagen kommen — und in der
Gegenprobe, dass er nicht einfach alles ablehnt.
"""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from webhook_ziel import HOECHSTLAENGE, ZielFehler, pruefen  # noqa: E402

OEFFENTLICH = "93.184.216.34"


def aufloeser_fuer(*adressen):
    def _auf(host, port, **kwargs):
        return [(None, None, None, "", (a, 443)) for a in adressen]

    return _auf


def wirft_gaierror(host, port, **kwargs):
    raise socket.gaierror("nicht auflösbar")


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://example.com/hook", "webhook:scheme_not_allowed"),
        ("ftp://example.com/hook", "webhook:scheme_not_allowed"),
        ("example.com/hook", "webhook:scheme_not_allowed"),
        ("https://", "webhook:host_missing"),
        ("https://u:p@example.com/h", "webhook:credentials_in_url"),
    ],
)
def test_form_der_adresse(url, code):
    with pytest.raises(ZielFehler) as fehler:
        pruefen(url, aufloeser=aufloeser_fuer(OEFFENTLICH))
    assert fehler.value.code == code


def test_zu_lang():
    url = "https://example.com/" + "x" * HOECHSTLAENGE
    with pytest.raises(ZielFehler) as fehler:
        pruefen(url, aufloeser=aufloeser_fuer(OEFFENTLICH))
    assert fehler.value.code == "webhook:url_too_long"


@pytest.mark.parametrize(
    "adresse",
    [
        "127.0.0.1",  # der eigene Prozess
        "169.254.169.254",  # Metadaten des Hosters
        "10.0.0.5",  # privates Netz
        "192.168.1.1",
        "172.16.0.1",
        "100.64.0.1",  # Carrier-Grade-NAT
        "::1",
        "fd00::1",  # eindeutig lokale IPv6-Adresse
        "0.0.0.0",
        "224.0.0.1",  # Multicast
    ],
)
def test_nichts_von_innen(adresse):
    with pytest.raises(ZielFehler) as fehler:
        pruefen("https://boese.example/h", aufloeser=aufloeser_fuer(adresse))
    assert fehler.value.code == "webhook:host_not_public"


def test_jede_adresse_zaehlt_nicht_nur_die_erste():
    """Die Fassung, die nur den ersten Treffer ansieht, käme hier durch —
    und beim nächsten Aufruf sortiert der Resolver anders."""
    with pytest.raises(ZielFehler) as fehler:
        pruefen(
            "https://doppelt.example/h",
            aufloeser=aufloeser_fuer(OEFFENTLICH, "127.0.0.1"),
        )
    assert fehler.value.code == "webhook:host_not_public"


def test_unaufloesbar_ist_absage():
    """Was wir nicht prüfen können, rufen wir nicht auf."""
    with pytest.raises(ZielFehler) as fehler:
        pruefen("https://gibtsnicht.example/h", aufloeser=wirft_gaierror)
    assert fehler.value.code == "webhook:host_unresolvable"


def test_leere_aufloesung_ist_absage():
    with pytest.raises(ZielFehler) as fehler:
        pruefen("https://leer.example/h", aufloeser=aufloeser_fuer())
    assert fehler.value.code == "webhook:host_unresolvable"


def test_oeffentliche_adresse_geht_durch():
    """Gegenprobe. Ohne sie wäre ein Wächter, der alles ablehnt, grün."""
    pruefen("https://example.com/hook", aufloeser=aufloeser_fuer(OEFFENTLICH))
    pruefen("https://example.com/hook", aufloeser=aufloeser_fuer("2606:2800:220::1"))
