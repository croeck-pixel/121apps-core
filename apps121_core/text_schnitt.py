"""Text in überlappende Abschnitte schneiden — die eine Fassung für die Flotte.

Herkunft: ``support-app/backend/app/services/document_chunker.py``. Hierher
gezogen, weil jede App mit Suche über eigene Dokumente denselben Schnitt
braucht und drei Fassungen davon drei verschiedene Trefferqualitäten bedeuten.

**Das Verfahren.** Zuerst an Absätzen trennen — dort liegen die inhaltlichen
Grenzen ohnehin. Dann benachbarte Absätze zu Abschnitten von etwa
``ziel_tokens`` zusammenlegen, mit ``ueberlappung_tokens`` Übergang zum
nächsten. Ein einzelner Absatz, der schon zu lang ist, wird an Satzgrenzen
zerlegt; hilft auch das nicht, hart am Tokenfenster.

Die Überlappung ist nicht Verschwendung, sondern der Grund, warum eine Frage
gefunden wird, deren Antwort quer über eine Abschnittsgrenze läuft.

**Der Tokenzähler wird hereingereicht, nicht geraten.** Wer nach Zeichen
schneidet, trifft die Grenzen der Modelle nicht: Kontextfenster und Preise
rechnen in Tokens, und ein deutscher Text hat pro Zeichen deutlich mehr Tokens
als ein englischer. Es gibt hier bewusst **keinen Rückfall auf Zeichenzählung**
(Regel #7) — ein Schnitt, der still ein anderes Maß benutzt, erzeugt zu lange
Abschnitte, die der Anbieter kommentarlos abschneidet. Der abgeschnittene Teil
ist danach nicht auffindbar, und niemand sieht einen Fehler.

**Wofür die Zählung taugt und wofür nicht.** ``cl100k_base`` ist das Maß der
OpenAI-Modelle; für Jina, Mistral oder Cohere ist es eine Näherung. Für die
Schnittgröße reicht das. **Für die Abrechnung nicht** — dort gilt, was der
Anbieter in seiner Antwort meldet, nie eine eigene Schätzung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

__all__ = [
    "Abschnitt",
    "Tokenzaehler",
    "tiktoken_zaehler",
    "schneiden",
    "ZIEL_TOKENS",
    "UEBERLAPPUNG_TOKENS",
]


class Tokenzaehler(Protocol):
    """Was der Schnitt von einem Tokenizer braucht — mehr nicht."""

    def encode(self, text: str) -> Sequence[int]: ...

    def decode(self, tokens: Sequence[int]) -> str: ...


def tiktoken_zaehler(kodierung: str = "cl100k_base") -> Tokenzaehler:
    """Der Zähler der OpenAI-Modelle.

    Wirft mit klarer Ansage, wenn ``tiktoken`` fehlt — statt still auf
    Zeichenzählung zu wechseln.
    """
    try:
        import tiktoken
    except ModuleNotFoundError as fehler:  # pragma: no cover - Umgebungsfrage
        raise RuntimeError(
            "tiktoken ist nicht installiert. Entweder installieren "
            "(pip install tiktoken) oder einen eigenen Tokenzaehler an "
            "schneiden() übergeben — geschätzt wird hier nicht."
        ) from fehler
    return tiktoken.get_encoding(kodierung)


#: 800 Tokens sind grob 600 Wörter, also drei bis fünf kurze Absätze — groß
#: genug, dass ein Gedanke zusammenbleibt, klein genug, dass die Antwort nicht
#: in Beiwerk ertrinkt.
ZIEL_TOKENS = 800
#: Rund ein Zehntel Übergang. Weniger reißt Sätze auseinander, deutlich mehr
#: verdoppelt Speicher und Einbettungskosten ohne bessere Treffer.
UEBERLAPPUNG_TOKENS = 80


@dataclass(frozen=True, slots=True)
class Abschnitt:
    index: int
    inhalt: str
    tokens: int


_ABSATZ_RE = re.compile(r"\n\s*\n+")
#: Nach Satzzeichen trennen. Ob dahinter wirklich ein neuer Satz beginnt,
#: entscheidet :func:`_beginnt_satz` — und zwar unicode-fähig.
_SATZENDE_RE = re.compile(r"(?<=[.!?])\s+")
#: Anführungszeichen und Klammern, die vor dem ersten Buchstaben stehen dürfen.
_OEFFNER = "\"'«»„“”‚‘’([{"


def _beginnt_satz(text: str) -> bool:
    """Ob ``text`` wie ein neuer Satz aussieht.

    **Warum keine Zeichenklasse.** Die Vorlage prüfte ``[A-ZÄÖÜ]`` — das trägt
    für Deutsch und Englisch und lässt die neun übrigen Flottensprachen fallen:
    Ein polnischer Satz, der mit „Łącznie" beginnt, ein dänischer mit „Året",
    ein französischer mit „État" wurde nicht als Satzanfang erkannt. Der lange
    Absatz blieb dann ungeteilt und wurde am Ende hart am Tokenfenster
    abgeschnitten — mitten im Wort. ``str.isupper()`` kennt das ganze Alphabet.

    Ziffern gelten nicht als Satzanfang: „z. B. 5 Stück" würde sonst getrennt.
    Nicht zu trennen ist die harmlosere Richtung.
    """
    for zeichen in text:
        if zeichen.isspace() or zeichen in _OEFFNER:
            continue
        return zeichen.isalpha() and zeichen.isupper()
    return False


def _saetze(absatz: str) -> list[str]:
    """Absatz in Sätze — Trennstellen ohne Großbuchstaben dahinter fallen weg."""
    teile = _SATZENDE_RE.split(absatz)
    zusammen: list[str] = []
    for teil in teile:
        if zusammen and not _beginnt_satz(teil):
            # Kein echter Satzanfang: Die Trennung war eine Abkürzung
            # („Dr.", „z. B.", „Nr.") und wird zurückgenommen.
            zusammen[-1] = f"{zusammen[-1]} {teil}"
        else:
            zusammen.append(teil)
    return [t.strip() for t in zusammen if t.strip()]


def _absaetze(text: str) -> list[str]:
    return [a.strip() for a in _ABSATZ_RE.split(text) if a.strip()]


def _langen_absatz_teilen(
    absatz: str, max_tokens: int, zaehler: Tokenzaehler
) -> list[str]:
    """Einen zu langen Absatz an Satzgrenzen zerlegen.

    Ist selbst ein einzelner Satz zu lang, wird hart am Tokenfenster
    geschnitten. Das ist hässlich, aber es ist die Stelle, an der es sichtbar
    hässlich sein soll — die Alternative wäre ein vom Anbieter still gekürzter
    Abschnitt.
    """
    ergebnis: list[str] = []
    puffer: list[str] = []
    puffer_tokens = 0

    for satz in _saetze(absatz):
        satz_tokens = len(zaehler.encode(satz))
        if satz_tokens > max_tokens:
            if puffer:
                ergebnis.append(" ".join(puffer))
                puffer, puffer_tokens = [], 0
            ids = zaehler.encode(satz)
            for start in range(0, len(ids), max_tokens):
                ergebnis.append(zaehler.decode(ids[start : start + max_tokens]))
            continue
        if puffer and puffer_tokens + satz_tokens > max_tokens:
            ergebnis.append(" ".join(puffer))
            puffer, puffer_tokens = [], 0
        puffer.append(satz)
        puffer_tokens += satz_tokens

    if puffer:
        ergebnis.append(" ".join(puffer))
    return ergebnis


def schneiden(
    text: str,
    *,
    zaehler: Tokenzaehler,
    ziel_tokens: int = ZIEL_TOKENS,
    ueberlappung_tokens: int = UEBERLAPPUNG_TOKENS,
) -> list[Abschnitt]:
    """Text in überlappende Abschnitte schneiden.

    :param zaehler: Pflicht, kein Standardwert — siehe Modulkopf.
    :param ziel_tokens: Richtgröße je Abschnitt. Muss zum Kontextfenster des
        Embedding-Modells passen (siehe ``embedding_modelle``).
    :param ueberlappung_tokens: Übergang zwischen zwei Abschnitten. ``0``
        schaltet ihn ab.

    Leerer oder nur aus Leerraum bestehender Text ergibt eine leere Liste —
    das ist kein Fehler, sondern ein Dokument ohne Textebene (etwa ein
    gescanntes PDF). Wer das als Fehler behandeln will, prüft die Länge; hier
    still eine Ausnahme zu werfen, würde eine ganze Stapelverarbeitung an
    einem einzigen Bild-PDF anhalten.
    """
    if ziel_tokens <= 0:
        raise ValueError(f"ziel_tokens muss positiv sein, ist {ziel_tokens}")
    if ueberlappung_tokens < 0:
        raise ValueError(
            f"ueberlappung_tokens darf nicht negativ sein, ist {ueberlappung_tokens}"
        )
    if ueberlappung_tokens >= ziel_tokens:
        # Sonst trägt jeder Abschnitt den ganzen vorigen mit und der Schnitt
        # kommt nie voran — im schlimmsten Fall eine Endlosschleife.
        raise ValueError(
            f"ueberlappung_tokens ({ueberlappung_tokens}) muss kleiner sein als "
            f"ziel_tokens ({ziel_tokens})"
        )
    if not text or not text.strip():
        return []

    # Schritt 1: Absätze, zu lange davon zerlegt.
    teile: list[tuple[str, int]] = []
    for absatz in _absaetze(text):
        absatz_tokens = len(zaehler.encode(absatz))
        if absatz_tokens <= ziel_tokens:
            teile.append((absatz, absatz_tokens))
        else:
            for stueck in _langen_absatz_teilen(absatz, ziel_tokens, zaehler):
                teile.append((stueck, len(zaehler.encode(stueck))))

    if not teile:
        return []

    # Schritt 2: gierig zu Abschnitten zusammenlegen.
    abschnitte: list[Abschnitt] = []
    puffer: list[str] = []
    puffer_tokens = 0
    index = 0

    for stueck, stueck_tokens in teile:
        if puffer and puffer_tokens + stueck_tokens > ziel_tokens:
            inhalt = "\n\n".join(puffer)
            abschnitte.append(Abschnitt(index=index, inhalt=inhalt, tokens=puffer_tokens))
            index += 1

            if ueberlappung_tokens > 0:
                schwanz_ids = zaehler.encode(inhalt)[-ueberlappung_tokens:]
                puffer = [zaehler.decode(schwanz_ids)]
                puffer_tokens = len(schwanz_ids)
            else:
                puffer, puffer_tokens = [], 0

        puffer.append(stueck)
        puffer_tokens += stueck_tokens

    if puffer:
        abschnitte.append(
            Abschnitt(index=index, inhalt="\n\n".join(puffer), tokens=puffer_tokens)
        )

    return abschnitte
