"""Selbsttest für den Embedding-Katalog.

Warum das ein Gate braucht: Die Dimension ist die einzige Zahl im ganzen
Suchaufbau, die sich nachträglich nur mit vollständiger Neuberechnung ändern
lässt. Ist sie falsch, fällt es entweder sofort auf (der Einfügeversuch
scheitert) oder gar nicht (die Spalte passt zufällig, die Treffer sind
Unsinn). Der zweite Fall ist der teure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from embedding_modelle import (  # noqa: E402
    MODELLE,
    DimensionFehler,
    EmbeddingModell,
    UngepruefteDimension,
    dimension_pruefen,
    fuer_spalte,
    modell,
    modelle_von,
)


def test_katalog_ist_nicht_leer():
    assert len(MODELLE) >= 6


def test_schluessel_sind_eindeutig():
    schluessel = [m.schluessel for m in MODELLE]
    assert len(schluessel) == len(set(schluessel))


def test_jedes_modell_ist_vollstaendig():
    for m in MODELLE:
        assert m.anbieter and m.name, m
        assert m.dimension > 0, m.schluessel
        assert m.max_eingabe_tokens > 0, m.schluessel


def test_modell_nachschlagen():
    m = modell("openai", "text-embedding-3-small")
    assert m.dimension == 1536
    assert m.schluessel == "openai/text-embedding-3-small"


def test_unbekanntes_modell_wirft_statt_zu_raten():
    """Kein Rückfall auf ein Standardmodell (Regel #7).

    Ein Tippfehler im Modellnamen bekäme sonst Vektoren eines anderen Modells
    in dieselbe Spalte — nicht auffindbar, aber auch nicht als Fehler sichtbar.
    """
    with pytest.raises(KeyError, match="Unbekanntes Embedding-Modell"):
        modell("openai", "text-embedding-4-riesig")


def test_fehlermeldung_nennt_die_bekannten():
    with pytest.raises(KeyError) as fehler:
        modell("jina", "tippfehler")
    assert "jina/jina-embeddings-v3" in str(fehler.value)


def test_modelle_je_anbieter():
    openai = modelle_von("openai")
    assert len(openai) == 2
    assert all(m.anbieter == "openai" for m in openai)
    assert modelle_von("gibt-es-nicht") == ()


def test_spaltenmass_nur_fuer_gemessene_modelle():
    assert fuer_spalte("mistral", "mistral-embed") == 1024


def test_ungepruefte_dimension_traegt_keine_spalte():
    """Eine Zahl aus der Modellkarte reicht für ``vector(N)`` nicht.

    Die Spalte ist die eine Entscheidung, die sich nur mit vollständiger
    Neuberechnung zurücknehmen lässt.
    """
    with pytest.raises(UngepruefteDimension, match="nicht gemessen"):
        fuer_spalte("mittwald", "Qwen3-Embedding-8B")


def test_ungepruefte_modelle_erklaeren_woher_die_zahl_kommt():
    for m in MODELLE:
        if not m.geprueft:
            assert m.hinweis, f"{m.schluessel}: ungeprüft ohne Hinweis"


def test_dimension_pruefen_bestaetigt_und_gibt_zurueck():
    assert dimension_pruefen("mistral", "mistral-embed", [0.0] * 1024) == 1024


def test_dimension_pruefen_schlaegt_bei_abweichung_an():
    with pytest.raises(DimensionFehler) as fehler:
        dimension_pruefen("mistral", "mistral-embed", [0.0] * 1536)
    text = str(fehler.value)
    assert "1024" in text and "1536" in text


def test_dimension_pruefen_gilt_auch_fuer_ungepruefte():
    """Genau dafür ist die Prüfung da — sie macht aus ungeprüft geprüft."""
    assert dimension_pruefen("mittwald", "Qwen3-Embedding-8B", [0.0] * 4096) == 4096


def test_modell_ist_unveraenderlich():
    m = MODELLE[0]
    assert isinstance(m, EmbeddingModell)
    with pytest.raises((AttributeError, TypeError)):
        m.dimension = 1  # type: ignore[misc]


def test_mehrsprachigkeit_ist_gesetzt():
    """Elf Sprachen: Ein einsprachiges Modell liefert für dänische Texte
    Vektoren, die nur so aussehen, als wären sie brauchbar."""
    assert all(isinstance(m.mehrsprachig, bool) for m in MODELLE)
    assert any(m.mehrsprachig for m in MODELLE)


def test_deutsche_und_franzoesische_anbieter_sind_vertreten():
    """Für Kunden mit EU-Auflage muss es eine Wahl geben, nicht nur OpenAI."""
    anbieter = {m.anbieter for m in MODELLE}
    assert "jina" in anbieter, "kein Anbieter aus Deutschland"
    assert "mistral" in anbieter, "kein Anbieter aus Frankreich"
