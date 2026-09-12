"""OAuth 2.1 für MCP — die Regeln, an denen es schiefgeht.

Umsetzung von §4.2 der Fleet-Spec: Authorization Code + PKCE, Dynamic Client
Registration (RFC 7591), damit Kunden die Apps als Custom Connector in
claude.ai per Klick verbinden können. Der Kanon verlangt das ausdrücklich als
**wiederverwendbares Modul** — „einmal richtig, viermal portieren, nicht
fünfmal erfinden".

**Hier stehen die Entscheidungen, nicht die Endpunkte.** Was eine gültige
Rücksprungadresse ist, wann ein Code verfällt, ob ein Prüfwert passt, wie weit
ein Geltungsbereich reichen darf. Die Endpunkte, die Speicherung und der
Zustimmungsdialog gehören in die App — sie unterscheiden sich, die Regeln
nicht.

**Warum ausgerechnet diese Funktionen.** OAuth geht fast immer an denselben
vier Stellen schief, und keine davon fällt im Betrieb auf:

1. *Offene Weiterleitung.* Wer `redirect_uri` unscharf vergleicht — Präfix,
   Teilzeichenkette, Platzhalter — verschenkt den Autorisierungscode an eine
   fremde Seite. Hier wird exakt verglichen, nach Normalisierung.
2. *PKCE-Abwertung.* Ein Client, der `plain` statt `S256` verlangt, hebt den
   Schutz auf. OAuth 2.1 kennt nur `S256`; `plain` wird abgelehnt.
3. *Wiederverwendung des Codes.* Ein Code, der zweimal eingelöst werden kann,
   ist ein zweiter Zugang. Er gilt einmal und kurz.
4. *Ausweitung des Geltungsbereichs.* Was am Ende im Token steht, darf nie
   mehr sein als das, was der Nutzer gesehen und bestätigt hat.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

__all__ = [
    "OAuthFehler",
    "CODE_LEBENSDAUER",
    "pruefwert_passt",
    "verifier_erzeugen",
    "challenge_aus",
    "rueckspruch_erlaubt",
    "code_erzeugen",
    "code_gueltig",
    "scopes_eingrenzen",
    "client_metadaten_pruefen",
]


class OAuthFehler(ValueError):
    """Trägt den Fehlercode, den die Spezifikation vorsieht.

    `code` ist einer aus RFC 6749 §4.1.2.1 (`invalid_request`,
    `invalid_grant`, `invalid_scope`, `invalid_redirect_uri`). Der Client
    wertet ihn aus; die Meldung ist für Menschen.
    """

    def __init__(self, code: str, meldung: str) -> None:
        super().__init__(meldung)
        self.code = code


#: Wie lange ein Autorisierungscode gilt.
#:
#: Eine Minute. Der Code wandert durch den Browser des Nutzers und wird
#: unmittelbar danach eingelöst; alles darüber ist nur Zeit, in der ein
#: abgefangener Code noch trägt. RFC 6749 empfiehlt höchstens zehn Minuten —
#: das ist die Obergrenze für langsame Menschen, nicht für Maschinen.
CODE_LEBENSDAUER = timedelta(minutes=1)


# ── PKCE ───────────────────────────────────────────────────────────────────


def verifier_erzeugen() -> str:
    """Ein Code-Verifier nach RFC 7636 §4.1 — 43 bis 128 Zeichen."""
    return secrets.token_urlsafe(64)[:96]


def challenge_aus(verifier: str) -> str:
    """Die Challenge zu einem Verifier: base64url(sha256(verifier)), ohne `=`.

    Nur `S256`. OAuth 2.1 hat `plain` gestrichen, und das aus gutem Grund: Bei
    `plain` ist die Challenge der Verifier, also schützt sie gegen niemanden,
    der den Autorisierungsaufruf mitliest.
    """
    verdaut = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(verdaut).decode("ascii").rstrip("=")


def pruefwert_passt(*, verifier: str, challenge: str, methode: str = "S256") -> bool:
    """Ob der beim Einlösen vorgelegte Verifier zur Challenge gehört.

    **`plain` wird abgelehnt, nicht durchgewinkt.** Ein Client, der es
    verlangt, bekommt eine Absage — sonst genügt es, `code_challenge_method`
    im Autorisierungsaufruf umzubiegen, um PKCE auszuhebeln. Genau das ist der
    Angriff, gegen den OAuth 2.1 die Methode gestrichen hat.
    """
    if methode != "S256":
        raise OAuthFehler(
            "invalid_request",
            f"code_challenge_method {methode!r} — OAuth 2.1 kennt nur S256.",
        )
    if not 43 <= len(verifier) <= 128:
        raise OAuthFehler(
            "invalid_grant", f"code_verifier hat {len(verifier)} Zeichen, erlaubt 43–128"
        )
    return hmac.compare_digest(challenge_aus(verifier), challenge)


# ── Rücksprungadresse ──────────────────────────────────────────────────────

#: Loopback-Adressen, die ein lokaler Client benutzen darf (RFC 8252 §7.3).
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def _normalisieren(uri: str) -> str:
    """Kleinschreibung für Schema und Host, Standardport weg, kein Fragment."""
    teile = urlsplit(uri.strip())
    host = (teile.hostname or "").lower()
    port = teile.port
    if (teile.scheme == "https" and port == 443) or (
        teile.scheme == "http" and port == 80
    ):
        port = None
    ort = f"{host}:{port}" if port else host
    return f"{teile.scheme.lower()}://{ort}{teile.path}"


def rueckspruch_erlaubt(vorgelegt: str, registriert: list[str]) -> bool:
    """Ob diese Rücksprungadresse zu diesem Client gehört.

    **Exakter Vergleich nach Normalisierung — kein Präfix, kein Platzhalter.**
    Das ist die Stelle, an der OAuth am häufigsten aufgebrochen wird: Wer
    „beginnt mit" prüft, lässt `https://app.example.com.angreifer.test`
    durch; wer `*` erlaubt, verschenkt jeden Code.

    Normalisiert wird trotzdem, weil sonst `https://App.Example.com/cb` und
    `https://app.example.com:443/cb` als verschieden gelten — dieselbe Adresse
    in anderer Schreibweise, und der Kunde sucht stundenlang.

    Ein Fragment im vorgelegten Wert ist ein Verstoß gegen RFC 6749 §3.1.2 und
    wird abgewiesen, nicht abgeschnitten.
    """
    if "#" in vorgelegt:
        raise OAuthFehler(
            "invalid_redirect_uri", "redirect_uri darf kein Fragment enthalten"
        )
    if not registriert:
        return False
    ziel = _normalisieren(vorgelegt)
    return any(ziel == _normalisieren(r) for r in registriert)


def _ist_sicher(uri: str) -> bool:
    """HTTPS — oder Loopback, wo es keine Leitung zum Abhören gibt.

    `http://localhost:1234/cb` ist der Weg, den lokale Clients (Claude
    Desktop) nehmen müssen: Sie haben kein Zertifikat. Ein `http` auf einen
    fremden Host wäre dagegen ein Code im Klartext über fremde Netze.
    """
    teile = urlsplit(uri)
    if teile.scheme == "https":
        return True
    return teile.scheme == "http" and (teile.hostname or "") in _LOOPBACK


# ── Autorisierungscode ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Autorisierungscode:
    klartext: str
    hash: str


def code_erzeugen() -> Autorisierungscode:
    """Ein Code samt Hash.

    Gespeichert wird nur der Hash — derselbe Gedanke wie beim API-Schlüssel:
    Wer die Datenbank liest, soll damit keinen Zugang einlösen können.
    """
    klartext = secrets.token_urlsafe(32)
    return Autorisierungscode(
        klartext=klartext,
        hash=hashlib.sha256(klartext.encode("ascii")).hexdigest(),
    )


def code_gueltig(
    *, ausgestellt: datetime, jetzt: datetime, eingeloest: bool
) -> bool:
    """Ob ein Code noch eingelöst werden darf.

    Einmal und kurz. Ein Code, der zweimal gilt, ist ein zweiter Zugang; einer,
    der lange gilt, ist ein Zugang für jeden, der die Browser-Historie sieht.

    Ein bereits eingelöster Code ist nicht nur ungültig — nach RFC 6749
    §4.1.2 soll der Server dann **alle** aus ihm entstandenen Token
    widerrufen. Das kann diese Funktion nicht tun; sie sagt nur, dass der Fall
    eingetreten ist, und der Aufrufer muss handeln.
    """
    if eingeloest:
        return False
    if ausgestellt.tzinfo is None or jetzt.tzinfo is None:
        raise OAuthFehler(
            "invalid_grant", "Zeitstempel ohne Zeitzone — der Vergleich wäre geraten"
        )
    return jetzt - ausgestellt < CODE_LEBENSDAUER


# ── Geltungsbereiche ───────────────────────────────────────────────────────


def scopes_eingrenzen(
    *, angefragt: list[str], erlaubt: set[str], zugestimmt: set[str] | None = None
) -> list[str]:
    """Was am Ende im Token steht.

    Drei Grenzen, alle nach unten: Was der Client anfragt, was die Person
    überhaupt darf, und — sofern es einen Zustimmungsdialog gab — was sie
    tatsächlich angehakt hat.

    **Nie mehr, nie stillschweigend.** Fragt ein Client etwas an, das die
    Person nicht darf, wird der Rest erteilt und das Übrige fällt weg
    (RFC 6749 §3.3 lässt das ausdrücklich zu). Fällt dabei ALLES weg, ist das
    ein Fehler und kein leeres Token: Ein Zugang ohne jeden Geltungsbereich
    sieht aus wie einer, der funktioniert, und kann nichts.
    """
    if not angefragt:
        raise OAuthFehler("invalid_scope", "Keine Geltungsbereiche angefragt")

    ergebnis = set(angefragt) & erlaubt
    if zugestimmt is not None:
        ergebnis &= zugestimmt
    if not ergebnis:
        raise OAuthFehler(
            "invalid_scope",
            f"Von {sorted(angefragt)} bleibt nichts übrig — der Zugang wäre leer.",
        )
    return sorted(ergebnis)


# ── Dynamic Client Registration (RFC 7591) ─────────────────────────────────

#: Ein Client-Name, den man einem Menschen zeigen kann.
_NAME_RE = re.compile(r"^[\w \-.()/+]{1,120}$", re.UNICODE)


def client_metadaten_pruefen(metadaten: dict) -> dict:
    """Eine Registrierung annehmen — oder begründet ablehnen.

    **DCR ist ein offener Endpunkt.** Jeder darf sich registrieren; das ist der
    Sinn (claude.ai tut es unaufgefordert). Genau deshalb wird hier streng
    geprüft: Was hier durchkommt, steht später in einem Zustimmungsdialog vor
    einem Menschen, der dem Namen glaubt.

    Geprüft wird, was Schaden anrichten kann:

    * mindestens eine Rücksprungadresse, und jede davon sicher
    * ein anzeigbarer Name ohne Steuerzeichen — sonst steht im Dialog etwas
      anderes, als der Nutzer liest
    * nur der Ablauf, den wir unterstützen (`authorization_code`)

    Zurück kommt die geprüfte Fassung, nicht die eingereichte: Was nicht
    geprüft wurde, wird auch nicht übernommen.
    """
    uris = metadaten.get("redirect_uris")
    if not isinstance(uris, list) or not uris:
        raise OAuthFehler("invalid_redirect_uri", "redirect_uris fehlt oder ist leer")
    if len(uris) > 10:
        raise OAuthFehler(
            "invalid_redirect_uri", f"{len(uris)} Rücksprungadressen — höchstens 10"
        )

    geprueft: list[str] = []
    for uri in uris:
        if not isinstance(uri, str) or not uri.strip():
            raise OAuthFehler("invalid_redirect_uri", "Leere Rücksprungadresse")
        if "#" in uri:
            raise OAuthFehler(
                "invalid_redirect_uri", f"Fragment in {uri!r} (RFC 6749 §3.1.2)"
            )
        if not _ist_sicher(uri):
            raise OAuthFehler(
                "invalid_redirect_uri",
                f"{uri!r} ist weder HTTPS noch Loopback — der Code liefe im "
                f"Klartext über fremde Netze.",
            )
        geprueft.append(uri.strip())

    name = str(metadaten.get("client_name", "")).strip()
    if not _NAME_RE.match(name):
        # Ein Name mit Zeilenumbruch oder Steuerzeichen kann im
        # Zustimmungsdialog etwas anderes vortäuschen, als er ist.
        raise OAuthFehler(
            "invalid_request",
            "client_name fehlt oder enthält Zeichen, die im Dialog täuschen könnten",
        )

    typen = metadaten.get("grant_types") or ["authorization_code"]
    if set(typen) - {"authorization_code", "refresh_token"}:
        raise OAuthFehler(
            "invalid_request",
            f"Nicht unterstützter Ablauf: {sorted(set(typen))}. "
            f"Nur authorization_code (mit PKCE) und refresh_token.",
        )

    return {
        "client_name": name,
        "redirect_uris": geprueft,
        "grant_types": sorted(set(typen)),
        # OAuth 2.1: öffentliche Clients ohne Geheimnis, dafür mit PKCE. Ein
        # Geheimnis in einer Desktop-Anwendung ist keines.
        "token_endpoint_auth_method": "none",
    }
