"""Support-Zugriff mit Einwilligung: wann der Plattform-Support ein Konto öffnen darf.

Spec: ``docs/FLEET_SUPPORT_ZUGRIFF_SPEC.md``. Herkunft: paperball-finance PR #604
(17.09.2026, ``services/support_freigabe.py``) — dort zuerst gebaut, hier als
Regel ohne Speicher gezogen, damit die übrigen Apps sich gleich *entscheiden*.

Was hier steht und was nicht
----------------------------
Hier steht die Entscheidung: gilt eine Freigabe, ist eine Anfrage noch offen,
darf angefragt / abgelehnt / widerrufen / impersoniert werden, wann endet eine
Sitzung, wie heißt eine vergangene Zeile. Nicht hier steht die Speicherung —
die App fragt ihre Tabelle (``support_access_grants``) und gibt die Tatsachen
herein. Dasselbe Prinzip wie :mod:`teilen_link` und :mod:`gutschein_regeln`.

Die Entscheidungen, die mehr zählen als der Code
------------------------------------------------
1. **Ohne laufende Freigabe keine Impersonation.** Nicht „Warnung“, nicht
   „nur Lesen ohne Freigabe“ — :func:`darf_impersonieren` gibt einen Code
   zurück, die Route antwortet 403 und legt KEINE Sitzung an.
2. **Eine Anfrage WIRD zur Freigabe.** Stimmt der Nutzer zu, wird dieselbe
   Zeile erteilt, statt eine zweite daneben zu legen — sonst stünde „Anfrage
   offen“ neben „Zugriff erteilt“. Höchstens eine offene Anfrage ODER eine
   laufende Freigabe je Nutzer.
3. **Eine Sitzung endet spätestens mit ihrer Freigabe** (:func:`sitzungsende`),
   auch wenn ihre eigene Laufzeit länger wäre.
4. **Widerruf wirkt sofort**, auch auf laufende Sitzungen. Keine Karenz — wer
   widerruft, will, dass der Support JETZT draußen ist.
5. **Im Zweifel zu.** Eine erteilte Zeile ohne Frist gilt nicht; eine Anfrage
   ohne Zeitpunkt ist verfallen. Ein ``NULL`` aus einem Altbestand darf keinen
   unbefristeten Zugang erzeugen.
6. **Fehler sind Codes** (Regel #23). Den Satz baut die App in der Sprache der
   Person.

Nur stdlib. Kein SQLAlchemy, kein FastAPI, keine App-Importe.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

__all__ = [
    "ANFRAGE_GUELTIG",
    "AUDIT_AKTIONEN",
    "DAUERN",
    "VERLAUF_HOECHSTENS",
    "Fehler",
    "Status",
    "Verlaufsstatus",
    "anfrage_offen",
    "darf_ablehnen",
    "darf_anfragen",
    "darf_impersonieren",
    "darf_widerrufen",
    "frist_bis",
    "laeuft",
    "sitzungsende",
    "verlaufsstatus",
]

#: Die Fristen, die ein Nutzer wählen kann. Eine Liste für Oberfläche und
#: Router — ein Wächter der App hält die Auswahl im Frontend dagegen.
#: Keine „unbegrenzt“-Option, mit Absicht (Entscheidung 5).
DAUERN: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

#: Wie lange eine unbeantwortete Anfrage offen bleibt. Danach verschwindet der
#: Hinweis beim Nutzer, und der Plattform-Admin darf neu anfragen.
ANFRAGE_GUELTIG = timedelta(days=7)

#: Wie viele vergangene Freigaben und Sitzungen die Übersicht zeigt.
VERLAUF_HOECHSTENS = 20


class Status(str, Enum):
    """Die vier Zustände, die eine Zeile in der Datenbank tragen kann."""

    REQUESTED = "requested"
    GRANTED = "granted"
    DECLINED = "declined"
    REVOKED = "revoked"


class Verlaufsstatus(str, Enum):
    """Wie eine VERGANGENE Zeile in der Übersicht heißt.

    Die Datenbank kennt nur vier Zustände; „Frist vorbei“ und „nie beantwortet“
    sind keine Handlung, sondern Zeitablauf, und stehen deshalb nur hier.
    """

    EXPIRED = "expired"  # erteilt, Frist vorbei
    LAPSED = "lapsed"  # angefragt, nie beantwortet
    DECLINED = "declined"
    REVOKED = "revoked"


class Fehler(str, Enum):
    """Maschinencodes. Die App übersetzt sie als ``errors.support_access.<code>``."""

    REQUEST_NOT_FOUND = "request_not_found"  # 404
    REQUEST_ALREADY_OPEN = "request_already_open"  # 409
    ACCESS_ALREADY_GRANTED = "access_already_granted"  # 409
    NO_ACTIVE_ACCESS = "no_active_access"  # 409
    NO_CONSENT = "no_consent"  # 403 beim Start der Impersonation


#: Die Audit-Aktionen (FLEET_ADMIN_SPEC §4.1, ``<bereich>.<verb>``). Als
#: Konstante, damit ein App-Wächter die geschriebenen Aktionen dagegen halten
#: kann — ein Tippfehler in einer Aktion ist ein Eintrag, den kein Filter findet.
AUDIT_AKTIONEN: frozenset[str] = frozenset(
    {
        "admin.support_access.request",
        "user.support_access.grant",
        "user.support_access.decline",
        "user.support_access.revoke",
        "impersonate.start",
        "impersonate.stop",
        "impersonate.denied",
        "impersonate.write_blocked",
    }
)


def _aware(wert: datetime, name: str) -> None:
    if wert.tzinfo is None:
        raise ValueError(f"{name} muss zeitzonenbehaftet sein (UTC)")


def laeuft(*, status: str, gueltig_bis: datetime | None, jetzt: datetime) -> bool:
    """Darf der Support unter DIESER Zeile jetzt hinein?"""
    _aware(jetzt, "jetzt")
    if status != Status.GRANTED.value:
        return False
    if gueltig_bis is None:
        return False  # Entscheidung 5: erteilt ohne Frist gilt nicht
    _aware(gueltig_bis, "gueltig_bis")
    return gueltig_bis > jetzt


def anfrage_offen(*, status: str, angefragt_am: datetime | None, jetzt: datetime) -> bool:
    """Ist DIESE Zeile eine unbeantwortete, nicht verfallene Anfrage?"""
    _aware(jetzt, "jetzt")
    if status != Status.REQUESTED.value or angefragt_am is None:
        return False
    _aware(angefragt_am, "angefragt_am")
    return angefragt_am > jetzt - ANFRAGE_GUELTIG


def frist_bis(dauer: str, *, jetzt: datetime) -> datetime:
    """Bis wann eine jetzt erteilte Freigabe gilt. Eine neue Frist gilt ab jetzt
    — verlängern wie verkürzen. Unbekannte Dauer wirft, statt still zu raten."""
    _aware(jetzt, "jetzt")
    if dauer not in DAUERN:
        raise ValueError(f"Unbekannte Dauer {dauer!r}, erlaubt: {sorted(DAUERN)}")
    return jetzt + DAUERN[dauer]


def darf_anfragen(*, freigabe_laeuft: bool, anfrage_offen: bool) -> Fehler | None:
    """Ein Plattform-Admin bittet um Zugriff. Laufende Freigabe geht vor:
    wer schon hinein darf, soll den Nutzer nicht ein zweites Mal fragen."""
    if freigabe_laeuft:
        return Fehler.ACCESS_ALREADY_GRANTED
    if anfrage_offen:
        return Fehler.REQUEST_ALREADY_OPEN
    return None


def darf_ablehnen(*, offene_anfrage_id: object | None, anfrage_id: object) -> Fehler | None:
    """Abgelehnt wird nur DIE offene Anfrage — nicht eine alte, verfallene oder
    fremde Kennung, die noch in einem offenen Tab steht."""
    if offene_anfrage_id is None or offene_anfrage_id != anfrage_id:
        return Fehler.REQUEST_NOT_FOUND
    return None


def darf_widerrufen(*, freigabe_laeuft: bool) -> Fehler | None:
    """Ohne laufende Freigabe ist Widerrufen ein Fehler, kein stilles „nichts getan“."""
    return None if freigabe_laeuft else Fehler.NO_ACTIVE_ACCESS


def darf_impersonieren(*, freigabe_laeuft: bool) -> Fehler | None:
    """Entscheidung 1. Die Zielprüfung (sich selbst, inaktiv, andere Admins)
    stellt die App VORHER — sie gilt unabhängig von der Einwilligung."""
    return None if freigabe_laeuft else Fehler.NO_CONSENT


def sitzungsende(*, gueltig_bis: datetime | None, gewuenscht: datetime) -> datetime:
    """Entscheidung 3: die Sitzung endet spätestens mit ihrer Freigabe."""
    _aware(gewuenscht, "gewuenscht")
    if gueltig_bis is None:
        raise ValueError("Freigabe ohne Frist — darunter darf keine Sitzung starten")
    _aware(gueltig_bis, "gueltig_bis")
    return min(gewuenscht, gueltig_bis)


def verlaufsstatus(status: str) -> Verlaufsstatus:
    """Wie eine vergangene Zeile heißt.

    Nur für Zeilen, die weder laufen noch offen sind: ``granted`` heißt dort
    „Frist vorbei“, ``requested`` „nie beantwortet“. Ein unbekannter Status
    wirft — ein neuer Zustand ohne Beschriftung soll auffallen.
    """
    if status == Status.GRANTED.value:
        return Verlaufsstatus.EXPIRED
    if status == Status.REQUESTED.value:
        return Verlaufsstatus.LAPSED
    if status == Status.DECLINED.value:
        return Verlaufsstatus.DECLINED
    if status == Status.REVOKED.value:
        return Verlaufsstatus.REVOKED
    raise ValueError(f"Unbekannter Status einer Support-Freigabe: {status!r}")
