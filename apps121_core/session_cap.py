"""Wie viele Geräte darf eine Person gleichzeitig angemeldet haben?

Flottenweit identische Regel. Beschlossen am 2026-07-31.

Warum es die Regel überhaupt braucht
------------------------------------
Der heutige Zustand ist in drei Apps faktisch „genau eins": survey, support und
aufträge führen einen einzigen ``current_refresh_jti`` am *User*. Der Login auf
Gerät 2 überschreibt ihn — Gerät 1 fliegt raus, ohne Meldung, ohne Spur. Genau
diese Lautlosigkeit hat die „grundlosen Logouts" so schwer auffindbar gemacht.

paperball-finance/-news führen echte Sitzungen, aber ohne Obergrenze.

Die Regel
---------
**Höchstens ``DEFAULT_MAX_SESSIONS`` aktive Sitzungen je Person.** Ist das
Kontingent voll, gewinnt der neue Login und die **am längsten unbenutzte**
Sitzung wird beendet.

Drei Entscheidungen, die wichtiger sind als die Zahl:

1. **Verdrängen statt abweisen.** „Zu viele Geräte, melde dich woanders ab"
   sperrt genau die Leute aus, die es am wenigsten können — das alte Gerät steht
   im Büro, die Person sitzt im Zug.

2. **Nach letzter Nutzung sortieren, nicht nach Erstellung.** Nach Alter zu
   verdrängen wirft den täglich genutzten Arbeitsrechner raus, weil er seit
   Wochen angemeldet ist, während ein einmal benutztes Handy überlebt.

3. **Sichtbar machen.** Die App MUSS die Verdrängung protokollieren und der
   Person zeigen, was passiert ist (Sitzungsliste in den Einstellungen,
   Hinweis beim nächsten Aufruf). Eine endende Sitzung ist nicht das Problem —
   eine lautlos endende schon.

Nebeneffekt fürs Geschäft: verdrängt dieselbe Kennung ständig Sitzungen, steht
das im Audit-Log. Das ist ein brauchbareres Sharing-Signal als eine harte
Grenze, ohne legitime Nutzung zu bestrafen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, Sequence

#: Arbeitsrechner + Laptop + Handy. Zwei wäre eins zu wenig: Rechner und Handy
#: sind bereits zwei, der Laptop würde den Rechner lautlos verdrängen — und ein
#: zweiter Browser zählt als eigenes Gerät. Wer die Zahl senken will, ändert sie
#: HIER und nicht pro App.
DEFAULT_MAX_SESSIONS = 3


class SessionLike(Protocol):
    """Was dieses Modul von einer Sitzung wissen muss.

    Absichtlich minimal: die Apps haben unterschiedliche Modelle, hier zählen
    nur Identität und letzte Nutzung.
    """

    id: object
    last_used_at: datetime | None
    created_at: datetime | None


@dataclass(frozen=True)
class CapOutcome:
    #: Sitzungen, die beendet werden müssen, damit Platz für die neue ist.
    #: Reihenfolge: am längsten unbenutzt zuerst.
    to_evict: tuple[object, ...]

    @property
    def evicts_anything(self) -> bool:
        return bool(self.to_evict)


def _sortierschluessel(s: SessionLike) -> tuple[int, datetime | None]:
    """Am längsten unbenutzt zuerst.

    Sitzungen ohne jede Zeitangabe kommen ganz nach vorn: über sie ist nichts
    bekannt, und eine Sitzung, die nie benutzt wurde, ist der harmloseste
    Kandidat. Das ``0``/``1`` sortiert diese Gruppe vor alle datierten, weil
    ``None`` sich nicht mit ``datetime`` vergleichen lässt.
    """
    zeit = s.last_used_at or s.created_at
    return (0, None) if zeit is None else (1, zeit)


def sessions_to_evict(
    active: Iterable[SessionLike],
    *,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
    keep_ids: Sequence[object] = (),
) -> CapOutcome:
    """Welche Sitzungen müssen weichen, damit eine weitere Platz hat?

    ``active``
        Alle derzeit aktiven Sitzungen der Person — **ohne** die gerade
        entstehende. Die App zählt selbst, was „aktiv" heißt (nicht widerrufen,
        nicht abgelaufen).
    ``keep_ids``
        Sitzungen, die nie verdrängt werden dürfen — insbesondere die eigene,
        falls der Aufrufer sie doch mitgibt. Schützt davor, dass ein Login sich
        selbst hinauswirft.

    Gibt eine leere Liste zurück, wenn noch Platz ist. Die App beendet dann
    genau die genannten Sitzungen, protokolliert das und macht es sichtbar.
    """
    if max_sessions < 1:
        raise ValueError("max_sessions muss mindestens 1 sein")

    geschuetzt = set(map(id_of, keep_ids)) if keep_ids else set()
    kandidaten = [s for s in active if id_of(s.id) not in geschuetzt]

    # Platz für die NEUE Sitzung: es dürfen höchstens max_sessions-1 bestehende
    # bleiben. Ohne dieses -1 wäre die Grenze faktisch max_sessions+1.
    erlaubt = max_sessions - 1
    ueberzaehlig = len(kandidaten) - erlaubt
    if ueberzaehlig <= 0:
        return CapOutcome(())

    kandidaten.sort(key=_sortierschluessel)
    return CapOutcome(tuple(s.id for s in kandidaten[:ueberzaehlig]))


def id_of(wert: object) -> object:
    """UUIDs kommen je nach App als ``UUID`` oder als String an — vergleichbar machen."""
    return str(wert)
