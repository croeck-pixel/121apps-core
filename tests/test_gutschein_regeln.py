"""Die Regeln, an denen Geld hängt. Jeder Ablehnungsgrund hat einen Test —
ein Grund ohne Test ist einer, der still verschwindet."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import gutschein_regeln as g  # noqa: E402

HEUTE = date(2026, 8, 14)
JETZT = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def stand(**kw) -> g.Codestand:
    return g.Codestand(**kw)


# ── Prüfung ────────────────────────────────────────────────────────────────
def test_gueltiger_code():
    assert g.pruefen(stand(), heute=HEUTE).gueltig


def test_unbekannter_code():
    assert g.pruefen(None, heute=HEUTE).grund == g.UNBEKANNT


def test_abgeschalteter_code():
    assert g.pruefen(stand(aktiv=False), heute=HEUTE).grund == g.INAKTIV


def test_abgelaufen():
    s = stand(redeemable_until=HEUTE - timedelta(days=1))
    assert g.pruefen(s, heute=HEUTE).grund == g.ABGELAUFEN


def test_letzter_tag_zaehlt_noch():
    """Sonst endet jede Kampagne einen Tag früher als angekündigt."""
    assert g.pruefen(stand(redeemable_until=HEUTE), heute=HEUTE).gueltig


def test_falscher_plan_intervall_waehrung():
    assert g.pruefen(stand(plans=("team",)), plan="einzel", heute=HEUTE).grund == g.FALSCHER_PLAN
    assert g.pruefen(stand(intervals=("year",)), interval="month", heute=HEUTE).grund == g.FALSCHES_INTERVALL
    assert g.pruefen(stand(currencies=("EUR",)), currency="CHF", heute=HEUTE).grund == g.FALSCHE_WAEHRUNG


def test_leere_liste_heisst_ueberall():
    """Die Falle: `if gewaehlt not in erlaubte` ohne Leerprüfung — danach gilt
    kein einziger Code mehr, in allen Apps gleichzeitig."""
    s = stand()
    for plan in ("test", "einzel", "team", "mandant"):
        assert g.pruefen(s, plan=plan, heute=HEUTE).gueltig
    # Gross-/Kleinschreibung darf nicht entscheiden
    assert g.pruefen(stand(currencies=("eur",)), currency="EUR", heute=HEUTE).gueltig


def test_bereits_an_anderen_code_gebunden():
    """Der erste Code gewinnt — und der Grund wird VOR den Code-Eigenschaften
    gemeldet, sonst schickt man den Nutzer wegen der falschen Ursache los."""
    s = stand(aktiv=False, redeemable_until=HEUTE - timedelta(days=99))
    e = g.pruefen(s, schon_gebunden_an_anderen_code=True, heute=HEUTE)
    assert e.grund == g.BEREITS_GEBUNDEN


def test_nur_neukunden():
    assert g.pruefen(stand(), ist_bestandskunde=True, heute=HEUTE).grund == g.NUR_NEUKUNDEN
    assert g.pruefen(stand(new_customers_only=False), ist_bestandskunde=True, heute=HEUTE).gueltig


def test_ausgeschoepft():
    s = stand(max_redemptions=5, einloesungen_bisher=5)
    assert g.pruefen(s, heute=HEUTE).grund == g.AUSGESCHOEPFT


def test_eigene_einloesung_umgeht_neukunden_und_kontingent():
    """Sonst scheitert der zweite Aufruf desselben Kunden — genau der, den ein
    Netzwerk-Retry auslöst."""
    s = stand(max_redemptions=1, einloesungen_bisher=1)
    e = g.pruefen(s, schon_mit_diesem_code_gebunden=True, ist_bestandskunde=True, heute=HEUTE)
    assert e.gueltig


# ── Rabattdauer ────────────────────────────────────────────────────────────
def test_eine_periode_ist_once_egal_welches_intervall():
    assert g.coupon_dauer("month", 1) == (g.Rabattdauer.EINMAL, None)
    assert g.coupon_dauer("year", 1) == (g.Rabattdauer.EINMAL, None)


def test_jahresrabatt_rechnet_in_monaten():
    """„2 Jahre" sind für Stripe 24 Monate, nicht 2."""
    assert g.coupon_dauer("year", 2) == (g.Rabattdauer.WIEDERHOLT, 24)
    assert g.coupon_dauer("month", 12) == (g.Rabattdauer.WIEDERHOLT, 12)


def test_null_perioden_ist_ein_fehler():
    with pytest.raises(ValueError):
        g.coupon_dauer("month", 0)


# ── Beteiligung ────────────────────────────────────────────────────────────
def test_relative_dauer():
    assert g.beteiligung_ende(JETZT, monate=24).year == 2028


