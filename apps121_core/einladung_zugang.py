"""Einladung mit kostenlosem Zugang — und das Ende eines Tarifs von Hand.

Anlass (14.10.2026): Friends & Family sollen jedes Werkzeug der Flotte
kostenlos nutzen. Die Verwaltung lädt eine Person ein und legt dabei fest,
mit welchem Tarif (Frei oder ein bezahlter), optional bis zu welchem Tag und
bei einem Account-Tarif mit welchem Account. Zuerst gebaut in
paperball-finance (PR #970, ``services/einladung_zugang.py``); hier stehen die
Regeln ohne Speicher, damit jede App sich gleich *entscheidet* — dasselbe
Prinzip wie :mod:`plan_freigabe` und :mod:`vertragsende`.

Was hier steht und was nicht
----------------------------
Hier steht: welche Angaben eine Einladung tragen darf (:func:`pruefe_zugang`),
was beim Annehmen an welchem Anker gesetzt wird (:func:`zuweisung`), wie viele
Plätze ein neuer Account bekommt (:func:`plaetze`), was die Annahmeseite VOR
dem Annehmen zeigen darf (:func:`vorschau`), wann ein Tarif von Hand endet
(:func:`ist_abgelaufen`) und worauf er dann zurückfällt (:func:`nach_ende`).
Nicht hier steht die Speicherung (Einladungs-Tabelle, Nutzer, Account), das
Anlegen des Accounts und der Mailversand — das besitzt die App.

Die Entscheidungen, die mehr zählen als der Code
------------------------------------------------
1. **Die Einladung trägt den Zugang, nicht ein zweiter Handgriff danach.**
   Vorher: einladen, warten, auf der Nutzerseite den Tarif setzen — und
   dazwischen lief das Konto auf dem kostenlosen Tarif. Jetzt gilt der Tarif
   ab der ersten Sekunde nach dem Annehmen.
2. **Ein Tarif aus der Einladung ist ein Tarif von Hand** (``plan_source =
   'manual'``, Fleet-Admin-Spec §6.3) — dieselbe Form wie die Zuweisung auf
   der Nutzer- oder Account-Seite. Kein Stripe-Webhook fasst ihn an
   (:func:`plan_freigabe.webhook_darf_plan_setzen`), die Kasse fordert nicht
   zur Zahlung auf (:func:`plan_freigabe.braucht_checkout`).
3. **Frei ist keine Angabe.** „Frei“ heißt: das Konto entsteht wie bei jeder
   Registrierung. Enddatum, Account-Name oder Plätze ohne bezahlten Tarif
   wären Angaben ohne Wirkung — die Verwaltung sähe in der Liste eine Zusage,
   die nie eintritt. Deshalb abgelehnt (:attr:`Fehler.OHNE_TARIF`), nicht
   still verworfen.
4. **Nur was der Katalog führt.** Tarife sind Instanzdaten; die App übergibt
   die Codes, die ihr Katalog heute aktiv führt. Ein Tarif, der zwischen
   Einladen und Annehmen aus dem Katalog verschwindet, verhindert das Konto
   nicht (die Person hat nichts falsch gemacht) — die App legt es ohne
   Zugang an und loggt ERROR (Regel #7: laut).
5. **Der letzte Tag gilt einschliesslich** und ist ein Kalendertag in Berliner
   Zeit — dieselbe Zone wie der Beat-Zeitplan. In UTC gerechnet läge der Lauf
   um 00:20 Berliner Zeit noch auf dem Vortag und beendete einen Tarif einen
   Tag zu spät. Ein letzter Tag in der Vergangenheit wird abgelehnt.
6. **Ein Account-Tarif legt einen neuen Account an** mit der Person als
   Inhaberin; der Tarif hängt am Account, Mitglieder erben ihn. Name ist
   Pflicht, Plätze optional (sonst die Plätze des Tarifs aus dem Katalog,
   mindestens 1), höchstens :data:`PLAETZE_HOECHSTENS` als Schutz gegen einen
   Tippfehler. Ein persönlicher Tarif trägt keinen Account.
7. **Kein Comp über ein laufendes Abo.** Bezahlt der Anker bereits über
   Stripe, würde ein Tarif von Hand das Abo weiterlaufen lassen, während der
   Webhook den Plan nicht mehr anfassen darf — Geld ohne Gegenwert. Die App
   meldet :attr:`Fehler.ABO_LAEUFT`; erst kündigen, dann schenken.
8. **Das Ende ist ein Lauf, kein Versprechen.** Ein Enddatum ohne täglichen
   Lauf wäre eine Zusage, die nie eintritt. Beat :data:`BEAT_NAME` um
   :data:`BEAT_ZEIT` (Berlin) setzt jeden abgelaufenen Tarif von Hand zurück
   auf den kostenlosen Tarif der App mit ``plan_source = 'stripe'``, schreibt
   ein Audit (:data:`AUDIT_AKTION`) und — **nach dem Commit** — die Mail
   :data:`MAIL_VORLAGE`. Eine Mail über einen Zustand, der dann doch
   zurückgerollt wird, wäre falsch. Idempotent: ein zurückgesetzter Tarif
   trägt kein Enddatum mehr, der zweite Lauf am selben Tag findet nichts.
9. **Fehler sind Codes** (Regel #23). Den Satz baut die App:
   ``errors.admin.invitation.zugang.<code>``.

Rabatt und KI (Entscheidungen vom 20.10.2026)
---------------------------------------------
10. **Ein Feld „Rabatt“, zwei Wege.** 100 % (oder keine Angabe) ist das
    Geschenk von oben: Tarif von Hand, kein Stripe, keine Zahlungsdaten.
    1–99 % ist ein **Einmal-Gutschein** für diese Einladung
    (:attr:`Zuweisung.gutschein`): die App legt beim Annehmen einen Code mit
    ``max_redemptions = 1`` an, bindet ihn an das neue Konto, und die Person
    zahlt im Checkout den rabattierten Preis (Gutschein-Spec). Ein
    100-%-Gutschein statt des Geschenks hätte ein 0-€-Abo erzeugt, das nach
    dem Ende still abbucht oder in den Mahnlauf fällt.
11. **Die Laufzeit des Rabatts** ist ``months`` (N Monate ab der ersten
    bezahlten Rechnung) oder ``forever`` — dieselben Werte wie
    ``gutschein_regeln.Rabattlaufzeit``. Ein dauerhafter Rabatt braucht dort
    eine Grenze; der Einmal-Code erfüllt sie immer.
12. **Was nur ein Geschenk tragen kann** — letzter Tag, Plätze, „ohne
    KI-Kontingent“, Testguthaben — lehnt ein Rabatt ab
    (:attr:`Fehler.NUR_GESCHENK`). Wer zahlt, bekommt den Tarif, wie er ist.
13. **KI-Kontingent:** ``tarif`` (Vorgabe) heißt das Monatskontingent des
    Tarifs, Nachkauf zum normalen Preis. ``ohne`` heißt Monatskontingent 0;
    die Plattform-KI läuft dann auf einem optionalen **Testguthaben** oder
    nachgekauften Credits, und in den BYOK-Apps setzt die App die
    Betriebsart ``beides`` (:data:`BYOK_OHNE_KONTINGENT`): ohne Kontingent
    soll die Person wählen können — eigener Schlüssel oder Credits kaufen.
    Mit der Vorgabe ``nur_plattform`` gäbe es den Schlüssel-Reiter gar nicht. ``nur_byok`` gehört nicht in die Einladung,
    sondern auf die Kontoseite der Verwaltung.
14. **Das Testguthaben ist geschenkt und verfällt** — gekaufte Credits nie.
    Frist ab dem Annehmen: die angegebenen Tage, sonst der letzte Tag des
    Geschenks, sonst :data:`TESTGUTHABEN_TAGE_VORGABE`. Die Verwaltung kann
    sie später verlängern (``credits.verlaengere_paket``).
15. **Nur wo es Credits gibt.** Ohne ``credits-py`` in der App gibt es kein
    Kontingent 0 und kein Testguthaben; ``ki_waehlbar=False`` lehnt die
    Angaben ab (:attr:`Fehler.KI_NICHT_WAEHLBAR`), statt sie still zu
    verwerfen.

Nur stdlib. Kein SQLAlchemy, kein FastAPI, keine App-Importe.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

__all__ = [
    "AUDIT_AKTION",
    "BEAT_NAME",
    "BEAT_ZEIT",
    "BERLIN",
    "BYOK_OHNE_KONTINGENT",
    "FEHLER_PRAEFIX",
    "GESCHENK_PROZENT",
    "KI_KONTINGENTE",
    "KI_OHNE",
    "KI_TARIF",
    "MAIL_VORLAGE",
    "PLAETZE_HOECHSTENS",
    "PLAN_SOURCE_MANUELL",
    "PLAN_SOURCE_NACH_ENDE",
    "RABATT_DAUERHAFT",
    "RABATT_LAUFZEITEN",
    "RABATT_MONATE",
    "TAGE_HOECHSTENS",
    "TESTGUTHABEN_HOECHSTENS",
    "TESTGUTHABEN_TAGE_VORGABE",
    "Anker",
    "EinladungsGutschein",
    "Fehler",
    "NachEnde",
    "Zugang",
    "ZugangUngueltig",
    "Zuweisung",
    "heute",
    "ist_abgelaufen",
    "nach_ende",
    "plaetze",
    "pruefe_enddatum",
    "pruefe_zugang",
    "testguthaben_gueltig_bis",
    "vorschau",
    "zuweisung",
]

#: Kalendertage der Plattform. Dieselbe Zone wie ``celery conf.timezone``.
BERLIN = ZoneInfo("Europe/Berlin")

#: Kein Geschäftslimit — Schutz gegen einen Tippfehler (500 statt 5).
PLAETZE_HOECHSTENS = 500

#: Fleet-Admin-Spec §6.3.
PLAN_SOURCE_MANUELL = "manual"
PLAN_SOURCE_NACH_ENDE = "stripe"

#: Name des Beat-Eintrags und Uhrzeit (Stunde, Minute; Berlin). Flottenweit
#: gleich, damit ein Blick in ``celery inspect scheduled`` jeder App reicht.
BEAT_NAME = "manuelle-tarife-beenden"
BEAT_ZEIT = (0, 20)

#: Audit-Aktion je beendetem Tarif und Schlüssel der Mailvorlage.
AUDIT_AKTION = "manual_plan_ended"
MAIL_VORLAGE = "manual_plan_ended"

#: Rabatt in Prozent, der ein Geschenk ist (Tarif von Hand statt Gutschein).
GESCHENK_PROZENT = 100

#: Laufzeiten des Rabatts — dieselben Werte wie ``gutschein_regeln.Rabattlaufzeit``.
RABATT_MONATE = "months"
RABATT_DAUERHAFT = "forever"
RABATT_LAUFZEITEN = (RABATT_MONATE, RABATT_DAUERHAFT)

#: KI-Kontingent der Einladung.
KI_TARIF = "tarif"
KI_OHNE = "ohne"
KI_KONTINGENTE = (KI_TARIF, KI_OHNE)

#: BYOK-Betriebsart, die „ohne KI-Kontingent“ in den BYOK-Apps setzt (BYOK-Spec §1).
BYOK_OHNE_KONTINGENT = "beides"

#: Frist des Testguthabens ohne Angabe und ohne letzten Tag des Geschenks.
TESTGUTHABEN_TAGE_VORGABE = 90
#: Schutz gegen Tippfehler, keine Geschäftsgrenzen: größtes Paket der Leiter, zehn Jahre.
TESTGUTHABEN_HOECHSTENS = 130_000
TAGE_HOECHSTENS = 3650

#: Präfix der Fehlerschlüssel in der App (``<präfix><code>``).
FEHLER_PRAEFIX = "errors.admin.invitation.zugang."


class Fehler(str, Enum):
    """Maschinencodes. Die App übersetzt sie als ``FEHLER_PRAEFIX + code``; alle 400."""

    OHNE_TARIF = "ohne_tarif"  # Enddatum/Account/Plätze ohne bezahlten Tarif
    TARIF_UNBEKANNT = "tarif_unbekannt"  # nicht im aktiven Katalog
    ENDE_VERGANGEN = "ende_vergangen"  # letzter Tag vor heute
    ACCOUNT_NAME_FEHLT = "account_name_fehlt"  # Account-Tarif ohne Namen
    PLAETZE_UNGUELTIG = "plaetze_ungueltig"  # < 1 oder > PLAETZE_HOECHSTENS
    ACCOUNT_NUR_MIT_ACCOUNTTARIF = "account_nur_mit_accounttarif"  # persönlicher Tarif mit Account
    ABO_LAEUFT = "abo_laeuft"  # der Anker bezahlt schon über Stripe
    RABATT_UNGUELTIG = "rabatt_ungueltig"  # nicht 1–100 %
    RABATT_LAUFZEIT_FEHLT = "rabatt_laufzeit_fehlt"  # 1–99 % ohne Laufzeit
    RABATT_MONATE_FEHLEN = "rabatt_monate_fehlen"  # „months“ ohne mindestens einen Monat
    RABATT_MONATE_BEI_DAUERHAFT = "rabatt_monate_bei_dauerhaft"  # „forever“ mit Monaten
    LAUFZEIT_OHNE_RABATT = "laufzeit_ohne_rabatt"  # Laufzeit bei einem Geschenk
    NUR_GESCHENK = "nur_geschenk"  # Enddatum/Plätze/KI ohne Kontingent/Testguthaben bei Rabatt
    KI_NICHT_WAEHLBAR = "ki_nicht_waehlbar"  # App ohne Credits
    TESTGUTHABEN_NUR_OHNE_KONTINGENT = "testguthaben_nur_ohne_kontingent"
    TESTGUTHABEN_UNGUELTIG = "testguthaben_ungueltig"  # < 1 oder > TESTGUTHABEN_HOECHSTENS
    TAGE_OHNE_TESTGUTHABEN = "tage_ohne_testguthaben"
    TAGE_UNGUELTIG = "tage_ungueltig"  # < 1 oder > TAGE_HOECHSTENS

    @property
    def schluessel(self) -> str:
        return FEHLER_PRAEFIX + self.value


class ZugangUngueltig(ValueError):
    """Eine Zugangsangabe, die die App mit 400 und dem Satz zu :attr:`code` ablehnt."""

    def __init__(self, code: Fehler, **werte: object) -> None:
        super().__init__(code.value)
        self.code = code
        #: Platzhalter für den Satz (z. B. ``hoechstens``).
        self.werte = werte


class Anker(str, Enum):
    """Woran der Tarif beim Annehmen gesetzt wird."""

    PERSON = "person"  # am Nutzer (persönlicher Tarif)
    ACCOUNT = "account"  # an einem neuen Account mit der Person als Inhaberin


@dataclass(frozen=True)
class Zugang:
    """Was eine Einladung beim Annehmen vergibt — geprüft, noch nicht angewandt.

    ``plan_code is None`` heißt Frei: das Konto entsteht wie bei jeder Registrierung.
    ``rabatt_prozent is None`` heißt Geschenk (100 %), sonst 1–99 % per Gutschein.
    """

    plan_code: Optional[str] = None
    plan_until: Optional[date] = None
    account_name: Optional[str] = None
    account_seats: Optional[int] = None
    ist_account: bool = False
    rabatt_prozent: Optional[int] = None
    rabatt_laufzeit: Optional[str] = None
    rabatt_monate: Optional[int] = None
    ki_kontingent: str = KI_TARIF
    testguthaben: Optional[int] = None
    testguthaben_tage: Optional[int] = None

    @property
    def ist_frei(self) -> bool:
        return self.plan_code is None

    @property
    def ist_geschenk(self) -> bool:
        return self.plan_code is not None and self.rabatt_prozent is None


@dataclass(frozen=True)
class EinladungsGutschein:
    """Der Einmal-Code, den die App beim Annehmen anlegt und an das neue Konto bindet.

    Die Felder heißen wie in der Gutschein-Spec §2.2; die App übernimmt sie
    unverändert und prüft sie mit ``gutschein_regeln.pruefe_rabatt``.
    """

    discount_percent: int
    discount_duration: str
    discount_months: Optional[int]
    plans: tuple[str, ...]
    max_redemptions: int = 1
    new_customers_only: bool = True


@dataclass(frozen=True)
class Zuweisung:
    """Was die App beim Annehmen setzt. ``anker is None``: nichts (Frei)."""

    anker: Optional[Anker]
    plan_code: Optional[str] = None
    plan_source: Optional[str] = None
    manual_plan_until: Optional[date] = None
    account_name: Optional[str] = None
    #: Nur bei Rabatt: der Code, den die App anlegt und bindet; der Tarif kommt aus dem Checkout.
    gutschein: Optional[EinladungsGutschein] = None
    #: ``ohne`` = Monatskontingent 0 am Anker, bis der Tarif von Hand endet.
    ki_kontingent: str = KI_TARIF
    #: BYOK-Betriebsart, die die App setzt (nur BYOK-Apps); ``None`` = Vorgabe der App.
    byok_betriebsart: Optional[str] = None
    #: Credits für ein Paket der Quelle ``test`` mit :func:`testguthaben_gueltig_bis`.
    testguthaben: Optional[int] = None


@dataclass(frozen=True)
class NachEnde:
    """Was der Lauf an einem abgelaufenen Anker setzt.

    Das KI-Kontingent geht zurück auf den Tarif: ``ohne`` gehört zum Geschenk.
    Ein Testguthaben bleibt unberührt — es hat seine eigene Frist.
    """

    plan_code: Optional[str]
    plan_source: str = PLAN_SOURCE_NACH_ENDE
    manual_plan_until: None = None
    ki_kontingent: str = KI_TARIF


def heute(jetzt: Optional[datetime] = None) -> date:
    """Der heutige Kalendertag in Berliner Zeit (``jetzt`` muss zeitzonenbewusst sein)."""
    if jetzt is None:
        return datetime.now(BERLIN).date()
    if jetzt.tzinfo is None:
        raise ValueError("jetzt braucht eine Zeitzone — ohne wäre der Kalendertag geraten")
    return jetzt.astimezone(BERLIN).date()


def pruefe_enddatum(plan_until: Optional[date], *, am: date) -> Optional[date]:
    """Prüft einen letzten Tag — auch für die Zuweisung auf Nutzer- und Account-Seite."""
    if plan_until is not None and plan_until < am:
        raise ZugangUngueltig(Fehler.ENDE_VERGANGEN)
    return plan_until


def pruefe_zugang(
    *,
    plan_code: Optional[str],
    plan_until: Optional[date],
    account_name: Optional[str],
    account_seats: Optional[int],
    persoenliche_tarife: Collection[str],
    account_tarife: Collection[str],
    am: date,
    kostenloser_tarif: Optional[str] = None,
    plaetze_hoechstens: int = PLAETZE_HOECHSTENS,
    rabatt_prozent: Optional[int] = None,
    rabatt_laufzeit: Optional[str] = None,
    rabatt_monate: Optional[int] = None,
    ki_kontingent: str = KI_TARIF,
    testguthaben: Optional[int] = None,
    testguthaben_tage: Optional[int] = None,
    ki_waehlbar: bool = False,
) -> Zugang:
    """Prüft die Zugangsangaben einer Einladung; :class:`ZugangUngueltig` bei einem Fehler.

    ``persoenliche_tarife`` und ``account_tarife`` sind die bezahlbaren Codes,
    die der Katalog der App heute aktiv führt. Ein leerer Code und der
    ``kostenloser_tarif`` der App bedeuten Frei (Entscheidung 3).
    ``ki_waehlbar``: die App führt Credits (``credits-py``) — erst dann gibt es
    ein Kontingent 0 und ein Testguthaben (Entscheidung 15).
    """
    if ki_kontingent not in KI_KONTINGENTE:
        raise ValueError(f"Unbekanntes KI-Kontingent {ki_kontingent!r}")
    if rabatt_laufzeit is not None and rabatt_laufzeit not in RABATT_LAUFZEITEN:
        raise ValueError(f"Unbekannte Rabattlaufzeit {rabatt_laufzeit!r}")
    gemeinsam = set(persoenliche_tarife) & set(account_tarife)
    if gemeinsam:
        raise ValueError(f"Tarif(e) {sorted(gemeinsam)} zugleich persönlich und Account — die App muss entscheiden")

    code = (plan_code or "").strip() or None
    if code is not None and code == kostenloser_tarif:
        code = None
    name = (account_name or "").strip() or None

    ki_angabe = ki_kontingent != KI_TARIF or testguthaben is not None or testguthaben_tage is not None
    if code is None:
        if (
            plan_until is not None or name is not None or account_seats is not None
            or rabatt_prozent is not None or rabatt_laufzeit is not None or rabatt_monate is not None
            or ki_angabe
        ):
            raise ZugangUngueltig(Fehler.OHNE_TARIF)
        return Zugang()

    if code not in persoenliche_tarife and code not in account_tarife:
        raise ZugangUngueltig(Fehler.TARIF_UNBEKANNT)
    pruefe_enddatum(plan_until, am=am)

    rabatt = _pruefe_rabatt(rabatt_prozent, rabatt_laufzeit, rabatt_monate)
    if rabatt is not None and (plan_until is not None or account_seats is not None or ki_angabe):
        raise ZugangUngueltig(Fehler.NUR_GESCHENK)
    if ki_angabe:
        _pruefe_ki(ki_kontingent, testguthaben, testguthaben_tage, ki_waehlbar=ki_waehlbar)
    ki = {
        "rabatt_prozent": rabatt,
        "rabatt_laufzeit": rabatt_laufzeit if rabatt is not None else None,
        "rabatt_monate": rabatt_monate if rabatt is not None else None,
        "ki_kontingent": ki_kontingent,
        "testguthaben": testguthaben,
        "testguthaben_tage": testguthaben_tage,
    }

    if code in account_tarife:
        if name is None:
            raise ZugangUngueltig(Fehler.ACCOUNT_NAME_FEHLT)
        if account_seats is not None and not 1 <= account_seats <= plaetze_hoechstens:
            raise ZugangUngueltig(Fehler.PLAETZE_UNGUELTIG, hoechstens=plaetze_hoechstens)
        return Zugang(code, plan_until, name, account_seats, ist_account=True, **ki)

    if name is not None or account_seats is not None:
        raise ZugangUngueltig(Fehler.ACCOUNT_NUR_MIT_ACCOUNTTARIF)
    return Zugang(code, plan_until, **ki)


def _pruefe_rabatt(
    prozent: Optional[int], laufzeit: Optional[str], monate: Optional[int]
) -> Optional[int]:
    """Rabatt der Einladung (Entscheidungen 10, 11); ``None`` = Geschenk."""
    if prozent is None or prozent == GESCHENK_PROZENT:
        if laufzeit is not None or monate is not None:
            raise ZugangUngueltig(Fehler.LAUFZEIT_OHNE_RABATT)
        return None
    if not 1 <= prozent < GESCHENK_PROZENT:
        raise ZugangUngueltig(Fehler.RABATT_UNGUELTIG)
    if laufzeit is None:
        raise ZugangUngueltig(Fehler.RABATT_LAUFZEIT_FEHLT)
    if laufzeit == RABATT_MONATE and (monate is None or monate < 1):
        raise ZugangUngueltig(Fehler.RABATT_MONATE_FEHLEN)
    if laufzeit == RABATT_DAUERHAFT and monate is not None:
        raise ZugangUngueltig(Fehler.RABATT_MONATE_BEI_DAUERHAFT)
    return prozent


def _pruefe_ki(
    kontingent: str, testguthaben: Optional[int], tage: Optional[int], *, ki_waehlbar: bool
) -> None:
    """KI-Kontingent und Testguthaben eines Geschenks (Entscheidungen 13–15)."""
    if not ki_waehlbar:
        raise ZugangUngueltig(Fehler.KI_NICHT_WAEHLBAR)
    if testguthaben is not None:
        if kontingent != KI_OHNE:
            raise ZugangUngueltig(Fehler.TESTGUTHABEN_NUR_OHNE_KONTINGENT)
        if not 1 <= testguthaben <= TESTGUTHABEN_HOECHSTENS:
            raise ZugangUngueltig(Fehler.TESTGUTHABEN_UNGUELTIG, hoechstens=TESTGUTHABEN_HOECHSTENS)
    if tage is not None:
        if testguthaben is None:
            raise ZugangUngueltig(Fehler.TAGE_OHNE_TESTGUTHABEN)
        if not 1 <= tage <= TAGE_HOECHSTENS:
            raise ZugangUngueltig(Fehler.TAGE_UNGUELTIG, hoechstens=TAGE_HOECHSTENS)


def zuweisung(zugang: Zugang, *, abo_laeuft: bool = False) -> Zuweisung:
    """Was beim Annehmen gesetzt wird (Entscheidungen 2, 6, 7) — ohne Speicher.

    ``abo_laeuft``: der Anker, an dem der Tarif landen würde, hat schon ein
    Stripe-Abo mit freischaltendem Status (``plan_freigabe.schaltet_frei``).
    Bei einem neuen Konto bzw. neuen Account ist das nie der Fall.
    """
    if zugang.ist_frei:
        return Zuweisung(anker=None)
    account_name = zugang.account_name if zugang.ist_account else None
    if not zugang.ist_geschenk:
        # Rabatt: das Konto entsteht wie bei jeder Registrierung (beim
        # Account-Tarif mit dem Namen aus der Einladung), der Tarif kommt aus
        # dem Checkout. Kein Tarif von Hand — also auch kein Konflikt mit einem Abo.
        assert zugang.rabatt_prozent is not None and zugang.rabatt_laufzeit is not None
        return Zuweisung(
            anker=None,
            account_name=account_name,
            gutschein=EinladungsGutschein(
                discount_percent=zugang.rabatt_prozent,
                discount_duration=zugang.rabatt_laufzeit,
                discount_months=zugang.rabatt_monate,
                plans=(zugang.plan_code,) if zugang.plan_code else (),
            ),
        )
    if abo_laeuft:
        raise ZugangUngueltig(Fehler.ABO_LAEUFT)
    ohne = zugang.ki_kontingent == KI_OHNE
    return Zuweisung(
        anker=Anker.ACCOUNT if zugang.ist_account else Anker.PERSON,
        plan_code=zugang.plan_code,
        plan_source=PLAN_SOURCE_MANUELL,
        manual_plan_until=zugang.plan_until,
        account_name=account_name,
        ki_kontingent=zugang.ki_kontingent,
        byok_betriebsart=BYOK_OHNE_KONTINGENT if ohne else None,
        testguthaben=zugang.testguthaben,
    )


def testguthaben_gueltig_bis(zugang: Zugang, *, angenommen_am: date) -> Optional[datetime]:
    """Ende des Testguthabens als ``credit_pakete.gueltig_bis`` (exklusiv, Berlin).

    N Tage einschließlich des Annahmetags, sonst der letzte Tag des Geschenks,
    sonst :data:`TESTGUTHABEN_TAGE_VORGABE` (Entscheidung 14). Zurück kommt der
    Beginn des Folgetags in Berliner Zeit — ``credits`` zählt ein Paket nur,
    solange ``gueltig_bis > jetzt``, der letzte Tag gilt so noch ganz.
    ``None``, wenn die Einladung kein Testguthaben trägt.
    """
    if zugang.testguthaben is None:
        return None
    if zugang.testguthaben_tage is not None:
        letzter = angenommen_am + timedelta(days=zugang.testguthaben_tage - 1)
    elif zugang.plan_until is not None:
        letzter = zugang.plan_until
    else:
        letzter = angenommen_am + timedelta(days=TESTGUTHABEN_TAGE_VORGABE - 1)
    return datetime.combine(letzter + timedelta(days=1), time(0), tzinfo=BERLIN)


def plaetze(zugang: Zugang, *, plaetze_im_katalog: Optional[int]) -> int:
    """Plätze des neuen Accounts: aus der Einladung, sonst aus dem Katalog, mindestens 1."""
    if not zugang.ist_account:
        raise ValueError("Plätze gibt es nur bei einem Account-Tarif")
    if zugang.account_seats is not None:
        return zugang.account_seats
    return max(plaetze_im_katalog or 1, 1)


def vorschau(zugang: Zugang) -> Optional[dict[str, object]]:
    """Was die öffentliche Annahmeseite VOR dem Annehmen zeigen darf.

    Tarif, letzter Tag (ISO) und Account-Name — nie, wer eingeladen hat, und
    keine Plätze (die gehen nur die Verwaltung und die Inhaberin an).
    ``None`` bei Frei: die Seite zeigt dann nichts zusätzlich.
    """
    if zugang.ist_frei:
        return None
    return {
        "plan_code": zugang.plan_code,
        "plan_until": zugang.plan_until.isoformat() if zugang.plan_until else None,
        "account_name": zugang.account_name if zugang.ist_account else None,
        "rabatt_prozent": zugang.rabatt_prozent,
        "rabatt_laufzeit": zugang.rabatt_laufzeit,
        "rabatt_monate": zugang.rabatt_monate,
        "ki_kontingent": zugang.ki_kontingent,
        "testguthaben": zugang.testguthaben,
    }


def ist_abgelaufen(*, plan_source: Optional[str], manual_plan_until: Optional[date], am: date) -> bool:
    """Ob der Lauf diesen Anker zurücksetzt: Tarif von Hand, letzter Tag vor ``am``.

    Unbefristete Tarife von Hand (kein Datum) und Stripe-/Rechnungs-Tarife
    bleiben stehen — auch wenn versehentlich ein Datum daran hängt.
    """
    return plan_source == PLAN_SOURCE_MANUELL and manual_plan_until is not None and manual_plan_until < am


def nach_ende(*, kostenloser_tarif: Optional[str]) -> NachEnde:
    """Worauf ein abgelaufener Tarif von Hand zurückfällt: den kostenlosen Tarif der App.

    ``kostenloser_tarif`` ist der Code, den auch eine frische Registrierung
    bekommt (``plan_freigabe.KOSTENLOSER_PLAN`` bzw. der der App). ``None``
    nur, wo die App „kein Tarif“ wirklich so speichert (paperball-finance am
    Account: ohne Tarif = kein Account-Grant).
    """
    return NachEnde(plan_code=kostenloser_tarif)
