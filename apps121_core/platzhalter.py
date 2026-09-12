"""Platzhalter überleben die Übersetzung — mechanisch, nicht auf Zuruf.

`t('watchlist.count', '{count} Wertpapiere', {count: 3})` ersetzt streng nach
NAMEN. Ein Übersetzer — Mensch wie Maschine — sieht in `{count}` aber ein Wort
und übersetzt es mit. Der Name passt dann nicht mehr, die Ersetzung greift nie,
und der Nutzer liest wörtlich „{compte} cours" statt „2.417 cours".

Gemessen am 01.09.2026 auf der Produktion von paperball-finance: **1949
Übersetzungszeilen in neun Sprachen** waren so kaputt.

    fr {compte}   nl {geteld}   pl {liczba}   pt {contagem}
    es {contar}   no {telling}  da {antal}    it {conteggio}

1843 davon mit umbenanntem Platzhalter, 70 ohne jeden Platzhalter, 36 mit
abweichender Anzahl.

Bei einem großen Teil der zweiten Gruppe fehlt sogar die schließende Klammer
(`{Cursussen`, `{Fuentes`, `{latencia: {latencia}ms`) — nachgemessen: 51 von
69, insgesamt 64 solcher Zeilen. Die sind **gar keine Platzhalter mehr** und
tauchen deshalb in keiner Platzhalter-Statistik auf; sie brauchen einen eigenen
Filter über die Klammerbilanz.

**Warum es jahrelang niemand sah:** Deutsch war sauber, und geprüft wird auf
Deutsch. Der Fehler sitzt naturgemäß in den Sprachen, die niemand im Team
liest — eine Stichprobe auf der Pivot-Sprache beweist bei i18n gar nichts.

**Auch Englisch war nicht immun**, nur unauffälliger: aus `${favoritesCount}`
wurde `${favouritesCount}`. Wer „na, EN sieht gut aus" als Beleg nimmt, hat
dieselbe Mechanik übersehen, nur in britischer Rechtschreibung.

**Die Ursache war eine Zuständigkeitslücke, kein Tippfehler.** Der E-Mail-Pfad
schützte seine Platzhalter von Anfang an mechanisch (`{x}` → `@@PLACEHOLDER_x@@`
→ zurück). Der Oberflächen-Pfad hatte stattdessen einen Satz im Prompt stehen:
„Preserve any placeholders like {count}". **Eine Bitte ist keine Garantie.**
Der Unterschied zwischen beiden steht in den Zahlen oben.

Deshalb liegt der Schutz hier und nicht in einer App: Beide paperball-Stacks
haben denselben Übersetzungspfad, und jede App, die je Texte durch DeepL oder
ein Modell schickt, braucht dieselben vier Zeilen (Regel #24).

Benutzung — der Anbieter sieht den Namen nie, und das Ergebnis wird gegengeprüft:

    from platzhalter import pruefen, schuetzen, wiederherstellen

    antwort = uebersetzen(schuetzen(quelltext), ziel="fr")
    text = pruefen(quelltext, wiederherstellen(antwort), key, "fr")

**Warum dieses Modul protokolliert, wo die anderen core-py-Bausteine nur
entscheiden:** Der Rückfall auf den Quelltext IST hier die Regel, und ein
stiller Rückfall wäre genau der Fehler, den das Modul verhindern soll
(Regel #7). Wer nur die Entscheidung will, ruft `platzhalter_von()` zweimal.

flottenweit identisch — nicht pro App editieren. Änderungen gehören ins
Fundament (`packages/core-py/platzhalter.py`) und werden von dort verteilt.
"""
import logging
import re

logger = logging.getLogger(__name__)

_PLATZHALTER = re.compile(r"\{(\w+)\}")
_GESCHUETZT = re.compile(r"@@PLACEHOLDER_(\w+)@@")


def platzhalter_von(text: str) -> set[str]:
    """Die Namen aller Platzhalter in einem Text."""
    return set(_PLATZHALTER.findall(text or ""))


def schuetzen(text: str) -> str:
    """`{name}` → `@@PLACEHOLDER_name@@`, damit kein Uebersetzer ihn anfasst."""
    return _PLATZHALTER.sub(r"@@PLACEHOLDER_\1@@", text or "")


def wiederherstellen(text: str) -> str:
    """`@@PLACEHOLDER_name@@` → `{name}`."""
    return _GESCHUETZT.sub(r"{\1}", text or "")


def pruefen(quelle: str, uebersetzung: str, key: str, sprache: str) -> str:
    """Gibt die Uebersetzung zurueck — oder die Quelle, wenn sie kaputt ist.

    Kein stiller Rueckfall (Regel #7): Wenn ein Uebersetzer die Platzhalter
    trotz Schutz verbogen hat, ist das ein Defekt und wird als ERROR geloggt.
    Sichtbarer Quelltext ist immer noch besser als ein `{compte}`, das nie
    ersetzt wird — der Nutzer sieht sonst Maschinerie statt einer Zahl.
    """
    if platzhalter_von(quelle) == platzhalter_von(uebersetzung):
        return uebersetzung
    logger.error(
        "Platzhalter verbogen: key=%s sprache=%s quelle=%r uebersetzung=%r — "
        "Uebersetzung verworfen, Quelltext bleibt stehen.",
        key, sprache, quelle, uebersetzung,
    )
    return quelle
