"""Gutscheincodes: wann ein Code gilt, was er wert ist, wann Geld fällig wird.

Spec: ``docs/FLEET_CODES_SPEC.md``.

Warum die Regel hier liegt und die Tabellen nicht
-------------------------------------------------
Wie bei :mod:`refresh_rotation`: **dieses Modul besitzt die Regel, die App
besitzt ihre Tabellen.** Die App ermittelt ein paar Tatsachen und bekommt eine
Entscheidung zurück.

Das ist keine Bequemlichkeit, sondern die einzige ehrliche Schnittstelle. Die
Codes-Tabelle hängt an der ``workspaces``-Tabelle der jeweiligen App, und die
heisst überall anders — survey kennt Mandanten, aufträge kennt Auftragnehmer,
paperball kennt Organisationen. Ein gemeinsames Speichermodul wäre in jeder App
ein bisschen falsch.

Die Entscheidungen dagegen sind überall dieselben, und sie sind die Stelle, an
der Geld entsteht. Genau sie gehören deshalb an **einen** Ort, mit **einem**
Testsatz.

Nur stdlib. Kein SQLAlchemy, kein Stripe, keine App-Importe.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "ABGELAUFEN",
    "ABO_RECHNUNGSGRUENDE",
    "AUSGESCHOEPFT",
    "BEREITS_GEBUNDEN",
    "FALSCHER_PLAN",
    "FALSCHES_INTERVALL",
    "FALSCHE_WAEHRUNG",
    "INAKTIV",
    "JAEHRLICHE_INTERVALLE",
    "NUR_NEUKUNDEN",
    "UNBEKANNT",
    "Beteiligungsbasis",
    "Codestand",
    "Pruefung",
    "Rabattdauer",
    "bemessungsgrundlage",
    "beteiligung_ende",
    "coupon_aus_monaten",
    "coupon_dauer",
    "gewaehrte_monate",
    "ist_abo_rechnung",
    "ist_auszahlbar",
    "ist_jaehrlich",
    "provision",
    "pruefen",
    "rechnungen_aus_monaten",
    "reifezeitpunkt",
    "zaehlt_fuer_beteiligung",
]

# ---------------------------------------------------------------------------
# Ablehnungsgründe — Maschinencodes, keine Prosa (Regel #23).
#
# Sie sind die Vertragsschnittstelle zum Frontend: die App übersetzt sie zu
# `codes.error.<grund>`. Wer hier einen Satz zurückgäbe, könnte ihn nirgends
# übersetzen — dieses Modul kennt weder Sprache noch Tonfall des Kunden.
# ---------------------------------------------------------------------------
UNBEKANNT = "code_unknown"
INAKTIV = "code_inactive"
ABGELAUFEN = "code_expired"
FALSCHER_PLAN = "code_not_for_plan"
FALSCHES_INTERVALL = "code_not_for_interval"
FALSCHE_WAEHRUNG = "code_not_for_currency"
AUSGESCHOEPFT = "code_exhausted"
NUR_NEUKUNDEN = "code_new_customers_only"
BEREITS_GEBUNDEN = "workspace_already_bound"


@dataclass(frozen=True)
class Codestand:
    """Was die App über den Code weiss. Alles, was zur Entscheidung nötig ist —
    und nichts darüber hinaus."""

    aktiv: bool = True
    redeemable_until: date | None = None
    plans: tuple[str, ...] = ()
    intervals: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()
    max_redemptions: int | None = None
    einloesungen_bisher: int = 0
    new_customers_only: bool = True


@dataclass(frozen=True)
class Pruefung:
    gueltig: bool
    grund: str | None = None


def _passt(gewaehlt: str | None, erlaubte: tuple[str, ...]) -> bool:
    """Leere Liste heisst **keine Einschränkung** — nicht „nichts erlaubt".

    Die Stelle, an der ein `if gewaehlt not in erlaubte` ohne Leerprüfung steht
    und danach kein einziger Code mehr gilt, in allen Apps gleichzeitig.
    """
    if not erlaubte:
        return True
    if gewaehlt is None:
        return True
    return gewaehlt.lower() in {e.lower() for e in erlaubte}


def pruefen(
    stand: Codestand | None,
    *,
    schon_gebunden_an_anderen_code: bool = False,
    schon_mit_diesem_code_gebunden: bool = False,
    plan: str | None = None,
    interval: str | None = None,
    currency: str | None = None,
    ist_bestandskunde: bool = False,
    heute: date | None = None,
) -> Pruefung:
    """Gilt dieser Code hier und jetzt?

    ``stand is None`` heisst: die App hat keinen Code unter dieser Zeichenkette
    gefunden. Die Normalisierung (trimmen, Grossschreibung) macht die App beim
    Suchen — Kunden tippen den Code ab, und die Schreibweise darf nie entscheiden.
    """
    heute = heute or datetime.now(timezone.utc).date()

    if stand is None:
        return Pruefung(False, UNBEKANNT)

    # Zuerst: trägt dieser Workspace schon einen ANDEREN Code? Der erste Code
    # gewinnt (§3.4) — und der Nutzer soll das erfahren, auch wenn der neu
    # eingegebene Code obendrein abgelaufen wäre. Sonst schickt man ihn wegen
    # der falschen Ursache los.
    if schon_gebunden_an_anderen_code:
        return Pruefung(False, BEREITS_GEBUNDEN)

    if not stand.aktiv:
        return Pruefung(False, INAKTIV)
    # Der letzte Tag des Fensters gehört dazu; sonst endet jede Kampagne einen
    # Tag früher als angekündigt.
    if stand.redeemable_until is not None and stand.redeemable_until < heute:
        return Pruefung(False, ABGELAUFEN)
    if not _passt(plan, stand.plans):
        return Pruefung(False, FALSCHER_PLAN)
    if not _passt(interval, stand.intervals):
        return Pruefung(False, FALSCHES_INTERVALL)
    if not _passt(currency, stand.currencies):
        return Pruefung(False, FALSCHE_WAEHRUNG)

    # Die beiden folgenden Regeln gelten nicht für die eigene, schon bestehende
    # Einlösung — sonst scheitert jeder Netzwerk-Retry desselben Kunden.
    if not schon_mit_diesem_code_gebunden:
        if stand.new_customers_only and ist_bestandskunde:
            return Pruefung(False, NUR_NEUKUNDEN)
        if (
            stand.max_redemptions is not None
            and stand.einloesungen_bisher >= stand.max_redemptions
        ):
            return Pruefung(False, AUSGESCHOEPFT)

    return Pruefung(True)


# ---------------------------------------------------------------------------
# Rabatt
# ---------------------------------------------------------------------------
class Rabattdauer(str, enum.Enum):
    """Stripes drei Coupon-Dauern."""

    EINMAL = "once"
    WIEDERHOLT = "repeating"
    DAUERHAFT = "forever"


#: Alles, was Stripe und die Apps „jährlich" nennen. Eine Menge statt einer
#: Abfrage je Aufrufstelle: ``"annual"`` zu vergessen kostet den Kunden den
#: halben Rabatt und fällt niemandem auf.
JAEHRLICHE_INTERVALLE = frozenset({"year", "yearly", "annual", "jahr", "jaehrlich"})


def ist_jaehrlich(interval: str) -> bool:
    return interval.lower() in JAEHRLICHE_INTERVALLE


def rechnungen_aus_monaten(interval: str, monate: int) -> int:
    """Wie viele Rechnungen ein Rabatt über ``monate`` Monate trifft.

    **Die gespeicherte Einheit ist der Monat, nicht die Rechnung.** Eine
    Rechnung ist bei monatlicher Zahlung ein Monat und bei jährlicher ein Jahr;
    wer die Zahl der Rechnungen speichert, legt eine Bedeutung fest, bevor
    feststeht, worauf sie sich bezieht — „3" hiesse dann drei Monate ODER drei
    Jahre, je nachdem, was der Kunde später wählt. Der Monat ist in beiden
    Fällen derselbe Monat.

    Bei jährlicher Zahlung wird auf ganze Jahre **aufgerundet**: es gibt keine
    halbe Rechnung. Was der Kunde dadurch tatsächlich bekommt, sagt
    :func:`gewaehrte_monate` — die Oberfläche muss es ihm zeigen, bevor er
    speichert.
    """
    if monate < 1:
        raise ValueError("monate muss mindestens 1 sein")
    if ist_jaehrlich(interval):
        return -(-monate // 12)
    return monate


def gewaehrte_monate(interval: str, monate: int) -> int:
    """Was der Kunde WIRKLICH bekommt — bei jährlicher Zahlung aufgerundet.

    „6 Monate Rabatt" werden bei jährlicher Zahlung zu zwölf: die erste
    Jahresrechnung ist rabattiert oder sie ist es nicht. Der Unterschied
    gehört vor die Entscheidung, nicht in die erste Abrechnung.
    """
    rechnungen = rechnungen_aus_monaten(interval, monate)
    return rechnungen * 12 if ist_jaehrlich(interval) else rechnungen


def coupon_dauer(interval: str, perioden: int) -> tuple[Rabattdauer, int | None]:
    """Stripe-Nahtstelle: ``perioden`` **Rechnungen** in eine Coupon-Dauer.

    Wer aus einer gespeicherten Zusage kommt, ruft :func:`coupon_aus_monaten` —
    diese Funktion hier nimmt bereits umgerechnete Rechnungen entgegen und ist
    die Stelle, an der Stripes Eigenheit sitzt:

    Bei **jährlicher** Zahlung wäre ``repeating`` mit ``duration_in_months``
    die Falle: die zweite Jahresrechnung fällt exakt auf den Ablauf des
    Fensters, und ob sie noch rabattiert wird, hängt an Sekunden. Eine Periode
    jährlich ist deshalb ``once``.

    Rückgabe: ``(dauer, duration_in_months)`` — der zweite Wert ist nur bei
    ``WIEDERHOLT`` gesetzt.
    """
    if perioden < 1:
        raise ValueError("perioden muss mindestens 1 sein")
    if ist_jaehrlich(interval):
        return (Rabattdauer.EINMAL, None) if perioden == 1 else (Rabattdauer.WIEDERHOLT, perioden * 12)
    return (Rabattdauer.EINMAL, None) if perioden == 1 else (Rabattdauer.WIEDERHOLT, perioden)


def coupon_aus_monaten(interval: str, monate: int) -> tuple[Rabattdauer, int | None]:
    """Die gespeicherte Zusage („N Monate Rabatt") als Stripe-Coupon-Dauer.

    Der Weg aus dem Feld in den Coupon — und der einzige, den eine App gehen
    sollte.
    """
    return coupon_dauer(interval, rechnungen_aus_monaten(interval, monate))


# ---------------------------------------------------------------------------
# Beteiligung
# ---------------------------------------------------------------------------
def _monate_dazu(zeitpunkt: datetime, monate: int) -> datetime:
    """Monate addieren, ohne `dateutil`.

    Der 31. plus einen Monat ist der letzte Tag des Folgemonats, nicht der 1.
    des übernächsten — sonst verschiebt sich eine Zusage bei jeder Verlängerung
    um einen Tag nach vorn.
    """
    jahr = zeitpunkt.year + (zeitpunkt.month - 1 + monate) // 12
    monat = (zeitpunkt.month - 1 + monate) % 12 + 1
    letzter = [31, 29 if (jahr % 4 == 0 and (jahr % 100 != 0 or jahr % 400 == 0)) else 28,
               31, 30, 31, 30, 31, 31, 30, 31, 30, 31][monat - 1]
    return zeitpunkt.replace(year=jahr, month=monat, day=min(zeitpunkt.day, letzter))


def beteiligung_ende(
    erstkauf: datetime, *, monate: int | None = None, bis: date | None = None
) -> datetime | None:
    """Wann die Beteiligung an diesem Kunden endet.

    Wird beim **ersten** Zahlungseingang berechnet und dann eingefroren. Wer sie
    bei jeder Zahlung neu aus dem Code ableitet, verkürzt oder verlängert
    laufende Zusagen, sobald jemand den Code ändert.

    Sind beide gesetzt, **gewinnt das frühere Ende**: eine befristete
    Kooperation begrenzt auch eine laufende relative Zusage.
    """
    ende = _monate_dazu(erstkauf, monate) if monate else None
    if bis is not None:
        absolut = datetime.combine(bis, datetime.min.time(), tzinfo=timezone.utc)
        ende = min(ende, absolut) if ende else absolut
    return ende


class Beteiligungsbasis(str, enum.Enum):
    """Woran der Partner beteiligt wird.

    Zwei Zusagen, die im Vertrag verschieden klingen und sich im Ledger um
    Beträge unterscheiden:

    * ``GESAMTUMSATZ`` — an allem, was der Kunde zahlt. Wächst der Kunde, wächst
      die Provision.
    * ``ERSTTARIF`` — an dem, was der Partner gebracht hat: dem zuerst
      gebuchten Tarif. Spätere Upgrades und Zukäufe zählen nicht.
    """

    GESAMTUMSATZ = "gross_revenue"
    ERSTTARIF = "initial_plan"


#: Stripes ``billing_reason`` für Rechnungen, die aus einem Abo entstehen.
#: Alles andere ist ein Einmal- oder Mengenkauf.
ABO_RECHNUNGSGRUENDE = frozenset({
    "subscription_create",
    "subscription_cycle",
    "subscription_update",
    "subscription_threshold",
})


def ist_abo_rechnung(billing_reason: str | None) -> bool:
    """Stammt diese Rechnung aus dem Abo — oder ist sie ein Zukauf?

    ``None`` heisst „unbekannt" und wird als Abo-Rechnung gewertet: bei
    ``GESAMTUMSATZ`` ändert es nichts, und bei ``ERSTTARIF`` deckelt der Betrag
    ohnehin. Eine Rechnung wegen einer fehlenden Angabe stillschweigend fallen
    zu lassen wäre die teurere Richtung — der Partner bekäme zu wenig und
    niemand sähe es.
    """
    if billing_reason is None:
        return True
    return billing_reason in ABO_RECHNUNGSGRUENDE


def zaehlt_fuer_beteiligung(
    basis: Beteiligungsbasis, *, billing_reason: str | None
) -> bool:
    """Wird diese Rechnung überhaupt provisioniert?

    Bei ``ERSTTARIF`` bleiben Einmal- und Mengenkäufe draussen. **Der Deckel
    allein genügt dafür nicht**: eine eigene Rechnung über ein Guthabenpaket
    liegt unter dem Deckel und würde voll provisioniert — obwohl sie genau das
    ist, was diese Zusage ausschliessen soll.
    """
    if basis is Beteiligungsbasis.GESAMTUMSATZ:
        return True
    return ist_abo_rechnung(billing_reason)


def bemessungsgrundlage(
    netto_minor: int,
    *,
    basis: Beteiligungsbasis = Beteiligungsbasis.GESAMTUMSATZ,
    deckel_minor: int | None = None,
) -> int:
    """Worauf der Satz gerechnet wird — netto, nach Rabatt, vor Gebühren (§5.1).

    Bei ``ERSTTARIF`` ist es ``min(gezahltes Netto, Deckel)``. Der Deckel ist
    der **Listenpreis** des zuerst gebuchten Tarifs im Intervall und in der
    Währung DIESER Rechnung — nicht der Betrag der ersten Rechnung:

    * Die erste Rechnung ist oft rabattiert. Wäre sie der Deckel, verdiente der
      Partner dauerhaft am rabattierten Wert, obwohl der Kunde längst den
      vollen Preis zahlt.
    * Ein fester Betrag zerbricht am Intervallwechsel. Wer von monatlich auf
      jährlich umstellt, bekäme eine Jahresrechnung gegen einen Monatsdeckel
      gehalten — der Partner verlöre rund 90 %, ohne dass jemand etwas falsch
      gemacht hat.

    Ist der Deckel unbekannt (Tarif oder Preis nicht mehr im Katalog), wird
    **nicht** ungedeckelt gebucht: das wäre stillschweigend eine andere Zusage
    als die vereinbarte. Die App muss den Fall sehen und beheben.
    """
    if netto_minor < 0:
        raise ValueError(
            "Ein negativer Umsatz ist keine Bemessungsgrundlage — Erstattungen "
            "laufen als Gegenbuchung, nicht als negativer Posten (§5.2)"
        )
    if basis is Beteiligungsbasis.GESAMTUMSATZ:
        return netto_minor
    if deckel_minor is None:
        raise ValueError(
            "Beteiligung am Ersttarif ohne bekannten Deckel: der Listenpreis "
            "des zuerst gebuchten Tarifs fehlt für Intervall und Währung "
            "dieser Rechnung"
        )
    if deckel_minor < 0:
        raise ValueError("deckel_minor darf nicht negativ sein")
    return min(netto_minor, deckel_minor)


def provision(basis_minor: int, satz: Decimal) -> int:
    """Provision in der kleinsten Währungseinheit, **kaufmännisch** gerundet.

    Pythons Standard rundet 0,5 zur geraden Zahl — über tausend Rechnungen
    landet die halbe Provision systematisch beim Haus. Das ist ein Streitpunkt,
    den niemand gewinnt, und er kostet weniger als ein Rundungsmodus.
    """
    return int((Decimal(basis_minor) * satz / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def reifezeitpunkt(gezahlt_am: datetime, karenz_tage: int) -> datetime:
    """Ab wann ein Posten auszahlbar wird.

    Die Karenz deckt Erstattungen und die grosse Masse der Rückbuchungen; was
    danach kommt, fängt der Clawback. Flottenweit 45 Tage (§5.5).
    """
    if karenz_tage < 1:
        raise ValueError("Karenz muss mindestens einen Tag betragen — ohne sie "
                         "wird Provision auf rückbuchbare Umsätze ausgezahlt")
    return gezahlt_am + timedelta(days=karenz_tage)


def ist_auszahlbar(payable_at: datetime, jetzt: datetime | None = None) -> bool:
    return payable_at <= (jetzt or datetime.now(timezone.utc))
