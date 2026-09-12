"""Land aus dem Reverse-Proxy-Header lesen — nicht aus der IP.

Der Host-nginx schlägt das Land einmal zentral in der MaxMind-Datenbank nach
(`conf.d/geoip.conf` → `$geo_country`) und reicht es als `X-Country-Code`
weiter. Er leert dabei `CF-IPCountry` und `X-Geo-Country`, damit niemand sein
Land per Header vortäuschen kann.

Warum nicht in der App nachschlagen
-----------------------------------
paperball-news hatte genau das versucht: `geoip2` im Backend, Pfadliste zur
`.mmdb`, Lookup je Anfrage. Die Datenbank lag nie im Image — jeder Aufruf gab
still `None` zurück und der Code darüber setzte hart „DE". Besucher aus Wien
oder Zürich galten monatelang als Deutsche, ohne dass irgendwo etwas ausschlug.

Ein Nachschlagen je App braucht die Datei, ihre Aktualisierung und den
korrekten Client-IP-Aufbau (hinter dem Proxy steht in `request.client.host` der
Proxy) — dreimal Gelegenheit, es falsch zu machen. Der Proxy hat all das schon.

Kein Rückfall auf eine eigene Auflösung: fehlt der Header, gibt es kein
Länder-Signal. Die aufrufende Kette geht dann zur nächsten Stufe über (Cookie,
Sprache, Default) — sichtbar und nachvollziehbar statt heimlich geraten.
"""
from __future__ import annotations

from typing import Iterable, Mapping

#: Reihenfolge = Vertrauensreihenfolge. `x-country-code` setzt unser eigener
#: nginx; die beiden anderen stammen aus Cloudflare-Setups und werden von ihm
#: geleert. Ein Client, der sie trotzdem schickt, kommt hier nie durch — der
#: Proxy hat sie vorher überschrieben.
COUNTRY_HEADERS: tuple[str, ...] = ("cf-ipcountry", "x-country-code", "x-geo-country")

#: nginx liefert für unbekannte IPs den Leerstring, Cloudflare „XX" (unbekannt)
#: und „T1" (Tor). Alle drei heißen: kein Signal.
_KEIN_SIGNAL = frozenset({"", "XX", "T1"})


def country_from_headers(
    headers: Mapping[str, str], *, header_names: Iterable[str] = COUNTRY_HEADERS
) -> str | None:
    """ISO-3166-1 alpha-2 aus den Proxy-Headern, sonst None.

    `headers` muss unabhängig von Groß-/Kleinschreibung nachschlagen — bei
    Starlette/FastAPI (`request.headers`) und `requests` ist das der Fall.
    """
    for name in header_names:
        wert = (headers.get(name) or "").strip().upper()
        if len(wert) == 2 and wert.isalpha() and wert not in _KEIN_SIGNAL:
            return wert
    return None
