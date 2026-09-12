"""Welches Embedding-Modell hat welche Dimension — flottenweit eine Auskunft.

**Warum das ein eigener Baustein ist.** Die Dimension eines Embedding-Modells
ist keine Konfiguration, sondern eine Eigenschaft des Modells: Wer eine Spalte
``vector(1536)`` anlegt und später auf ein 1024-dimensionales Modell wechselt,
muss jeden gespeicherten Vektor neu berechnen. Deshalb darf die Zahl nicht in
jeder App neu geraten werden.

Der Bestand am 07.08.2026 zeigt, wohin das sonst führt:

* ``support-app`` verdrahtet ``text-embedding-3-small`` samt ``Vector(1536)``
  fest im Code — ein anderer Anbieter ist dort nicht vorgesehen.
* ``paperball-news`` legt Vektoren als JSON ab statt als ``vector``; damit gibt
  es keine Dimensionsprüfung und keinen Index.
* Zwei Modelle im paperball-Katalog stehen ohne Dimension da.

**Was dieser Baustein NICHT tut.** Er ruft keine API auf und lädt kein Modell.
Er beantwortet genau eine Frage — „wie breit ist der Vektor" — und stellt eine
Prüfung bereit, mit der eine App die Antwort gegen die echte Schnittstelle
hält.

**Geprüft heißt gemessen.** ``geprueft=False`` bedeutet: Die Zahl stammt aus der
Modellkarte oder der Architektur (verborgene Schichtbreite), nicht aus einer
Antwort der laufenden Schnittstelle. Für ein Feld ``vector(N)`` ist das zu
wenig — ein Tippfehler in der Modellkarte fällt sonst erst auf, wenn schon
Vektoren darin liegen. :func:`fuer_spalte` verweigert deshalb ungeprüfte
Modelle; :func:`dimension_pruefen` ist der Weg, aus ungeprüft geprüft zu
machen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "EmbeddingModell",
    "MODELLE",
    "DimensionFehler",
    "UngepruefteDimension",
    "modell",
    "fuer_spalte",
    "dimension_pruefen",
    "modelle_von",
]


class DimensionFehler(ValueError):
    """Die gemessene Dimension weicht von der hinterlegten ab."""


class UngepruefteDimension(RuntimeError):
    """Ein Modell soll eine Vektorspalte tragen, ist aber nicht gemessen."""


@dataclass(frozen=True, slots=True)
class EmbeddingModell:
    """Ein Embedding-Modell und was man wissen muss, bevor man es benutzt.

    :param anbieter: Schlüssel des Anbieters, wie ihn der Plattform-Katalog
        führt (``platform_providers.key``) — nicht die Implementierung. ``jina``
        spricht das OpenAI-Protokoll, bleibt aber ``jina``.
    :param name: Der Modellname, wie ihn die Schnittstelle erwartet.
    :param dimension: Breite des Vektors.
    :param geprueft: Ob die Dimension gegen eine echte Antwort gemessen wurde.
    :param max_eingabe_tokens: Kontextfenster des Modells. Begrenzt die
        Schnittgröße — ein Abschnitt, der nicht hineinpasst, wird vom Anbieter
        stillschweigend abgeschnitten, und der abgeschnittene Teil ist dann
        nicht auffindbar.
    :param mehrsprachig: Ob das Modell über Englisch hinaus trägt. Für eine
        Flotte in elf Sprachen ist das keine Nebensache: Ein einsprachiges
        Modell liefert für dänische Texte Vektoren, die nur so aussehen, als
        wären sie brauchbar.
    """

    anbieter: str
    name: str
    dimension: int
    geprueft: bool
    max_eingabe_tokens: int
    mehrsprachig: bool
    hinweis: str = ""

    @property
    def schluessel(self) -> str:
        """``anbieter/name`` — eindeutig über alle Anbieter hinweg."""
        return f"{self.anbieter}/{self.name}"


#: Alle bekannten Embedding-Modelle der Flotte.
#:
#: Reihenfolge ist Anzeigereihenfolge. Neue Modelle gehören hierher und nicht
#: in die App — sonst steht dieselbe Zahl bald an fünf Stellen.
MODELLE: tuple[EmbeddingModell, ...] = (
    EmbeddingModell(
        anbieter="openai",
        name="text-embedding-3-small",
        dimension=1536,
        geprueft=True,
        max_eingabe_tokens=8191,
        mehrsprachig=True,
        hinweis="Der Bestand in support-app liegt in dieser Dimension.",
    ),
    EmbeddingModell(
        anbieter="openai",
        name="text-embedding-3-large",
        dimension=3072,
        geprueft=True,
        max_eingabe_tokens=8191,
        mehrsprachig=True,
    ),
    EmbeddingModell(
        anbieter="mistral",
        name="mistral-embed",
        dimension=1024,
        geprueft=True,
        max_eingabe_tokens=8000,
        mehrsprachig=True,
        hinweis="Frankreich; für Kunden mit EU-Auflage die naheliegende Wahl.",
    ),
    EmbeddingModell(
        anbieter="jina",
        name="jina-embeddings-v3",
        dimension=1024,
        geprueft=True,
        max_eingabe_tokens=8192,
        mehrsprachig=True,
        hinweis="Berlin. In paperball-news im Einsatz, dort aber als JSON abgelegt.",
    ),
    EmbeddingModell(
        anbieter="mittwald",
        name="Qwen3-Embedding-8B",
        dimension=4096,
        geprueft=False,
        max_eingabe_tokens=32768,
        mehrsprachig=True,
        hinweis=(
            "4096 ist die verborgene Schichtbreite von Qwen3-8B, nicht gemessen. "
            "Das Modell beherrscht Matroschka-Kürzung — wer kürzt, bekommt eine "
            "andere Dimension und muss sie hier eintragen."
        ),
    ),
    EmbeddingModell(
        anbieter="stackit",
        name="intfloat/e5-mistral-7b-instruct",
        dimension=4096,
        geprueft=False,
        max_eingabe_tokens=32768,
        mehrsprachig=True,
        hinweis="4096 folgt aus dem Mistral-7B-Unterbau, nicht gemessen.",
    ),
)

_NACH_SCHLUESSEL = {m.schluessel: m for m in MODELLE}


def modell(anbieter: str, name: str) -> EmbeddingModell:
    """Das Modell zu Anbieter und Name.

    Wirft, wenn es unbekannt ist. **Kein Rückfall auf ein Standardmodell
    (Regel #7):** Wer versehentlich einen falschen Namen einträgt, bekäme sonst
    Vektoren eines anderen Modells in dieselbe Spalte — nicht auffindbar, aber
    auch nicht als Fehler sichtbar, weil die Dimension zufällig passen kann.
    """
    gefunden = _NACH_SCHLUESSEL.get(f"{anbieter}/{name}")
    if gefunden is None:
        bekannt = ", ".join(sorted(_NACH_SCHLUESSEL))
        raise KeyError(f"Unbekanntes Embedding-Modell {anbieter}/{name}. Bekannt: {bekannt}")
    return gefunden


def modelle_von(anbieter: str) -> tuple[EmbeddingModell, ...]:
    """Alle Modelle eines Anbieters, in Katalogreihenfolge."""
    return tuple(m for m in MODELLE if m.anbieter == anbieter)


def fuer_spalte(anbieter: str, name: str) -> int:
    """Die Dimension für ein ``vector(N)``-Feld — nur für gemessene Modelle.

    Eine Spalte festzulegen ist die eine Entscheidung, die sich später nur mit
    vollständiger Neuberechnung zurücknehmen lässt. Eine Zahl aus einer
    Modellkarte reicht dafür nicht: Erst messen (:func:`dimension_pruefen`),
    dann ``geprueft=True`` eintragen, dann die Spalte anlegen.
    """
    m = modell(anbieter, name)
    if not m.geprueft:
        raise UngepruefteDimension(
            f"{m.schluessel}: Dimension {m.dimension} ist nicht gemessen. "
            f"Erst mit dimension_pruefen() gegen die Schnittstelle halten, "
            f"dann geprueft=True setzen. {m.hinweis}".strip()
        )
    return m.dimension


def dimension_pruefen(anbieter: str, name: str, vektor: Sequence[float]) -> int:
    """Einen echten Antwortvektor gegen den Katalog halten.

    Gedacht für den Vertragstest einer App: einmal einbetten, das Ergebnis
    hierher geben. Stimmt es, ist die Zahl belegt; stimmt es nicht, hat
    entweder der Anbieter das Modell geändert oder der Katalog ist falsch —
    beides muss laut sein, bevor Vektoren gespeichert werden.

    Gibt die geprüfte Dimension zurück, damit der Aufruf als Zusicherung
    lesbar bleibt.
    """
    m = modell(anbieter, name)
    gemessen = len(vektor)
    if gemessen != m.dimension:
        raise DimensionFehler(
            f"{m.schluessel}: Katalog sagt {m.dimension}, Schnittstelle "
            f"liefert {gemessen}. Katalog anpassen ODER Modellname prüfen — "
            f"bevor irgendetwas gespeichert wird."
        )
    return gemessen
