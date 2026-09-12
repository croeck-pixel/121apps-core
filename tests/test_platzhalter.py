"""Selbsttest für den Platzhalter-Schutz.

Warum das ein Gate braucht: der Fehlerfall ist geräuschlos und sitzt in den
Sprachen, die niemand liest. Ein `{compte}` löst keine Ausnahme aus, es steht
einfach da — und `de`/`en`, die als einzige geprüft werden, sind sauber. In
paperball-finance blieben so 1949 Zeilen in neun Sprachen jahrelang kaputt.

Die Gegenproben sind hier wichtiger als die Positivfälle: Ein Wächter, der
alles verwirft, ist genauso nutzlos wie einer, der nichts verwirft.
"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from platzhalter import (  # noqa: E402
    platzhalter_von,
    pruefen,
    schuetzen,
    wiederherstellen,
)


# ---------------------------------------------------------------------------
# Namen lesen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, erwartet", [
    ("{count} Kurse", {"count"}),
    ("{done} / {total} Simulationen", {"done", "total"}),
    ("gar keiner", set()),
    ("", set()),
    (None, set()),
    # Kein Platzhalter im Sinne von `t()`: die Ersetzung kennt nur \w+.
    ("{ count }", set()),
    ("{mit-strich}", set()),
    ("{}", set()),
    # Eine offene Klammer ist keiner — genau der nl-Fall `{Cursussen`.
    ("{Cursussen", set()),
])
def test_platzhalter_von_liest_genau_die_namen(text, erwartet):
    assert platzhalter_von(text) == erwartet


# ---------------------------------------------------------------------------
# Schützen und zurückholen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "{count} Kurse",
    "{done} / {total} Simulationen",
    "Hallo {name}, du hast {n} neue Nachrichten",
    "ohne Platzhalter",
    "{count} mal {count} — derselbe Name zweimal",
    "",
])
def test_schutz_ist_umkehrbar(text):
    assert wiederherstellen(schuetzen(text)) == text


def test_der_schutz_versteckt_den_namen_wirklich():
    """Gegenprobe zum Test darüber: Wäre `{count}` im geschützten Text noch als
    Platzhalter zu sehen, könnte ein Übersetzer ihn weiterhin anfassen — und
    der ganze Umweg wäre Zierde."""
    geschuetzt = schuetzen("{count} Kurse")
    assert "{" not in geschuetzt and "}" not in geschuetzt
    assert geschuetzt == "@@PLACEHOLDER_count@@ Kurse"


def test_leerer_text_faellt_nicht_um():
    """Ein fehlender Text ist ein leerer, kein Absturz mitten im Batch."""
    assert schuetzen(None) == ""
    assert wiederherstellen(None) == ""


def test_ein_schon_geschuetzter_text_wird_nicht_doppelt_geschuetzt():
    assert schuetzen(schuetzen("{count}")) == "@@PLACEHOLDER_count@@"


# ---------------------------------------------------------------------------
# Die Gegenprüfung — genau die Fälle aus der Messung vom 01.09.2026
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("quelle, uebersetzung, sprache", [
    # Umbenannt: 1843 Zeilen. Je eine echte Zeile pro betroffener Sprache.
    ("{count} Kurse", "{compte} cours", "fr"),
    ("{count} Kurse", "{geteld} cursussen", "nl"),
    ("{count} Kurse", "{liczba} kursów", "pl"),
    ("{count} Kurse", "{contagem} cursos", "pt"),
    ("{count} Kurse", "{contar} cursos", "es"),
    ("{count} Kurse", "{telling} kurs", "no"),
    ("{count} Kurse", "{antal} kurser", "da"),
    ("{count} Kurse", "{conteggio} corsi", "it"),
    # Klammer weg: nicht einmal mehr ein Platzhalter.
    ("{count} Kurse", "{Cursussen", "nl"),
    # Ganz weg: 70 Zeilen.
    ("{count} Kurse", "Kurser", "da"),
    # Anzahl abweichend: 36 Zeilen.
    ("{done} / {total}", "{done} von allen", "de"),
])
def test_verbogene_platzhalter_werden_verworfen(quelle, uebersetzung, sprache):
    assert pruefen(quelle, uebersetzung, "k", sprache) == quelle


@pytest.mark.parametrize("quelle, uebersetzung", [
    ("{count} Kurse", "{count} prices"),
    ("{done} / {total} Simulationen", "{total} af {done} simuleringer"),
    ("ohne Platzhalter", "sans espace réservé"),
])
def test_heile_uebersetzung_kommt_durch(quelle, uebersetzung):
    """Gegenprobe: Der Wächter darf nicht alles verwerfen. Der zweite Fall ist
    der Grund, warum nach NAMEN und nicht nach REIHENFOLGE verglichen wird —
    beim Übersetzen darf sich die Stellung im Satz ändern."""
    assert pruefen(quelle, uebersetzung, "k", "xx") == uebersetzung


def test_der_rueckfall_ist_laut(caplog):
    """Regel #7: Ein Rückfall, den niemand sieht, versteckt den eigentlichen
    Fehler. Genau so blieb der Bug jahrelang unentdeckt."""
    with caplog.at_level(logging.ERROR):
        pruefen("{count} Kurse", "{compte} cours", "watchlist.count", "fr")
    assert caplog.records, "der Rückfall wurde stillschweigend genommen"
    satz = caplog.records[0].getMessage()
    assert "watchlist.count" in satz and "fr" in satz


def test_heile_uebersetzung_meldet_nichts(caplog):
    """Gegenprobe: sonst ertrinkt das echte Signal im Rauschen."""
    with caplog.at_level(logging.ERROR):
        pruefen("{count} Kurse", "{count} courses", "k", "en")
    assert not caplog.records


# ---------------------------------------------------------------------------
# Schutz + Prüfung zusammen — so wird es in den Apps verdrahtet
# ---------------------------------------------------------------------------

def test_der_ganze_weg_haelt_einen_uebersetzer_aus_der_den_namen_anfassen_will():
    """Nachbau des echten Ablaufs: schützen → übersetzen → zurückholen → prüfen.

    Der Übersetzer hier ist so gebaut, dass er JEDES Wort übersetzt, das er
    versteht — genau das Verhalten, das die 1949 Zeilen erzeugt hat.
    """
    def gieriger_uebersetzer(text):
        # Wortweise, wie ein Uebersetzer arbeitet. Genau deshalb traegt die
        # Schutzhuelle einen Unterstrich: in `@@PLACEHOLDER_count@@` ist
        # `count` kein eigenes Wort mehr, sondern Teil eines Tokens.
        for wort, ziel in (("count", "compte"), ("Kurse", "cours")):
            text = re.sub(rf"\b{wort}\b", ziel, text)
        return text

    quelle = "{count} Kurse"

    ohne_schutz = pruefen(quelle, gieriger_uebersetzer(quelle), "k", "fr")
    assert ohne_schutz == quelle, "ohne Schutz muss der Wächter greifen"

    mit_schutz = pruefen(
        quelle,
        wiederherstellen(gieriger_uebersetzer(schuetzen(quelle))),
        "k",
        "fr",
    )
    assert mit_schutz == "{count} cours", "mit Schutz überlebt der Name die Übersetzung"
