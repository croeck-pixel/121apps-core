"""Teilen-Links: eine Ansicht, ein Link, kein Login — die Regeln als Code.

Umsetzung von `docs/FLEET_SHARED_VIEWS_SPEC.md`. Der Anlass: mehrere Apps
brauchen dasselbe — einem Kunden, einer Geschäftsführung, einem Kollegen ohne
Zugang etwas zeigen, ohne ihn erst anzulegen. Wer das pro App erfindet, erfindet
auch die Fehler pro App neu, und die Fehler dieser Klasse sind still: ein Link
ohne Ablauf lebt für immer in einem Postfach, ein Widerruf mit Karenz nimmt dem
Widerruf genau den Zweck, und eine Fehlermeldung, die „abgelaufen" von
„gibt's nicht" unterscheidet, macht den Link zum Auskunftsdienst.

**Was hier steht und was nicht.** Hier steht die Logik: wie ein Token entsteht,
wie er gehasht und verglichen wird, wann er gilt. Nicht hier steht die
Speicherung — die Apps legen ihre Tabellen unterschiedlich an (verschiedene
Mandanten-Modelle, verschiedene Session-Factories), aber sie sollen sich gleich
*entscheiden*. Dasselbe Prinzip wie bei `locale_resolver` und `api_schluessel`.

**Die Hash-Funktionen sind absichtlich dieselben wie in `api_schluessel`** —
und absichtlich hier nochmal, statt importiert. core-py wird als EINZELNE
DATEI kopiert; ein Import zwänge jede App, die nur Teilen-Links will, auch das
API-Schlüssel-Modul mitzuschleppen. Zwanzig Zeilen Wiederholung sind billiger
als diese Kopplung. Ändert sich das Hash-Verfahren, ändern es beide.

Die fünf Entscheidungen, die mehr zählen als der Code
-----------------------------------------------------

1. **Ablauf ist Pflicht, nicht Option.** Ein Teilen-Link ist eine URL, die
   Zugriff *ist* — sie wandert per Mail und Chat weiter und bleibt dort. Ohne
   Ablaufdatum ist jeder je erzeugte Link auf Dauer gültig. Deshalb gibt es
   keinen Weg, „unbegrenzt" zu wählen; `MAX_GUELTIG` ist die Obergrenze.

2. **Widerruf wirkt sofort, ohne Karenz.** Der API-Schlüssel-Kanon gibt einem
   rotierten Vorgänger 24 Stunden, damit Clients tauschen können. Hier wäre
   dieselbe Karenz falsch: Wer widerruft, will *jetzt*, dass niemand mehr
   hineinsieht — meist genau deshalb, weil der Link an der falschen Stelle
   gelandet ist.

3. **Nach außen sehen alle Fehlzustände gleich aus.** Unbekannt, abgelaufen,
   widerrufen: für den Aufrufer 404. `zustand()` nennt den Grund trotzdem
   genau, weil das Protokoll ihn braucht — aber die Route darf ihn nicht
   ausliefern. Sonst beantwortet der Link die Frage „hat es diesen Bericht
   je gegeben?", und das ist eine Auskunft über fremde Kundschaft.

4. **Der Token gehört in den Pfad, nie in die Query.** Query-Zeichenketten
   landen in Server-Logs, in Analytics und in `Referer`-Kopfzeilen. Die Seite
   MUSS zusätzlich `Referrer-Policy: no-referrer` senden, sonst reicht ein
   eingebettetes Bild von fremdem Host, um den Token weiterzugeben.

5. **Kein Login heißt kein Kontext.** Die Seite zeigt genau die freigegebene
   Ansicht — keinen Workspace-Umschalter, keine Kontodaten, keine Navigation
   in andere Bereiche. Ein Teilen-Link ist eine Fähigkeit für EINE Sache, und
   was er sonst noch zeigt, hat niemand freigegeben.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

#: 32 Byte aus `secrets` → 43 Zeichen URL-sicheres Base64. Kurz genug für eine
#: Mail, lang genug, dass Raten aussichtslos ist. Weniger nicht: ein Token, der
#: in eine Zeile passen „soll", ist der Anfang von 8 Zeichen und einem Skript.
TOKEN_BYTES = 32

#: `st_` wie *shared token*. Das Präfix ist keine Sicherheit, sondern
#: Auffindbarkeit: taucht es in einem Log oder einem Ticket auf, weiß der
#: Support sofort, worum es sich handelt — und Secret-Scanning kann greifen.
LINK_PRAEFIX = "st_"

_TOKEN_RE = re.compile(r"^st_([A-Za-z0-9_-]{43})$")

#: Voreinstellung, wenn der Aufrufer nichts angibt. 30 Tage decken den
#: Normalfall (ein Bericht, über den man in den nächsten Wochen spricht), ohne
#: dass jemand aktiv aufräumen muss.
DEFAULT_GUELTIG = timedelta(days=30)

#: Die Obergrenze. Ein Jahr ist lang genug für einen Jahresbericht und kurz
#: genug, dass ein vergessener Link irgendwann von selbst stirbt.
MAX_GUELTIG = timedelta(days=365)

#: Aufrufe je Minute und Token. Der Endpunkt ist unangemeldet erreichbar; ohne
#: Grenze ist er ein kostenloser Lastgenerator auf teure Auswertungs-Abfragen.
#: Großzügig genug für eine Seite, die nachlädt, und für ein paar Leute, die
#: gleichzeitig hineinsehen.
RATE_LIMIT_JE_MINUTE = 60


class Zustand(str, Enum):
    """Warum ein Token nicht (mehr) trägt.

    Für das Protokoll gedacht, nicht für die Antwort: die Route macht aus
    allem außer `GUELTIG` ein 404 (siehe Entscheidung 3 im Modulkopf).
    """

    GUELTIG = "gueltig"
    UNBEKANNT = "unbekannt"
    ABGELAUFEN = "abgelaufen"
    WIDERRUFEN = "widerrufen"


class TeilenLinkFehler(ValueError):
    """Ungültige Eingabe beim Erzeugen — kein Zustand eines bestehenden Links."""


@dataclass(frozen=True)
class NeuerLink:
    """Das Ergebnis von :func:`erzeugen`.

    `token` existiert genau einmal: hier. Gespeichert wird `token_hash`.
    Eine Funktion, die den Klartext aus dem Bestand zurückholt, gibt es nicht
    und soll es nicht geben — ein nachträglich anzeigbarer Token ist kein
    Geheimnis mehr.
    """

    token: str
    token_hash: str
    laeuft_ab_am: datetime


def erzeugen(*, jetzt: datetime, gueltig: timedelta = DEFAULT_GUELTIG) -> NeuerLink:
    """Einen neuen Teilen-Link erzeugen.

    ``jetzt`` wird übergeben statt hier gelesen, damit die Funktion prüfbar
    bleibt und die App EINE Zeitquelle behält (Regel: keine versteckte Uhr in
    einer Bibliothek).
    """
    if gueltig <= timedelta(0):
        raise TeilenLinkFehler("Gueltigkeit muss positiv sein")
    if gueltig > MAX_GUELTIG:
        raise TeilenLinkFehler(f"Gueltigkeit hoechstens {MAX_GUELTIG.days} Tage")
    if jetzt.tzinfo is None:
        raise TeilenLinkFehler("jetzt muss zeitzonenbehaftet sein (UTC)")

    token = LINK_PRAEFIX + secrets.token_urlsafe(TOKEN_BYTES)
    return NeuerLink(token=token, token_hash=hashen(token), laeuft_ab_am=jetzt + gueltig)


def hashen(token: str) -> str:
    """SHA-256 als Hexadezimal. Gespeichert wird nur das."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def passt(token: str, gespeicherter_hash: str) -> bool:
    """Zeitkonstanter Vergleich.

    `hmac.compare_digest` statt `==`: ein Vergleich, der beim ersten
    abweichenden Zeichen abbricht, verrät über die Laufzeit, wie viele Zeichen
    stimmten. Bei 43 Zeichen ist das theoretisch, aber es kostet nichts.
    """
    if not wohlgeformt(token):
        return False
    return hmac.compare_digest(hashen(token), gespeicherter_hash)


