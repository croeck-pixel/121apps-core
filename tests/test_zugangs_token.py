"""Selbsttest: woher das Access-Token einer Anfrage kommt (FLEET_ADMIN_SPEC §2.2).

Anlass: paperball-finance las in der Schreibsperre nur den Header, die
Auth-Dependency auch das Cookie — seit der Cookie-Umstellung griff die Sperre
nie. Die Tests halten beide Quellen fest, jede mit Gegenprobe.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from zugangs_token import token_der_anfrage  # noqa: E402


def test_nur_cookie_liefert_das_token():
    """Der Befund aus finance: Browser schickt nur das HttpOnly-Cookie."""
    assert token_der_anfrage(None, "abc.def.ghi") == "abc.def.ghi"


def test_nur_header_liefert_das_token():
    assert token_der_anfrage("Bearer abc.def.ghi", None) == "abc.def.ghi"


def test_header_geht_vor_cookie():
    assert token_der_anfrage("Bearer aus-dem-kopf", "aus-dem-cookie") == "aus-dem-kopf"


@pytest.mark.parametrize("kopf", ["bearer x", "BEARER x", "  Bearer   x  "])
def test_bearer_unabhaengig_von_schreibweise(kopf):
    assert token_der_anfrage(kopf, None) == "x"


@pytest.mark.parametrize("kopf", ["Basic dXNlcjpwdw==", "Bearer", "Bearer   ", "x"])
def test_kein_bearer_faellt_aufs_cookie(kopf):
    """Ein fremder Header darf das Cookie nicht verdecken — sonst wäre die
    Sperre mit `Authorization: Basic …` umgehbar."""
    assert token_der_anfrage(kopf, "aus-dem-cookie") == "aus-dem-cookie"


@pytest.mark.parametrize("kopf,cookie", [(None, None), ("", ""), ("Basic x", "  "), (None, "")])
def test_gegenprobe_ohne_token_nichts(kopf, cookie):
    assert token_der_anfrage(kopf, cookie) is None
