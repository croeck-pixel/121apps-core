"""§4.9 Vorwarnung vor der ersten vollen Rechnung. Jeder Grund hat einen Test
und eine Gegenprobe — eine Regel, die nie „nein" sagt, verschickt jeden Monat
eine Preissprung-Mail, und eine, die nie „ja" sagt, fällt erst bei der
Kündigungswelle auf."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import gutschein_vorwarnung as v  # noqa: E402

JETZT = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
IN_14 = JETZT + timedelta(days=14)


def vorschau(**kw) -> v.Vorschau:
    werte = dict(
        abo_id="sub_1", periode_beginn=IN_14, betrag_minor=3900, rabatt_minor=0,
        waehrung="eur",
    )
    werte.update(kw)
    return v.Vorschau(**werte)


def entscheide(vs: v.Vorschau | None = None, **kw) -> v.Entscheidung:
    werte = dict(code_laufzeit="months", vorige_rechnung_rabattiert=True, jetzt=JETZT)
    werte.update(kw)
    return v.entscheiden(vs or vorschau(), **werte)


# ── Der eine Fall, der eine Mail auslöst ─────────────────────────────────────
def test_erste_volle_rechnung_14_tage_vorher():
    e = entscheide()
    assert e == v.Entscheidung(True, v.ERSTE_VOLLE_RECHNUNG, verspaetet=False, tage_vorher=14)


def test_kurz_unter_14_tagen_zaehlt_noch_als_14():
    # Stripe erzeugt das Ereignis nicht sekundengenau.
    e = entscheide(vorschau(periode_beginn=IN_14 - timedelta(minutes=30)))
    assert e.senden and e.tage_vorher == 14 and not e.verspaetet


def test_zu_spaet_geht_trotzdem_raus_aber_markiert():
    # Stripe steht noch auf dem Standard von 3 Tagen.
    e = entscheide(vorschau(periode_beginn=JETZT + timedelta(days=3)))
    assert e.senden and e.verspaetet and e.tage_vorher == 3


def test_frueher_als_14_tage_ist_nicht_verspaetet():
    e = entscheide(vorschau(periode_beginn=JETZT + timedelta(days=30)))
    assert e.senden and not e.verspaetet and e.tage_vorher == 30


# ── Gründe gegen die Mail, jeweils mit Gegenprobe ───────────────────────────
def test_ohne_code_keine_mail():
    assert entscheide(code_laufzeit=None) == v.Entscheidung(False, v.KEIN_CODE)


def test_dauerhaft_nie():
    e = entscheide(vorschau(rabatt_minor=1170, betrag_minor=2730), code_laufzeit="forever")
    assert e == v.Entscheidung(False, v.DAUERHAFT)


def test_dauerhaft_auch_wenn_vorige_rabattiert_und_jetzt_voll_ist_ein_fehler():
    # Zugesagt ist „dauerhaft", Stripe bucht gleich voll ab: kein Mailfall,
    # sondern ein Befund, den die App laut melden muss.
    e = entscheide(vorschau(rabatt_minor=0), code_laufzeit="forever")
    assert e == v.Entscheidung(False, v.DAUERHAFT_OHNE_RABATT)


def test_dauerhaft_bei_nullrechnung_kein_fehler():
    e = entscheide(vorschau(rabatt_minor=0, betrag_minor=0), code_laufzeit="forever")
    assert e.grund == v.DAUERHAFT


def test_noch_rabattiert():
    assert entscheide(vorschau(rabatt_minor=780)).grund == v.NOCH_RABATTIERT
    # Gegenprobe: ein Cent weniger Rabatt — keiner — und die Mail geht.
    assert entscheide(vorschau(rabatt_minor=0)).senden


def test_zweite_volle_rechnung_loest_nichts_aus():
    e = entscheide(vorige_rechnung_rabattiert=False)
    assert e == v.Entscheidung(False, v.VORIGE_UNRABATTIERT)
    assert entscheide(vorige_rechnung_rabattiert=True).senden


def test_nullrechnung():
    assert entscheide(vorschau(betrag_minor=0)).grund == v.NULLRECHNUNG
    assert entscheide(vorschau(betrag_minor=-100)).grund == v.NULLRECHNUNG
    assert entscheide(vorschau(betrag_minor=1)).senden


def test_rechnung_schon_vorbei():
    assert entscheide(vorschau(periode_beginn=JETZT)).grund == v.RECHNUNG_VORBEI
    assert entscheide(vorschau(periode_beginn=JETZT - timedelta(days=1))).grund == v.RECHNUNG_VORBEI
    assert entscheide(vorschau(periode_beginn=JETZT + timedelta(seconds=1))).senden


def test_schon_gewarnt():
    assert entscheide(schon_gewarnt=True) == v.Entscheidung(False, v.SCHON_GEWARNT)
    assert entscheide(schon_gewarnt=False).senden


def test_unbekannte_laufzeit_ist_laut():
    with pytest.raises(ValueError):
        entscheide(code_laufzeit="repeating")


# ── Schlüssel ───────────────────────────────────────────────────────────────
def test_schluessel_je_abo_und_periode():
    a = v.schluessel("sub_1", IN_14)
    assert a == f"sub_1:{int(IN_14.timestamp())}"
    assert a == v.schluessel("sub_1", IN_14.astimezone(timezone(timedelta(hours=2))))
    assert a != v.schluessel("sub_2", IN_14)
    assert a != v.schluessel("sub_1", IN_14 + timedelta(days=30))


def test_schluessel_ohne_zeitzone_oder_abo():
    with pytest.raises(ValueError):
        v.schluessel("sub_1", IN_14.replace(tzinfo=None))
    with pytest.raises(ValueError):
        v.schluessel("", IN_14)


# ── Stripe-Ereignis ─────────────────────────────────────────────────────────
BEGINN = int(IN_14.timestamp())
VORHER = BEGINN - 30 * 86400


def upcoming_alt(**kw) -> dict:
    """Form bis API-Version 2025-03-31.basil."""
    inv = {
        "object": "invoice",
        "subscription": "sub_1",
        "currency": "EUR",
        "total": 3900,
        "total_discount_amounts": [],
        # Rechnungsfelder = abgelaufene Periode — darf NICHT gelesen werden.
        "period_start": VORHER, "period_end": BEGINN,
        "lines": {"data": [
            {"type": "invoiceitem", "period": {"start": VORHER, "end": BEGINN}},
            {"type": "subscription", "period": {"start": BEGINN, "end": BEGINN + 30 * 86400}},
        ]},
    }
    inv.update(kw)
    return inv


def upcoming_neu(**kw) -> dict:
    """Form ab API-Version 2025-03-31.basil."""
    inv = {
        "object": "invoice",
        "parent": {"type": "subscription_details",
                   "subscription_details": {"subscription": "sub_1"}},
        "currency": "eur",
        "total": 3900,
        "total_discount_amounts": [],
        "period_start": VORHER, "period_end": BEGINN,
        "lines": {"data": [
            {"parent": {"type": "subscription_item_details"},
             "period": {"start": BEGINN, "end": BEGINN + 30 * 86400}},
        ]},
    }
    inv.update(kw)
    return inv


@pytest.mark.parametrize("bauen", [upcoming_alt, upcoming_neu])
def test_aus_upcoming_beide_formen(bauen):
    vs = v.aus_upcoming(bauen())
    assert vs == v.Vorschau("sub_1", IN_14, 3900, 0, "eur")


def test_aus_upcoming_liest_abo_zeile_nicht_rechnungsperiode():
    vs = v.aus_upcoming(upcoming_alt())
    assert vs.periode_beginn != datetime.fromtimestamp(VORHER, tz=timezone.utc)


def test_aus_upcoming_summiert_rabatte():
    vs = v.aus_upcoming(upcoming_alt(total_discount_amounts=[
        {"amount": 500, "discount": "di_1"}, {"amount": 280, "discount": "di_2"}]))
    assert vs.rabatt_minor == 780


def test_aus_upcoming_aufgeklapptes_abo():
    vs = v.aus_upcoming(upcoming_alt(subscription={"id": "sub_9", "object": "subscription"}))
    assert vs.abo_id == "sub_9"


@pytest.mark.parametrize("kaputt", [
    {"subscription": None},
    {"total_discount_amounts": None},
    {"total": None},
    {"currency": ""},
    {"lines": {"data": [{"type": "invoiceitem", "period": {"start": BEGINN}}]}},
    {"lines": {"data": [{"type": "subscription", "period": {}}]}},
])
def test_aus_upcoming_fehlende_angaben_sind_laut(kaputt):
    with pytest.raises(ValueError):
        v.aus_upcoming(upcoming_alt(**kaputt))


def test_ende_zu_ende_monatlich_drei_monate_rabatt():
    """Drei Vorschauen nacheinander, wie Stripe sie bei einem repeating-Coupon
    über 3 Monate schickt: rabattiert, voll (Mail), voll (keine Mail)."""
    rabattiert = v.aus_upcoming(upcoming_neu(total=2730, total_discount_amounts=[{"amount": 1170}]))
    assert entscheide(rabattiert).grund == v.NOCH_RABATTIERT

    erste_volle = v.aus_upcoming(upcoming_neu())
    assert entscheide(erste_volle, vorige_rechnung_rabattiert=True).senden

    zweite_volle = v.aus_upcoming(upcoming_neu())
    assert not entscheide(zweite_volle, vorige_rechnung_rabattiert=False).senden


# ── Abo-Stand (send_invoice: Stripe schickt kein invoice.upcoming) ───────────
def stand(**kw) -> v.Vorschau:
    werte = dict(abo_id="sub_1", naechste_rechnung_am=IN_14,
                 rabatt_ende=IN_14, rabatt_aktiv=True, betrag_minor=4100, waehrung="EUR")
    werte.update(kw)
    return v.aus_abo_stand(**werte)


def test_abo_stand_rabatt_endet_genau_zur_rechnung_ist_voll():
    assert stand().rabatt_minor == 0
    assert entscheide(stand(), nur_im_vorlauf=True).senden


def test_abo_stand_rabatt_endet_eine_sekunde_spaeter_ist_rabattiert():
    vs = stand(rabatt_ende=IN_14 + timedelta(seconds=1))
    assert entscheide(vs, nur_im_vorlauf=True).grund == v.NOCH_RABATTIERT


def test_abo_stand_dauerhaft_und_ohne_rabatt():
    dauerhaft = stand(rabatt_ende=None)
    assert dauerhaft.rabatt_minor == 1
    assert entscheide(dauerhaft, code_laufzeit="forever").grund == v.DAUERHAFT
    ohne = stand(rabatt_ende=None, rabatt_aktiv=False)
    assert ohne.rabatt_minor == 0
    with pytest.raises(ValueError):
        stand(rabatt_aktiv=False)


def test_abo_stand_jahresrechnung_nicht_elf_monate_vorher():
    vs = stand(naechste_rechnung_am=JETZT + timedelta(days=330), rabatt_ende=JETZT)
    e = entscheide(vs, nur_im_vorlauf=True)
    assert e == v.Entscheidung(False, v.ZU_FRUEH, tage_vorher=330)
    # Gegenprobe: das Stripe-Ereignis darf auch früher kommen.
    assert entscheide(vs).senden
    # und ab 14 Tagen vorher sagt der tägliche Lauf ja.
    assert entscheide(vs, nur_im_vorlauf=True, jetzt=vs.periode_beginn - timedelta(days=14)).senden


def test_abo_stand_ohne_zeitzone_ist_laut():
    with pytest.raises(ValueError):
        stand(naechste_rechnung_am=IN_14.replace(tzinfo=None))


# ── Abo endet ───────────────────────────────────────────────────────────────
def test_gekuendigtes_abo_bekommt_keine_vorwarnung():
    assert entscheide(abo_endet=True) == v.Entscheidung(False, v.ABO_ENDET)
    assert entscheide(abo_endet=False).senden


# ── Rabattende aus der App + täglicher Lauf ─────────────────────────────────
ERSTE = datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc)


def test_rabatt_ende_monate_und_monatsende():
    assert v.rabatt_ende(ERSTE, 1) == datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc)
    assert v.rabatt_ende(ERSTE, 3) == datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc)
    # jährlich: gewaehrte_monate liefert schon 12 (aufgerundet)
    assert v.rabatt_ende(ERSTE, 12) == datetime(2027, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert v.rabatt_ende(datetime(2027, 2, 28, tzinfo=timezone.utc), 12) == datetime(2028, 2, 28, tzinfo=timezone.utc)


def test_rabatt_ende_dauerhaft_und_fehler():
    assert v.rabatt_ende(ERSTE, None) is None
    with pytest.raises(ValueError):
        v.rabatt_ende(ERSTE, 0)
    with pytest.raises(ValueError):
        v.rabatt_ende(ERSTE.replace(tzinfo=None), 3)


ENDE = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def test_faellig_fenster():
    assert v.faellig(ENDE, jetzt=ENDE - timedelta(days=14, seconds=1)).grund == v.ZU_FRUEH
    e = v.faellig(ENDE, jetzt=ENDE - timedelta(days=14))
    assert e == v.Entscheidung(True, v.ERSTE_VOLLE_RECHNUNG, verspaetet=False, tage_vorher=14)
    spaet = v.faellig(ENDE, jetzt=ENDE - timedelta(days=2))
    assert spaet.senden and spaet.verspaetet and spaet.tage_vorher == 2
    assert v.faellig(ENDE, jetzt=ENDE - timedelta(seconds=1)).senden
    assert v.faellig(ENDE, jetzt=ENDE).grund == v.VERPASST
    assert v.faellig(ENDE, jetzt=ENDE + timedelta(days=5)).grund == v.VERPASST


def test_faellig_nie():
    jetzt = ENDE - timedelta(days=10)
    assert v.faellig(None, jetzt=jetzt).grund == v.DAUERHAFT
    assert v.faellig(ENDE, schon_gewarnt=True, jetzt=jetzt).grund == v.SCHON_GEWARNT
    assert v.faellig(ENDE, abo_endet=True, jetzt=jetzt).grund == v.ABO_ENDET
    assert v.faellig(ENDE, jetzt=jetzt).senden
    with pytest.raises(ValueError):
        v.faellig(ENDE.replace(tzinfo=None), jetzt=jetzt)


def test_pruefe_preise():
    v.pruefe_preise(3900, 2730, "eur")
    v.pruefe_preise(3900, 0, "eur")
    for normal, rab, w in [(2730, 2730, "eur"), (2000, 2730, "eur"), (3900, -1, "eur"), (3900, 2730, "")]:
        with pytest.raises(ValueError):
            v.pruefe_preise(normal, rab, w)
