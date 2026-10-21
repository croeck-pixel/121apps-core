"""Tests für packages/core-py/einladung_zugang.py — je Entscheidung mit Gegenprobe."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import einladung_zugang as ez  # noqa: E402

HEUTE = date(2026, 10, 14)
PERSOENLICH = ("einzel",)
ACCOUNT = ("team", "mandant")


def _pruefe(**felder):
    werte = {"plan_code": None, "plan_until": None, "account_name": None, "account_seats": None}
    werte.update(felder)
    return ez.pruefe_zugang(
        persoenliche_tarife=PERSOENLICH,
        account_tarife=ACCOUNT,
        am=HEUTE,
        kostenloser_tarif="test",
        **werte,
    )


def _absage(**felder) -> ez.ZugangUngueltig:
    with pytest.raises(ez.ZugangUngueltig) as fehler:
        _pruefe(**felder)
    return fehler.value


# --- Entscheidung 3: Frei ist keine Angabe ----------------------------------


@pytest.mark.parametrize("code", [None, "", "  ", "test"])
def test_frei_traegt_nichts(code) -> None:
    zugang = _pruefe(plan_code=code)
    assert zugang == ez.Zugang()
    assert zugang.ist_frei


@pytest.mark.parametrize("felder", [
    {"plan_until": HEUTE},
    {"account_name": "Familie"},
    {"account_seats": 3},
    {"plan_code": "test", "plan_until": HEUTE},  # der kostenlose Tarif ist Frei
])
def test_angaben_ohne_tarif_werden_abgelehnt(felder) -> None:
    assert _absage(**felder).code is ez.Fehler.OHNE_TARIF


def test_leerer_account_name_ist_keine_angabe() -> None:
    """Gegenprobe zu OHNE_TARIF: ein Feld voller Leerzeichen ist leer, kein Name."""
    assert _pruefe(account_name="   ") == ez.Zugang()


# --- Entscheidung 4: nur was der Katalog führt ------------------------------


@pytest.mark.parametrize("code", ["gold", "Einzel", "TEAM"])
def test_unbekannter_tarif(code: str) -> None:
    assert _absage(plan_code=code).code is ez.Fehler.TARIF_UNBEKANNT


def test_katalog_ist_was_die_app_uebergibt() -> None:
    """Ein Tarif, den der Code kennt, der Katalog der Instanz aber nicht führt."""
    with pytest.raises(ez.ZugangUngueltig) as fehler:
        ez.pruefe_zugang(
            plan_code="mandant", plan_until=None, account_name="A", account_seats=None,
            persoenliche_tarife=PERSOENLICH, account_tarife=("team",), am=HEUTE,
        )
    assert fehler.value.code is ez.Fehler.TARIF_UNBEKANNT


def test_tarif_zugleich_persoenlich_und_account_ist_ein_programmierfehler() -> None:
    with pytest.raises(ValueError, match="zugleich"):
        ez.pruefe_zugang(
            plan_code="team", plan_until=None, account_name="A", account_seats=None,
            persoenliche_tarife=("team",), account_tarife=("team",), am=HEUTE,
        )


def test_code_wird_getrimmt() -> None:
    assert _pruefe(plan_code=" einzel ").plan_code == "einzel"


# --- Entscheidung 5: letzter Tag einschliesslich, Berlin --------------------


def test_letzter_tag_heute_gilt_gestern_nicht() -> None:
    assert _pruefe(plan_code="einzel", plan_until=HEUTE).plan_until == HEUTE
    assert _absage(plan_code="einzel", plan_until=HEUTE - timedelta(days=1)).code is ez.Fehler.ENDE_VERGANGEN


def test_enddatum_auf_der_nutzerseite_gleiche_regel() -> None:
    assert ez.pruefe_enddatum(None, am=HEUTE) is None
    assert ez.pruefe_enddatum(HEUTE, am=HEUTE) == HEUTE
    with pytest.raises(ez.ZugangUngueltig):
        ez.pruefe_enddatum(HEUTE - timedelta(days=1), am=HEUTE)


def test_heute_rechnet_in_berlin_nicht_in_utc() -> None:
    """00:20 Berliner Zeit am 15.10. ist in UTC noch der 14.10. — der Lauf läuft am 15."""
    um_0020_berlin = datetime(2026, 10, 14, 22, 20, tzinfo=timezone.utc)  # MESZ = UTC+2
    assert um_0020_berlin.date() == date(2026, 10, 14)
    assert ez.heute(um_0020_berlin) == date(2026, 10, 15)


def test_heute_ohne_zeitzone_wirft() -> None:
    with pytest.raises(ValueError, match="Zeitzone"):
        ez.heute(datetime(2026, 10, 14, 23, 0))


# --- Entscheidung 6: Account-Tarif ------------------------------------------


def test_persoenlicher_tarif_traegt_keinen_account() -> None:
    assert _absage(plan_code="einzel", account_name="Familie").code is ez.Fehler.ACCOUNT_NUR_MIT_ACCOUNTTARIF
    assert _absage(plan_code="einzel", account_seats=2).code is ez.Fehler.ACCOUNT_NUR_MIT_ACCOUNTTARIF


def test_account_tarif_braucht_namen() -> None:
    assert _absage(plan_code="team").code is ez.Fehler.ACCOUNT_NAME_FEHLT
    assert _absage(plan_code="team", account_name="   ").code is ez.Fehler.ACCOUNT_NAME_FEHLT


@pytest.mark.parametrize("plaetze", [0, -1, ez.PLAETZE_HOECHSTENS + 1])
def test_ungueltige_plaetze(plaetze: int) -> None:
    fehler = _absage(plan_code="team", account_name="A", account_seats=plaetze)
    assert fehler.code is ez.Fehler.PLAETZE_UNGUELTIG
    assert fehler.werte == {"hoechstens": ez.PLAETZE_HOECHSTENS}


@pytest.mark.parametrize("plaetze", [1, ez.PLAETZE_HOECHSTENS])
def test_plaetze_an_den_grenzen_gelten(plaetze: int) -> None:
    assert _pruefe(plan_code="team", account_name="A", account_seats=plaetze).account_seats == plaetze


def test_account_tarif_gueltig() -> None:
    zugang = _pruefe(plan_code="team", account_name="  Familie  ", account_seats=4, plan_until=HEUTE)
    assert zugang == ez.Zugang("team", HEUTE, "Familie", 4, ist_account=True)


def test_plaetze_aus_einladung_sonst_katalog_mindestens_eins() -> None:
    mit = _pruefe(plan_code="team", account_name="A", account_seats=3)
    ohne = _pruefe(plan_code="team", account_name="A")
    assert ez.plaetze(mit, plaetze_im_katalog=10) == 3
    assert ez.plaetze(ohne, plaetze_im_katalog=10) == 10
    assert ez.plaetze(ohne, plaetze_im_katalog=None) == 1
    assert ez.plaetze(ohne, plaetze_im_katalog=0) == 1
    assert ez.plaetze(ohne, plaetze_im_katalog=-2) == 1  # kaputter Katalogwert
    with pytest.raises(ValueError):
        ez.plaetze(_pruefe(plan_code="einzel"), plaetze_im_katalog=5)


# --- Entscheidung 2 + 7: was beim Annehmen gesetzt wird ---------------------


def test_persoenlicher_tarif_wird_von_hand_gesetzt() -> None:
    z = ez.zuweisung(_pruefe(plan_code="einzel", plan_until=HEUTE))
    assert z == ez.Zuweisung(ez.Anker.PERSON, "einzel", "manual", HEUTE, None)


def test_account_tarif_am_account() -> None:
    z = ez.zuweisung(_pruefe(plan_code="mandant", account_name="Kanzlei"))
    assert (z.anker, z.plan_code, z.plan_source, z.manual_plan_until, z.account_name) == (
        ez.Anker.ACCOUNT, "mandant", "manual", None, "Kanzlei",
    )


def test_frei_setzt_nichts() -> None:
    assert ez.zuweisung(ez.Zugang()) == ez.Zuweisung(anker=None)
    # auch mit laufendem Abo — Frei verschenkt nichts, also kein Konflikt
    assert ez.zuweisung(ez.Zugang(), abo_laeuft=True).anker is None


def test_kein_comp_ueber_laufendes_abo() -> None:
    with pytest.raises(ez.ZugangUngueltig) as fehler:
        ez.zuweisung(_pruefe(plan_code="einzel"), abo_laeuft=True)
    assert fehler.value.code is ez.Fehler.ABO_LAEUFT


def test_manual_ist_was_plan_freigabe_vor_webhooks_schuetzt() -> None:
    """Gegenprobe gegen den Nachbarbaustein: der gesetzte Wert ist der, den der Webhook in Ruhe lässt."""
    import plan_freigabe

    assert plan_freigabe.webhook_darf_plan_setzen(ez.PLAN_SOURCE_MANUELL) is False
    assert plan_freigabe.webhook_darf_plan_setzen(ez.PLAN_SOURCE_NACH_ENDE) is True


# --- Annahmeseite -----------------------------------------------------------


def test_vorschau_nennt_tarif_tag_und_account_aber_keine_plaetze() -> None:
    v = ez.vorschau(_pruefe(plan_code="team", account_name="Familie", account_seats=4, plan_until=HEUTE))
    ohne_rabatt = {"rabatt_prozent": None, "rabatt_laufzeit": None, "rabatt_monate": None,
                   "rabatt_danach": None, "ki_kontingent": "tarif", "testguthaben": None}
    assert v == {"plan_code": "team", "plan_until": "2026-10-14", "account_name": "Familie", **ohne_rabatt}
    assert ez.vorschau(_pruefe(plan_code="einzel")) == {
        "plan_code": "einzel", "plan_until": None, "account_name": None, **ohne_rabatt}
    assert ez.vorschau(ez.Zugang()) is None


# --- Entscheidung 8: das Ende -----------------------------------------------


@pytest.mark.parametrize(("quelle", "bis", "erwartet"), [
    ("manual", HEUTE - timedelta(days=1), True),  # gestern war der letzte Tag
    ("manual", HEUTE, False),  # heute ist noch der letzte Tag
    ("manual", HEUTE + timedelta(days=30), False),
    ("manual", None, False),  # unbefristet
    ("stripe", HEUTE - timedelta(days=1), False),  # Stripe-Tarif mit Altlast-Datum
    ("invoice", HEUTE - timedelta(days=1), False),
    (None, HEUTE - timedelta(days=1), False),
])
def test_ist_abgelaufen(quelle, bis, erwartet: bool) -> None:
    assert ez.ist_abgelaufen(plan_source=quelle, manual_plan_until=bis, am=HEUTE) is erwartet


def test_nach_ende_kostenloser_tarif_und_stripe() -> None:
    n = ez.nach_ende(kostenloser_tarif="test")
    assert (n.plan_code, n.plan_source, n.manual_plan_until) == ("test", "stripe", None)
    assert ez.nach_ende(kostenloser_tarif=None).plan_code is None


def test_lauf_ist_idempotent() -> None:
    """Was zurückgesetzt wurde, ist beim zweiten Lauf nicht mehr abgelaufen."""
    n = ez.nach_ende(kostenloser_tarif="free")
    assert ez.ist_abgelaufen(plan_source=n.plan_source, manual_plan_until=n.manual_plan_until, am=HEUTE) is False


# --- Konstanten, auf die sich die Apps verlassen ----------------------------


def test_fehlerschluessel() -> None:
    assert ez.Fehler.OHNE_TARIF.schluessel == "errors.admin.invitation.zugang.ohne_tarif"
    assert {f.value for f in ez.Fehler} == {
        "ohne_tarif", "tarif_unbekannt", "ende_vergangen", "account_name_fehlt",
        "plaetze_ungueltig", "account_nur_mit_accounttarif", "abo_laeuft",
        "rabatt_ungueltig", "rabatt_laufzeit_fehlt", "rabatt_monate_fehlen",
        "rabatt_monate_bei_dauerhaft", "laufzeit_ohne_rabatt", "nur_geschenk",
        "ki_nicht_waehlbar", "testguthaben_nur_ohne_kontingent", "testguthaben_ungueltig",
        "tage_ohne_testguthaben", "tage_ungueltig",
        "ende_und_laufzeit", "danach_fehlt", "danach_bei_dauerhaft", "zahlung_spaeter_nur_geschenk",
    }


def test_beat_und_mail_flottenweit_gleich() -> None:
    assert (ez.BEAT_NAME, ez.BEAT_ZEIT, ez.MAIL_VORLAGE, ez.AUDIT_AKTION) == (
        "manuelle-tarife-beenden", (0, 20), "manual_plan_ended", "manual_plan_ended",
    )


def test_nur_stdlib() -> None:
    quelle = (Path(ez.__file__)).read_text(encoding="utf-8")
    for fremd in ("sqlalchemy", "fastapi", "stripe", "from app"):
        assert f"import {fremd}" not in quelle and f"from {fremd}" not in quelle


# --- Entscheidungen 10–12: Rabatt per Einmal-Gutschein ----------------------


def test_hundert_prozent_ist_das_geschenk() -> None:
    z = _pruefe(plan_code="einzel", rabatt_prozent=100)
    assert z.ist_geschenk and z.rabatt_prozent is None
    assert ez.zuweisung(z).plan_source == "manual"
    assert ez.zuweisung(z).gutschein is None


def test_rabatt_wird_einmal_gutschein_ohne_tarif_von_hand() -> None:
    z = _pruefe(plan_code="einzel", rabatt_prozent=30, rabatt_laufzeit="forever")
    w = ez.zuweisung(z)
    assert (w.anker, w.plan_code, w.plan_source, w.manual_plan_until) == (None, None, None, None)
    assert w.gutschein == ez.EinladungsGutschein(
        discount_percent=30, discount_duration="forever", discount_months=None, plans=("einzel",),
        max_redemptions=1, new_customers_only=True,
    )


def test_rabatt_beim_accounttarif_traegt_den_namen() -> None:
    w = ez.zuweisung(_pruefe(plan_code="team", account_name="Familie", rabatt_prozent=20,
                             rabatt_laufzeit="months", rabatt_monate=12, rabatt_danach="zahlung_vorab"))
    assert w.account_name == "Familie" and w.gutschein is not None
    assert (w.gutschein.discount_duration, w.gutschein.discount_months) == ("months", 12)


def test_rabatt_ist_nie_abo_konflikt() -> None:
    """Kein Tarif von Hand — also kein Comp über ein laufendes Abo (Entscheidung 7)."""
    z = _pruefe(plan_code="einzel", rabatt_prozent=50, rabatt_laufzeit="months", rabatt_monate=3,
                rabatt_danach="zahlung_vorab")
    assert ez.zuweisung(z, abo_laeuft=True).gutschein is not None


def test_einladungs_gutschein_besteht_die_gutscheinregeln() -> None:
    """Der Einmal-Code erfüllt die Pflichtgrenze eines dauerhaften Rabatts von selbst."""
    import gutschein_regeln as g

    assert (ez.RABATT_MONATE, ez.RABATT_DAUERHAFT) == tuple(l.value for l in g.Rabattlaufzeit)
    c = ez.zuweisung(_pruefe(plan_code="einzel", rabatt_prozent=25, rabatt_laufzeit="forever")).gutschein
    assert c is not None
    assert g.pruefe_rabatt(discount_percent=c.discount_percent, discount_duration=c.discount_duration,
                           discount_months=c.discount_months, max_redemptions=c.max_redemptions,
                           redeemable_until=None).gueltig


@pytest.mark.parametrize("prozent", [0, 101, -1])
def test_rabatt_ausserhalb_abgelehnt(prozent: int) -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit="forever").code \
        is ez.Fehler.RABATT_UNGUELTIG


@pytest.mark.parametrize(("felder", "code"), [
    ({"rabatt_prozent": 30}, ez.Fehler.RABATT_LAUFZEIT_FEHLT),
    ({"rabatt_prozent": 30, "rabatt_laufzeit": "months"}, ez.Fehler.RABATT_MONATE_FEHLEN),
    ({"rabatt_prozent": 30, "rabatt_laufzeit": "months", "rabatt_monate": 0}, ez.Fehler.RABATT_MONATE_FEHLEN),
    ({"rabatt_prozent": 30, "rabatt_laufzeit": "forever", "rabatt_monate": 6}, ez.Fehler.RABATT_MONATE_BEI_DAUERHAFT),
    ({"rabatt_laufzeit": "forever"}, ez.Fehler.LAUFZEIT_OHNE_RABATT),
    ({"rabatt_prozent": 100, "rabatt_monate": 6}, ez.Fehler.LAUFZEIT_OHNE_RABATT),
])
def test_rabattlaufzeit(felder: dict, code: ez.Fehler) -> None:
    assert _absage(plan_code="einzel", **felder).code is code


@pytest.mark.parametrize("extra", [
    {"plan_until": HEUTE},
    {"ki_kontingent": "ohne"},
    {"testguthaben": 5000, "ki_kontingent": "ohne"},
])
def test_was_nur_ein_geschenk_tragen_kann(extra: dict) -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=30, rabatt_laufzeit="forever",
                   ki_waehlbar=True, **extra).code is ez.Fehler.NUR_GESCHENK


def test_plaetze_nur_beim_geschenk() -> None:
    assert _absage(plan_code="team", account_name="F", account_seats=3, rabatt_prozent=30,
                   rabatt_laufzeit="forever").code is ez.Fehler.NUR_GESCHENK


@pytest.mark.parametrize("extra", [
    {"rabatt_prozent": 30, "rabatt_laufzeit": "forever"},
    {"rabatt_prozent": 100},
    {"ki_kontingent": "ohne"},
    {"testguthaben": 1000},
])
def test_frei_traegt_weder_rabatt_noch_ki(extra: dict) -> None:
    assert _absage(ki_waehlbar=True, **extra).code is ez.Fehler.OHNE_TARIF


def test_unbekannte_werte_sind_programmierfehler() -> None:
    with pytest.raises(ValueError):
        _pruefe(plan_code="einzel", ki_kontingent="viel")
    with pytest.raises(ValueError):
        _pruefe(plan_code="einzel", rabatt_prozent=30, rabatt_laufzeit="ewig")


# --- Entscheidungen 13–15: KI-Kontingent und Testguthaben -------------------


def test_ki_vorgabe_ist_der_tarif() -> None:
    w = ez.zuweisung(_pruefe(plan_code="einzel"))
    assert (w.ki_kontingent, w.byok_betriebsart, w.testguthaben) == ("tarif", None, None)


def test_ohne_kontingent_setzt_beides_und_testguthaben() -> None:
    w = ez.zuweisung(_pruefe(plan_code="einzel", ki_kontingent="ohne", testguthaben=5000, ki_waehlbar=True))
    assert (w.ki_kontingent, w.byok_betriebsart, w.testguthaben) == ("ohne", "beides", 5000)


def test_ohne_kontingent_auch_ohne_testguthaben() -> None:
    w = ez.zuweisung(_pruefe(plan_code="einzel", ki_kontingent="ohne", ki_waehlbar=True))
    assert (w.ki_kontingent, w.testguthaben) == ("ohne", None)


@pytest.mark.parametrize("extra", [
    {"ki_kontingent": "ohne"},
    {"ki_kontingent": "ohne", "testguthaben": 1000},
])
def test_ohne_credits_in_der_app_nicht_waehlbar(extra: dict) -> None:
    assert _absage(plan_code="einzel", **extra).code is ez.Fehler.KI_NICHT_WAEHLBAR


def test_testguthaben_nur_ohne_kontingent() -> None:
    assert _absage(plan_code="einzel", testguthaben=1000, ki_waehlbar=True).code \
        is ez.Fehler.TESTGUTHABEN_NUR_OHNE_KONTINGENT


@pytest.mark.parametrize("menge", [0, ez.TESTGUTHABEN_HOECHSTENS + 1])
def test_testguthaben_ausserhalb_abgelehnt(menge: int) -> None:
    f = _absage(plan_code="einzel", ki_kontingent="ohne", testguthaben=menge, ki_waehlbar=True)
    assert f.code is ez.Fehler.TESTGUTHABEN_UNGUELTIG and f.werte == {"hoechstens": ez.TESTGUTHABEN_HOECHSTENS}


def test_testguthaben_grenze_gilt() -> None:
    assert _pruefe(plan_code="einzel", ki_kontingent="ohne", testguthaben=ez.TESTGUTHABEN_HOECHSTENS,
                   ki_waehlbar=True).testguthaben == ez.TESTGUTHABEN_HOECHSTENS


def test_tage_ohne_testguthaben_abgelehnt() -> None:
    assert _absage(plan_code="einzel", ki_kontingent="ohne", testguthaben_tage=30, ki_waehlbar=True).code \
        is ez.Fehler.TAGE_OHNE_TESTGUTHABEN


@pytest.mark.parametrize("tage", [0, ez.TAGE_HOECHSTENS + 1])
def test_tage_ausserhalb_abgelehnt(tage: int) -> None:
    assert _absage(plan_code="einzel", ki_kontingent="ohne", testguthaben=1000, testguthaben_tage=tage,
                   ki_waehlbar=True).code is ez.Fehler.TAGE_UNGUELTIG


def _bis(**felder) -> datetime:
    z = _pruefe(plan_code="einzel", ki_kontingent="ohne", testguthaben=1000, ki_waehlbar=True, **felder)
    bis = ez.testguthaben_gueltig_bis(z, angenommen_am=HEUTE)
    assert bis is not None
    return bis


def test_testguthaben_frist_vorgabe_90_tage_einschliesslich() -> None:
    bis = _bis()
    assert bis == datetime(2027, 1, 12, 0, 0, tzinfo=ez.BERLIN)  # letzter Tag 11.01.2027 = Tag 90
    assert (bis.date() - HEUTE).days == ez.TESTGUTHABEN_TAGE_VORGABE


def test_testguthaben_frist_aus_tagen() -> None:
    assert _bis(testguthaben_tage=1) == datetime(2026, 10, 15, 0, 0, tzinfo=ez.BERLIN)  # nur der Annahmetag


def test_testguthaben_frist_endet_mit_dem_geschenk() -> None:
    assert _bis(plan_until=date(2026, 11, 30)) == datetime(2026, 12, 1, 0, 0, tzinfo=ez.BERLIN)


def test_testguthaben_tage_schlagen_das_geschenkende() -> None:
    assert _bis(plan_until=date(2026, 11, 30), testguthaben_tage=7) == datetime(2026, 10, 21, 0, 0, tzinfo=ez.BERLIN)


def test_testguthaben_frist_ist_berliner_mitternacht() -> None:
    """In UTC ist das 23:00 bzw. 22:00 des letzten Tages — nicht Mitternacht UTC."""
    assert _bis().astimezone(timezone.utc) == datetime(2027, 1, 11, 23, 0, tzinfo=timezone.utc)


def test_ohne_testguthaben_keine_frist() -> None:
    assert ez.testguthaben_gueltig_bis(_pruefe(plan_code="einzel"), angenommen_am=HEUTE) is None


def test_nach_ende_kontingent_wieder_vom_tarif() -> None:
    assert ez.nach_ende(kostenloser_tarif="test").ki_kontingent == "tarif"


def test_vorschau_nennt_rabatt_und_testguthaben() -> None:
    v = ez.vorschau(_pruefe(plan_code="einzel", rabatt_prozent=30, rabatt_laufzeit="months", rabatt_monate=12,
                            rabatt_danach="zahlung_vorab"))
    assert v is not None and (v["rabatt_prozent"], v["rabatt_laufzeit"], v["rabatt_monate"]) == (30, "months", 12)
    v = ez.vorschau(_pruefe(plan_code="einzel", ki_kontingent="ohne", testguthaben=5000, ki_waehlbar=True))
    assert v is not None and (v["ki_kontingent"], v["testguthaben"]) == ("ohne", 5000)


# --- Entscheidungen 16–18: Laufzeit auch bei 100 %, und was danach kommt ------


def _monate(prozent: int, danach: str | None, monate: int = 24, **extra):
    return _pruefe(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit="months",
                   rabatt_monate=monate, rabatt_danach=danach, **extra)


def test_geschenk_in_monaten_rechnet_den_letzten_tag_beim_annehmen() -> None:
    z = _monate(100, "starttarif")
    assert z.ist_geschenk and z.rabatt_prozent == 100
    w = ez.zuweisung(z, angenommen_am=date(2026, 10, 21))
    assert (w.plan_source, w.manual_plan_until, w.gutschein, w.danach) == (
        "manual", date(2028, 10, 20), None, None)


def test_geschenk_in_monaten_ohne_annahmetag_ist_programmierfehler() -> None:
    with pytest.raises(ValueError):
        ez.zuweisung(_monate(100, "starttarif"))


@pytest.mark.parametrize(("angenommen", "monate", "letzter"), [
    (date(2026, 10, 21), 1, date(2026, 11, 20)),
    (date(2026, 1, 31), 1, date(2026, 2, 27)),   # 31. + 1 Monat = 28.02., letzter Tag davor
    (date(2027, 1, 31), 13, date(2028, 2, 28)),  # Schaltjahr: 29.02. ist der erste Tag danach
    (date(2026, 10, 21), 120, date(2036, 10, 20)),
])
def test_geschenk_letzter_tag(angenommen: date, monate: int, letzter: date) -> None:
    assert ez.geschenk_letzter_tag(angenommen, monate) == letzter


def test_geschenk_letzter_tag_braucht_einen_monat() -> None:
    with pytest.raises(ValueError):
        ez.geschenk_letzter_tag(HEUTE, 0)


def test_geschenk_dauerhaft_ist_unbefristet_ohne_danach() -> None:
    z = _pruefe(plan_code="einzel", rabatt_prozent=100, rabatt_laufzeit="forever")
    w = ez.zuweisung(z)
    assert z.ist_geschenk and (w.manual_plan_until, w.danach) == (None, None)


def test_bestand_geschenk_mit_datum_bleibt_gueltig() -> None:
    """Gegenprobe zu ENDE_UND_LAUFZEIT: ohne Laufzeit trägt das Geschenk weiter ein Datum."""
    w = ez.zuweisung(_pruefe(plan_code="einzel", rabatt_prozent=100, plan_until=HEUTE))
    assert w.manual_plan_until == HEUTE


@pytest.mark.parametrize("prozent", [100, 30])
def test_datum_und_laufzeit_zugleich_abgelehnt(prozent: int) -> None:
    code = _absage(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit="months",
                   rabatt_monate=6, rabatt_danach="starttarif", plan_until=HEUTE).code
    assert code is (ez.Fehler.ENDE_UND_LAUFZEIT if prozent == 100 else ez.Fehler.NUR_GESCHENK)


@pytest.mark.parametrize("prozent", [100, 30])
def test_befristet_braucht_danach(prozent: int) -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit="months",
                   rabatt_monate=6).code is ez.Fehler.DANACH_FEHLT


@pytest.mark.parametrize("prozent", [100, 30])
def test_dauerhaft_traegt_kein_danach(prozent: int) -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit="forever",
                   rabatt_danach="starttarif").code is ez.Fehler.DANACH_BEI_DAUERHAFT


def test_danach_ohne_laufzeit_abgelehnt() -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=100, rabatt_danach="starttarif").code \
        is ez.Fehler.LAUFZEIT_OHNE_RABATT


def test_danach_ohne_tarif_abgelehnt() -> None:
    assert _absage(rabatt_danach="starttarif").code is ez.Fehler.OHNE_TARIF


def test_unbekanntes_danach_ist_programmierfehler() -> None:
    with pytest.raises(ValueError):
        _monate(100, "irgendwann")


def test_zahlung_spaeter_nur_bei_hundert_prozent() -> None:
    assert _absage(plan_code="einzel", rabatt_prozent=30, rabatt_laufzeit="months",
                   rabatt_monate=6, rabatt_danach="zahlung_spaeter").code is ez.Fehler.ZAHLUNG_SPAETER_NUR_GESCHENK


def test_zahlung_spaeter_ist_geschenk_mit_merker() -> None:
    z = _monate(100, "zahlung_spaeter", monate=12)
    w = ez.zuweisung(z, angenommen_am=date(2026, 10, 21))
    assert z.ist_geschenk
    assert (w.plan_source, w.manual_plan_until, w.danach, w.gutschein) == (
        "manual", date(2027, 10, 20), "zahlung_spaeter", None)


def test_zahlung_spaeter_darf_was_ein_geschenk_darf() -> None:
    z = _pruefe(plan_code="team", account_name="F", account_seats=3, rabatt_prozent=100,
                rabatt_laufzeit="months", rabatt_monate=12, rabatt_danach="zahlung_spaeter",
                ki_kontingent="ohne", testguthaben=1000, ki_waehlbar=True)
    assert z.ist_geschenk and z.account_seats == 3


def test_hundert_prozent_zahlung_vorab_wird_gutschein() -> None:
    z = _monate(100, "zahlung_vorab")
    w = ez.zuweisung(z)
    assert not z.ist_geschenk
    assert (w.anker, w.plan_source, w.manual_plan_until) == (None, None, None)
    assert w.gutschein == ez.EinladungsGutschein(
        discount_percent=100, discount_duration="months", discount_months=24, plans=("einzel",),
        endet_mit_rabatt=False, intervals=())


@pytest.mark.parametrize("extra", [
    {"account_seats": 3, "plan_code": "team", "account_name": "F"},
    {"ki_kontingent": "ohne", "ki_waehlbar": True},
])
def test_hundert_prozent_zahlung_vorab_traegt_nichts_vom_geschenk(extra: dict) -> None:
    felder = {"plan_code": "einzel", "rabatt_prozent": 100, "rabatt_laufzeit": "months",
              "rabatt_monate": 6, "rabatt_danach": "zahlung_vorab", **extra}
    assert _absage(**felder).code is ez.Fehler.NUR_GESCHENK


def test_rabatt_danach_starttarif_beendet_das_abo() -> None:
    g = ez.zuweisung(_monate(30, "starttarif", monate=6)).gutschein
    assert g is not None and g.endet_mit_rabatt and g.intervals == ()


def test_rabatt_danach_bezahlt_laeuft_weiter() -> None:
    g = ez.zuweisung(_monate(30, "zahlung_vorab", monate=6)).gutschein
    assert g is not None and not g.endet_mit_rabatt


@pytest.mark.parametrize(("prozent", "danach", "laufzeit", "erwartet"), [
    (100, "zahlung_vorab", "months", ("monthly",)),
    (30, "zahlung_vorab", "months", ("monthly",)),
    (30, "starttarif", "months", ()),   # endet mit dem Rabatt — kein Weiterlaufen
    (30, None, "forever", ()),          # kein „danach“, kein Preissprung
])
def test_privatkunden_zahlen_danach_monatlich(prozent, danach, laufzeit, erwartet) -> None:
    z = _pruefe(plan_code="einzel", rabatt_prozent=prozent, rabatt_laufzeit=laufzeit,
                rabatt_monate=6 if laufzeit == "months" else None, rabatt_danach=danach)
    g = ez.zuweisung(z, nur_intervall="monthly").gutschein
    assert g is not None and g.intervals == erwartet


def test_b2b_ohne_intervallgrenze() -> None:
    g = ez.zuweisung(_monate(100, "zahlung_vorab")).gutschein
    assert g is not None and g.intervals == ()


def test_vorschau_nennt_danach() -> None:
    v = ez.vorschau(_monate(100, "zahlung_spaeter"))
    assert v is not None and (v["rabatt_prozent"], v["rabatt_monate"], v["rabatt_danach"]) == (
        100, 24, "zahlung_spaeter")


@pytest.mark.parametrize(("zahlungsmittel", "offen", "ergebnis"), [
    (True, True, ez.ENDE_ABO_ANLEGEN),
    (False, True, ez.ENDE_ZAHLUNGSMITTEL_FEHLT),
    (True, False, ez.ENDE_VERKAUF_ZU),
    (False, False, ez.ENDE_VERKAUF_ZU),
])
def test_ende_entscheiden(zahlungsmittel: bool, offen: bool, ergebnis: str) -> None:
    assert ez.ende_entscheiden(zahlungsmittel=zahlungsmittel, verkauf_offen=offen) == ergebnis


@pytest.mark.parametrize(("am", "erinnert", "erwartet"), [
    (date(2027, 10, 6), False, False),   # 15 Tage vorher: zu früh
    (date(2027, 10, 7), False, True),    # 14 Tage einschließlich des letzten Tags
    (date(2027, 10, 20), False, True),   # letzter Tag
    (date(2027, 10, 21), False, False),  # vorbei — das Ende entscheidet der Lauf
    (date(2027, 10, 10), True, False),   # schon erinnert
])
def test_erinnerung_faellig(am: date, erinnert: bool, erwartet: bool) -> None:
    assert ez.erinnerung_faellig(date(2027, 10, 20), schon_erinnert=erinnert, am=am) is erwartet


def test_erinnerung_wie_vorwarnung() -> None:
    import gutschein_vorwarnung as v

    assert ez.ERINNERUNG_TAGE == v.VORLAUF_TAGE


def test_einladungs_gutschein_ueber_hundert_prozent_besteht_die_gutscheinregeln() -> None:
    import gutschein_regeln as g

    c = ez.zuweisung(_monate(100, "zahlung_vorab")).gutschein
    assert c is not None
    assert g.pruefe_rabatt(discount_percent=c.discount_percent, discount_duration=c.discount_duration,
                           discount_months=c.discount_months, max_redemptions=c.max_redemptions,
                           redeemable_until=None).gueltig


def test_neue_fehler_haben_schluessel() -> None:
    for f in (ez.Fehler.ENDE_UND_LAUFZEIT, ez.Fehler.DANACH_FEHLT, ez.Fehler.DANACH_BEI_DAUERHAFT,
              ez.Fehler.ZAHLUNG_SPAETER_NUR_GESCHENK):
        assert f.schluessel.startswith("errors.admin.invitation.zugang.")
