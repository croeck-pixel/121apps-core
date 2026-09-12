"""Selbsttest für die Sitzungs-Obergrenze.

Warum das ein Gate braucht: die Regel entscheidet, wem der Zugang genommen wird.
Ein Sortierfehler wirft den täglich genutzten Arbeitsrechner statt des einmal
benutzten Handys raus — und niemand meldet das als Bug, weil es wie „ich war
wohl zu lange weg" aussieht.
"""
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from session_cap import (  # noqa: E402
    DEFAULT_MAX_SESSIONS,
    sessions_to_evict,
)

JETZT = datetime(2026, 7, 31, 12, 0, 0)


@dataclass
class S:
    id: str
    last_used_at: datetime | None = None
    created_at: datetime | None = None


def vor(stunden: float) -> datetime:
    return JETZT - timedelta(hours=stunden)


def test_empfehlung_ist_drei():
    """Zwei wäre eins zu wenig: Rechner + Handy sind schon zwei, der Laptop
    würde den Rechner verdrängen."""
    assert DEFAULT_MAX_SESSIONS == 3


def test_unter_der_grenze_wird_nichts_verdraengt():
    aktiv = [S("a", vor(1)), S("b", vor(2))]
    assert sessions_to_evict(aktiv).to_evict == ()


def test_platz_wird_fuer_die_neue_sitzung_freigemacht():
    """Bei 3 aktiven und Grenze 3 muss EINE weichen — sonst wären es danach 4."""
    aktiv = [S("a", vor(1)), S("b", vor(10)), S("c", vor(2))]
    e = sessions_to_evict(aktiv)
    assert e.to_evict == ("b",), "die am längsten unbenutzte"
    assert e.evicts_anything


def test_sortiert_nach_letzter_nutzung_nicht_nach_alter():
    """Der Kern der Regel: der seit Wochen angemeldete, aber täglich genutzte
    Arbeitsrechner darf NICHT dem einmal benutzten Handy weichen."""
    arbeitsrechner = S("arbeit", last_used_at=vor(0.5), created_at=vor(24 * 30))
    handy = S("handy", last_used_at=vor(48), created_at=vor(2))
    laptop = S("laptop", last_used_at=vor(3), created_at=vor(5))
    e = sessions_to_evict([arbeitsrechner, handy, laptop])
    assert e.to_evict == ("handy",)


def test_faellt_auf_created_at_zurueck():
    aktiv = [S("a", None, vor(1)), S("b", None, vor(9)), S("c", None, vor(3))]
    assert sessions_to_evict(aktiv).to_evict == ("b",)


def test_sitzung_ganz_ohne_zeitangabe_geht_zuerst():
    """Über sie ist nichts bekannt — und eine nie benutzte ist der harmloseste
    Kandidat. Vor allem darf der Vergleich None/datetime nicht abstuerzen."""
    aktiv = [S("unbekannt", None, None), S("b", vor(100)), S("c", vor(1))]
    assert sessions_to_evict(aktiv).to_evict == ("unbekannt",)


def test_mehrere_ueberzaehlige_werden_alle_genannt():
    aktiv = [S(str(i), vor(i)) for i in range(1, 7)]  # 6 aktive
    e = sessions_to_evict(aktiv)
    assert len(e.to_evict) == 4, "6 aktive + 1 neue, Grenze 3 → 4 muessen weichen"
    assert e.to_evict == ("6", "5", "4", "3"), "am laengsten unbenutzt zuerst"


def test_geschuetzte_sitzung_wird_nie_verdraengt():
    """Schuetzt davor, dass ein Login sich selbst hinauswirft."""
    aktiv = [S("eigene", vor(99)), S("b", vor(1)), S("c", vor(2))]
    e = sessions_to_evict(aktiv, keep_ids=["eigene"])
    assert "eigene" not in e.to_evict


def test_geschuetzte_zaehlen_nicht_gegen_das_kontingent():
    """Sonst wuerde die eigene Sitzung eine fremde verdraengen, obwohl sie gar
    nicht doppelt gezaehlt gehoert."""
    aktiv = [S("eigene", vor(99)), S("b", vor(1))]
    assert sessions_to_evict(aktiv, keep_ids=["eigene"]).to_evict == ()


def test_grenze_eins_verdraengt_alles_andere():
    aktiv = [S("a", vor(1)), S("b", vor(2))]
    e = sessions_to_evict(aktiv, max_sessions=1)
    assert set(e.to_evict) == {"a", "b"}


def test_grenze_null_ist_ein_fehler():
    with pytest.raises(ValueError):
        sessions_to_evict([], max_sessions=0)


def test_leere_liste_ist_harmlos():
    assert sessions_to_evict([]).to_evict == ()
