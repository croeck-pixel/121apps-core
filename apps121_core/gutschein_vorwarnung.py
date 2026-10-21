"""Vorwarnung vor der ersten vollen Rechnung (FLEET_CODES_SPEC §4.9).

Spec: ``docs/FLEET_CODES_SPEC.md`` §4.9 — Pflicht im MVP: eine Mail **14 Tage**
vor der ersten Rechnung zum Normalpreis. Der Preissprung ist der
Kündigungsmoment; wer ihn nicht ankündigt, verliert Kunden genau dann, wenn sie
am wertvollsten sind, und bekommt dazu Rückbuchungen („das habe ich nie
bestellt").

Wie bei :mod:`gutschein_regeln`: **dieses Modul besitzt die Regel, die App
besitzt Tabellen, Mail und Wortlaut.** Die App liest das Stripe-Ereignis, gibt
ein paar Tatsachen herein und bekommt eine Entscheidung mit Grund zurück.

Woher das Signal kommt
----------------------
Stripe schickt ``invoice.upcoming`` eine einstellbare Zahl Tage vor jeder
Abo-Verlängerung (Standard **3 Tage** — für §4.9 zu spät). Die Einstellung ist
eine Konto-Einstellung je Modus, siehe ``README.md`` dieses Pakets. Das
Ereignis trägt eine **Vorschau** der kommenden Rechnung, und Stripe hat den
Rabatt darin schon ausgerechnet: läuft ein ``repeating``-Coupon vor dem
Rechnungsdatum aus, steht in der Vorschau kein Rabatt mehr. Diese Vorschau ist
deshalb die Wahrheit — die App rechnet Coupon-Fenster nicht selbst nach,
sondern liest, was Stripe gleich abbuchen wird.

**Bei Rechnung statt Karte kommt kein Ereignis.** Für Abos mit
``collection_method=send_invoice`` (Schulen, Firmen auf Rechnung) schickt
Stripe ``invoice.upcoming`` nicht. Dafür gibt es :func:`aus_abo_stand`: ein
täglicher Lauf der App liest ``discount.end`` und das Periodenende des Abos
und entscheidet mit derselben Regel — mit ``nur_im_vorlauf=True``, damit eine
Jahresrechnung nicht elf Monate zu früh angekündigt wird.

Erst dann ist es die *erste* volle Rechnung, wenn die **vorige** rabattiert war.
Das macht die Regel zustandslos: die zweite volle Rechnung hat eine
unrabattierte Vorgängerin und löst nichts aus — ohne dass die App sich merken
müsste, ob sie schon einmal gewarnt hat. Gemerkt wird nur der
:func:`schluessel` je Abo und Periode, gegen Stripes Wiederholungen desselben
Ereignisses.

Nur stdlib. Kein Stripe-SDK, keine App-Importe — das Ereignis kommt als ``dict``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "ABO_ENDET",
    "VERPASST",
    "DAUERHAFT",
    "DAUERHAFT_OHNE_RABATT",
    "ERSTE_VOLLE_RECHNUNG",
    "KEIN_CODE",
    "NOCH_RABATTIERT",
    "NULLRECHNUNG",
    "RECHNUNG_VORBEI",
    "SCHON_GEWARNT",
    "VORIGE_UNRABATTIERT",
    "VORLAUF_TAGE",
    "ZU_FRUEH",
    "Entscheidung",
    "Vorschau",
    "aus_abo_stand",
    "faellig",
    "pruefe_preise",
    "rabatt_ende",
    "aus_upcoming",
    "entscheiden",
    "schluessel",
]

#: Wie viele Tage vorher die Mail gehen soll — und worauf die Stripe-Einstellung
#: „Upcoming renewal events" zu stellen ist.
VORLAUF_TAGE = 14

# ---------------------------------------------------------------------------
# Gründe — Maschinencodes (Regel #23). Die App loggt sie; nur
# ERSTE_VOLLE_RECHNUNG verschickt eine Mail, nur DAUERHAFT_OHNE_RABATT ist ein
# Fehler, den ein Mensch ansehen muss.
# ---------------------------------------------------------------------------
ERSTE_VOLLE_RECHNUNG = "first_full_price_invoice"
KEIN_CODE = "no_code_bound"
DAUERHAFT = "discount_forever"
DAUERHAFT_OHNE_RABATT = "forever_discount_missing"
NOCH_RABATTIERT = "still_discounted"
VORIGE_UNRABATTIERT = "previous_invoice_not_discounted"
NULLRECHNUNG = "zero_amount_invoice"
RECHNUNG_VORBEI = "invoice_date_passed"
SCHON_GEWARNT = "already_warned"
ZU_FRUEH = "not_yet_within_lead_time"
#: Das Fenster ist vorbei, der Preissprung schon passiert. Keine Mail mehr —
#: eine Ankündigung nach der Abbuchung ist keine —, aber laut loggen: ein Lauf
#: ist ausgefallen oder kam zu spät.
VERPASST = "lead_time_missed"
#: Das Abo endet zum Periodenende (``cancel_at_period_end``) oder ist beendet:
#: es kommt keine volle Rechnung.
ABO_ENDET = "subscription_ending"


@dataclass(frozen=True)
class Vorschau:
    """Was aus ``invoice.upcoming`` gebraucht wird — und nichts darüber hinaus.

    ``periode_beginn`` ist der Beginn der neuen Abo-Periode — die Verlängerung,
    an der Stripe die Rechnung erstellt und abbucht, und zugleich Teil des
    Idempotenz-Schlüssels. ``betrag_minor`` ist, was der Kunde
    zahlen wird (``total``), ``rabatt_minor`` die Summe aus
    ``total_discount_amounts``.
    """

    abo_id: str
    periode_beginn: datetime
    betrag_minor: int
    rabatt_minor: int
    waehrung: str


@dataclass(frozen=True)
class Entscheidung:
    senden: bool
    grund: str
    #: Nur bei ``senden``: weniger als :data:`VORLAUF_TAGE` vor der Rechnung.
    #: Die Mail geht trotzdem — spät gewarnt ist besser als gar nicht —, aber
    #: die App loggt es laut: dann steht die Stripe-Einstellung nicht auf 14
    #: Tage, oder das Abo ist jünger als der Vorlauf.
    verspaetet: bool = False
    tage_vorher: int | None = None


def schluessel(abo_id: str, periode_beginn: datetime) -> str:
    """Idempotenz-Schlüssel: ein Abo, eine Periode, höchstens eine Mail.

    Stripe stellt Ereignisse **mindestens einmal** zu, und ``invoice.upcoming``
    kommt bei einer Änderung am Abo (Plätze, Plan) für dieselbe Periode erneut.
    Die App legt den Schlüssel mit ``UNIQUE`` ab und verschickt nur, wenn das
    Einfügen geklappt hat — in derselben Transaktion, nicht „erst prüfen, dann
    einfügen".

    Sekundengenau in UTC: zwei Perioden desselben Abos beginnen nie in
    derselben Sekunde, und die Zeitzone darf den Schlüssel nicht verschieben.
    """
    if not abo_id:
        raise ValueError("abo_id fehlt — ohne Abo gibt es keine Verlängerung")
    if periode_beginn.tzinfo is None:
        raise ValueError("periode_beginn braucht eine Zeitzone")
    return f"{abo_id}:{int(periode_beginn.timestamp())}"


def entscheiden(
    vorschau: Vorschau,
    *,
    code_laufzeit: str | None,
    vorige_rechnung_rabattiert: bool,
    schon_gewarnt: bool = False,
    abo_endet: bool = False,
    nur_im_vorlauf: bool = False,
    jetzt: datetime | None = None,
) -> Entscheidung:
    """Ist die kommende Rechnung die erste ohne Rabatt — und soll die Mail raus?

    ``code_laufzeit`` ist ``discount_duration`` des an das Konto gebundenen
    Codes (``"months"``/``"forever"``), ``None`` ohne Code. Ohne Code gab es
    keinen Rabatt aus diesem System und damit keinen Preissprung, den es
    anzukündigen gilt.

    ``vorige_rechnung_rabattiert``: hatte die zuletzt bezahlte Abo-Rechnung
    einen Rabatt? (Stripe: ``subscription.latest_invoice.total_discount_amounts``
    nicht leer — oder die eigene Buchung der App.)

    ``schon_gewarnt``: der :func:`schluessel` dieser Vorschau liegt schon in der
    Tabelle der App.

    ``abo_endet``: ``cancel_at_period_end`` oder ein beendetes Abo — wer schon
    gekündigt hat, bekommt keine Ankündigung einer Rechnung, die nie kommt.

    ``nur_im_vorlauf``: für den täglichen Lauf über den Abo-Stand. Dort fragt
    die App jeden Tag, und erst ab :data:`VORLAUF_TAGE` vor der Rechnung ist
    die Antwort „ja". Beim Stripe-Ereignis bleibt es ``False`` — Stripe
    entscheidet über den Zeitpunkt, und eine Einstellung auf 30 Tage ist kein
    Grund, die Mail zu verschlucken.

    Die Reihenfolge ist Absicht: erst die Fälle, in denen es nie eine Mail
    gibt, dann der Fehlerfall, dann die Zeit.
    """
    jetzt = jetzt or datetime.now(timezone.utc)

    if code_laufzeit is None:
        return Entscheidung(False, KEIN_CODE)

    if code_laufzeit == "forever":
        # Dauerhaft heisst: kein Preissprung, keine Vorwarnung (§4.9 letzter
        # Satz). Fehlt der Rabatt in der Vorschau trotzdem, wird der Kunde
        # gleich zum vollen Preis abgebucht, obwohl ihm „dauerhaft" zugesagt
        # ist — das ist ein Fehler der App oder ein entfernter Coupon, und er
        # muss gesehen werden, bevor Stripe abbucht.
        if vorschau.rabatt_minor <= 0 and vorschau.betrag_minor > 0:
            return Entscheidung(False, DAUERHAFT_OHNE_RABATT)
        return Entscheidung(False, DAUERHAFT)
    if code_laufzeit != "months":
        raise ValueError(f"unbekannte discount_duration: {code_laufzeit!r}")

    if abo_endet:
        return Entscheidung(False, ABO_ENDET)
    if vorschau.rabatt_minor > 0:
        return Entscheidung(False, NOCH_RABATTIERT)
    if not vorige_rechnung_rabattiert:
        # Entweder ist der Sprung schon passiert (zweite volle Rechnung), oder
        # der Code griff nie (gebunden, aber nie rabattiert bezahlt). In
        # beiden Fällen gibt es nichts anzukündigen.
        return Entscheidung(False, VORIGE_UNRABATTIERT)
    if vorschau.betrag_minor <= 0:
        # Guthaben am Kunden oder Gutschrift: es wird nichts abgebucht, also
        # ist es auch kein Preissprung. Die nächste Vorschau entscheidet neu.
        return Entscheidung(False, NULLRECHNUNG)

    sekunden = (vorschau.periode_beginn - jetzt).total_seconds()
    if sekunden <= 0:
        return Entscheidung(False, RECHNUNG_VORBEI)
    if schon_gewarnt:
        return Entscheidung(False, SCHON_GEWARNT)

    # Angebrochene Tage zählen nicht als Vorlauf: „in 13,9 Tagen" ist für den
    # Kunden „in 13 Tagen". Eine Stunde Spielraum, weil Stripe das Ereignis
    # nicht auf die Sekunde genau 14 Tage vorher erzeugt.
    tage = int((sekunden + 3600) // 86400)
    if nur_im_vorlauf and tage > VORLAUF_TAGE:
        return Entscheidung(False, ZU_FRUEH, tage_vorher=tage)
    return Entscheidung(
        True, ERSTE_VOLLE_RECHNUNG, verspaetet=tage < VORLAUF_TAGE, tage_vorher=tage
    )


def aus_abo_stand(
    *,
    abo_id: str,
    naechste_rechnung_am: datetime,
    rabatt_ende: datetime | None,
    rabatt_aktiv: bool,
    betrag_minor: int,
    waehrung: str,
) -> Vorschau:
    """Die Vorschau aus dem Abo selbst — für Abos ohne ``invoice.upcoming``.

    ``naechste_rechnung_am``: Ende der laufenden Periode (Stripe
    ``items.data[].current_period_end``, ältere API-Versionen
    ``current_period_end``). ``rabatt_ende``: ``discount.end`` des Abos —
    ``None`` bei ``forever`` oder ohne Rabatt; ``rabatt_aktiv`` sagt, welcher
    der beiden Fälle es ist. ``betrag_minor``: der Normalpreis der nächsten
    Rechnung, wie die App ihn kennt (Katalogpreis × Plätze).

    **Endet der Rabatt genau zum Rechnungszeitpunkt, ist die Rechnung voll.**
    So rechnet Stripe einen ``repeating``-Coupon über N Monate: N rabattierte
    Rechnungen, die (N+1)-te fällt auf ``discount.end`` und ist voll. Wer hier
    ``<`` statt ``<=`` schreibt, warnt einen Monat zu spät — nach dem
    Preissprung.
    """
    if rabatt_ende is not None and not rabatt_aktiv:
        raise ValueError("rabatt_ende ohne aktiven Rabatt ist kein Abo-Stand")
    for feld, wert in (("naechste_rechnung_am", naechste_rechnung_am),
                       ("rabatt_ende", rabatt_ende)):
        if wert is not None and wert.tzinfo is None:
            raise ValueError(f"{feld} braucht eine Zeitzone")
    noch_rabattiert = rabatt_aktiv and (
        rabatt_ende is None or rabatt_ende > naechste_rechnung_am
    )
    if not waehrung:
        raise ValueError("waehrung fehlt")
    return Vorschau(
        abo_id=abo_id,
        periode_beginn=naechste_rechnung_am,
        betrag_minor=betrag_minor,
        # Der Betrag des Rabatts ist hier unbekannt und für die Regel egal:
        # sie fragt nur, OB rabattiert wird.
        rabatt_minor=1 if noch_rabattiert else 0,
        waehrung=waehrung.lower(),
    )


# ---------------------------------------------------------------------------
# Ohne Stripe-Abfrage: Rabattende aus den Daten der App
# ---------------------------------------------------------------------------
def _monate_dazu(zeitpunkt: datetime, monate: int) -> datetime:
    """Wie ``gutschein_regeln._monate_dazu`` — bewusst dupliziert, weil jedes
    Modul hier allein kopierbar bleibt (die Apps führen sie byte-identisch,
    ohne Geschwister-Import). Der 31. plus ein Monat ist der letzte Tag des
    Folgemonats; so legt auch Stripe die Verlängerung."""
    jahr = zeitpunkt.year + (zeitpunkt.month - 1 + monate) // 12
    monat = (zeitpunkt.month - 1 + monate) % 12 + 1
    schalt = jahr % 4 == 0 and (jahr % 100 != 0 or jahr % 400 == 0)
    letzter = [31, 29 if schalt else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][monat - 1]
    return zeitpunkt.replace(year=jahr, month=monat, day=min(zeitpunkt.day, letzter))


def rabatt_ende(erste_zahlung: datetime, gewaehrte_monate: int | None) -> datetime | None:
    """Wann die erste Rechnung zum Normalpreis fällig wird — aus der App selbst.

    ``erste_zahlung``: Zeitpunkt der ersten bezahlten (rabattierten)
    Abo-Rechnung, gleichzeitig der Abrechnungsanker. ``gewaehrte_monate``:
    ``gutschein_regeln.gewaehrte_monate(interval, discount_months)`` — also
    bei jährlicher Zahlung schon auf ganze Jahre aufgerundet; ``None`` bei
    ``forever`` (es gibt kein Ende).

    Warum nicht Stripes ``discount.end``: bei einem ``once``-Coupon (eine
    Jahresrechnung, §4.2) ist es leer, und nach der ersten Rechnung ist der
    Rabatt vom Abo verschwunden. Die eine Quelle, die für beide Coupon-Arten
    gilt, ist die erste Rechnung plus die zugesagten Monate.
    """
    if erste_zahlung.tzinfo is None:
        raise ValueError("erste_zahlung braucht eine Zeitzone")
    if gewaehrte_monate is None:
        return None
    if gewaehrte_monate < 1:
        raise ValueError("gewaehrte_monate muss mindestens 1 sein — leer heisst dauerhaft, nie 0")
    return _monate_dazu(erste_zahlung, gewaehrte_monate)


def faellig(
    ende: datetime | None,
    *,
    schon_gewarnt: bool = False,
    abo_endet: bool = False,
    jetzt: datetime | None = None,
) -> Entscheidung:
    """Täglicher Lauf: ist heute der Tag für die Vorwarnung?

    Fenster ``[ende − 14 Tage, ende)``: davor :data:`ZU_FRUEH`, ab ``ende``
    :data:`VERPASST` (keine Mail nach dem Preissprung, laut loggen).
    ``ende`` aus :func:`rabatt_ende`; ``None`` = dauerhaft.

    Der Lauf braucht keine Stripe-Einstellung und deckt Karte und Rechnung
    gleich ab. Wer ``invoice.upcoming`` nutzt, nimmt :func:`entscheiden` —
    beide Wege sind gleichwertig, eine App wählt **einen** davon je Abo-Art,
    damit niemand zwei Mails bekommt (der :func:`schluessel` schützt nur
    innerhalb eines Weges, wenn beide denselben Periodenbeginn verwenden).
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    if ende is None:
        return Entscheidung(False, DAUERHAFT)
    if ende.tzinfo is None:
        raise ValueError("ende braucht eine Zeitzone")
    if abo_endet:
        return Entscheidung(False, ABO_ENDET)
    if jetzt >= ende:
        return Entscheidung(False, VERPASST)
    if schon_gewarnt:
        return Entscheidung(False, SCHON_GEWARNT)
    if jetzt < ende - timedelta(days=VORLAUF_TAGE):
        return Entscheidung(False, ZU_FRUEH)
    tage = int(((ende - jetzt).total_seconds() + 3600) // 86400)
    return Entscheidung(True, ERSTE_VOLLE_RECHNUNG, verspaetet=tage < VORLAUF_TAGE, tage_vorher=tage)


def pruefe_preise(normal_minor: int, rabattiert_minor: int, waehrung: str) -> None:
    """Die beiden Preise der Mail — die App liefert sie, das Modul prüft nur.

    Die Mail ist nur ehrlich, wenn sie einen Sprung ankündigt: Normalpreis
    über dem bisherigen. Ist er es nicht, stimmt der Katalog oder der Code
    nicht, und eine Mail „ab dann zahlst du 0 € mehr" wäre der Beleg dafür.
    """
    if not waehrung:
        raise ValueError("waehrung fehlt")
    if rabattiert_minor < 0:
        raise ValueError("rabattiert_minor darf nicht negativ sein")
    if normal_minor <= rabattiert_minor:
        raise ValueError("Normalpreis nicht über dem rabattierten — kein Preissprung")


# ---------------------------------------------------------------------------
# Stripe-Nahtstelle
# ---------------------------------------------------------------------------
def _zeit(wert: Any, feld: str) -> datetime:
    if not isinstance(wert, int) or isinstance(wert, bool):
        raise ValueError(f"{feld} fehlt oder ist kein Unix-Zeitstempel")
    return datetime.fromtimestamp(wert, tz=timezone.utc)


def _abo_id(invoice: Mapping[str, Any]) -> str:
    """Abo-ID über beide Stripe-Formen.

    Bis API-Version ``2025-03-31.basil`` steht sie in ``subscription``, danach
    in ``parent.subscription_details.subscription``. Die Flotte hat beide im
    Einsatz (Vokabero liest beide). Das ist keine Ausweichkette über ähnliche
    Felder, sondern dieselbe Angabe in zwei dokumentierten Formaten — und
    fehlt sie in beiden, ist es keine Abo-Rechnung, und das wird gesagt.
    """
    if "subscription" in invoice:
        abo = invoice["subscription"]
    else:
        details = (invoice.get("parent") or {}).get("subscription_details") or {}
        abo = details.get("subscription")
    if isinstance(abo, Mapping):
        abo = abo.get("id")
    if not isinstance(abo, str) or not abo:
        raise ValueError("invoice.upcoming ohne Abo — keine Abo-Verlängerung")
    return abo


def _ist_abo_zeile(zeile: Mapping[str, Any]) -> bool:
    # Alte Form: ``type == "subscription"``; neue Form (basil): ``parent.type``.
    if "type" in zeile:
        return zeile["type"] == "subscription"
    return (zeile.get("parent") or {}).get("type") == "subscription_item_details"


def aus_upcoming(invoice: Mapping[str, Any]) -> Vorschau:
    """``event.data.object`` von ``invoice.upcoming`` als :class:`Vorschau`.

    Der Periodenbeginn kommt aus der **Abo-Zeile**, nicht aus
    ``invoice.period_start``: bei einer Verlängerungsrechnung beschreiben die
    Rechnungsfelder die *abgelaufene* Periode (dort sammeln sich nutzungs-
    abhängige Posten), die Abo-Zeile dagegen die neue — und deren Beginn ist
    der Zeitpunkt, an dem Stripe abbucht.
    """
    zeilen = ((invoice.get("lines") or {}).get("data")) or []
    abo_zeilen = [z for z in zeilen if _ist_abo_zeile(z)]
    if not abo_zeilen:
        raise ValueError("invoice.upcoming ohne Abo-Zeile — keine Abo-Verlängerung")
    # Mehrere Abo-Zeilen (mehrere Preise am Abo) beginnen gemeinsam; die
    # früheste ist die Verlängerung.
    beginn = min(
        _zeit((z.get("period") or {}).get("start"), "lines.data[].period.start")
        for z in abo_zeilen
    )

    rabatte = invoice.get("total_discount_amounts")
    if rabatte is None:
        raise ValueError("total_discount_amounts fehlt — Rabatt nicht bestimmbar")
    rabatt = sum(int(r["amount"]) for r in rabatte)

    total = invoice.get("total")
    if not isinstance(total, int):
        raise ValueError("total fehlt")
    waehrung = invoice.get("currency")
    if not isinstance(waehrung, str) or not waehrung:
        raise ValueError("currency fehlt")

    return Vorschau(
        abo_id=_abo_id(invoice),
        periode_beginn=beginn,
        betrag_minor=total,
        rabatt_minor=rabatt,
        waehrung=waehrung.lower(),
    )
