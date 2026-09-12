"""Wie oft darf dieselbe Herkunft einen Auth-Endpunkt aufrufen?

Flottenweit identische Regel. Beschlossen am 04.09.2026.

Warum es die Regel überhaupt braucht
------------------------------------
Auth-Endpunkte sind die billigste Angriffsfläche einer App, und drei der
Angriffe brauchen keinerlei Zugangsdaten:

* **Brute-Force** gegen ``/login`` — durchprobieren, bis ein Passwort passt.
* **Konto-Aufzählung** gegen ``/register`` und ``/forgot-password`` — wer
  unterschiedliche Antworten für „Adresse bekannt" und „unbekannt" bekommt,
  liest die Nutzerliste aus. Auch wer identisch antwortet, verrät sich über
  die Laufzeit.
* **E-Mail-Bombing** über ``/forgot-password`` und ``/resend-verification``
  — der Angreifer schickt fremde Post, auf Kosten des Zustellrufs der Domain.
  Das ist der teuerste der drei: eine verbrannte Absender-Reputation trifft
  jede Mail der App, nicht nur die missbrauchte.

Vier Apps hatten dafür vier verschiedene Antworten, keine davon vollständig:
zweimal ``slowapi`` mit ``memory://`` (Zähler weg bei jedem Neustart, nicht
über Replicas geteilt), einmal ``slowapi`` mit Redis aber ohne Übersetzung,
einmal ein handgeschriebenes Fenster. Kopie Nummer fünf wäre die falsche
Antwort gewesen.

Die Regel
---------
**Je Herkunft und Bucket ein gleitendes Fenster.** Die Grenzen stehen in
``LIMITS`` und werden HIER geändert, nicht pro App.

Vier Entscheidungen, die wichtiger sind als die Zahlen:

1. **Gleitendes Fenster, kein festes.** Ein festes Fenster (INCR + EXPIRE)
   lässt an der Fenstergrenze das Doppelte durch: fünf Versuche um 09:59:59,
   fünf weitere um 10:00:00. Bei „3 Mails pro Stunde" sind das sechs Mails in
   einer Sekunde — genau der Fall, den die Grenze verhindern soll.

2. **Der abgewiesene Versuch zählt nicht mit.** Wer über der Grenze ist,
   bekommt keinen neuen Eintrag ins Fenster. Sonst verlängert jeder Klick auf
   „nochmal senden" die eigene Sperre, und ``Retry-After`` wird zur Lüge.

3. **Bei Redis-Ausfall durchlassen, aber laut protokollieren.** Ein
   Rate-Limiter, der bei Störung sperrt, macht aus einem Redis-Ausfall einen
   Totalausfall der Anmeldung. Das Durchlassen ist bewusst — und muss auf
   ERROR-Ebene ins Log, sonst maskiert es den Redis-Ausfall (Regel #7).

4. **Die 429-Meldung ist übersetzt und nennt eine Wartezeit.** „Too many
   requests" ohne Zahl liest sich wie ein Defekt; die Person klickt weiter und
   verlängert nichts, wundert sich aber. ``Retry-After`` gehört in den Header
   UND in den Satz.

Was dieses Modul NICHT tut
--------------------------
Es spricht weder mit Redis noch mit FastAPI und kennt die i18n der App nicht.
Die Apps benutzen unterschiedliche Redis-Clients (synchron und asynchron),
unterschiedliche IP-Helfer und unterschiedliche i18n — hier steht nur, was
flottenweit gleich sein muss: die Grenzen, die Schlüsselform und die
Entscheidung. Das Rezept für die drei Redis-Aufrufe steht in ``REDIS_REZEPT``.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Herkunft, wenn die App keine IP ermitteln kann. Ein fester Wert ist besser
#: als gar keine Begrenzung: dann teilen sich alle unbekannten Aufrufer ein
#: Kontingent, statt unbegrenzt durchzukommen.
UNBEKANNTE_HERKUNFT = "unbekannt"

#: Präfix aller Schlüssel. Getrennt von anderen Redis-Nutzungen der App, damit
#: ein `FLUSHDB` auf Sperren gezielt möglich ist, ohne Sitzungen zu treffen.
SCHLUESSEL_PRAEFIX = "rl"


@dataclass(frozen=True)
class Regel:
    """Wie viele Aufrufe in welchem Zeitraum."""

    limit: int
    fenster_sekunden: int

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit muss mindestens 1 sein")
        if self.fenster_sekunden < 1:
            raise ValueError("fenster_sekunden muss mindestens 1 sein")


#: Die flottenweiten Grenzen. Je Bucket eine Regel.
#:
#: Die Zahlen sind an echtem Verhalten ausgerichtet, nicht am Angreifer: wer
#: sein Passwort vergisst, tippt es zwei-, dreimal falsch, nicht elfmal. Wer
#: eine Bestätigungsmail nicht bekommt, klickt zweimal auf „nochmal senden" und
#: schaut dann in den Spam-Ordner. Grenzen, die legitimes Verhalten treffen,
#: werden irgendwann hochgesetzt und schützen dann gar nichts mehr.
LIMITS: dict[str, Regel] = {
    # Anmelden: großzügig, weil Tippfehler + mehrere Geräte + Autofill-Versuche
    # zusammenkommen. Fängt das massenhafte Durchprobieren, nicht den Alltag.
    # Ersetzt KEINE Konto-Sperre nach Fehlversuchen — die zählt je Konto, das
    # hier zählt je Herkunft. Ein Angreifer mit einer Passwortliste gegen 1000
    # Konten löst keine einzige Konto-Sperre aus, wohl aber diese Grenze.
    "login": Regel(limit=10, fenster_sekunden=60),
    # Registrieren: fünf Konten in zehn Minuten aus einer Herkunft ist bereits
    # viel. Bremst Konto-Aufzählung („ist die Adresse vergeben?") spürbar.
    "register": Regel(limit=5, fenster_sekunden=600),
    # Passwort vergessen: verschickt Post an eine FREMDE Adresse. Deshalb die
    # strengste Grenze der Liste — hier zahlt der Zustellruf der Domain.
    "passwort_vergessen": Regel(limit=3, fenster_sekunden=3600),
    # Bestätigung erneut senden: dieselbe Begründung wie oben.
    "bestaetigung_erneut": Regel(limit=3, fenster_sekunden=3600),
    # Passwort zurücksetzen: rät an einem Token. Streng, weil ein Treffer die
    # volle Kontoübernahme ist.
    "passwort_zuruecksetzen": Regel(limit=5, fenster_sekunden=600),
    # E-Mail bestätigen: rät ebenfalls an einem Token, aber ein Treffer bestätigt
    # nur eine Adresse. Etwas lockerer, weil Mail-Clients Links vorab abrufen und
    # eine zu strenge Grenze echte Bestätigungen verschluckt.
    "email_bestaetigen": Regel(limit=10, fenster_sekunden=600),
    # Magic-Link einlösen: rät an einem Token, und ein Treffer ist die volle
    # Anmeldung — also dieselbe Strenge wie das Zurücksetzen. Mail-Clients rufen
    # solche Links vorab ab, deshalb nicht schärfer als 5.
    "magic_login": Regel(limit=5, fenster_sekunden=600),
    # SSO-Einstieg (OAuth-Redirect, SAML-Request): billig für den Aufrufer, aber
    # nicht gratis für uns — jeder Aufruf legt einen State in Redis an und fragt
    # die Organisation aus der DB. Locker gehalten, weil ein Mensch beim Anmelden
    # durchaus mehrfach hin- und herspringt (Konto wechseln, Zurück-Taste).
    "sso_start": Regel(limit=20, fenster_sekunden=60),
}


@dataclass(frozen=True)
class Entscheidung:
    """Was die App mit diesem Aufruf tun soll."""

    erlaubt: bool
    #: Wie viele Aufrufe nach diesem noch frei sind. Nie negativ.
    verbleibend: int
    #: Sekunden bis zum nächsten freien Versuch. 0, wenn erlaubt.
    #: Gehört in den ``Retry-After``-Header UND in die Meldung.
    retry_after: int


def schluessel(bucket: str, herkunft: str) -> str:
    """Redis-Schlüssel für Bucket + Herkunft.

    Flottenweit dieselbe Form, damit ein Blick in Redis in jeder App gleich
    aussieht und Betriebsskripte über alle Apps funktionieren.
    """
    return f"{SCHLUESSEL_PRAEFIX}:{bucket}:{herkunft or UNBEKANNTE_HERKUNFT}"


def regel_fuer(bucket: str) -> Regel:
    """Die Regel eines Buckets. Unbekannter Bucket ist ein Programmierfehler.

    Bewusst kein stiller Standardwert (Regel #7): ein vertippter Bucket-Name
    würde sonst lautlos die falsche — womöglich gar keine — Grenze anwenden,
    und das fiele erst beim Vorfall auf.
    """
    try:
        return LIMITS[bucket]
    except KeyError:
        bekannt = ", ".join(sorted(LIMITS))
        raise KeyError(f"Unbekannter Rate-Limit-Bucket {bucket!r}. Bekannt: {bekannt}") from None


def entscheide(
    *,
    treffer_im_fenster: int,
    aeltester_treffer: float | None,
    jetzt: float,
    regel: Regel,
) -> Entscheidung:
    """Darf dieser Aufruf durch?

    ``treffer_im_fenster``
        Anzahl der bereits gezählten Aufrufe im Fenster — **ohne** den
        gerade laufenden.
    ``aeltester_treffer``
        Zeitstempel (Unix-Sekunden) des ältesten Eintrags im Fenster, oder
        ``None``, wenn das Fenster leer ist. Daraus entsteht ``retry_after``:
        frei wird der Platz, sobald dieser Eintrag aus dem Fenster fällt.
    ``jetzt``
        Aktueller Zeitstempel in Unix-Sekunden.

    Die App zählt vorher, entscheidet hier, und trägt den Aufruf **nur bei
    ``erlaubt``** nach (Entscheidung 2 im Modulkopf).
    """
    if treffer_im_fenster < regel.limit:
        return Entscheidung(
            erlaubt=True,
            verbleibend=regel.limit - treffer_im_fenster - 1,
            retry_after=0,
        )

    if aeltester_treffer is None:
        # Voll, aber kein Zeitstempel bekannt — dann ist das ganze Fenster die
        # ehrlichste Auskunft. Sollte nicht vorkommen; lieber zu lang warten
        # lassen als eine erfundene kurze Zahl nennen.
        wartezeit = float(regel.fenster_sekunden)
    else:
        wartezeit = (aeltester_treffer + regel.fenster_sekunden) - jetzt

    # Aufrunden und mindestens 1: eine „0" im Retry-After-Header liest sich als
    # „sofort nochmal", und der nächste Versuch liefe direkt wieder ins 429.
    return Entscheidung(
        erlaubt=False,
        verbleibend=0,
        retry_after=max(1, _aufrunden(wartezeit)),
    )


def _aufrunden(sekunden: float) -> int:
    ganz = int(sekunden)
    return ganz if ganz == sekunden else ganz + 1


#: Wie die App zählt — flottenweit dasselbe Rezept, damit die Zahlen in
#: ``LIMITS`` überall dasselbe bedeuten.
#:
#: Drei Aufrufe, die ersten beiden in EINER Pipeline (Redis führt sie
#: zusammenhängend aus):
#:
#:   1. ``ZREMRANGEBYSCORE key -inf (jetzt - fenster)``  — Abgelaufenes weg
#:   2. ``ZCARD key`` und ``ZRANGE key 0 0 WITHSCORES``  — Anzahl + Ältester
#:      -> ``entscheide(...)``
#:   3. nur wenn erlaubt: ``ZADD key jetzt <eindeutig>`` + ``EXPIRE key fenster``
#:
#: Der ``EXPIRE`` bei jedem Eintrag ist kein Versehen: er hält den Schlüssel am
#: Leben, solange Verkehr da ist, und lässt ihn danach von selbst verschwinden.
#: Ohne ihn bliebe je Herkunft ein Schlüssel für immer stehen.
#:
#: Das Mitglied im Sortiersatz muss eindeutig sein (Zeitstempel + Zufall),
#: sonst überschreiben zwei Aufrufe in derselben Millisekunde einander und
#: einer wird nicht gezählt.
REDIS_REZEPT = "ZREMRANGEBYSCORE -> ZCARD + ZRANGE 0 0 -> entscheide -> ZADD + EXPIRE"
