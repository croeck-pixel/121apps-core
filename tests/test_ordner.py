"""Selbsttest für den Ordner-Kanon.

Warum das ein Gate braucht: Ordner sehen aus wie eine triviale Sache, und
genau deshalb wurden sie viermal neu gebaut. Die Fehler dieser Klasse sind
nicht laut, sondern zermürbend — ein Dialog, der immer fragt, wird
weggeklickt; ein Ordner, dessen Löschen den Inhalt mitnimmt, kostet Daten;
zwei Ordner, die sich nur in der Groß-/Kleinschreibung unterscheiden, sind in
einer Liste nicht auseinanderzuhalten.

Die Tests prüfen deshalb nicht „läuft durch", sondern die sechs Entscheidungen
aus dem Modulkopf — jede mit ihrer Gegenprobe.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from ordner import (  # noqa: E402
    NAME_MAX,
    POSITION_SCHRITT,
    Entfernen,
    NameFehler,
    OrdnerAnsicht,
    Rolle,
    Wurzel,
    Wurzel,
    Zuordnen,
    Zuordnung,
    baue_antwort,
    darf_inhalt_aendern,
    darf_ordner_verwalten,
    darf_sehen,
    entscheide_entfernen,
    entscheide_zuordnen,
    naechste_position,
    neu_ordnen,
    plane_ordner_loeschen,
    pruefe_name,
    wurzel_fuer,
)

# ---------------------------------------------------------------------------
# Entscheidung 3: der Dialog erscheint nur, wenn er etwas entscheidet
# ---------------------------------------------------------------------------


def test_mehrfach_in_zwei_ordnern_fragt():
    """Der einzige Fall, in dem gefragt werden MUSS."""
    plan = entscheide_entfernen(Zuordnung.MEHRFACH, 2)
    assert plan.aktion is Entfernen.FRAGEN
    assert plan.verbleibende_ordner == 1


def test_mehrfach_in_einem_ordner_fragt_nicht():
    """Gegenprobe: bei genau einem Ordner ist 'nur hier' == 'überall'."""
    plan = entscheide_entfernen(Zuordnung.MEHRFACH, 1)
    assert plan.aktion is Entfernen.AUS_ORDNER_STILL
    assert plan.verbleibende_ordner == 0


def test_eindeutige_zuordnung_fragt_nie():
    """Gegenprobe: wo es nur einen Ordner geben kann, gibt es nichts zu fragen.

    Auch nicht bei einem widersprüchlichen Zählerstand — käme der je vor, wäre
    er ein Datenfehler und keine Rechtfertigung für einen Dialog.
    """
    for anzahl in (1, 2, 5):
        plan = entscheide_entfernen(Zuordnung.EINDEUTIG, anzahl)
        assert plan.aktion is Entfernen.AUS_ORDNER_STILL


def test_aus_der_wurzel_heraus_meint_immer_den_bestand():
    """In der Wurzelansicht gibt es keinen Ordner, aus dem man nehmen könnte."""
    plan = entscheide_entfernen(Zuordnung.MEHRFACH, 3, aus_ordner=False)
    assert plan.aktion is Entfernen.AUS_BESTAND_STILL


def test_objekt_ohne_ordner_geht_direkt_aus_dem_bestand():
    plan = entscheide_entfernen(Zuordnung.MEHRFACH, 0)
    assert plan.aktion is Entfernen.AUS_BESTAND_STILL


def test_verbleibende_ordner_ist_die_zahl_fuer_den_dialogtext():
    """'bleibt in N Ordnern' darf nicht geraten sein."""
    assert entscheide_entfernen(Zuordnung.MEHRFACH, 4).verbleibende_ordner == 3


def test_geteilter_ordner_meldet_dass_es_andere_betrifft():
    plan = entscheide_entfernen(Zuordnung.MEHRFACH, 2, geteilter_ordner=True)
    assert plan.betrifft_andere is True
    # Gegenprobe: privat betrifft niemanden sonst.
    assert entscheide_entfernen(Zuordnung.MEHRFACH, 2).betrifft_andere is False


def test_negative_anzahl_ist_ein_fehler():
    with pytest.raises(ValueError):
        entscheide_entfernen(Zuordnung.MEHRFACH, -1)


# ---------------------------------------------------------------------------
# Entscheidung 4: Ordner löschen nimmt den Inhalt nicht mit
# ---------------------------------------------------------------------------


def test_ordner_loeschen_loescht_niemals_den_inhalt():
    plan = plane_ordner_loeschen(objekte_im_ordner=7, davon_nur_hier=3)
    assert plan.inhalt_wird_geloescht is False
    assert plan.objekte == 7
    assert plan.danach_ohne_ordner == 3


def test_leerer_ordner_hat_keine_folgen():
    plan = plane_ordner_loeschen(0, 0)
    assert plan.objekte == 0
    assert plan.danach_ohne_ordner == 0


def test_mehr_nur_hier_als_insgesamt_ist_ein_fehler():
    """Ein Zählfehler des Aufrufers darf nicht als Dialogtext durchgehen."""
    with pytest.raises(ValueError):
        plane_ordner_loeschen(objekte_im_ordner=2, davon_nur_hier=3)


def test_negative_anzahlen_beim_loeschen_sind_ein_fehler():
    with pytest.raises(ValueError):
        plane_ordner_loeschen(-1, 0)


# ---------------------------------------------------------------------------
# Entscheidung 5: die Wurzel heißt nach der Kardinalität
# ---------------------------------------------------------------------------


def test_wurzel_haengt_an_der_kardinalitaet():
    assert wurzel_fuer(Zuordnung.EINDEUTIG) is Wurzel.UNGEORDNET
    assert wurzel_fuer(Zuordnung.MEHRFACH) is Wurzel.ALLE


# ---------------------------------------------------------------------------
# Entscheidung 6: teilen gibt das Löschrecht nicht mit
# ---------------------------------------------------------------------------


def test_mitglied_darf_inhalt_aendern_aber_nicht_den_ordner():
    assert darf_inhalt_aendern(Rolle.MITGLIED, geteilt=True) is True
    assert darf_ordner_verwalten(Rolle.MITGLIED, geteilt=True) is False


def test_eigentuemer_und_org_admin_duerfen_verwalten():
    assert darf_ordner_verwalten(Rolle.EIGENTUEMER, geteilt=True) is True
    assert darf_ordner_verwalten(Rolle.ORG_ADMIN, geteilt=True) is True


def test_privater_ordner_ist_auch_fuer_die_verwaltung_privat():
    """Administrieren heißt Mandanten verwalten, nicht in fremde Ablagen sehen."""
    assert darf_sehen(Rolle.ORG_ADMIN, geteilt=False) is False
    assert darf_ordner_verwalten(Rolle.ORG_ADMIN, geteilt=False) is False
    # Gegenprobe: der Eigentümer sieht seinen privaten Ordner sehr wohl.
    assert darf_sehen(Rolle.EIGENTUEMER, geteilt=False) is True


def test_fremde_sehen_nichts():
    assert darf_sehen(Rolle.FREMD, geteilt=True) is False
    assert darf_sehen(Rolle.FREMD, geteilt=False) is False
    assert darf_inhalt_aendern(Rolle.FREMD, geteilt=True) is False


def test_mitglied_sieht_privaten_ordner_nicht():
    assert darf_sehen(Rolle.MITGLIED, geteilt=False) is False
    assert darf_inhalt_aendern(Rolle.MITGLIED, geteilt=False) is False


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------


def test_name_wird_aussen_beschnitten():
    assert pruefe_name("  Kern-ETFs  ").name == "Kern-ETFs"


def test_innere_mehrfach_leerzeichen_werden_zusammengezogen():
    """Sonst entstehen zwei Ordner, die in der Liste identisch aussehen."""
    assert pruefe_name("Kern    ETFs").name == "Kern ETFs"


def test_leerer_name_wird_abgelehnt():
    for roh in ("", "   ", "\t\n"):
        assert pruefe_name(roh).fehler is NameFehler.LEER


def test_zu_langer_name_wird_abgelehnt():
    assert pruefe_name("x" * NAME_MAX).ok is True
    assert pruefe_name("x" * (NAME_MAX + 1)).fehler is NameFehler.ZU_LANG


def test_duplikat_unabhaengig_von_grossschreibung():
    ergebnis = pruefe_name("kern-etfs", vergebene_namen=["Kern-ETFs"])
    assert ergebnis.fehler is NameFehler.BELEGT


def test_duplikat_erkennt_auch_scharfes_s():
    """`casefold` statt `lower` — 'STRASSE' und 'straße' sind derselbe Ordner."""
    assert pruefe_name("STRASSE", vergebene_namen=["Straße"]).fehler is NameFehler.BELEGT


def test_duplikat_erkennt_unterschiedliche_unicode_normalform():
    """Zusammengesetztes und vorkomponiertes 'ä' sehen gleich aus."""
    zerlegt = "Ma\u0308rkte"        # a + kombinierendes Trema
    vorkomponiert = "M\u00e4rkte"   # ae als ein Zeichen
    assert zerlegt != vorkomponiert   # sonst prueft der Test nichts
    assert pruefe_name(zerlegt, vergebene_namen=[vorkomponiert]).fehler is NameFehler.BELEGT


def test_freier_name_geht_durch():
    ergebnis = pruefe_name("Dividenden", vergebene_namen=["Kern-ETFs", "Beobachten"])
    assert ergebnis.ok is True
    assert ergebnis.name == "Dividenden"


def test_ohne_vergebene_namen_wird_nicht_auf_duplikate_geprueft():
    assert pruefe_name("Kern-ETFs").ok is True


def test_fehlerfall_liefert_keinen_namen():
    """Ein abgelehnter Name darf nicht versehentlich gespeichert werden."""
    assert pruefe_name("").name == ""
    assert pruefe_name("x" * (NAME_MAX + 1)).name == ""


# ---------------------------------------------------------------------------
# Reihenfolge
# ---------------------------------------------------------------------------


def test_erster_ordner_bekommt_position_null():
    assert naechste_position([]) == 0


def test_neuer_ordner_stellt_sich_hinten_an():
    assert naechste_position([0, 10, 20]) == 30


def test_naechste_position_haelt_auch_bei_luecken_abstand():
    assert naechste_position([0, 5, 7]) == 7 + POSITION_SCHRITT


def test_neu_ordnen_vergibt_lueckenhafte_positionen_in_reihenfolge():
    assert neu_ordnen(["c", "a", "b"]) == {"c": 0, "a": 10, "b": 20}


def test_neu_ordnen_laesst_platz_zum_dazwischenschieben():
    positionen = sorted(neu_ordnen(["a", "b"]).values())
    assert positionen[1] - positionen[0] > 1


def test_neu_ordnen_lehnt_doppelte_kennungen_ab():
    """Ein Programmierfehler des Aufrufers wird nicht stillschweigend geglättet."""
    with pytest.raises(ValueError):
        neu_ordnen(["a", "b", "a"])


def test_neu_ordnen_mit_leerer_liste():
    assert neu_ordnen([]) == {}


# ---------------------------------------------------------------------------
# Antwort-Form
# ---------------------------------------------------------------------------


def _ansicht(id_, name, position, **kw):
    return OrdnerAnsicht(id=id_, name=name, position=position, **kw)


def test_antwort_nennt_kardinalitaet_und_wurzel():
    """Die Oberfläche darf beides nicht aus einer eigenen Konstante ziehen."""
    antwort = baue_antwort([], [], Zuordnung.MEHRFACH)
    assert antwort["zuordnung"] == "mehrfach"
    assert antwort["wurzel"] == "alle"

    antwort = baue_antwort([], [], Zuordnung.EINDEUTIG)
    assert antwort["zuordnung"] == "eindeutig"
    assert antwort["wurzel"] == "ungeordnet"


def test_ordner_kommen_nach_position_sortiert():
    antwort = baue_antwort(
        [_ansicht("b", "B", 20), _ansicht("a", "A", 0), _ansicht("c", "C", 10)],
        [],
        Zuordnung.EINDEUTIG,
    )
    assert [o["id"] for o in antwort["ordner"]] == ["a", "c", "b"]


def test_gleiche_position_wird_nach_namen_entschieden():
    """Ohne zweites Kriterium wäre die Reihenfolge die der Datenbank."""
    antwort = baue_antwort(
        [_ansicht("x", "Zebra", 0), _ansicht("y", "alpha", 0)],
        [],
        Zuordnung.EINDEUTIG,
    )
    assert [o["name"] for o in antwort["ordner"]] == ["alpha", "Zebra"]


def test_antwort_traegt_inhalt_und_freigabe_durch():
    antwort = baue_antwort(
        [_ansicht("a", "Kern-ETFs", 0, objekte=[{"isin": "IE00B3RBWM25"}], geteilt=True)],
        [{"isin": "IE00BLP5S460"}],
        Zuordnung.MEHRFACH,
    )
    ordner = antwort["ordner"][0]
    assert ordner["geteilt"] is True
    assert ordner["objekte"] == [{"isin": "IE00B3RBWM25"}]
    assert antwort["wurzel_objekte"] == [{"isin": "IE00BLP5S460"}]


def test_ordner_ansicht_teilen_sich_keine_liste():
    """Gegenprobe zum klassischen Fehler mit veränderlichen Standardwerten."""
    a, b = OrdnerAnsicht("a", "A", 0), OrdnerAnsicht("b", "B", 10)
    a.objekte.append("x")
    assert b.objekte == []


# ---------------------------------------------------------------------------
# Zuordnen: was „diese Objekte in jenen Ordner" bedeutet
# ---------------------------------------------------------------------------


def test_bei_mehrfachzuordnung_kommt_der_ordner_dazu():
    """„Verschieben" müsste raten, aus welchem der bestehenden Ordner das
    Objekt verschwindet — diese Angabe gibt es nicht."""
    assert entscheide_zuordnen(Zuordnung.MEHRFACH) is Zuordnen.HINZUFUEGEN


def test_bei_eindeutiger_zuordnung_ersetzt_der_ordner_den_alten():
    """Ein Objekt hat dort genau einen Platz — „dazulegen" gibt es nicht."""
    assert entscheide_zuordnen(Zuordnung.EINDEUTIG) is Zuordnen.VERSCHIEBEN


