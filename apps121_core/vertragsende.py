"""Vertragsende ohne Anmeldung: Kündigen (§312k BGB) und Widerrufen (§356a BGB).

Spec: ``docs/FLEET_VERTRAGSENDE_SPEC.md``. Beschlossen am 29.09.2026, zuerst
gebaut in paperball-finance. Hier stehen die Regeln ohne Speicher, damit alle
Apps sich gleich *entscheiden*: dasselbe Prinzip wie :mod:`support_zugriff`
und :mod:`gutschein_regeln`.

Was hier steht und was nicht
----------------------------
Hier steht: ist eine Erklärung vollständig, welche Verträge meint sie, zu
welchem Zeitpunkt endet jeder davon, läuft die Widerrufsfrist noch, wie viel
wird erstattet, darf eine Kündigung zurückgenommen werden, und wann darf die
Zeile weg. Nicht hier steht die Speicherung (``contract_notices`` in der App),
der Zahlungsanbieter (Stripe ruft die App) und der Mailversand.

Die Entscheidungen, die mehr zählen als der Code
------------------------------------------------
1. **Das Formular verrät nicht, wer Kunde ist.** Die Antwort auf das Absenden
   ist für jede Eingabe dieselbe — Beleg der Erklärung, wie sie abgegeben wurde,
   nie „Vertrag gefunden“. Was gefunden wurde, steht nur in der Mail an die
   angegebene Adresse. Deshalb fragt das Formular nach dem Umfang
   (:class:`Umfang`: „mein persönliches Abo“ / „Abo eines Accounts, dessen
   Inhaber ich bin“ / „alle“) und nie nach einer Auswahl aus einer Liste.
2. **Zugeordnet wird über die E-Mail-Adresse, nie über die Rechnungsnummer
   allein.** Eine Rechnungsnummer lässt sich raten oder steht auf einem
   weitergeleiteten Beleg. Passt nur sie, wird nichts automatisch beendet —
   die Erklärung geht an den Support (:attr:`Pruefgrund.INVOICE_ONLY`).
3. **Eine ordentliche Kündigung endet ohne Handgriff.** Frühestens zum Ende
   des laufenden Abrechnungszeitraums, sonst zum gewünschten Tag. Eine
   außerordentliche endet genauso automatisch; nur die Frage nach einem
   FRÜHEREN Ende und einer Erstattung geht an einen Menschen.
4. **Ein Widerruf in der Frist beendet sofort und erstattet** — ganz, solange
   der Kunde nicht ausdrücklich verlangt hat, dass die Leistung vor Ablauf der
   Frist beginnt (§357a Abs. 2); dann anteilig. Ein Widerruf NACH der Frist
   ist keine Sackgasse: er wird als ordentliche Kündigung zum frühestmöglichen
   Zeitpunkt umgesetzt (:attr:`Hinweis.WITHDRAWAL_LATE`), und die Mail sagt es.
5. **Die Widerrufsfrist rechnet zugunsten des Kunden.** Ohne Belehrung höchstens
   zwölf Monate und 14 Tage (§356 Abs. 3). Das Fristende fällt nie auf einen
   Samstag, Sonntag oder bundesweiten Feiertag (§193 BGB) — landesweite
   Feiertage verlängern hier nicht, bundesweite schon; im Zweifel länger.
6. **Eine Kündigung lässt sich zurücknehmen, bis sie wirkt.** Der Link in der
   Bestätigung ist die Antwort auf Entscheidung 1: wer eine fremde Adresse
   einträgt, beendet nichts sofort — der Inhaber bekommt die Mail und nimmt
   zurück. Ein Widerruf ist nicht per Link rücknehmbar (Geld ist geflossen).
7. **Fehler sind Codes** (Regel #23). Den Satz baut die App in der Sprache der
   Person.

Nur stdlib. Kein SQLAlchemy, kein FastAPI, keine App-Importe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

__all__ = [
    "AUDIT_AKTIONEN",
    "BERLIN",
    "GRUND_MAX",
    "MAIL_VORLAGEN",
    "NAME_MAX",
    "RECHNUNGSNUMMER_MAX",
    "WIDERRUFSFRIST_TAGE",
    "WIEDERHOLUNG_FENSTER",
    "Art",
    "Entscheidung",
    "Fehler",
    "Hinweis",
    "Massnahme",
    "Pruefgrund",
    "Schritt",
    "Status",
    "Umfang",
    "Vertrag",
    "Zeitpunkt",
    "Zuordnung",
    "darf_zuruecknehmen",
    "ende_des_tages",
    "entscheide",
    "erstattung_cent",
    "ist_honigtopf",
    "loeschbar_ab",
    "normalisiere_email",
    "ordne_zu",
    "pruefe_erklaerung",
    "widerrufsfrist_ende",
    "wiederholungs_schluessel",
    "zuruecknahme_gueltig_bis",
]

#: Fristen nach deutschem Recht rechnen in deutschen Kalendertagen, nicht in UTC.
BERLIN = ZoneInfo("Europe/Berlin")

#: §355 Abs. 2 BGB.
WIDERRUFSFRIST_TAGE = 14

#: §356 Abs. 3 S. 2 BGB: ohne Belehrung erlischt das Widerrufsrecht spätestens
#: zwölf Monate und 14 Tage nach Vertragsschluss.
_HOECHSTFRIST_MONATE = 12

#: Längen, die die Oberfläche als ``maxLength`` setzt und das Backend prüft.
NAME_MAX = 200
GRUND_MAX = 2000
RECHNUNGSNUMMER_MAX = 64

#: Dieselbe Erklärung (Adresse + Art + Umfang) innerhalb dieses Fensters ist
#: ein Doppelklick oder ein Neuladen, keine zweite Erklärung: gleicher Beleg,
#: keine zweite Mail.
WIEDERHOLUNG_FENSTER = timedelta(minutes=10)

#: Regelverjährung (§195, §199 BGB): drei Jahre ab Ende des Jahres, in dem die
#: Erklärung einging. So lange ist sie Beweismittel — danach darf sie weg.
_AUFBEWAHRUNG_JAHRE = 3

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Art(str, Enum):
    """Was erklärt wird. §312k Abs. 3 Nr. 1 verlangt die Art der Kündigung."""

    ORDINARY = "ordinary"  # ordentliche Kündigung
    EXTRAORDINARY = "extraordinary"  # außerordentliche Kündigung, mit Grund
    WITHDRAWAL = "withdrawal"  # Widerruf (§356a)


class Umfang(str, Enum):
    """Welcher Vertrag gemeint ist — ohne eine Kundenliste zu zeigen."""

    PERSONAL = "personal"  # mein persönliches Abo
    ACCOUNT = "account"  # Abo eines Accounts, dessen Inhaber ich bin
    ALL = "all"  # alle meine Verträge


class Zeitpunkt(str, Enum):
    """§312k Abs. 3 Nr. 4: wann der Vertrag enden soll. Fehlt die Angabe,
    gilt der frühestmögliche Zeitpunkt (§312k Abs. 4 S. 2)."""

    EARLIEST = "earliest"
    DATE = "date"


class Status(str, Enum):
    """Die Zustände einer Zeile in ``contract_notices``."""

    RECEIVED = "received"  # gespeichert, Verarbeitung steht aus
    APPLIED = "applied"  # automatisch umgesetzt, nichts offen
    REVIEW = "review"  # umgesetzt, soweit es geht — Rest liegt beim Support
    UNMATCHED = "unmatched"  # kein Vertrag unter dieser Adresse, an Support
    REVOKED = "revoked"  # vom Kunden über den Link zurückgenommen


class Massnahme(str, Enum):
    """Was mit EINEM Vertrag geschieht."""

    END_AT = "end_at"  # endet zum Zeitpunkt ``zum`` (Stripe: cancel_at)
    END_NOW_REFUND = "end_now_refund"  # endet sofort, Erstattung
    ALREADY_ENDING = "already_ending"  # endet ohnehin zu oder vor ``zum``


class Pruefgrund(str, Enum):
    """Warum ein Mensch draufschauen muss. Beendet wird trotzdem, was geht."""

    EARLIER_END_REQUESTED = "earlier_end_requested"  # außerordentlich
    INVOICE_ONLY = "invoice_only"  # nur die Rechnungsnummer passt
    NO_CONTRACT = "no_contract"  # nichts gefunden


class Hinweis(str, Enum):
    """Was die Bestätigungsmail zusätzlich sagen muss."""

    WITHDRAWAL_LATE = "withdrawal_late"  # Frist vorbei → als Kündigung umgesetzt
    DATE_BEFORE_EARLIEST = "date_before_earliest"  # Wunschtag zu früh → frühestmöglich


class Fehler(str, Enum):
    """Maschinencodes. Die App übersetzt sie als ``errors.contract_notice.<code>``."""

    NAME_REQUIRED = "name_required"  # 422
    EMAIL_INVALID = "email_invalid"  # 422
    REASON_REQUIRED = "reason_required"  # 422, außerordentlich ohne Grund
    DATE_REQUIRED = "date_required"  # 422, „zum Datum“ ohne Datum
    DATE_IN_PAST = "date_in_past"  # 422
    TOO_LONG = "too_long"  # 422
    NOTICE_NOT_FOUND = "notice_not_found"  # 404, Rücknahme-Link unbekannt
    NOT_REVOCABLE = "not_revocable"  # 409, Widerruf oder schon zurückgenommen
    ALREADY_EFFECTIVE = "already_effective"  # 409, Vertrag ist schon beendet


#: Audit-Aktionen (FLEET_ADMIN_SPEC §4.1, ``<bereich>.<verb>``).
AUDIT_AKTIONEN: frozenset[str] = frozenset(
    {
        "contract_notice.receive",
        "contract_notice.apply",
        "contract_notice.review",
        "contract_notice.revoke",
        "contract_notice.refund",
    }
)

#: Mail-Vorlagen, die jede App in allen ihren Sprachen führt.
MAIL_VORLAGEN: frozenset[str] = frozenset(
    {
        "contract_notice_confirmation",  # an die angegebene Adresse, immer
        "contract_notice_support",  # an den Support bei REVIEW/UNMATCHED
    }
)


# --- Eingabe ---------------------------------------------------------------


def normalisiere_email(email: str | None) -> str:
    """Kleinschreibung, ohne Rand. Für Vergleich UND Speicherung."""
    return (email or "").strip().lower()


def ist_honigtopf(wert: str | None) -> bool:
    """Das unsichtbare Feld ist gefüllt → ein Programm, kein Mensch.

    Die App antwortet trotzdem mit demselben Beleg (Entscheidung 1 gilt auch
    für Programme) und verarbeitet nichts.
    """
    return bool(wert and wert.strip())


def pruefe_erklaerung(
    *,
    art: Art,
    name: str | None,
    email: str | None,
    zeitpunkt: Zeitpunkt,
    wunschdatum: date | None,
    grund: str | None,
    rechnungsnummer: str | None,
    heute: date,
) -> list[Fehler]:
    """Alle Fehler auf einmal — ein Formular, das nur den ersten nennt, schickt
    die Person dreimal zurück. ``heute`` ist das Datum in Berlin."""
    fehler: list[Fehler] = []
    name_s = (name or "").strip()
    if not name_s:
        fehler.append(Fehler.NAME_REQUIRED)
    if not _EMAIL.match(normalisiere_email(email)):
        fehler.append(Fehler.EMAIL_INVALID)
    if art is Art.EXTRAORDINARY and not (grund or "").strip():
        fehler.append(Fehler.REASON_REQUIRED)
    # Ein Widerruf wirkt sofort; ein Wunschtermin dort wäre bedeutungslos.
    if art is not Art.WITHDRAWAL and zeitpunkt is Zeitpunkt.DATE:
        if wunschdatum is None:
            fehler.append(Fehler.DATE_REQUIRED)
        elif wunschdatum < heute:
            fehler.append(Fehler.DATE_IN_PAST)
    if (
        len(name_s) > NAME_MAX
        or len((grund or "").strip()) > GRUND_MAX
        or len((rechnungsnummer or "").strip()) > RECHNUNGSNUMMER_MAX
    ):
        fehler.append(Fehler.TOO_LONG)
    return fehler


def wiederholungs_schluessel(email: str, art: Art, umfang: Umfang) -> str:
    """Womit die App prüft, ob dieselbe Erklärung gerade schon einging."""
    return f"{normalisiere_email(email)}|{art.value}|{umfang.value}"


# --- Zuordnung -------------------------------------------------------------


@dataclass(frozen=True)
class Vertrag:
    """Was die App über einen laufenden Vertrag weiß.

    ``emails`` sind ALLE Adressen, unter denen der Vertrag erkannt wird:
    Anmeldeadresse des Kontos, Rechnungsadresse beim Zahlungsanbieter, beim
    Account die Adresse des Inhabers — normalisiert.
    """

    id: str
    umfang: Umfang  # PERSONAL oder ACCOUNT, nie ALL
    emails: frozenset[str]
    rechnungsnummern: frozenset[str]
    abgeschlossen_am: datetime
    laufzeitende: datetime  # Ende des laufenden Abrechnungszeitraums
    endet_am: datetime | None = None  # bereits geplantes Ende
    belehrt_am: datetime | None = None  # Widerrufsbelehrung erteilt
    #: Hat der Kunde ausdrücklich verlangt, dass die Leistung vor Ablauf der
    #: Widerrufsfrist beginnt, und wurde er über den Wertersatz belehrt? Nur
    #: dann wird anteilig erstattet (§357a Abs. 2).
    leistungsbeginn_verlangt: bool = False

    def __post_init__(self) -> None:
        if self.umfang is Umfang.ALL:
            raise ValueError("Ein Vertrag ist persönlich oder ein Account, nie beides.")
        for feld in ("abgeschlossen_am", "laufzeitende", "endet_am", "belehrt_am"):
            wert = getattr(self, feld)
            if wert is not None and wert.tzinfo is None:
                raise ValueError(f"{feld} braucht eine Zeitzone.")


@dataclass(frozen=True)
class Zuordnung:
    """Welche Verträge eine Erklärung meint."""

    #: Adresse passt und Umfang passt — diese werden automatisch beendet.
    vertraege: tuple[Vertrag, ...]
    #: Nur die Rechnungsnummer passt — NICHT automatisch (Entscheidung 2).
    nur_rechnung: tuple[Vertrag, ...]


def ordne_zu(
    *,
    email: str,
    umfang: Umfang,
    rechnungsnummer: str | None,
    kandidaten: list[Vertrag] | tuple[Vertrag, ...],
) -> Zuordnung:
    """Die App gibt alle Verträge herein, die über Adresse ODER Rechnungsnummer
    in Frage kommen; hier wird entschieden, welche gemeint sind.

    Die Rechnungsnummer ENGT NICHT EIN: wer „alle“ wählt und eine Nummer
    angibt, meint trotzdem alle. Sie hilft nur, wenn die Adresse nichts findet.
    """
    adresse = normalisiere_email(email)
    passend = tuple(
        v
        for v in kandidaten
        if adresse in v.emails and (umfang is Umfang.ALL or v.umfang is umfang)
    )
    if passend:
        return Zuordnung(vertraege=passend, nur_rechnung=())
    nummer = (rechnungsnummer or "").strip()
    if not nummer:
        return Zuordnung(vertraege=(), nur_rechnung=())
    return Zuordnung(
        vertraege=(),
        nur_rechnung=tuple(v for v in kandidaten if nummer in v.rechnungsnummern),
    )


# --- Fristen ---------------------------------------------------------------


def ende_des_tages(tag: date) -> datetime:
    """„Zum 31.10.“ heißt: bis 31.10. 24:00 Berliner Zeit."""
    return datetime.combine(tag + timedelta(days=1), time(0, 0), tzinfo=BERLIN)


def _ostersonntag(jahr: int) -> date:
    # Gaußsche Osterformel in der Fassung von Meeus/Jones/Butcher.
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    monat, tag = divmod(h + l_ - 7 * m + 114, 31)
    return date(jahr, monat, tag + 1)


def _bundesweite_feiertage(jahr: int) -> set[date]:
    ostern = _ostersonntag(jahr)
    return {
        date(jahr, 1, 1),
        ostern - timedelta(days=2),  # Karfreitag
        ostern + timedelta(days=1),  # Ostermontag
        date(jahr, 5, 1),
        ostern + timedelta(days=39),  # Christi Himmelfahrt
        ostern + timedelta(days=50),  # Pfingstmontag
        date(jahr, 10, 3),
        date(jahr, 12, 25),
        date(jahr, 12, 26),
    }


def _werktag_ab(tag: date) -> date:
    """§193 BGB: fällt das Fristende auf Samstag, Sonntag oder Feiertag, tritt
    der nächste Werktag an seine Stelle."""
    while tag.weekday() >= 5 or tag in _bundesweite_feiertage(tag.year):
        tag += timedelta(days=1)
    return tag


def _plus_monate(tag: date, monate: int) -> date:
    jahr, monat = divmod(tag.month - 1 + monate, 12)
    jahr += tag.year
    monat += 1
    # §188 Abs. 3: fehlt der Tag im Zielmonat, gilt der letzte des Monats.
    for t in (tag.day, 30, 29, 28):
        try:
            return date(jahr, monat, t)
        except ValueError:
            continue
    raise AssertionError("unerreichbar")


def widerrufsfrist_ende(abgeschlossen_am: datetime, belehrt_am: datetime | None) -> datetime:
    """Bis wann ein Widerruf fristgerecht ist (Zeitpunkt, exklusiv).

    Die Frist beginnt mit dem Vertragsschluss, nicht aber vor der Belehrung
    (§356 Abs. 3 S. 1); der Tag des Ereignisses zählt nicht mit (§187 Abs. 1).
    Ohne Belehrung — oder mit einer, die zu spät kam — ist nach zwölf Monaten
    und 14 Tagen Schluss (§356 Abs. 3 S. 2).
    """
    start = abgeschlossen_am.astimezone(BERLIN).date()
    hoechstens = _plus_monate(start, _HOECHSTFRIST_MONATE) + timedelta(days=WIDERRUFSFRIST_TAGE)
    if belehrt_am is None:
        letzter = hoechstens
    else:
        beginn = max(abgeschlossen_am, belehrt_am).astimezone(BERLIN).date()
        letzter = min(beginn + timedelta(days=WIDERRUFSFRIST_TAGE), hoechstens)
    return ende_des_tages(_werktag_ab(letzter))


def erstattung_cent(
    *,
    gezahlt_cent: int,
    leistungsbeginn_verlangt: bool,
    genutzt: timedelta,
    laufzeit: timedelta,
) -> int:
    """Wie viel ein Widerruf in der Frist zurückzahlt.

    Ohne ausdrückliches Verlangen des Leistungsbeginns (samt Belehrung über den
    Wertersatz) alles. Sonst der Gesamtpreis abzüglich des Anteils der schon
    erbrachten Zeit (§357a Abs. 2 S. 4) — gerundet zugunsten des Kunden.
    """
    if gezahlt_cent < 0:
        raise ValueError("gezahlt_cent darf nicht negativ sein.")
    if not leistungsbeginn_verlangt:
        return gezahlt_cent
    gesamt = laufzeit.total_seconds()
    if gesamt <= 0:
        raise ValueError("laufzeit muss positiv sein.")
    anteil = min(max(genutzt.total_seconds(), 0.0), gesamt)
    wertersatz = int(gezahlt_cent * anteil // gesamt)  # abrunden = Kunde vorn
    return gezahlt_cent - wertersatz


# --- Entscheidung ----------------------------------------------------------


@dataclass(frozen=True)
class Schritt:
    """Was mit einem Vertrag geschieht."""

    vertrag_id: str
    massnahme: Massnahme
    #: Ende des Vertrags. Bei ``END_NOW_REFUND`` der Eingang der Erklärung.
    zum: datetime


@dataclass(frozen=True)
class Entscheidung:
    """Was die App umsetzt. ``status`` ist der Zustand NACH erfolgreicher
    Umsetzung; scheitert der Zahlungsanbieter, setzt die App ``REVIEW``."""

    status: Status
    schritte: tuple[Schritt, ...]
    pruefgruende: tuple[Pruefgrund, ...]
    hinweise: tuple[Hinweis, ...]


def entscheide(
    *,
    art: Art,
    zeitpunkt: Zeitpunkt,
    wunschdatum: date | None,
    zuordnung: Zuordnung,
    eingang: datetime,
) -> Entscheidung:
    """Die ganze Entscheidung für eine Erklärung."""
    if eingang.tzinfo is None:
        raise ValueError("eingang braucht eine Zeitzone.")

    if not zuordnung.vertraege:
        if zuordnung.nur_rechnung:
            return Entscheidung(Status.REVIEW, (), (Pruefgrund.INVOICE_ONLY,), ())
        return Entscheidung(Status.UNMATCHED, (), (Pruefgrund.NO_CONTRACT,), ())

    schritte: list[Schritt] = []
    hinweise: set[Hinweis] = set()
    for v in zuordnung.vertraege:
        if art is Art.WITHDRAWAL:
            if eingang < widerrufsfrist_ende(v.abgeschlossen_am, v.belehrt_am):
                schritte.append(Schritt(v.id, Massnahme.END_NOW_REFUND, eingang))
                continue
            # Entscheidung 4: zu spät widerrufen heißt ordentlich gekündigt.
            hinweise.add(Hinweis.WITHDRAWAL_LATE)
            ziel = v.laufzeitende
        else:
            ziel = v.laufzeitende
            if zeitpunkt is Zeitpunkt.DATE and wunschdatum is not None:
                gewuenscht = ende_des_tages(wunschdatum)
                if gewuenscht < v.laufzeitende:
                    hinweise.add(Hinweis.DATE_BEFORE_EARLIEST)
                else:
                    ziel = gewuenscht
        if v.endet_am is not None and v.endet_am <= ziel:
            schritte.append(Schritt(v.id, Massnahme.ALREADY_ENDING, v.endet_am))
        else:
            schritte.append(Schritt(v.id, Massnahme.END_AT, ziel))

    pruefgruende: tuple[Pruefgrund, ...] = ()
    if art is Art.EXTRAORDINARY:
        pruefgruende = (Pruefgrund.EARLIER_END_REQUESTED,)
    return Entscheidung(
        status=Status.REVIEW if pruefgruende else Status.APPLIED,
        schritte=tuple(schritte),
        pruefgruende=pruefgruende,
        hinweise=tuple(sorted(hinweise, key=lambda h: h.value)),
    )


# --- Zurücknehmen und Aufbewahren -----------------------------------------


def zuruecknahme_gueltig_bis(*, wirksam_zum: datetime | None, eingang: datetime) -> datetime:
    """Bis wann der Link in der Bestätigung trägt: bis der Vertrag endet; ohne
    Vertrag (UNMATCHED) 30 Tage — lange genug, um die Mail zu lesen."""
    return wirksam_zum if wirksam_zum is not None else eingang + timedelta(days=30)


def darf_zuruecknehmen(
    *,
    art: Art,
    status: Status,
    wirksam_zum: datetime | None,
    jetzt: datetime,
) -> Fehler | None:
    """``None`` heißt: zurücknehmen erlaubt."""
    if art is Art.WITHDRAWAL or status is Status.REVOKED:
        return Fehler.NOT_REVOCABLE
    if wirksam_zum is not None and jetzt >= wirksam_zum:
        return Fehler.ALREADY_EFFECTIVE
    return None


def loeschbar_ab(eingang: datetime) -> datetime:
    """Ab wann eine Erklärung gelöscht werden darf (und soll)."""
    jahr = eingang.astimezone(BERLIN).year + _AUFBEWAHRUNG_JAHRE + 1
    return datetime(jahr, 1, 1, tzinfo=BERLIN)