def test_monatsende_bleibt_monatsende():
    """Der 31. plus ein Monat ist der letzte Tag des Folgemonats — sonst
    verschiebt sich eine Zusage bei jeder Verlängerung nach vorn."""
    ende = g.beteiligung_ende(datetime(2026, 1, 31, tzinfo=timezone.utc), monate=1)
    assert ende == datetime(2026, 2, 28, tzinfo=timezone.utc)


def test_frueheres_ende_gewinnt():
    """Eine befristete Kooperation begrenzt auch eine laufende relative Zusage."""
    ende = g.beteiligung_ende(JETZT, monate=24, bis=date(2026, 12, 31))
    assert ende.year == 2026
    # ...und umgekehrt: ist das absolute Ende später, zählt die relative Dauer
    spaet = g.beteiligung_ende(JETZT, monate=6, bis=date(2030, 1, 1))
    assert spaet.year == 2027


def test_ohne_angabe_kein_ende():
    assert g.beteiligung_ende(JETZT) is None


# ── Geld ───────────────────────────────────────────────────────────────────
def test_provision():
    assert g.provision(3900, Decimal("15")) == 585


def test_kaufmaennisch_gerundet_nicht_bankers():
    """3,70 € × 15 % = 55,5 Cent → 56, nicht 55. Pythons Standard rundet zur
    geraden Zahl, und die halbe Provision landet dann systematisch beim Haus."""
    assert g.provision(370, Decimal("15")) == 56


def test_reifezeitpunkt_und_auszahlbarkeit():
    p = g.reifezeitpunkt(JETZT, 45)
    assert p == JETZT + timedelta(days=45)
    assert not g.ist_auszahlbar(p, JETZT + timedelta(days=44))
    assert g.ist_auszahlbar(p, JETZT + timedelta(days=46))


def test_karenz_null_ist_ein_fehler():
    """Ohne Karenz wird Provision auf rückbuchbare Umsätze ausgezahlt."""
    with pytest.raises(ValueError):
        g.reifezeitpunkt(JETZT, 0)


# ── Rabattdauer: gespeichert wird der MONAT ────────────────────────────────
def test_jaehrliche_schreibweisen():
    for wort in ("year", "yearly", "annual", "Jahr", "JAEHRLICH"):
        assert g.ist_jaehrlich(wort), wort
    for wort in ("month", "monthly", "monat"):
        assert not g.ist_jaehrlich(wort)


def test_monate_in_rechnungen():
    assert g.rechnungen_aus_monaten("monthly", 12) == 12
    assert g.rechnungen_aus_monaten("yearly", 12) == 1
    assert g.rechnungen_aus_monaten("yearly", 24) == 2


def test_angebrochenes_jahr_wird_aufgerundet():
    """Es gibt keine halbe Rechnung — 6 Monate treffen die erste Jahresrechnung."""
    assert g.rechnungen_aus_monaten("yearly", 6) == 1
    assert g.rechnungen_aus_monaten("yearly", 13) == 2


def test_was_der_kunde_wirklich_bekommt():
    """Der Satz, den die Oberfläche VOR dem Speichern zeigen muss."""
    assert g.gewaehrte_monate("monthly", 6) == 6
    assert g.gewaehrte_monate("yearly", 6) == 12
    assert g.gewaehrte_monate("yearly", 24) == 24


def test_null_monate_sind_kein_dauerrabatt():
    """Die Falle, die einen zugesagten Rabatt still verschwinden liess: ein
    leeres Feld ist keine unbegrenzte Zusage, sondern eine fehlende."""
    with pytest.raises(ValueError):
        g.rechnungen_aus_monaten("monthly", 0)


def test_coupon_aus_monaten():
    assert g.coupon_aus_monaten("monthly", 1) == (g.Rabattdauer.EINMAL, None)
    assert g.coupon_aus_monaten("monthly", 12) == (g.Rabattdauer.WIEDERHOLT, 12)
    # Ein Jahr jährlich ist GENAU eine Rechnung — `repeating` mit 12 Monaten
    # liesse die zweite auf den Ablauf des Fensters fallen (§4.2).
    assert g.coupon_aus_monaten("yearly", 12) == (g.Rabattdauer.EINMAL, None)
    assert g.coupon_aus_monaten("yearly", 24) == (g.Rabattdauer.WIEDERHOLT, 24)


# ── Bemessungsgrundlage ────────────────────────────────────────────────────
GESAMT = g.Beteiligungsbasis.GESAMTUMSATZ
ERST = g.Beteiligungsbasis.ERSTTARIF


def test_gesamtumsatz_nimmt_die_rechnung_wie_sie_ist():
    assert g.bemessungsgrundlage(9900, basis=GESAMT) == 9900


