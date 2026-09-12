"""Selbsttest für den Textschnitt.

Warum das ein Gate braucht: Ein falscher Schnitt ist unsichtbar. Die
Verarbeitung läuft durch, die Abschnitte werden gespeichert, die Suche
antwortet — nur eben an der Stelle nicht, an der die Antwort steht. Ohne Test
merkt man das erst, wenn ein Kunde sagt „das steht doch in meinem Handbuch".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from text_schnitt import (  # noqa: E402
    UEBERLAPPUNG_TOKENS,
    ZIEL_TOKENS,
    Abschnitt,
    schneiden,
)


class WortZaehler:
    """Ein Token je Wort — deterministisch und ohne tiktoken.

    Der Schnitt bekommt seinen Zähler hereingereicht; genau deshalb braucht
    dieser Test keine Modelldatei und läuft in jeder Umgebung gleich.
    """

    def encode(self, text: str) -> list[int]:
        # Die Wörter selbst müssen rekonstruierbar bleiben, weil decode() für
        # die Überlappung gebraucht wird. Deshalb ein Wortverzeichnis statt
        # einer Streuwertfunktion.
        ids = []
        for wort in text.split(" "):
            if wort not in self._index:
                self._index[wort] = len(self._worte)
                self._worte.append(wort)
            ids.append(self._index[wort])
        return ids

    def decode(self, tokens) -> str:
        return " ".join(self._worte[t] for t in tokens)

    def __init__(self) -> None:
        self._worte: list[str] = []
        self._index: dict[str, int] = {}


@pytest.fixture
def zaehler() -> WortZaehler:
    return WortZaehler()


def absatz(woerter: int, wort: str = "wort") -> str:
    return " ".join(f"{wort}{i}" for i in range(woerter))


def test_leerer_text_ergibt_nichts(zaehler):
    assert schneiden("", zaehler=zaehler) == []
    assert schneiden("   \n\n  \t ", zaehler=zaehler) == []


def test_kurzer_text_bleibt_ein_abschnitt(zaehler):
    abschnitte = schneiden("Ein kurzer Satz.", zaehler=zaehler)
    assert len(abschnitte) == 1
    assert abschnitte[0].inhalt == "Ein kurzer Satz."
    assert abschnitte[0].index == 0


def test_absaetze_werden_zusammengelegt_bis_zum_ziel(zaehler):
    text = "\n\n".join(absatz(30, f"a{i}_") for i in range(6))
    abschnitte = schneiden(text, zaehler=zaehler, ziel_tokens=100, ueberlappung_tokens=0)
    assert len(abschnitte) > 1
    # Kein Abschnitt überschreitet das Ziel nennenswert: Der letzte
    # hinzugefügte Teil darf es reißen, aber nur um dessen eigene Größe.
    assert all(a.tokens <= 100 + 30 for a in abschnitte)


def test_indizes_sind_lueckenlos_und_aufsteigend(zaehler):
    text = "\n\n".join(absatz(40, f"b{i}_") for i in range(10))
    abschnitte = schneiden(text, zaehler=zaehler, ziel_tokens=200)
    assert [a.index for a in abschnitte] == list(range(len(abschnitte)))


def test_ueberlappung_traegt_den_schwanz_weiter(zaehler):
    text = "\n\n".join(absatz(50, f"c{i}_") for i in range(4))
    ohne = schneiden(text, zaehler=zaehler, ziel_tokens=60, ueberlappung_tokens=0)
    mit = schneiden(text, zaehler=zaehler, ziel_tokens=60, ueberlappung_tokens=10)

    # Mit Überlappung beginnt der zweite Abschnitt mit dem Ende des ersten.
    schwanz = " ".join(mit[0].inhalt.split(" ")[-10:])
    assert mit[1].inhalt.startswith(schwanz)
    # Ohne Überlappung gerade nicht — sonst prüfte der Test nichts.
    assert not ohne[1].inhalt.startswith(schwanz)


def test_zu_langer_absatz_wird_an_satzgrenzen_geteilt(zaehler):
    lang = " ".join(f"Satz nummer {i} steht hier." for i in range(40))
    abschnitte = schneiden(lang, zaehler=zaehler, ziel_tokens=20, ueberlappung_tokens=0)
    assert len(abschnitte) > 1
    # An Satzgrenzen geteilt heißt: kein Abschnitt endet mitten im Satz.
    assert all(a.inhalt.rstrip().endswith(".") for a in abschnitte)


def test_einzelner_ueberlanger_satz_wird_hart_geschnitten(zaehler):
    # Ein Satz ohne jedes Satzzeichen, länger als das Fenster.
    riese = absatz(100, "x")
    abschnitte = schneiden(riese, zaehler=zaehler, ziel_tokens=10, ueberlappung_tokens=0)
    assert len(abschnitte) >= 10
    # Nichts geht verloren: Alle Wörter sind noch da, in Reihenfolge.
    assert " ".join(a.inhalt for a in abschnitte) == riese


@pytest.mark.parametrize(
    "satzanfang,sprache",
    [
        ("Łącznie mamy tutaj wynik.", "polnisch"),
        ("Året var ganske godt her.", "dänisch"),
        ("État des lieux tout complet.", "französisch"),
        ("Årsredovisning för hela året.", "schwedisch"),
        ("Ñandú corre por el campo.", "spanisch"),
        ("Über allen Gipfeln ist Ruh.", "deutsch"),
        ("Ordinary English sentence here.", "englisch"),
    ],
)
def test_satzgrenze_auch_ausserhalb_des_deutschen_alphabets(zaehler, satzanfang, sprache):
    """Die Vorlage prüfte ``[A-ZÄÖÜ]`` — neun der elf Sprachen fielen durch.

    Ein Absatz aus zwei Sätzen, der zu lang für einen Abschnitt ist, muss an
    der Satzgrenze geteilt werden. Wird der zweite Satzanfang nicht erkannt,
    bleibt der Absatz ungeteilt und wird hart am Tokenfenster geschnitten —
    mitten im Wort.
    """
    erster = "Der erste Satz ist ausreichend lang gebaut fuer diesen Zweck."
    abschnitte = schneiden(
        f"{erster} {satzanfang}", zaehler=zaehler, ziel_tokens=11, ueberlappung_tokens=0
    )
    assert len(abschnitte) == 2, f"{sprache}: nicht an der Satzgrenze geteilt"
    assert abschnitte[0].inhalt == erster
    assert abschnitte[1].inhalt == satzanfang


def test_abkuerzung_trennt_nicht(zaehler):
    """„z. B." und „Nr." beenden keinen Satz — dahinter steht klein weiter."""
    text = "Wir liefern z.B. schnell und zwar sehr. Der zweite Satz kommt hier."
    abschnitte = schneiden(text, zaehler=zaehler, ziel_tokens=8, ueberlappung_tokens=0)
    # Geteilt wird nur am echten Satzende, nicht nach „z.B.".
    assert abschnitte[0].inhalt == "Wir liefern z.B. schnell und zwar sehr."


def test_ziffer_ist_kein_satzanfang(zaehler):
    """Nicht zu trennen ist die harmlosere Richtung."""
    text = "Wir liefern ca. 5 Stueck pro Woche aus. Danach ist Schluss."
    abschnitte = schneiden(text, zaehler=zaehler, ziel_tokens=9, ueberlappung_tokens=0)
    assert abschnitte[0].inhalt == "Wir liefern ca. 5 Stueck pro Woche aus."


def test_ueberlappung_kleiner_als_ziel_wird_erzwungen(zaehler):
    """Sonst trägt jeder Abschnitt den ganzen vorigen — der Schnitt käme nie voran."""
    with pytest.raises(ValueError, match="kleiner"):
        schneiden("egal", zaehler=zaehler, ziel_tokens=10, ueberlappung_tokens=10)


@pytest.mark.parametrize(
    "kwargs,muster",
    [
        ({"ziel_tokens": 0}, "positiv"),
        ({"ziel_tokens": -5}, "positiv"),
        ({"ueberlappung_tokens": -1}, "negativ"),
    ],
)
def test_unsinnige_masse_werfen(zaehler, kwargs, muster):
    with pytest.raises(ValueError, match=muster):
        schneiden("egal", zaehler=zaehler, **kwargs)


def test_zaehler_ist_pflicht():
    """Kein Standardzähler: Zeichenzählung wäre ein stiller Rückfall (Regel #7)."""
    with pytest.raises(TypeError):
        schneiden("egal")  # type: ignore[call-arg]


def test_abschnitt_ist_unveraenderlich(zaehler):
    a = schneiden("Kurz.", zaehler=zaehler)[0]
    assert isinstance(a, Abschnitt)
    with pytest.raises((AttributeError, TypeError)):
        a.inhalt = "anders"  # type: ignore[misc]


def test_vorgaben_passen_zusammen():
    assert 0 < UEBERLAPPUNG_TOKENS < ZIEL_TOKENS
