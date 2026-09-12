"""Refresh-Token-Rotation: was tun, wenn der vorgelegte Token nicht der aktuelle ist?

Flottenweit identische Entscheidungsregel. Beschlossen am 2026-07-31, nachdem
dieselbe Fehlklasse in paperball-finance an einem Tag fünf Zwangs-Logouts
erzeugt hat.

Warum nur die ENTSCHEIDUNG und nicht die Speicherung
----------------------------------------------------
Die Apps legen Sitzungen unterschiedlich ab:

* paperball-finance/-news: Tabelle `user_sessions`, ein Zeile je Gerät
* survey, support, aufträge: EIN `current_refresh_jti` am *User*

Ein gemeinsames Speicher-Modul müsste beides abbilden und wäre in jeder App
falsch. Der Fehler saß aber ohnehin nicht in der Speicherung, sondern in der
Bewertung: jeder nicht-aktuelle Token galt als Diebstahl, und die Reaktion
darauf war der Widerruf **aller** Sitzungen des Nutzers.

Dieses Modul besitzt deshalb die Regel, die App besitzt ihre Tabellen. Die App
ermittelt drei Tatsachen und bekommt eine Entscheidung zurück.

Was schiefging (Belege aus Prod)
--------------------------------
Drei völlig legitime Fälle landeten im Diebstahls-Zweig:

1. Zwei Tabs erneuern gleichzeitig — der zweite kommt mit dem Token an, den der
   erste Sekundenbruchteile vorher abgelöst hat.
2. Retry nach einem Netzwerk-Aussetzer: der Server hat rotiert, die Antwort kam
   nie an, der Browser versucht es mit dem alten Token erneut.
3. Ein altes Cookie einer längst beendeten Sitzung.

Am 28.07.2026 standen in `security_audit_logs` sechs Diebstahls-Alarme, kein
einziger echt; zwei davon in derselben Sekunde — die Signatur zweier Tabs.

Nebenbefund: der pauschale Massenwiderruf war zugleich ein Abmelde-Hebel. Wer
irgendeinen alten, noch nicht abgelaufenen Refresh-Token besaß, konnte den
Nutzer beliebig oft aus allen Geräten werfen.

Die Regel
---------
Ein Signal, das sich nicht authentifizieren lässt, darf keine destruktive
Massenaktion auslösen. Erkennung behalten, Reaktion proportional machen.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Wie lange ein soeben abgelöster Token noch gilt. Lang genug für parallele
# Tabs und einen Retry, kurz genug, dass ein wirklich gestohlener Token nicht
# nennenswert länger nutzbar bleibt.
DEFAULT_GRACE_SECONDS = 60


class RefreshDecision(str, Enum):
    """Was die App mit diesem Refresh-Versuch tun soll."""

    #: Regulär: neuen Token ausstellen, alten als Vorgänger merken.
    ROTATE = "rotate"

    #: Paralleler Aufruf innerhalb der Karenz. Neuen Access-Token ausstellen,
    #: aber NICHT erneut rotieren — und den mitgeschickten Refresh-Token
    #: unverändert zurückgeben. Siehe Hinweis unten.
    ACCEPT_WITHIN_GRACE = "accept_within_grace"

    #: Ein Token dieser Sitzung, dessen Karenz abgelaufen ist. Das ist echte
    #: Wiederverwendung → NUR diese Sitzung widerrufen, nicht alle Geräte.
    REVOKE_THIS_SESSION = "revoke_this_session"

    #: Gänzlich unbekannt (abgelaufene oder längst beendete Sitzung).
    #: Protokollieren, diesen einen Aufruf ablehnen, sonst nichts anfassen.
    REJECT_ONLY = "reject_only"


@dataclass(frozen=True)
class RefreshOutcome:
    decision: RefreshDecision
    #: Kurzer Grund für das Audit-Log — bewusst maschinenlesbar und stabil.
    audit_code: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.decision in (RefreshDecision.ROTATE, RefreshDecision.ACCEPT_WITHIN_GRACE)


def decide_refresh(
    *,
    matches_current: bool,
    matches_previous: bool = False,
    seconds_since_rotation: float | None = None,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
) -> RefreshOutcome:
    """Bewertet einen vorgelegten Refresh-Token.

    Die App ermittelt die drei Tatsachen aus ihrer eigenen Speicherung:

    ``matches_current``
        Der Token ist der aktuell gültige dieser Sitzung.
    ``matches_previous``
        Der Token ist der zuletzt abgelöste dieser Sitzung. Wer nur einen
        aktuellen Wert speichert, übergibt hier ``False`` — dann gibt es keine
        Karenz, aber immer noch keinen Massenwiderruf.
    ``seconds_since_rotation``
        Alter der letzten Rotation. ``None`` heißt „unbekannt" und wird
        vorsichtig als *außerhalb* der Karenz gewertet: lieber eine Sitzung zu
        viel widerrufen als einen gestohlenen Token unbegrenzt gelten lassen.

    Reihenfolge zählt: ``matches_current`` gewinnt immer, damit ein Token, der
    zugleich als Vorgänger geführt wird, nicht in der Karenz landet.
    """
    if matches_current:
        return RefreshOutcome(RefreshDecision.ROTATE)

    if matches_previous:
        innerhalb = (
            seconds_since_rotation is not None
            and 0 <= seconds_since_rotation <= grace_seconds
        )
        if innerhalb:
            return RefreshOutcome(RefreshDecision.ACCEPT_WITHIN_GRACE)
        return RefreshOutcome(
            RefreshDecision.REVOKE_THIS_SESSION, audit_code="refresh_token_reuse"
        )

    return RefreshOutcome(RefreshDecision.REJECT_ONLY, audit_code="refresh_token_unknown")


# ---------------------------------------------------------------------------
# Hinweis für Implementierende — die eigentliche Denkfalle
# ---------------------------------------------------------------------------
#
# Bei ACCEPT_WITHIN_GRACE muss die App den MITGESCHICKTEN Refresh-Token
# unverändert zurückgeben und NICHT erneut rotieren.
#
# Rotiert sie stattdessen ein zweites Mal, überholen sich zwei Rotationen: Tab A
# bekommt T1, Tab B bekommt T2, das Cookie trägt am Ende den Token, dessen
# Antwort zuletzt ankam — und der andere ist beim nächsten Versuch weder aktuell
# noch Vorgänger. Der Fehler wäre damit nur verschoben, nicht behoben.
#
# Und eine Ebene darüber, aus demselben Vorfall gelernt (finance PR #80):
# Wenn ein Endpoint den Token in der Datenbank rotiert UND Cookies setzt, darf
# danach nichts mehr werfen. Eine Ausnahme nach dem Rotieren verwirft das
# Response-Objekt samt Set-Cookie-Headern — der Server ist weiter, der Browser
# nicht, und beim nächsten Versuch sieht der alte Token wie Diebstahl aus. Genau
# das war die eigentliche Ursache der Logouts; das Karenzfenster hat sie nur
# abgemildert. Reihenfolge deshalb: erst alles bauen, was werfen kann, dann
# rotieren und Cookies setzen.
