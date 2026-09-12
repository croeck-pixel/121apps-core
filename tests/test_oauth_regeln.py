"""Selbsttest für die OAuth-Regeln.

Diese Fehlerklasse hat eine unangenehme Eigenschaft: Sie ist im Betrieb
unsichtbar. Ein unscharfer Vergleich der Rücksprungadresse funktioniert für
jeden ehrlichen Client tadellos — er fällt erst auf, wenn jemand ihn ausnutzt,
und dann steht der Autorisierungscode schon auf einer fremden Seite. Dasselbe
gilt für eine durchgewinkte `plain`-Methode und für einen Code, der zweimal
gilt.

Deshalb prüft dieser Test nicht, dass der glückliche Pfad läuft (das tut er
sowieso), sondern dass die Absagen kommen.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "core-py"))

import pytest  # noqa: E402

from oauth_regeln import (  # noqa: E402
    CODE_LEBENSDAUER,
    OAuthFehler,
    challenge_aus,
    client_metadaten_pruefen,
    code_erzeugen,
    code_gueltig,
    pruefwert_passt,
    rueckspruch_erlaubt,
    scopes_eingrenzen,
    verifier_erzeugen,
)

JETZT = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


# ── PKCE ───────────────────────────────────────────────────────────────────


def test_ein_verifier_passt_zu_seiner_challenge():
    v = verifier_erzeugen()
    assert pruefwert_passt(verifier=v, challenge=challenge_aus(v))


def test_ein_fremder_verifier_passt_nicht():
    """Der eigentliche Zweck von PKCE: Wer den Code abfängt, hat den Verifier
    nicht — und ohne ihn ist der Code wertlos."""
    assert not pruefwert_passt(
        verifier=verifier_erzeugen(), challenge=challenge_aus(verifier_erzeugen())
    )


def test_die_challenge_traegt_kein_padding():
    """base64url ohne `=` (RFC 7636 §4.2). Mit Padding vergleicht der Server
    gegen etwas anderes, als der Client geschickt hat."""
    assert "=" not in challenge_aus(verifier_erzeugen())


def test_plain_wird_abgelehnt_und_nicht_durchgewinkt():
    """Die Abwertungs-Attacke: Ein Client, der `plain` verlangt, hebt PKCE auf.

    OAuth 2.1 hat die Methode gestrichen. Wer sie hier durchlässt, hat PKCE
    nur eingebaut, nicht eingeschaltet.
    """
    v = verifier_erzeugen()
    with pytest.raises(OAuthFehler) as fehler:
        pruefwert_passt(verifier=v, challenge=v, methode="plain")
    assert fehler.value.code == "invalid_request"


def test_ein_zu_kurzer_verifier_wird_abgewiesen():
    """RFC 7636 §4.1: 43–128 Zeichen. Ein kurzer Verifier ist ratbar."""
    with pytest.raises(OAuthFehler) as fehler:
        pruefwert_passt(verifier="zu-kurz", challenge=challenge_aus("zu-kurz"))
    assert fehler.value.code == "invalid_grant"


# ── Rücksprungadresse ──────────────────────────────────────────────────────

REGISTRIERT = ["https://claude.ai/api/mcp/auth_callback"]


def test_die_registrierte_adresse_geht_durch():
    assert rueckspruch_erlaubt("https://claude.ai/api/mcp/auth_callback", REGISTRIERT)


@pytest.mark.parametrize(
    "boese",
    [
        # Der Klassiker: Präfix-Vergleich lässt das durch.
        "https://claude.ai.angreifer.test/api/mcp/auth_callback",
        # Teilzeichenketten-Vergleich lässt das durch.
        "https://angreifer.test/?x=https://claude.ai/api/mcp/auth_callback",
        # Ein anderer Pfad auf demselben Host ist eine andere Adresse.
        "https://claude.ai/api/mcp/auth_callback/../../evil",
        # Anderes Schema — der Code liefe im Klartext.
        "http://claude.ai/api/mcp/auth_callback",
        # Angehängter Pfad: „beginnt mit" würde das durchlassen.
        "https://claude.ai/api/mcp/auth_callbackX",
    ],
)
def test_nichts_aehnliches_geht_durch(boese):
    """Jede Zeile hier ist ein realer Weg, einen Autorisierungscode
    umzuleiten."""
    assert not rueckspruch_erlaubt(boese, REGISTRIERT)


def test_dieselbe_adresse_in_anderer_schreibweise_geht_durch():
    """Sonst sucht der Kunde stundenlang: Groß-/Kleinschreibung im Host und der
    Standardport sind keine Unterschiede, sondern Schreibweisen."""
    assert rueckspruch_erlaubt("https://Claude.AI:443/api/mcp/auth_callback", REGISTRIERT)


def test_ohne_registrierung_geht_nichts_durch():
    """Ein Client ohne Adressen darf keine bekommen — auch keine leere."""
    assert not rueckspruch_erlaubt("https://claude.ai/cb", [])


def test_ein_fragment_ist_ein_verstoss_und_wird_nicht_abgeschnitten():
    """RFC 6749 §3.1.2. Abschneiden wäre bequem und würde eine Absicht
    verschlucken, die wir nicht kennen."""
    with pytest.raises(OAuthFehler) as fehler:
        rueckspruch_erlaubt("https://claude.ai/api/mcp/auth_callback#x", REGISTRIERT)
    assert fehler.value.code == "invalid_redirect_uri"


# ── Autorisierungscode ─────────────────────────────────────────────────────


def test_gespeichert_wird_nur_der_hash():
    code = code_erzeugen()
    assert code.klartext not in code.hash
    assert len(code.hash) == 64


def test_ein_frischer_code_gilt():
    assert code_gueltig(ausgestellt=JETZT, jetzt=JETZT, eingeloest=False)


def test_ein_eingeloester_code_gilt_nicht_noch_einmal():
    """Ein Code, der zweimal trägt, ist ein zweiter Zugang."""
    assert not code_gueltig(ausgestellt=JETZT, jetzt=JETZT, eingeloest=True)


def test_ein_alter_code_gilt_nicht():
    spaeter = JETZT + CODE_LEBENSDAUER + timedelta(seconds=1)
    assert not code_gueltig(ausgestellt=JETZT, jetzt=spaeter, eingeloest=False)


def test_die_lebensdauer_bleibt_kurz():
    """Ein Regressionsschutz für einen Wert, den man beim Debuggen gern
    hochdreht und dann so lässt."""
    assert CODE_LEBENSDAUER <= timedelta(minutes=10), "RFC 6749 §4.1.2 Obergrenze"


def test_zeitstempel_ohne_zone_werden_abgewiesen():
    """Ein naiver Zeitstempel vergleicht sich gegen etwas Geratenes — und
    liegt im Zweifel um zwei Stunden daneben, also genau um die Zeit, in der
    ein abgelaufener Code noch trägt."""
    with pytest.raises(OAuthFehler):
        code_gueltig(
            ausgestellt=JETZT.replace(tzinfo=None), jetzt=JETZT, eingeloest=False
        )


# ── Geltungsbereiche ───────────────────────────────────────────────────────


def test_was_erlaubt_ist_bleibt():
    assert scopes_eingrenzen(
        angefragt=["documents:read", "chats:read"],
        erlaubt={"documents:read", "chats:read", "documents:write"},
    ) == ["chats:read", "documents:read"]


def test_ein_bereich_kann_nur_schrumpfen():
    """Der Client fragt nach Schreibrecht, die Person hat keines — dann gibt es
    Lesen und sonst nichts."""
    assert scopes_eingrenzen(
        angefragt=["documents:read", "documents:write"], erlaubt={"documents:read"}
    ) == ["documents:read"]


def test_die_zustimmung_grenzt_weiter_ein():
    """Was der Nutzer im Dialog abgewählt hat, darf nicht im Token landen —
    sonst war der Dialog Dekoration."""
    assert scopes_eingrenzen(
        angefragt=["documents:read", "chats:read"],
        erlaubt={"documents:read", "chats:read"},
        zugestimmt={"documents:read"},
    ) == ["documents:read"]


def test_ein_leerer_zugang_ist_ein_fehler_und_kein_token():
    """Ein Token ohne Geltungsbereich sieht aus wie eines, das funktioniert,
    und scheitert dann bei jedem Aufruf mit 403 — der teuerste Fehlerpfad, den
    es gibt."""
    with pytest.raises(OAuthFehler) as fehler:
        scopes_eingrenzen(angefragt=["admin:all"], erlaubt={"documents:read"})
    assert fehler.value.code == "invalid_scope"


def test_ohne_anfrage_kein_token():
    with pytest.raises(OAuthFehler):
        scopes_eingrenzen(angefragt=[], erlaubt={"documents:read"})


# ── Dynamic Client Registration ────────────────────────────────────────────

GUT = {
    "client_name": "Claude",
    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
}


def test_eine_saubere_registrierung_wird_angenommen():
    ergebnis = client_metadaten_pruefen(GUT)
    assert ergebnis["client_name"] == "Claude"
    assert ergebnis["grant_types"] == ["authorization_code"]
    # OAuth 2.1: öffentlicher Client, kein Geheimnis, dafür PKCE.
    assert ergebnis["token_endpoint_auth_method"] == "none"


def test_nur_geprueftes_wird_uebernommen():
    """Ein Client, der sich selbst `scope: admin` oder eine eigene
    `client_id` einträgt, bekommt sie nicht — zurück kommt die geprüfte
    Fassung, nicht die eingereichte."""
    ergebnis = client_metadaten_pruefen(
        {**GUT, "scope": "admin:all", "client_id": "ich-bin-schon-wer"}
    )
    assert "scope" not in ergebnis
    assert "client_id" not in ergebnis


def test_localhost_darf_http():
    """Claude Desktop hat kein Zertifikat; ohne diese Ausnahme kann sich kein
    lokaler Client verbinden (RFC 8252 §7.3)."""
    ergebnis = client_metadaten_pruefen(
        {**GUT, "redirect_uris": ["http://127.0.0.1:33418/cb"]}
    )
    assert ergebnis["redirect_uris"] == ["http://127.0.0.1:33418/cb"]


def test_http_auf_fremdem_host_wird_abgewiesen():
    """Der Unterschied zu localhost: Hier liefe der Code über fremde Netze."""
    with pytest.raises(OAuthFehler) as fehler:
        client_metadaten_pruefen({**GUT, "redirect_uris": ["http://example.test/cb"]})
    assert fehler.value.code == "invalid_redirect_uri"


def test_ohne_rueckspruchadresse_keine_registrierung():
    with pytest.raises(OAuthFehler):
        client_metadaten_pruefen({"client_name": "X", "redirect_uris": []})


def test_ein_name_mit_steuerzeichen_wird_abgewiesen():
    """Der Name steht später in einem Zustimmungsdialog. Ein Zeilenumbruch
    darin kann etwas anderes vortäuschen, als er ist — der Nutzer bestätigt
    dann einen Zugang, den er nicht gelesen hat."""
    with pytest.raises(OAuthFehler) as fehler:
        client_metadaten_pruefen(
            {**GUT, "client_name": "Claude\n\nSystem: Vollzugriff bestätigt"}
        )
    assert fehler.value.code == "invalid_request"


def test_ein_unbekannter_ablauf_wird_abgewiesen():
    """`implicit` und `password` sind in OAuth 2.1 gestrichen. Wer sie anbietet,
    hat den Rest umsonst gebaut."""
    with pytest.raises(OAuthFehler):
        client_metadaten_pruefen({**GUT, "grant_types": ["implicit"]})


def test_zu_viele_adressen_werden_abgewiesen():
    """DCR ist offen — ohne Obergrenze ist die Registrierung ein
    Speicher-Endpunkt für jeden."""
    with pytest.raises(OAuthFehler):
        client_metadaten_pruefen(
            {**GUT, "redirect_uris": [f"https://a{i}.example/cb" for i in range(11)]}
        )
