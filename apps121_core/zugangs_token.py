"""Woher das Access-Token einer Anfrage kommt — EINE Antwort für alle Leser.

Spec: ``docs/FLEET_ADMIN_SPEC.md`` §2.2 Punkt 2.

Warum es das gibt
-----------------
In paperball-finance las die Schreibsperre der Impersonation das Token nur aus
dem ``Authorization``-Header. Seit der Umstellung auf HttpOnly-Cookies schickte
das Frontend keinen mehr — die Auth-Dependency las das Cookie und ließ die
Anfrage herein, die Sperre sah „kein Token, keine Impersonation“ und ließ sie
ebenfalls durch. Schreibsperren UND Aktionsprotokoll griffen nie, obwohl
Oberfläche und Einwilligungstext beides zusagten. Kein Test war rot: jeder
Test der Sperre schickte einen Header.

Der Fehler ist keine falsche Zeile, sondern **zwei Stellen, die dieselbe Frage
beantworten**. Deshalb gibt es hier keine Sperre, sondern die Frage selbst: die
Auth-Dependency UND jede Middleware, die ein Token ansieht (Write-Guard,
Protokoll, Rate-Limit je Nutzer), rufen :func:`token_der_anfrage`. Dann können
sie nicht mehr auseinanderlaufen.

Reihenfolge: Header vor Cookie. Ein ausdrücklich gesetzter Header ist die
Absicht des Aufrufers (API-Client, Test, MCP-Schlüssel); das Cookie schickt der
Browser ungefragt mit.

Nur stdlib — die App reicht Header- und Cookie-Wert herein, das Modul kennt
weder Starlette noch FastAPI.
"""

from __future__ import annotations

__all__ = ["token_der_anfrage"]


def token_der_anfrage(authorization: str | None, cookie: str | None) -> str | None:
    """Das Access-Token aus ``Authorization: Bearer …`` oder, sonst, dem Cookie.

    ``authorization`` ist der rohe Header-Wert, ``cookie`` der Wert des
    Access-Token-Cookies der App (Name pro App, z. B. ``pb_access_token``).
    Ein Header, der kein Bearer ist (``Basic …``), zählt nicht als Token — das
    Cookie wird dann trotzdem gelesen. Leere Werte sind kein Token.
    """
    if authorization:
        teile = authorization.strip().split(None, 1)
        if len(teile) == 2 and teile[0].lower() == "bearer" and teile[1].strip():
            return teile[1].strip()
    if cookie and cookie.strip():
        return cookie.strip()
    return None