def test_die_beiden_faelle_sind_verschieden():
    """Gegenprobe: eine Funktion, die immer dasselbe zurückgibt, hätte beide
    Tests oben bestanden."""
    assert entscheide_zuordnen(Zuordnung.EINDEUTIG) is not entscheide_zuordnen(
        Zuordnung.MEHRFACH
    )


# ---------------------------------------------------------------------------
# Die Wurzel ist waehlbar (Regel 5)
# ---------------------------------------------------------------------------


def test_die_wurzel_folgt_ohne_angabe_der_kardinalitaet():
    antwort = baue_antwort([], [], Zuordnung.MEHRFACH)
    assert antwort["wurzel"] == "alle"


def test_die_app_darf_bei_mehrfachzuordnung_ungeordnet_waehlen():
    """Sonst steht ein einsortiertes Objekt im Ordner UND in der Wurzel."""
    antwort = baue_antwort([], [], Zuordnung.MEHRFACH, wurzel=Wurzel.UNGEORDNET)
    assert antwort["wurzel"] == "ungeordnet"


def test_die_wahl_aendert_die_kardinalitaet_nicht():
    """Gegenprobe: `wurzel` beschriftet, sie schreibt keine Zuordnung um —
    davon haengt der Loeschdialog ab."""
    antwort = baue_antwort([], [], Zuordnung.MEHRFACH, wurzel=Wurzel.UNGEORDNET)
    assert antwort["zuordnung"] == "mehrfach"
