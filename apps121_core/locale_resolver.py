"""Sprache und Land eines Besuchers bestimmen — eine Kette, keine Vermutung.

**Sprache und Land sind zwei Fragen.** Ein Deutschsprachiger in Zürich will
Deutsch, nicht Französisch; ein Deutscher im Urlaub in Italien will nicht
plötzlich italienische Preise. Deshalb hat jede der beiden Fragen ihre eigene
Kette, und die IP entscheidet **nie** über die Sprache:

    Sprache : Cookie → Accept-Language → Land→Sprache      → Standard
    Land    : Cookie → Land vom Proxy   → Sprache→Heimatland → Standard

Zuerst gewinnt, wer zuerst antwortet. Die Kette läuft einmal beim ersten
Besuch; danach steht das Ergebnis im Cookie und ist damit die kanonische
Auskunft für anonyme Besucher. Bei angemeldeten Nutzern gewinnt, was am Konto
steht — die App schreibt den Wert zurück ins Cookie, damit die beiden nie
auseinanderlaufen.

Das Land kommt ausschließlich aus dem Reverse-Proxy-Header (siehe
`geo_country.py`), nie aus einem eigenen IP-Nachschlag in der App.

**Warum das hierher gehört.** Die Messung vom 28.07.2026
(`docs/INVENTORY.md`) fand `locale_resolver.py` in fünf Apps — **kein
einziges identisches Paar**, obwohl der Docstring überall derselbe war. Fünf
Fassungen einer Entscheidungsregel heißt: fünf Antworten auf die Frage,
welche Sprache jemand sieht. Kanonisch war `marketing-app`; diese Fassung
stammt von dort und ist von den App-Importen befreit, damit sie ohne
Installation in jedem Backend liegt.

**Kein Rückfall, der etwas verdeckt.** Jede Stufe der Kette ist ein echtes
Signal, kein Notnagel für einen Fehler weiter oben. Der Standard am Ende ist
eine Setzung, keine Reparatur — wer gar nichts mitteilt, bekommt die
Standardsprache, und das ist die einzige mögliche Antwort.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection

#: Land (ISO-3166-1 alpha-2) → Sprache, die dort erwartet wird.
#:
#: Nur benutzt, wenn `Accept-Language` nichts Brauchbares liefert — also
#: praktisch nur bei Klienten ohne Header. Die IP ist hier ein
#: Ersatz-Signal für die Sprache, kein Ersatz für den Willen des Besuchers.
LAND_STANDARDSPRACHE: dict[str, str] = {
    "DE": "de",
    "AT": "de",
    "CH": "de",
    "LI": "de",
    "LU": "de",
    "GB": "en",
    "US": "en",
    "IE": "en",
    "CA": "en",
    "AU": "en",
    "NZ": "en",
    "ES": "es",
    "MX": "es",
    "AR": "es",
    "CO": "es",
    "CL": "es",
    "PE": "es",
    "FR": "fr",
    "BE": "fr",
    "MC": "fr",
    "IT": "it",
    "SM": "it",
    "NL": "nl",
    "PL": "pl",
    "SE": "sv",
    "PT": "pt",
    "BR": "pt",
    "NO": "no",
    "DK": "da",
}

#: Sprache → Heimatland, wenn kein Länder-Signal vorliegt.
#:
#: Ohne diese Zuordnung rät man alphabetisch — und genau das ist am
#: 31.07.2026 in 121assist passiert: Deutsch landete auf `/at/deutsch`,
#: Französisch auf `/be/francais`, Italienisch auf `/ch/italiano`, Englisch
#: auf `/ca/english`. Formal gültige Kombinationen, alle falsch.
SPRACHE_HEIMATLAND: dict[str, str] = {
    "de": "DE",
    "en": "GB",
    "es": "ES",
    "fr": "FR",
    "it": "IT",
    "nl": "NL",
    "pl": "PL",
    "sv": "SE",
    "pt": "PT",
    "no": "NO",
    "da": "DK",
}


@dataclass(frozen=True)
class Sprachraum:
    """Was eine App führt — ihre einzige Wahrheit darüber.

    Die Liste kommt aus der App, nicht aus dem Fundament: Nicht jede Anwendung
    führt alle Sprachen der Flotte, und eine hier verdrahtete Liste würde einer
    App Sprachen unterstellen, für die sie keine Texte hat.
    """

    sprachen: Collection[str]
    standard_sprache: str
    standard_land: str = "DE"

    def __post_init__(self) -> None:
        if self.standard_sprache not in self.sprachen:
            raise ValueError(
                f"Standardsprache {self.standard_sprache!r} fehlt in {sorted(self.sprachen)!r}"
            )


def normalisiere_sprache(wert: str | None, *, raum: Sprachraum) -> str | None:
    """„de-DE" → „de", und nur wenn die App diese Sprache auch führt."""
    if not wert:
        return None
    code = wert.lower().split("-")[0]
    return code if code in raum.sprachen else None


def normalisiere_land(wert: str | None) -> str | None:
    """Ein plausibles ISO-3166-1-alpha-2-Kürzel in Großbuchstaben, sonst None."""
    if wert and len(wert) == 2 and wert.isalpha():
        return wert.upper()
    return None


def sprache_aus_accept_language(header: str | None, *, raum: Sprachraum) -> str | None:
    """Die beste geführte Sprache aus dem Header — mit q-Gewichten.

    „de-DE,de;q=0.9,en;q=0.8" → „de". Die Gewichte auszuwerten ist nicht
    Kosmetik: Browser schicken die Zweitsprache regelmäßig zuerst, wenn die
    Erstsprache regional gekennzeichnet ist.
    """
    if not header:
        return None
    bewertet: list[tuple[float, int, str]] = []
    for stelle, teil in enumerate(header.split(",")):
        marke = teil.strip()
        if not marke:
            continue
        stuecke = marke.split(";")
        tag = stuecke[0].strip().lower()
        gewicht = 1.0
        for zusatz in stuecke[1:]:
            zusatz = zusatz.strip()
            if zusatz.startswith("q="):
                try:
                    gewicht = float(zusatz[2:])
                except ValueError:
                    # Ein unlesbares Gewicht heißt „ganz hinten", nicht „egal".
                    gewicht = 0.0
        bewertet.append((gewicht, stelle, tag.split("-")[0]))
    # Höchstes Gewicht zuerst; bei Gleichstand bleibt die Reihenfolge des
    # Headers erhalten.
    for _gewicht, _stelle, sprache in sorted(bewertet, key=lambda t: (-t[0], t[1])):
        if sprache in raum.sprachen:
            return sprache
    return None


def bestimme_sprache(
    *,
    cookie: str | None,
    accept_language: str | None,
    land_vom_proxy: str | None,
    raum: Sprachraum,
) -> str:
    """Cookie → Accept-Language → Land→Sprache → Standard."""
    aus_land = LAND_STANDARDSPRACHE.get((land_vom_proxy or "").upper())
    return (
        normalisiere_sprache(cookie, raum=raum)
        or sprache_aus_accept_language(accept_language, raum=raum)
        # Auch die Landessprache muss die App führen — sonst zeigte sie
        # Schlüssel statt Text.
        or (aus_land if aus_land in raum.sprachen else None)
        or raum.standard_sprache
    )


def bestimme_land(
    *,
    cookie: str | None,
    land_vom_proxy: str | None,
    sprache: str,
    raum: Sprachraum,
) -> str:
    """Cookie → Land vom Proxy → Sprache→Heimatland → Standard."""
    return (
        normalisiere_land(cookie)
        or normalisiere_land(land_vom_proxy)
        or SPRACHE_HEIMATLAND.get(sprache)
        or raum.standard_land
    )


def heimatland(sprache: str, *, raum: Sprachraum) -> str:
    """Das Heimatland einer Sprache — für Konten ohne hinterlegtes Land."""
    normalisiert = normalisiere_sprache(sprache, raum=raum) or raum.standard_sprache
    return SPRACHE_HEIMATLAND.get(normalisiert, raum.standard_land)
