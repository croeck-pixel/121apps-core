"""Selbsttest für den Vertragsende-Kanon (docs/FLEET_VERTRAGSENDE_SPEC.md).

Die Fehler dieser Klasse sind teuer und still: eine Frist, die einen Tag zu
früh endet, ist ein verweigerter Widerruf; eine Zuordnung über die
Rechnungsnummer allein beendet fremde Verträge; eine Kündigung, die „zum
Wunschtag“ vor dem Periodenende endet, verschenkt einen Monat. Jede Regel hat
ihre Gegenprobe.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from vertragsende import (  # noqa: E402
    AUDIT_AKTIONEN,
    BERLIN,
    GRUND_MAX,
    Art,
    Fehler,
    Hinweis,
    Massnahme,
    Pruefgrund,
    Status,
    Umfang,
    Vertrag,
    Zeitpunkt,
    darf_zuruecknehmen,
    ende_des_tages,
    entscheide,
    erstattung_cent,
    ist_honigtopf,
    loeschbar_ab,
    normalisiere_email,
    ordne_zu,
    pruefe_erklaerung,
    widerrufsfrist_ende,
    wiederholungs_schluessel,
    zuruecknahme_gueltig_bis,
)

UTC = timezone.utc
HEUTE = date(2026, 9, 29)
EINGANG = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


def vertrag(**kw):
    werte = dict(
        id="sub_1",
        umfang=Umfang.PERSONAL,
        emails=frozenset({"kunde@example.com"}),
        rechnungsnummern=frozenset({"INV-1"}),
        abgeschlossen_am=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        laufzeitende=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        belehrt_am=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )
    werte.update(kw)
    return Vertrag(**werte)


def pruefe(**kw):
    werte = dict(
        art=Art.ORDINARY,
        name="Kim Muster",
        email="kunde@example.com",
        zeitpunkt=Zeitpunkt.EARLIEST,
        wunschdatum=None,
        grund=None,
        rechnungsnummer=None,
        heute=HEUTE,
    )
    werte.update(kw)
    return pruefe_erklaerung(**werte)


# --- Eingabe ---------------------------------------------------------------


def test_vollstaendige_erklaerung_hat_keine_fehler():
    assert pruefe() == []


def test_alle_fehler_auf_einmal():
    fehler = pruefe(
        art=Art.EXTRAORDINARY,
        name="  ",
        email="keine-adresse",
        zeitpunkt=Zeitpunkt.DATE,
        wunschdatum=None,
    )
    assert fehler == [
        Fehler.NAME_REQUIRED,
        Fehler.EMAIL_INVALID,
        Fehler.REASON_REQUIRED,
        Fehler.DATE_REQUIRED,
    ]


def test_ausserordentlich_braucht_grund_ordentlich_nicht():
    assert Fehler.REASON_REQUIRED in pruefe(art=Art.EXTRAORDINARY)
    assert pruefe(art=Art.EXTRAORDINARY, grund="Leistung fällt aus") == []


def test_wunschdatum_in_der_vergangenheit():
    assert pruefe(zeitpunkt=Zeitpunkt.DATE, wunschdatum=HEUTE - timedelta(days=1)) == [
        Fehler.DATE_IN_PAST
    ]
    assert pruefe(zeitpunkt=Zeitpunkt.DATE, wunschdatum=HEUTE) == []


def test_widerruf_ignoriert_den_zeitpunkt():
    """Ein Widerruf wirkt sofort — ein fehlendes Datum ist dort kein Fehler."""
    assert pruefe(art=Art.WITHDRAWAL, zeitpunkt=Zeitpunkt.DATE, wunschdatum=None) == []


def test_ueberlange_eingaben():
    assert pruefe(art=Art.EXTRAORDINARY, grund="x" * (GRUND_MAX + 1)) == [Fehler.TOO_LONG]


def test_honigtopf_und_adresse():
    assert ist_honigtopf("http://spam") is True
    assert ist_honigtopf("   ") is False
    assert ist_honigtopf(None) is False
    assert normalisiere_email("  Kunde@Example.COM ") == "kunde@example.com"


def test_wiederholung_erkennt_dieselbe_erklaerung_unabhaengig_von_schreibweise():
    a = wiederholungs_schluessel("Kunde@example.com", Art.ORDINARY, Umfang.ALL)
    b = wiederholungs_schluessel(" kunde@EXAMPLE.com", Art.ORDINARY, Umfang.ALL)
    assert a == b
    assert a != wiederholungs_schluessel("kunde@example.com", Art.WITHDRAWAL, Umfang.ALL)


# --- Zuordnung -------------------------------------------------------------


def test_zuordnung_ueber_adresse_und_umfang():
    p = vertrag(id="p")
    a = vertrag(id="a", umfang=Umfang.ACCOUNT)
    z = ordne_zu(email="KUNDE@example.com", umfang=Umfang.PERSONAL, rechnungsnummer=None, kandidaten=[p, a])
    assert [v.id for v in z.vertraege] == ["p"]
    z = ordne_zu(email="kunde@example.com", umfang=Umfang.ALL, rechnungsnummer=None, kandidaten=[p, a])
    assert [v.id for v in z.vertraege] == ["p", "a"]


def test_rechnungsnummer_allein_beendet_nichts():
    """Entscheidung 2: eine geratene Nummer darf keinen fremden Vertrag beenden."""
    fremd = vertrag(emails=frozenset({"jemand@example.com"}))
    z = ordne_zu(email="angreifer@example.com", umfang=Umfang.ALL, rechnungsnummer="INV-1", kandidaten=[fremd])
    assert z.vertraege == ()
    assert z.nur_rechnung == (fremd,)
    e = entscheide(art=Art.ORDINARY, zeitpunkt=Zeitpunkt.EARLIEST, wunschdatum=None, zuordnung=z, eingang=EINGANG)
    assert e.status is Status.REVIEW
    assert e.schritte == ()
    assert e.pruefgruende == (Pruefgrund.INVOICE_ONLY,)


def test_rechnungsnummer_engt_nicht_ein():
    p = vertrag(id="p", rechnungsnummern=frozenset({"INV-1"}))
    a = vertrag(id="a", umfang=Umfang.ACCOUNT, rechnungsnummern=frozenset({"INV-2"}))
    z = ordne_zu(email="kunde@example.com", umfang=Umfang.ALL, rechnungsnummer="INV-1", kandidaten=[p, a])
    assert [v.id for v in z.vertraege] == ["p", "a"]


def test_nichts_gefunden_geht_an_den_support():
    z = ordne_zu(email="x@example.com", umfang=Umfang.ALL, rechnungsnummer=None, kandidaten=[vertrag()])
    e = entscheide(art=Art.ORDINARY, zeitpunkt=Zeitpunkt.EARLIEST, wunschdatum=None, zuordnung=z, eingang=EINGANG)
    assert e.status is Status.UNMATCHED
    assert e.pruefgruende == (Pruefgrund.NO_CONTRACT,)


def test_vertrag_ohne_zeitzone_oder_mit_umfang_alle_fliegt_auf():
    with pytest.raises(ValueError):
        vertrag(laufzeitende=datetime(2026, 10, 20))
    with pytest.raises(ValueError):
        vertrag(umfang=Umfang.ALL)


# --- Kündigung -------------------------------------------------------------


def _eine(v, **kw):
    z = ordne_zu(email="kunde@example.com", umfang=Umfang.ALL, rechnungsnummer=None, kandidaten=[v])
    werte = dict(art=Art.ORDINARY, zeitpunkt=Zeitpunkt.EARLIEST, wunschdatum=None, zuordnung=z, eingang=EINGANG)
    werte.update(kw)
    return entscheide(**werte)


def test_ordentlich_endet_zum_periodenende_ohne_handgriff():
    v = vertrag()
    e = _eine(v)
    assert e.status is Status.APPLIED
    assert e.pruefgruende == ()
    (s,) = e.schritte
    assert s.massnahme is Massnahme.END_AT
    assert s.zum == v.laufzeitende


def test_wunschtag_nach_periodenende_wird_uebernommen():
    e = _eine(vertrag(), zeitpunkt=Zeitpunkt.DATE, wunschdatum=date(2026, 12, 31))
    (s,) = e.schritte
    assert s.zum == ende_des_tages(date(2026, 12, 31))
    assert s.zum == datetime(2027, 1, 1, 0, 0, tzinfo=BERLIN)
    assert e.hinweise == ()


def test_wunschtag_vor_periodenende_heisst_fruehestmoeglich_und_wird_gesagt():
    v = vertrag()
    e = _eine(v, zeitpunkt=Zeitpunkt.DATE, wunschdatum=date(2026, 10, 1))
    (s,) = e.schritte
    assert s.zum == v.laufzeitende
    assert e.hinweise == (Hinweis.DATE_BEFORE_EARLIEST,)


def test_schon_gekuendigter_vertrag_wird_nicht_verlaengert():
    frueh = datetime(2026, 10, 5, tzinfo=UTC)
    e = _eine(vertrag(endet_am=frueh), zeitpunkt=Zeitpunkt.DATE, wunschdatum=date(2026, 12, 31))
    (s,) = e.schritte
    assert s.massnahme is Massnahme.ALREADY_ENDING
    assert s.zum == frueh


def test_ausserordentlich_endet_automatisch_und_geht_zusaetzlich_an_den_support():
    v = vertrag()
    e = _eine(v, art=Art.EXTRAORDINARY)
    assert e.status is Status.REVIEW
    assert e.pruefgruende == (Pruefgrund.EARLIER_END_REQUESTED,)
    (s,) = e.schritte
    assert s.massnahme is Massnahme.END_AT and s.zum == v.laufzeitende


# --- Widerruf --------------------------------------------------------------


def test_widerruf_in_der_frist_beendet_sofort():
    e = _eine(vertrag(), art=Art.WITHDRAWAL)
    assert e.status is Status.APPLIED
    (s,) = e.schritte
    assert s.massnahme is Massnahme.END_NOW_REFUND
    assert s.zum == EINGANG


def test_widerruf_nach_der_frist_wird_ordentliche_kuendigung():
    v = vertrag(
        abgeschlossen_am=datetime(2026, 8, 1, tzinfo=UTC),
        belehrt_am=datetime(2026, 8, 1, tzinfo=UTC),
    )
    e = _eine(v, art=Art.WITHDRAWAL)
    (s,) = e.schritte
    assert s.massnahme is Massnahme.END_AT
    assert s.zum == v.laufzeitende
    assert e.hinweise == (Hinweis.WITHDRAWAL_LATE,)


def test_frist_beginnt_am_folgetag_und_endet_um_mitternacht_berlin():
    # Mittwoch 16.09.2026 23:30 Berlin = 21:30 UTC → Frist Tag 1 ist der 17.09.,
    # Tag 14 der 30.09. (Mittwoch) → Ende 01.10. 00:00 Berlin.
    schluss = datetime(2026, 9, 16, 21, 30, tzinfo=UTC)
    ende = widerrufsfrist_ende(schluss, schluss)
    assert ende == datetime(2026, 10, 1, 0, 0, tzinfo=BERLIN)
    # Gegenprobe UTC-Datum: um 22:30 UTC ist es in Berlin schon der 17.09.
    spaet = datetime(2026, 9, 16, 22, 30, tzinfo=UTC)
    assert widerrufsfrist_ende(spaet, spaet) == datetime(2026, 10, 2, 0, 0, tzinfo=BERLIN)


def test_fristende_am_wochenende_rutscht_auf_montag():
    # Samstag 05.09.2026 + 14 = Samstag 19.09. → Montag 21.09.
    schluss = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    assert widerrufsfrist_ende(schluss, schluss) == ende_des_tages(date(2026, 9, 21))


def test_fristende_am_feiertag_rutscht_weiter():
    # 19.09.2026 + 14 = Samstag 03.10. (Tag der Deutschen Einheit, zugleich
    # Samstag) → Montag 05.10.
    schluss = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    assert widerrufsfrist_ende(schluss, schluss) == ende_des_tages(date(2026, 10, 5))
    # Karfreitag 2027 ist der 26.03. — 12.03. + 14 = Freitag 26.03. → Dienstag
    # 30.03. (Ostermontag 29.03. dazwischen).
    schluss = datetime(2027, 3, 12, 10, 0, tzinfo=UTC)
    assert widerrufsfrist_ende(schluss, schluss) == ende_des_tages(date(2027, 3, 30))


def test_ohne_belehrung_zwoelf_monate_und_vierzehn_tage():
    schluss = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    # 15.01.2027 + 14 = Freitag 29.01.2027
    assert widerrufsfrist_ende(schluss, None) == ende_des_tages(date(2027, 1, 29))


def test_spaete_belehrung_startet_die_frist_neu_aber_nie_ueber_die_hoechstfrist():
    schluss = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    belehrung = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    # 10.09. + 14 = Donnerstag 24.09.
    assert widerrufsfrist_ende(schluss, belehrung) == ende_des_tages(date(2026, 9, 24))
    sehr_spaet = datetime(2028, 1, 1, tzinfo=UTC)
    assert widerrufsfrist_ende(schluss, sehr_spaet) == widerrufsfrist_ende(schluss, None)


def test_monatsende_bei_der_hoechstfrist():
    # 29.02.2028 + 12 Monate → 28.02.2029 (§188 Abs. 3), + 14 = 14.03.2029 (Mi)
    schluss = datetime(2028, 2, 29, 10, 0, tzinfo=UTC)
    assert widerrufsfrist_ende(schluss, None) == ende_des_tages(date(2029, 3, 14))


# --- Erstattung ------------------------------------------------------------


def test_ohne_verlangten_leistungsbeginn_alles_zurueck():
    assert (
        erstattung_cent(
            gezahlt_cent=1990,
            leistungsbeginn_verlangt=False,
            genutzt=timedelta(days=10),
            laufzeit=timedelta(days=30),
        )
        == 1990
    )


def test_mit_verlangtem_leistungsbeginn_anteilig_zugunsten_des_kunden():
    # 1000 * 10/30 = 333,33 Wertersatz → abgerundet 333 → 667 zurück
    assert (
        erstattung_cent(
            gezahlt_cent=1000,
            leistungsbeginn_verlangt=True,
            genutzt=timedelta(days=10),
            laufzeit=timedelta(days=30),
        )
        == 667
    )
    # nie mehr Wertersatz als gezahlt, nie negative Nutzung
    assert erstattung_cent(gezahlt_cent=1000, leistungsbeginn_verlangt=True, genutzt=timedelta(days=99), laufzeit=timedelta(days=30)) == 0
    assert erstattung_cent(gezahlt_cent=1000, leistungsbeginn_verlangt=True, genutzt=timedelta(days=-1), laufzeit=timedelta(days=30)) == 1000


def test_unsinnige_erstattung_fliegt_auf():
    with pytest.raises(ValueError):
        erstattung_cent(gezahlt_cent=-1, leistungsbeginn_verlangt=False, genutzt=timedelta(0), laufzeit=timedelta(days=1))
    with pytest.raises(ValueError):
        erstattung_cent(gezahlt_cent=1, leistungsbeginn_verlangt=True, genutzt=timedelta(0), laufzeit=timedelta(0))


# --- Zurücknehmen und Aufbewahren -----------------------------------------


def test_kuendigung_zuruecknehmen_bis_sie_wirkt():
    wirksam = datetime(2026, 10, 20, tzinfo=UTC)
    assert darf_zuruecknehmen(art=Art.ORDINARY, status=Status.APPLIED, wirksam_zum=wirksam, jetzt=EINGANG) is None
    assert (
        darf_zuruecknehmen(art=Art.ORDINARY, status=Status.APPLIED, wirksam_zum=wirksam, jetzt=wirksam)
        is Fehler.ALREADY_EFFECTIVE
    )
    assert (
        darf_zuruecknehmen(art=Art.ORDINARY, status=Status.REVOKED, wirksam_zum=wirksam, jetzt=EINGANG)
        is Fehler.NOT_REVOCABLE
    )


def test_widerruf_ist_nicht_per_link_ruecknehmbar():
    assert (
        darf_zuruecknehmen(art=Art.WITHDRAWAL, status=Status.APPLIED, wirksam_zum=None, jetzt=EINGANG)
        is Fehler.NOT_REVOCABLE
    )


def test_link_gilt_bis_zum_vertragsende_sonst_dreissig_tage():
    wirksam = datetime(2026, 10, 20, tzinfo=UTC)
    assert zuruecknahme_gueltig_bis(wirksam_zum=wirksam, eingang=EINGANG) == wirksam
    assert zuruecknahme_gueltig_bis(wirksam_zum=None, eingang=EINGANG) == EINGANG + timedelta(days=30)


def test_aufbewahrung_drei_jahre_ab_jahresende():
    assert loeschbar_ab(EINGANG) == datetime(2030, 1, 1, tzinfo=BERLIN)
    # Silvester 23:30 Berlin zählt noch zum alten Jahr
    silvester = datetime(2026, 12, 31, 22, 30, tzinfo=UTC)
    assert loeschbar_ab(silvester) == datetime(2030, 1, 1, tzinfo=BERLIN)


def test_audit_aktionen_haben_die_kanonische_form():
    for aktion in AUDIT_AKTIONEN:
        bereich, verb = aktion.split(".")
        assert bereich == "contract_notice" and verb.isalpha()
