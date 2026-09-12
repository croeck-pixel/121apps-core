"""API-Schlüssel: Format, Prüfung, Geltungsbereiche — der Kanon als Code.

Umsetzung von §2 der Fleet-Spec (`FLEET_MCP_API_SPEC.md` im marketing-Repo).
Die Messung dort fand **fünf Apps mit fünf Fassungen**: `sk_live_`/`sk_mcp_`
mit freien Permissions-Zeichenketten, `auf_` rollengebunden ohne Ablauf,
finance mit Scopes und Audit. Jede war einmal ein „machen wir schnell hier".

**Was hier steht und was nicht.** Hier steht die Logik: Wie ein Schlüssel
aussieht, wie er gehasht und verglichen wird, ob ein Geltungsbereich reicht,
ob ein rotierter Vorgänger noch trägt. Nicht hier steht die Speicherung — die
Apps legen ihre Tabellen unterschiedlich an, aber sie sollen sich gleich
*entscheiden* (dasselbe Prinzip wie bei `locale_resolver`).

**Der Klartext existiert genau einmal.** `erzeugen()` gibt ihn zurück, danach
kennt ihn nur noch der Kunde. Gespeichert wird der SHA-256-Hash. Eine
Funktion, die den Klartext aus dem Bestand rekonstruiert, gibt es nicht und
soll es nicht geben — ein Schlüssel, der sich nachträglich anzeigen lässt, ist
kein Geheimnis mehr, sondern ein Passwort im Klartext mit Zusatzschritten.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

# Sortiert, weil der Fleet-Lint-Satz RUF022 fährt: eine unsortierte Liste
# blockiert sonst in JEDER App, die den Baustein kopiert, den Lint-Job — und
# die App darf ihn nicht patchen (Regel #24). Ein Baustein, der die CI seiner
# Nutzer rot macht, wird abgeschaltet statt benutzt.
__all__ = [
    "APP_MUSTER",
    "GRACE_HOECHSTENS",
    "GRACE_STANDARD",
    "SAMMEL_LESESCOPE",
    "NeuerSchluessel",
    "SchluesselFehler",
    "erzeugen",
    "grace_ende",
    "hashen",
    "ist_gueltig",
    "passt",
    "praefix_aus",
    "scope_erfuellt",
]


class SchluesselFehler(ValueError):
    """Der Schlüssel hat nicht die Form, die der Kanon verlangt."""


#: Das Kürzel der App im Schlüssel: `mkt`, `ast`, `srv`, `vnd`, `ppf`, `pba` …
#:
#: Drei bis vier Kleinbuchstaben. App-eindeutig, damit Secret-Scanning bei
#: GitHub greift und der Support im Ernstfall sofort weiß, wohin ein
#: geleakter Schlüssel gehört.
APP_MUSTER = re.compile(r"^[a-z]{2,5}$")

#: `sk_<app>_<8 Zeichen Präfix>_<32 Zeichen Geheimnis>`
_SCHLUESSEL_RE = re.compile(r"^sk_([a-z]{2,5})_([a-z0-9]{8})_([A-Za-z0-9_-]{32,})$")

#: Der Sammel-Lesescope aus §2.3. Wer ihn hat, darf alles Lesende.
#:
#: Kein `*`: Ein Platzhalter, der auch Schreibendes einschlösse, wäre genau die
#: Abkürzung, die aus einem Lese-Schlüssel unbemerkt einen Vollzugriff macht.
SAMMEL_LESESCOPE = "read"

#: Wie lange ein rotierter Vorgänger noch trägt (§2.5).
GRACE_STANDARD = timedelta(hours=24)
GRACE_HOECHSTENS = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class NeuerSchluessel:
    """Was bei der Erzeugung entsteht.

    `klartext` ist das einzige Mal, dass der Schlüssel vollständig existiert.
    Er gehört in die Antwort und **nicht** ins Log, nicht ins Audit und nicht
    in eine Fehlermeldung.
    """

    klartext: str
    #: Anzeigespalte für Listen und Support-Triage: `sk_pba_a1b2c3d4`.
    praefix: str
    #: Was gespeichert wird.
    hash: str


def erzeugen(app: str) -> NeuerSchluessel:
    """Einen neuen Schlüssel bauen.

    Der Präfix ist Teil des Geheimnisses und zugleich die Suchspalte. Das ist
    Absicht: Ohne ihn müsste die Prüfung jeden Schlüssel der Datenbank hashen
    und vergleichen — bei zehntausend Schlüsseln zehntausend Hashes je Anfrage.
    Mit ihm ist es ein Index-Treffer und ein Vergleich.

    Acht Zeichen aus `[a-z0-9]` sind rund 2,8 Billionen Möglichkeiten; sie
    müssen nicht eindeutig sein, weil der Hash entscheidet — sie müssen nur
    die Menge klein halten.
    """
    if not APP_MUSTER.match(app):
        raise SchluesselFehler(
            f"App-Kürzel {app!r} passt nicht auf {APP_MUSTER.pattern} — es steht "
            f"im Schlüssel und muss flottenweit eindeutig sein."
        )
    praefix_teil = secrets.token_hex(4)
    geheimnis = secrets.token_urlsafe(24)
    klartext = f"sk_{app}_{praefix_teil}_{geheimnis}"
    return NeuerSchluessel(
        klartext=klartext,
        praefix=f"sk_{app}_{praefix_teil}",
        hash=hashen(klartext),
    )


def hashen(klartext: str) -> str:
    """SHA-256, hexadezimal.

    Kein bcrypt oder Argon2, und das ist hier richtig: Die schützen kurze,
    erratbare Passwörter durch Rechenaufwand. Ein Schlüssel hat 192 Bit
    Zufall — er ist nicht zu raten, und ein teurer Hash machte nur jede
    API-Anfrage langsam.
    """
    return hashlib.sha256(klartext.encode("utf-8")).hexdigest()


def praefix_aus(klartext: str) -> str:
    """Den Präfix aus einem vorgelegten Schlüssel lesen — für den Nachschlag.

    Wirft bei allem, was nicht wie ein Schlüssel aussieht. Der Aufrufer soll
    daraus **nicht** eine eigene Fehlermeldung machen: Ob ein Schlüssel
    formal falsch oder schlicht unbekannt ist, geht den Anrufer nichts an.
    Beides ist 401 mit demselben Text; alles andere wäre ein Orakel, mit dem
    man gültige Präfixe erraten kann.
    """
    treffer = _SCHLUESSEL_RE.match(klartext)
    if treffer is None:
        raise SchluesselFehler("kein gültiges Schlüsselformat")
    return f"sk_{treffer.group(1)}_{treffer.group(2)}"


def passt(klartext: str, gespeicherter_hash: str) -> bool:
    """Ob der vorgelegte Schlüssel zum gespeicherten Hash gehört.

    `compare_digest`, nicht `==`: Ein Vergleich, der beim ersten
    abweichenden Zeichen abbricht, verrät über seine Laufzeit, wie viele
    Zeichen stimmten. Das ist bei einem 64-Zeichen-Hash zwar mühsam
    auszunutzen, aber der richtige Vergleich kostet nichts.
    """
    return hmac.compare_digest(hashen(klartext), gespeicherter_hash)


def scope_erfuellt(verlangt: str, vorhanden: Iterable[str]) -> bool:
    """Ob ein Schlüssel mit diesen Geltungsbereichen das darf.

    Zwei Regeln, mehr nicht:

    * Wer den Bereich hat, darf.
    * Wer :data:`SAMMEL_LESESCOPE` hat, darf alles auf `:read` — und nur das.

    **Kein Präfix-Vergleich.** `documents:` als Bereich zu haben und daraus
    `documents:write` abzuleiten wäre bequem und macht aus einem Lese-Zugang
    unbemerkt einen Schreibenden. Wer schreiben darf, hat den Bereich beim
    Namen.
    """
    menge = set(vorhanden)
    if verlangt in menge:
        return True
    return verlangt.endswith(":read") and SAMMEL_LESESCOPE in menge


def ist_gueltig(
    *,
    jetzt: datetime,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    ersteller_aktiv: bool,
) -> bool:
    """Ob ein gefundener Schlüssel überhaupt noch trägt (§2.4).

    `ersteller_aktiv` ist der Punkt, den vier von fünf Apps nicht hatten: Ein
    Schlüssel kann nie mehr als sein Ersteller. Wird jemand deaktiviert oder
    verliert die Rolle, hört sein Schlüssel auf zu wirken — sonst überlebt ein
    Zugang den Zugang.
    """
    if not ersteller_aktiv:
        return False
    if revoked_at is not None and revoked_at <= jetzt:
        return False
    if expires_at is not None and expires_at <= jetzt:
        return False
    return True


def grace_ende(rotiert_am: datetime, dauer: timedelta = GRACE_STANDARD) -> datetime:
    """Bis wann der Vorgänger nach einer Rotation noch trägt (§2.5).

    Ohne Karenz bricht eine Rotation jeden laufenden Client in dem Moment, in
    dem der neue Schlüssel entsteht — und zwar bevor irgendjemand ihn
    einsetzen konnte. Mit Karenz rotiert man morgens und tauscht bis abends.

    Die Obergrenze ist :data:`GRACE_HOECHSTENS`: Ein Vorgänger, der wochenlang
    weiterläuft, ist kein Übergang mehr, sondern ein zweiter gültiger
    Schlüssel, von dem niemand weiß.
    """
    if dauer <= timedelta(0):
        raise SchluesselFehler(f"Karenz muss positiv sein, ist {dauer}")
    if dauer > GRACE_HOECHSTENS:
        raise SchluesselFehler(
            f"Karenz {dauer} über der Obergrenze {GRACE_HOECHSTENS} — länger ist "
            f"kein Übergang mehr, sondern ein zweiter gültiger Schlüssel."
        )
    if rotiert_am.tzinfo is None:
        # Ein naiver Zeitstempel wird später gegen einen zeitzonenbewussten
        # verglichen und wirft dann — an einer Stelle, die mit der Rotation
        # nichts mehr zu tun hat.
        raise SchluesselFehler("rotiert_am braucht eine Zeitzone")
    return rotiert_am.astimezone(timezone.utc) + dauer