def test_ersttarif_deckelt_das_upgrade():
    """Kunde startet auf Einzel (39 €) und wechselt auf Team (99 €) — der
    Partner verdient weiter an dem, was er gebracht hat."""
    assert g.bemessungsgrundlage(9900, basis=ERST, deckel_minor=3900) == 3900


def test_ersttarif_deckelt_ein_downgrade_nicht():
    assert g.bemessungsgrundlage(3900, basis=ERST, deckel_minor=9900) == 3900


def test_deckel_ist_der_listenpreis_nicht_die_erste_rechnung():
    """Die erste Rechnung ist rabattiert (31,20 statt 39 €). Gerechnet wird auf
    das tatsächlich Gezahlte — der Deckel greift erst darüber."""
    assert g.bemessungsgrundlage(3120, basis=ERST, deckel_minor=3900) == 3120


def test_jahresrechnung_gegen_jahresdeckel():
    """Der Deckel kommt je Rechnung aus dem Katalog, im Intervall DIESER
    Rechnung. Ein fester Monatsbetrag würde hier 90 % wegnehmen."""
    assert g.bemessungsgrundlage(39000, basis=ERST, deckel_minor=39000) == 39000


def test_ersttarif_ohne_deckel_wird_nicht_gebucht():
    """Ungedeckelt zu buchen wäre stillschweigend eine andere Zusage."""
    with pytest.raises(ValueError):
        g.bemessungsgrundlage(9900, basis=ERST)


def test_negativer_umsatz_ist_keine_grundlage():
    with pytest.raises(ValueError):
        g.bemessungsgrundlage(-100, basis=GESAMT)


# ── Welche Rechnung überhaupt zählt ────────────────────────────────────────
def test_abo_rechnung_erkannt():
    assert g.ist_abo_rechnung("subscription_cycle")
    assert g.ist_abo_rechnung("subscription_create")
    assert not g.ist_abo_rechnung("manual")
    assert not g.ist_abo_rechnung("quote_accept")


def test_unbekannter_grund_zaehlt_mit():
    """Zu wenig Provision fällt niemandem auf — zu viel schon."""
    assert g.ist_abo_rechnung(None)


def test_gesamtumsatz_zaehlt_auch_zukaeufe():
    assert g.zaehlt_fuer_beteiligung(GESAMT, billing_reason="manual")


def test_ersttarif_laesst_zukaeufe_draussen():
    """Der Deckel allein würde hier versagen: ein Guthabenpaket für 200 €
    liegt UNTER dem Deckel und wäre voll provisioniert."""
    assert not g.zaehlt_fuer_beteiligung(ERST, billing_reason="manual")
    assert g.zaehlt_fuer_beteiligung(ERST, billing_reason="subscription_cycle")


# ── Kopfprämie (CPO) ───────────────────────────────────────────────────────
def test_kopfpraemie_genau_einmal():
    """Ein Abo hat keine Bestellung, sondern eine Folge von Rechnungen."""
    assert g.kopfpraemie(5000, ist_erste_zahlung=True) == 5000
    assert g.kopfpraemie(5000, ist_erste_zahlung=False) == 0


def test_ohne_cpo_keine_praemie():
    assert g.kopfpraemie(None, ist_erste_zahlung=True) == 0


def test_praemie_von_null_ist_ein_fehler():
    """Wer keine Prämie geben will, lässt das Feld leer — eine gesetzte Null
    ist eine Zusage, die keine ist."""
    with pytest.raises(ValueError):
        g.kopfpraemie(0, ist_erste_zahlung=True)


def test_praemie_und_beteiligung_schliessen_sich_nicht_aus():
    """Beide Felder sind unabhängig: Kopfprämie UND laufende Beteiligung."""
    praemie = g.kopfpraemie(5000, ist_erste_zahlung=True)
    laufend = g.provision(
        g.bemessungsgrundlage(3900, basis=GESAMT), Decimal("15")
    )
    assert (praemie, laufend) == (5000, 585)


def test_die_drei_ledger_arten_sind_verschieden():
    assert len({g.BETEILIGUNG, g.KOPFPRAEMIE, g.GEGENBUCHUNG}) == 3


def test_amortisation_wird_aufgerundet():
    """50 € Prämie bei 39 €/Monat sind zwei Monate — ein halber zahlt nichts ein."""
    assert g.monate_bis_amortisiert(5000, 3900) == 2
    assert g.monate_bis_amortisiert(3900, 3900) == 1
    assert g.monate_bis_amortisiert(50000, 3900) == 13


def test_amortisation_ohne_umsatz_ist_ein_fehler():
    with pytest.raises(ValueError):
        g.monate_bis_amortisiert(5000, 0)
