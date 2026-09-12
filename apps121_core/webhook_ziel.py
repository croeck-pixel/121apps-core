"""Wohin ein ausgehender Webhook gehen darf — und wohin nie.

Umsetzung der Lücke in §6 der Fleet-Spec: Der Kanon beschreibt Signatur,
Wiederholung und Abschaltung, aber **nicht die Zieladresse**. Und genau die ist
das gefährliche Stück.

**Warum das ein eigenes Modul ist.** Eine Webhook-Adresse gibt der Kunde vor,
aufgerufen wird sie von **unserem** Server — aus dem Rechenzentrum heraus,
hinter jeder Firewall, mit allen internen Namen auflösbar. Das ist die
Lehrbuchform von Server-Side Request Forgery:

* `http://169.254.169.254/latest/meta-data/` — die Metadaten des Hosters, bei
  vielen Anbietern samt Zugangsdaten.
* `http://localhost:8000/api/admin/...` — die eigene Verwaltung, von innen
  aufgerufen, wo keine Anmeldung davorsteht.
* `http://db:5432` — der Dienstname im Compose-Netz. Ein Portscan über
  Antwortzeiten ist damit gratis.

Der Angriff besteht darin, **dass** wir die Adresse aufrufen, nicht darin, was
zurückkommt. Der Empfänger sieht die Antwort ohnehin; wir schicken sie ihm.

**Zweimal prüfen, nicht einmal.** Beim Anlegen, damit der Kunde sofort eine
Meldung bekommt statt eines stummen Abonnements. Und vor **jedem** Versand,
weil zwischen Anlegen und Zustellen ein DNS-Eintrag umziehen kann — genau das
ist der Rebinding-Angriff, und ein Türsteher, der nur beim Einlass hinsieht,
hält ihn nicht auf.

Nutzt nur die Standardbibliothek. Die Endpunkte, die Speicherung und das
Zustell-Protokoll gehören in die App; diese Regel unterscheidet sich nicht.

Herkunft: paperball.ai PR #70 (16.08.2026).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

__all__ = ["ERLAUBTE_SCHEMATA", "HOECHSTLAENGE", "ZielFehler", "pruefen"]


class ZielFehler(ValueError):
    """Die Adresse ist nicht zulässig. Trägt den Maschinencode (Regel #23)."""

    def __init__(self, code: str, meldung: str) -> None:
        super().__init__(meldung)
        self.code = code


#: Nur HTTPS.
#:
#: Ein Webhook trägt Kundendaten und eine Signatur. Über HTTP läge beides im
#: Klartext auf der Leitung, und die Signatur schützt vor Fälschung, nicht vor
#: Mitlesen. Für lokale Entwicklung gibt es bewusst keine Ausnahme: Eine
#: Ausnahme, die man im Code findet, findet auch jemand anders.
ERLAUBTE_SCHEMATA = frozenset({"https"})

#: Länger als das ist keine Adresse mehr, sondern ein Transportmittel.
HOECHSTLAENGE = 500


def pruefen(url: str, *, aufloeser=socket.getaddrinfo) -> None:
    """Die Adresse prüfen. Wirft `ZielFehler`, wenn sie nicht taugt.

    `aufloeser` ist nur für Tests da — im Betrieb bleibt es `getaddrinfo`.
    """
    teile = urlsplit(url.strip())

    if teile.scheme not in ERLAUBTE_SCHEMATA:
        raise ZielFehler(
            "webhook:scheme_not_allowed",
            f"{teile.scheme or 'ohne Schema'} — nur HTTPS",
        )
    if not teile.hostname:
        raise ZielFehler("webhook:host_missing", "Keine Adresse angegeben")
    if teile.username or teile.password:
        # `https://user:pass@ziel/` — Zugangsdaten in der Adresse landen in
        # jedem Log, das die URL enthält, auch im Zustell-Protokoll des Kunden.
        raise ZielFehler(
            "webhook:credentials_in_url",
            "Zugangsdaten gehören nicht in die Adresse",
        )
    if len(url) > HOECHSTLAENGE:
        raise ZielFehler(
            "webhook:url_too_long", f"{len(url)} Zeichen, erlaubt {HOECHSTLAENGE}"
        )

    adresse_pruefen(teile.hostname, aufloeser=aufloeser)


def adresse_pruefen(host: str, *, aufloeser=socket.getaddrinfo) -> None:
    """Jede Adresse, auf die der Name zeigt, muss öffentlich sein.

    **Jede, nicht die erste.** Ein Name kann auf mehrere Adressen zeigen, und
    wer nur den ersten Treffer prüft, lässt einen Angreifer durch, der eine
    öffentliche und eine private hinterlegt — spätestens beim zweiten Versuch,
    wenn der Resolver anders sortiert.

    Ein Auflösungsfehler ist eine Absage, kein Durchwinken: Was wir nicht
    prüfen können, rufen wir nicht auf.
    """
    try:
        treffer = aufloeser(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as fehler:
        raise ZielFehler(
            "webhook:host_unresolvable", f"{host} ist nicht auflösbar"
        ) from fehler

    if not treffer:
        raise ZielFehler(
            "webhook:host_unresolvable", f"{host} löst auf nichts auf"
        )

    for eintrag in treffer:
        roh = eintrag[4][0]
        adresse = ipaddress.ip_address(roh)
        if nicht_erreichbar_von_aussen(adresse):
            raise ZielFehler(
                "webhook:host_not_public",
                f"{host} zeigt auf {roh} — das ist keine öffentliche Adresse",
            )


def nicht_erreichbar_von_aussen(adresse) -> bool:
    """Ist diese IP etwas, das nur von innen erreichbar ist?

    **`is_global` statt einer Aufzählung.** Die naheliegende Fassung listet
    `is_private or is_loopback or is_link_local or is_reserved or
    is_multicast or is_unspecified` auf — und übersieht `100.64.0.0/10`, den
    Adressbereich für Carrier-Grade-NAT (RFC 6598). Der ist in Pythons Sinn
    **nicht privat**, aber sehr wohl das Netz des Providers; in einem
    Rechenzentrum liegen dort reale Nachbarn. Genau dieser Fall stand in der
    ersten Fassung offen und fiel erst in der Testtabelle hier auf.

    `is_global` kennt darüber hinaus die Bereiche für Benchmarking
    (`198.18.0.0/15`) und Dokumentation (`192.0.2.0/24`) — eine Aufzählung
    müsste jede davon einzeln nachziehen.

    **Multicast bleibt trotzdem verboten.** `224.0.0.1` meldet
    `is_global=True`, weil es routbar ist. Ein Webhook an eine
    Multicast-Adresse ist gleichwohl keiner.
    """
    return not adresse.is_global or adresse.is_multicast
