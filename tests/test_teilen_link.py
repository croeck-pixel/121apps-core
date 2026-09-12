"""Selbsttest für den Teilen-Link-Kanon.

Warum das ein Gate braucht: Die Fehler dieser Klasse sind still. Ein Link ohne
Ablauf funktioniert — für immer. Ein Widerruf mit Karenz funktioniert auch,
nur eben nicht sofort, und genau das merkt niemand, solange niemand hinsieht.
Und ein Zustand, der nach außen dringt, sieht aus wie eine hilfreiche
Fehlermeldung, bis jemand damit fremde Berichte abzählt.

Die Tests prüfen deshalb nicht „läuft durch", sondern die vier Entscheidungen,
die den Kanon ausmachen — jede mit ihrer Gegenprobe.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from teilen_link import (  # noqa: E402
    DEFAULT_GUELTIG,
    MAX_GUELTIG,
    RATE_LIMIT_JE_MINUTE,
    LINK_PRAEFIX,
    TeilenLinkFehler,
    Zustand,
    erzeugen,
    hashen,
    ist_gueltig,
    passt,
    utc_jetzt,
    verbleibend,
    wohlgeformt,
    zustand,
)

JETZT = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Erzeugen
# ---------------------------------------------------------------------------


def test_token_traegt_das_praefix_und_ist_wohlgeformt():
    neu = erzeugen(jetzt=JETZT)
    assert neu.token.startswith(LINK_PRAEFIX)
    assert wohlgeformt(neu.token)


def test_zwei_links_sind_verschieden():
    """Klingt banal — wäre die Quelle nicht `secrets`, sondern eine Uhr oder
    ein Zähler, kämen zwei gleichzeitig erzeugte Links identisch heraus."""
    a = erzeugen(jetzt=JETZT)
    b = erzeugen(jetzt=JETZT)
    assert a.token != b.token
    assert a.token_hash != b.token_hash


def test_der_klartext_wird_nicht_gespeichert():
    """Der Hash darf den Token nicht enthalten — sonst wäre die Datenbank ein
    Klartext-Speicher mit Zusatzschritten."""
    neu = erzeugen(jetzt=JETZT)
    assert neu.token not in neu.token_hash
    assert neu.token_hash == hashen(neu.token)
    assert len(neu.token_hash) == 64


def test_ablauf_wird_gesetzt_und_folgt_der_vorgabe():
    neu = erzeugen(jetzt=JETZT)
    assert neu.laeuft_ab_am == JETZT + DEFAULT_GUELTIG


def test_unbegrenzt_gibt_es_nicht():
    """Entscheidung 1: Es MUSS unmöglich sein, einen ewigen Link zu erzeugen."""
    with pytest.raises(TeilenLinkFehler):
        erzeugen(jetzt=JETZT, gueltig=MAX_GUELTIG + timedelta(days=1))
    with pytest.raises(TeilenLinkFehler):
        erzeugen(jetzt=JETZT, gueltig=timedelta(0))
    with pytest.raises(TeilenLinkFehler):
        erzeugen(jetzt=JETZT, gueltig=timedelta(days=-1))


def test_naive_zeit_wird_abgelehnt():
    """Eine Uhr ohne Zeitzone erzeugt einen Ablauf, der je nach Serverstandort
    Stunden daneben liegt — lieber laut scheitern."""
    with pytest.raises(TeilenLinkFehler):
        erzeugen(jetzt=datetime(2026, 6, 15, 12, 0))


# ---------------------------------------------------------------------------
# Vergleichen
# ---------------------------------------------------------------------------


def test_passender_token_passt_und_fremder_nicht():
    neu = erzeugen(jetzt=JETZT)
    assert passt(neu.token, neu.token_hash)
    assert not passt(erzeugen(jetzt=JETZT).token, neu.token_hash)


def test_unsinn_erreicht_die_datenbank_gar_nicht():
    """`wohlgeformt` ist der Türsteher vor dem öffentlichen Endpunkt."""
    for müll in ("", "   ", "sk_mkt_abc", "st_", "st_zu-kurz", "../../etc/passwd", None):
        assert not wohlgeformt(müll)  # type: ignore[arg-type]
        assert not passt(müll, "egal")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Zustand — die eigentliche Fachlogik
# ---------------------------------------------------------------------------


def _zustand(**abweichung):
    basis = dict(
        hash_passt=True,
        widerrufen_am=None,
        laeuft_ab_am=JETZT + timedelta(days=1),
        jetzt=JETZT,
    )
    basis.update(abweichung)
    return zustand(**basis)


def test_gueltiger_link_gilt():
    assert _zustand() is Zustand.GUELTIG
    assert ist_gueltig(
        hash_passt=True, widerrufen_am=None, laeuft_ab_am=JETZT + timedelta(days=1), jetzt=JETZT
    )


def test_unbekannter_hash_ist_unbekannt():
    assert _zustand(hash_passt=False) is Zustand.UNBEKANNT


def test_abgelaufener_link_gilt_nicht():
    assert _zustand(laeuft_ab_am=JETZT - timedelta(seconds=1)) is Zustand.ABGELAUFEN


def test_exakt_zum_ablaufzeitpunkt_ist_schon_zu():
    """Die Grenze gehört nach unten: „gilt bis 12:00" heißt um 12:00:00 nicht
    mehr. Andernfalls hinge die Antwort an der Auflösung der Uhr."""
    assert _zustand(laeuft_ab_am=JETZT) is Zustand.ABGELAUFEN


def test_widerruf_wirkt_sofort_ohne_karenz():
    """Entscheidung 2. Anders als beim rotierten API-Schlüssel gibt es hier
    KEINE Übergangsfrist — der Widerruf ist der Zweck."""
    assert _zustand(widerrufen_am=JETZT) is Zustand.WIDERRUFEN
    assert _zustand(widerrufen_am=JETZT - timedelta(seconds=1)) is Zustand.WIDERRUFEN


def test_widerruf_schlaegt_ablauf():
    """Beides zugleich → im Protokoll steht die HANDLUNG, nicht der Zeitablauf."""
    assert (
        _zustand(widerrufen_am=JETZT - timedelta(days=2), laeuft_ab_am=JETZT - timedelta(days=1))
        is Zustand.WIDERRUFEN
    )


def test_fehlendes_ablaufdatum_gilt_als_zu():
    """Im Zweifel zu: ein `NULL` aus einem Altbestand oder einer vergessenen
    Migration darf keinen ewigen Zugang erzeugen."""
    assert _zustand(laeuft_ab_am=None) is Zustand.ABGELAUFEN


def test_alle_fehlzustaende_sind_fuer_den_aufrufer_ununterscheidbar():
    """Entscheidung 3, als ausführbare Regel: `ist_gueltig` darf nur zwei
    Antworten kennen. Wer den Grund braucht, ruft `zustand` — und zwar fürs
    Protokoll, nicht für die Antwort."""
    faelle = [
        dict(hash_passt=False),
        dict(laeuft_ab_am=JETZT - timedelta(days=1)),
        dict(widerrufen_am=JETZT),
        dict(laeuft_ab_am=None),
    ]
    for fall in faelle:
        basis = dict(
            hash_passt=True, widerrufen_am=None, laeuft_ab_am=JETZT + timedelta(days=1), jetzt=JETZT
        )
        basis.update(fall)
        assert ist_gueltig(**basis) is False
        assert zustand(**basis) is not Zustand.GUELTIG


# ---------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------


def test_verbleibende_zeit_wird_nie_negativ():
    assert verbleibend(JETZT + timedelta(days=3), JETZT) == timedelta(days=3)
    assert verbleibend(JETZT - timedelta(days=3), JETZT) == timedelta(0)
    assert verbleibend(None, JETZT) == timedelta(0)


def test_uhr_ist_zeitzonenbehaftet():
    assert utc_jetzt().tzinfo is not None


def test_grenzwerte_sind_gesetzt_und_plausibel():
    """Die Zahlen sind der Kanon. Wer sie ändert, ändert ihn flottenweit —
    dieser Test macht das zu einer bewussten Handlung statt zu einem Tippfehler."""
    assert DEFAULT_GUELTIG == timedelta(days=30)
    assert MAX_GUELTIG == timedelta(days=365)
    assert DEFAULT_GUELTIG < MAX_GUELTIG
    assert RATE_LIMIT_JE_MINUTE == 60