def wohlgeformt(token: str) -> bool:
    """Sieht das überhaupt wie ein Token aus?

    Vorgeschaltet, damit offensichtlicher Unsinn gar nicht erst zu einer
    Datenbank-Abfrage führt — der Endpunkt ist öffentlich erreichbar.
    """
    return bool(_TOKEN_RE.match(token or ""))


def zustand(
    *,
    hash_passt: bool,
    widerrufen_am: datetime | None,
    laeuft_ab_am: datetime | None,
    jetzt: datetime,
) -> Zustand:
    """Der genaue Grund, warum ein Token trägt oder nicht.

    Die Reihenfolge ist Absicht: **Widerruf schlägt Ablauf.** Wer einen Link
    widerruft, tut das als Handlung; im Protokoll soll genau die stehen und
    nicht „war ohnehin abgelaufen".

    Ein Datensatz OHNE Ablaufdatum gilt als abgelaufen, nicht als unbegrenzt.
    So kann eine vergessene Migration oder ein `NULL` aus einem Altbestand
    keinen ewigen Zugang erzeugen — im Zweifel zu.
    """
    if not hash_passt:
        return Zustand.UNBEKANNT
    if widerrufen_am is not None:
        return Zustand.WIDERRUFEN
    if laeuft_ab_am is None or laeuft_ab_am <= jetzt:
        return Zustand.ABGELAUFEN
    return Zustand.GUELTIG


def ist_gueltig(
    *,
    hash_passt: bool,
    widerrufen_am: datetime | None,
    laeuft_ab_am: datetime | None,
    jetzt: datetime,
) -> bool:
    """Kurzform für den Normalfall in der Route."""
    return (
        zustand(
            hash_passt=hash_passt,
            widerrufen_am=widerrufen_am,
            laeuft_ab_am=laeuft_ab_am,
            jetzt=jetzt,
        )
        is Zustand.GUELTIG
    )


def verbleibend(laeuft_ab_am: datetime | None, jetzt: datetime) -> timedelta:
    """Wie lange der Link noch trägt — nie negativ.

    Für die Anzeige beim Ersteller („läuft in 12 Tagen ab"). Ein abgelaufener
    Link liefert `0`, damit die Oberfläche keine negative Dauer formatieren
    muss.
    """
    if laeuft_ab_am is None:
        return timedelta(0)
    rest = laeuft_ab_am - jetzt
    return rest if rest > timedelta(0) else timedelta(0)


def utc_jetzt() -> datetime:
    """Eine zeitzonenbehaftete Uhr für Aufrufer, die keine eigene haben."""
    return datetime.now(timezone.utc)
