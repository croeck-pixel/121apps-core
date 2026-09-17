# core-py — geteilte Backend-Regeln

> Python-Bausteine, die in allen Apps identisch gelten sollen. Beginnt bewusst
> mit **Regeln**, nicht mit Speicher-Code: die Apps legen ihre Daten
> unterschiedlich ab, aber sie sollen sich gleich *entscheiden*.

## Enthalten

| Modul | Was | Seit |
|---|---|---|
| [`refresh_rotation.py`](refresh_rotation.py) | Wie ein nicht-aktueller Refresh-Token zu bewerten ist | 31.07.2026 |
| [`session_cap.py`](session_cap.py) | Wie viele Geräte gleichzeitig angemeldet sein dürfen | 31.07.2026 |
| [`geo_country.py`](geo_country.py) | Land des Besuchers aus dem Proxy-Header statt aus einem eigenen IP-Nachschlag | 31.07.2026 |
| [`locale_resolver.py`](locale_resolver.py) | Welche Sprache und welches Land ein Besucher sieht — eine Kette statt fünf Fassungen | 05.08.2026 |
| [`text_schnitt.py`](text_schnitt.py) | Wie ein Dokument in durchsuchbare Abschnitte zerfällt | 07.08.2026 |
| [`embedding_modelle.py`](embedding_modelle.py) | Welches Embedding-Modell welche Vektorbreite hat — und ob die Zahl gemessen ist | 07.08.2026 |
| [`api_schluessel.py`](api_schluessel.py) | Format, Prüfung und Geltungsbereiche der Kunden-API-Schlüssel (Fleet-Spec §2) | 11.08.2026 |
| [`oauth_regeln.py`](oauth_regeln.py) | OAuth 2.1 + PKCE + Dynamic Client Registration für MCP-Connectors (Fleet-Spec §4.2) | 12.08.2026 |
| [`teilen_link.py`](teilen_link.py) | Teilen-Links ohne Login: Token, Ablauf, Widerruf ([Spec](../../docs/FLEET_SHARED_VIEWS_SPEC.md)) | 17.08.2026 |
| [`ordner.py`](ordner.py) | Ordner: Kardinalität, Entfernen-Entscheidung, Löschfolgen, Wurzelansicht, Rechte ([Spec](../../docs/FLEET_FOLDERS_SPEC.md)) | 30.08.2026 |
| [`platzhalter.py`](platzhalter.py) | Dass `{count}` eine Übersetzung überlebt — mechanisch, nicht per Prompt-Bitte | 01.09.2026 |
| [`rate_limit.py`](rate_limit.py) | Wie oft dieselbe Herkunft einen Auth-Endpunkt aufrufen darf | 04.09.2026 |
| [`support_zugriff.py`](support_zugriff.py) | Wann der Plattform-Support ein Konto öffnen darf: Einwilligung, Anfrage, Frist, Widerruf, Sitzungsende ([Spec](../../docs/FLEET_SUPPORT_ZUGRIFF_SPEC.md)) | 17.09.2026 |
| [`zugangs_token.py`](zugangs_token.py) | Woher das Access-Token einer Anfrage kommt — eine Antwort für Auth-Dependency UND Write-Guard ([FLEET_ADMIN_SPEC §2.2](../../docs/FLEET_ADMIN_SPEC.md#22-write-guard-pflicht--keine-impersonation-ohne)) | 17.09.2026 |

## `refresh_rotation` — warum es das gibt

In paperball-finance wertete der Refresh **jeden** nicht-aktuellen Token als
Diebstahl und widerrief daraufhin **alle** Sitzungen des Nutzers. Am 28.07.2026
erzeugte das fünf Zwangs-Logouts an einem Tag; im Audit-Log standen sechs
Diebstahls-Alarme, kein einziger echt. Zwei davon in derselben Sekunde — die
Signatur zweier paralleler Tabs.

Drei völlig legitime Fälle landen in diesem Zweig:

1. Zwei Tabs erneuern gleichzeitig
2. Retry nach Netzwerk-Aussetzer (Server hat rotiert, Antwort kam nie an)
3. Altes Cookie einer längst beendeten Sitzung

Nebenbefund: der pauschale Massenwiderruf war zugleich ein **Abmelde-Hebel** —
wer irgendeinen alten, unabgelaufenen Refresh-Token besaß, konnte den Nutzer
beliebig oft aus allen Geräten werfen.

**Die Regel:** Ein Signal, das sich nicht authentifizieren lässt, darf keine
destruktive Massenaktion auslösen. Erkennung behalten, Reaktion proportional.

| Token | Entscheidung |
|---|---|
| aktuell | `ROTATE` |
| Vorgänger, < 60 s | `ACCEPT_WITHIN_GRACE` — kein Alarm, keine zweite Rotation |
| Vorgänger, älter | `REVOKE_THIS_SESSION` — nur diese, nicht alle Geräte |
| unbekannt | `REJECT_ONLY` — protokollieren, sonst nichts anfassen |

### Benutzung

Die App ermittelt drei Tatsachen aus ihrer eigenen Speicherung und bekommt eine
Entscheidung zurück:

```python
from refresh_rotation import RefreshDecision, decide_refresh

ergebnis = decide_refresh(
    matches_current=(session is not None),
    matches_previous=(vorgaenger is not None),
    seconds_since_rotation=alter_in_sekunden,
)

if ergebnis.decision is RefreshDecision.ACCEPT_WITHIN_GRACE:
    # Neuen Access-Token ausstellen, den mitgeschickten Refresh-Token
    # UNVERAENDERT zurueckgeben und NICHT erneut rotieren.
    ...
```

### Zwei Fallen, beide real aufgetreten

**Bei `ACCEPT_WITHIN_GRACE` nicht erneut rotieren.** Sonst überholen sich zwei
Rotationen: Tab A bekommt T1, Tab B bekommt T2, das Cookie trägt am Ende den
Token, dessen Antwort zuletzt ankam — und der andere ist beim nächsten Versuch
weder aktuell noch Vorgänger. Der Fehler wäre nur verschoben.

**Nach dem Rotieren darf nichts mehr werfen.** Wenn der Endpoint den Token in
der Datenbank wechselt *und* Cookies setzt, verwirft eine Ausnahme danach das
Response-Objekt samt `Set-Cookie`. Der Server ist weiter, der Browser nicht —
und beim nächsten Versuch sieht der alte Token wie Diebstahl aus. Genau das war
in finance die **eigentliche** Ursache der Logouts (PR #80); das Karenzfenster
(PR #66) hat sie nur abgemildert. Reihenfolge: erst alles bauen, was werfen
kann, dann rotieren und Cookies setzen.

## `session_cap` — höchstens 3 Geräte, und zwar sichtbar

**Beschlossen: 3.** Arbeitsrechner + Laptop + Handy. Zwei wäre eins zu wenig —
Rechner und Handy sind schon zwei, der Laptop würde den Rechner verdrängen, und
ein zweiter Browser zählt als eigenes Gerät.

Heute ist der Zustand in drei Apps faktisch **eins**: survey, support und
aufträge führen einen einzigen `current_refresh_jti` am *User*, der Login auf
Gerät 2 überschreibt ihn. finance/news haben echte Sitzungen, aber keine Grenze.

Drei Entscheidungen, die wichtiger sind als die Zahl:

| | Regel | Warum |
|---|---|---|
| 1 | **Verdrängen statt abweisen** | „Melde dich woanders ab" sperrt genau die aus, die es nicht können — das alte Gerät steht im Büro |
| 2 | **Nach letzter Nutzung, nicht nach Alter** | Sonst fliegt der täglich genutzte Arbeitsrechner raus, weil er seit Wochen angemeldet ist, und das einmal benutzte Handy bleibt |
| 3 | **Sichtbar machen** | Eine endende Sitzung ist nicht das Problem — eine lautlos endende schon |

Punkt 3 ist Pflicht, nicht Kür: Sitzungsliste in den Einstellungen (Gerät,
letzte Nutzung, Abmelde-Knopf), Audit-Eintrag bei jeder Verdrängung, Hinweis für
die betroffene Person.

Nebeneffekt fürs Geschäft: verdrängt dieselbe Kennung ständig Sitzungen, steht
das im Audit-Log. Das ist ein brauchbareres Sharing-Signal als eine harte
Grenze, ohne legitime Nutzung zu bestrafen.

```python
from session_cap import sessions_to_evict

ergebnis = sessions_to_evict(aktive_sitzungen_des_users, keep_ids=[eigene_id])
for sitzung_id in ergebnis.to_evict:
    beenden(sitzung_id)          # widerrufen
    audit("session.evicted", …)  # protokollieren
```

## Verteilungsweg

Noch **Kopie**: das Modul ist abhängigkeitsfrei (nur stdlib) und passt als eine
Datei neben die App-Auth. Ein `pip`-Paket lohnt erst, wenn mehrere Module
zusammenkommen — dann wird `core-py` ein installierbares Paket und diese Datei
zieht mit um.

Wer kopiert, schreibt in den Kopf: *flottenweit identisch, nicht pro App
editieren.* Änderungen an der Regel gehören hierher.

## Stand je App

Siehe [`docs/ROLLOUT.md`](../../docs/ROLLOUT.md).

## `rate_limit` — warum es das gibt

Vier Apps, vier verschiedene Antworten auf dieselbe Frage, keine davon
vollständig — gemessen am 04.09.2026:

| App | Ansatz | Was fehlt |
|---|---|---|
| survey | `slowapi`, `memory://` | Zähler weg bei jedem Neustart, nicht über Replicas geteilt |
| support | `slowapi`, Redis wenn konfiguriert | 429-Meldung fest auf `"de"` — survey hatte genau diesen Fehler schon gefixt, die Kopie hat es nie erfahren |
| marketing | `slowapi`, Redis, 17 Zeilen | keine Übersetzung, ein globales Limit statt Grenzen je Endpunkt |
| aufträge | Redis-Fenster als FastAPI-Dependency | am nächsten dran, aber festes Fenster (`INCR` + `EXPIRE`) statt gleitendem |

paperball-finance und -news hatten **gar nichts** an den Auth-Endpunkten.

Dass support den Locale-Fehler trug, den survey längst behoben hatte, ist der
eigentliche Befund: eine Kopie erbt Fehler, aber keine Korrekturen.

### Was hier steht und was nicht

Das Modul spricht **weder mit Redis noch mit FastAPI** und kennt die i18n der
App nicht — die Apps benutzen synchrone und asynchrone Redis-Clients,
verschiedene IP-Helfer und verschiedene i18n. Hier steht nur, was flottenweit
gleich sein muss: die Grenzen (`LIMITS`), die Schlüsselform (`schluessel`) und
die Entscheidung (`entscheide`). Das Zähl-Rezept steht als `REDIS_REZEPT` im
Modul; die drei Redis-Aufrufe schreibt jede App in ihrem eigenen Stil.

### Benutzung

```python
from app.utils.fleet.rate_limit import entscheide, regel_fuer, schluessel

regel = regel_fuer("passwort_vergessen")
key = schluessel("passwort_vergessen", ip)

# 1. Abgelaufenes weg, dann zählen (eine Pipeline)
# 2. entscheide(...)
e = entscheide(treffer_im_fenster=anzahl, aeltester_treffer=aeltester,
               jetzt=time.time(), regel=regel)
if not e.erlaubt:
    raise HTTPException(429, detail=..., headers={"Retry-After": str(e.retry_after)})
# 3. nur jetzt nachtragen: ZADD + EXPIRE
```

### Zwei Fallen, beide real

**Der abgewiesene Versuch darf nicht mitgezählt werden.** Wer ihn mitzählt,
verlängert mit jedem Klick auf „nochmal senden" die eigene Sperre — und
`Retry-After` wird zur Lüge, weil das Fenster mitwandert.

**Bei Redis-Ausfall durchlassen, aber auf ERROR-Ebene protokollieren.** Ein
Limiter, der bei Störung sperrt, macht aus einem Redis-Ausfall einen
Totalausfall der Anmeldung. Ohne das laute Log maskiert das Durchlassen
zuverlässig den eigentlichen Ausfall (Regel #7).

## `geo_country` — warum es das gibt

Das Land des Besuchers kommt aus **einem** Nachschlag: der Host-nginx fragt die
MaxMind-Datenbank und setzt `X-Country-Code`. Er leert dabei `CF-IPCountry` und
`X-Geo-Country`, damit niemand sein Land per Header behaupten kann.

Der Baustein liest nur — und gibt `None` zurück, wenn kein Signal da ist. Genau
das ist der Punkt: paperball-news schlug selbst nach, die Datenbank lag in keinem
Image, jeder Aufruf gab still `None`, und die Zeile darunter setzte hart „DE".
Ein Besucher aus Wien galt als Deutscher, und niemand konnte es merken — es gab
weder Ausnahme noch Log noch einen Unterschied im Ergebnis.

```python
from geo_country import country_from_headers

land = country_from_headers(request.headers)   # "CH" oder None
```

`None` heißt: **kein** Länder-Signal. Nicht „Deutschland". Wer daraus etwas
ableitet, geht zur nächsten Stufe (Cookie, Sprache, Vorgabe) — sichtbar, statt
ein geratenes Land als gemessenes auszugeben.


## `locale_resolver` — warum es das gibt

Die Messung vom 28.07.2026 ([INVENTORY](../../docs/INVENTORY.md)) fand
`locale_resolver.py` in **fünf** Apps — kein einziges identisches Paar,
obwohl der Docstring überall derselbe war. Fünf Fassungen einer
Entscheidungsregel heißen: fünf Antworten auf die Frage, welche Sprache
jemand sieht. Der Fehlerfall ist dabei geräuschlos — wer die falsche Sprache
bekommt, sieht eine Seite, die für ihn fremdsprachig ist; kein Log, keine
Ausnahme, oft nicht einmal eine Beschwerde.

**Sprache und Land sind zwei Fragen, nicht eine.** Ein Deutschsprachiger in
Zürich will Deutsch, nicht Französisch. Ein Deutscher im Urlaub in Italien
will keine italienischen Preise. Deshalb zwei Ketten, und die IP entscheidet
nie über die Sprache:

| | Kette |
|---|---|
| Sprache | Cookie → `Accept-Language` → Land→Sprache → Standard |
| Land | Cookie → Land vom Proxy → Sprache→Heimatland → Standard |

Das Heimatland je Sprache ist der Teil, den man leicht weglässt — und dann
alphabetisch rät. Genau das ist am 31.07.2026 in 121assist passiert: Deutsch
landete auf `/at/deutsch`, Französisch auf `/be/francais`, Englisch auf
`/ca/english`. Formal gültige Kombinationen, alle falsch.

### Benutzung

Die App sagt einmal, was sie führt — und bekommt Antworten:

```python
from locale_resolver import Sprachraum, bestimme_land, bestimme_sprache

RAUM = Sprachraum(sprachen=("de", "en"), standard_sprache="de")

sprache = bestimme_sprache(
    cookie=request.cookies.get("locale"),
    accept_language=request.headers.get("accept-language"),
    land_vom_proxy=country_from_headers(request.headers),   # geo_country.py
    raum=RAUM,
)
land = bestimme_land(
    cookie=request.cookies.get("country"),
    land_vom_proxy=country_from_headers(request.headers),
    sprache=sprache,
    raum=RAUM,
)
```

`Sprachraum` verlangt, dass die Standardsprache in der Liste steht — sonst
liefert die Kette am Ende eine Sprache, für die es keine Texte gibt, und das
fällt erst dem Besucher auf.

Die Sprachliste kommt **aus der App**, nicht von hier: Nicht jede Anwendung
führt alle elf Sprachen der Flotte, und eine hier verdrahtete Liste würde
einer App Sprachen unterstellen, für die sie keine Texte hat. Führt eine App
eine Sprache nicht, überspringt die Kette sie sichtbar und geht zur nächsten
Stufe — statt still auf eine Pivot-Sprache zurückzufallen (Regel #7).

## `text_schnitt` + `embedding_modelle` — warum es das gibt

Vier Apps brauchen Suche über eigene Dokumente. Der Bestand am 07.08.2026:

| App | Schnitt | Embedding | Ablage |
|---|---|---|---|
| **support-app** | vollständig, tokenbasiert | fest auf `text-embedding-3-small` verdrahtet | `Vector(1536)` |
| **paperball-news** | eigen | Jina v3 (Berlin) | **JSON statt `vector`** — keine Dimensionsprüfung, kein Index |
| **marketing-app** | — | eine Aufrufstelle | — |
| **paperball.ai** | — | — | — |

Zwei verschiedene Fehler, dieselbe Ursache:

**Der Schnitt war deutsch-englisch.** Die Vorlage erkannte einen Satzanfang an
`[A-ZÄÖÜ]`. Ein polnischer Satz, der mit „Łącznie" beginnt, ein dänischer mit
„Året", ein französischer mit „État" fiel durch — in einer Flotte, die elf
Sprachen führt. Der zu lange Absatz blieb dann ungeteilt und wurde am
Tokenfenster hart abgeschnitten, mitten im Wort. Hier prüft `str.isupper()`,
das kennt das ganze Alphabet. Der Gegentest (alte Zeichenklasse einsetzen)
macht genau fünf der sieben Sprachfälle rot.

**Die Vektorbreite wurde geraten.** Sie ist die einzige Zahl im ganzen Aufbau,
die sich nachträglich nur mit vollständiger Neuberechnung ändern lässt — und
sie stand in support-app im Code, in paperball-news nirgends, und im
paperball-Katalog bei zwei Modellen gar nicht. `embedding_modelle` beantwortet
sie einmal.

`geprueft=False` heißt: Die Zahl stammt aus der Modellkarte oder der
Architektur, nicht aus einer Antwort der laufenden Schnittstelle. `fuer_spalte()`
verweigert solche Modelle — eine Modellkarte mit Tippfehler fällt sonst erst
auf, wenn schon Vektoren in der Spalte liegen.

```python
from embedding_modelle import dimension_pruefen, fuer_spalte
from text_schnitt import schneiden, tiktoken_zaehler

# Migration: Spaltenbreite — nur gemessene Modelle kommen durch.
breite = fuer_spalte("mistral", "mistral-embed")          # 1024

# Vertragstest der App: einmal einbetten, Ergebnis gegen den Katalog halten.
dimension_pruefen("mistral", "mistral-embed", antwort.data[0].embedding)

# Verarbeitung: der Tokenzähler wird hereingereicht, nicht geraten.
for abschnitt in schneiden(text, zaehler=tiktoken_zaehler()):
    ...
```

Der Zähler ist Pflicht und hat **keinen** Rückfall auf Zeichenzählung
(Regel #7): Ein Schnitt, der still ein anderes Maß benutzt, erzeugt zu lange
Abschnitte, die der Anbieter kommentarlos kürzt. Der gekürzte Teil ist danach
nicht auffindbar, und niemand sieht einen Fehler.

`cl100k_base` ist das Maß der OpenAI-Modelle; für Jina, Mistral oder Cohere
eine Näherung. Für die Schnittgröße reicht das. **Für die Abrechnung nicht** —
dort gilt, was der Anbieter meldet, nie eine eigene Schätzung.


## `api_schluessel` — warum es das gibt

Die Fleet-Spec (`FLEET_MCP_API_SPEC.md`, marketing-Repo §2) hat **fünf Apps
mit fünf Fassungen** gefunden:

| App | Format | Rechte | Ablauf |
|---|---|---|---|
| support, survey | `sk_live_` / `sk_mcp_` | freie Permissions-Zeichenketten | `expires_at` |
| aufträge | `auf_` | rollengebunden | **keiner** |
| finance | `sk_mcp_` | Scopes + Audit | `expires_at`, `revoked_at` |
| marketing | — | — | — |

Jede war einmal ein „machen wir schnell hier". Der Kanon verlangt **einen**
Schlüsseltyp je App für REST *und* MCP — eine Verwaltung, zwei Zugänge.

**Hier steht die Logik, nicht die Speicherung.** Wie ein Schlüssel aussieht,
wie er gehasht und verglichen wird, ob ein Geltungsbereich reicht, ob ein
rotierter Vorgänger noch trägt. Die Tabellen legen die Apps selbst an — sie
sollen sich gleich *entscheiden*, nicht gleich ablegen.

```python
from api_schluessel import erzeugen, praefix_aus, passt, scope_erfuellt

neu = erzeugen("pba")          # sk_pba_a1b2c3d4_<32 Zeichen>
speichern(praefix=neu.praefix, hash=neu.hash)
einmal_anzeigen(neu.klartext)  # danach nie wieder

# Beim Aufruf: Präfix nachschlagen, Hash vergleichen, Bereich prüfen.
zeile = laden(praefix_aus(vorgelegt))
if passt(vorgelegt, zeile.hash) and scope_erfuellt("documents:read", zeile.scopes):
    ...
```

Vier Entscheidungen, die im Code begründet sind:

**Der Präfix ist Suchspalte UND Teil des Geheimnisses.** Ohne ihn müsste jede
Anfrage jeden Schlüssel der Datenbank hashen und vergleichen.

**SHA-256, nicht bcrypt.** Teure Hashes schützen kurze, erratbare Passwörter.
Ein Schlüssel hat 192 Bit Zufall — er ist nicht zu raten, und ein teurer Hash
machte nur jede API-Anfrage langsam.

**Der Sammel-Lesescope deckt kein Schreiben.** Kein `*`, kein Präfix-Vergleich:
`documents:` zu haben und daraus `documents:write` abzuleiten wäre bequem und
macht aus einem Lese-Zugang unbemerkt einen Vollzugriff. Die Gegenprobe dazu
ist ein eigener Test.

**Ein Schlüssel kann nie mehr als sein Ersteller.** Das hatten vier von fünf
Apps nicht: Wird jemand deaktiviert oder verliert die Rolle, hört sein
Schlüssel auf zu wirken — sonst überlebt ein Zugang den Zugang.


## `oauth_regeln` — warum es das gibt

Ein API-Schlüssel reicht für n8n und für ein Skript. Für **claude.ai als
Custom Connector** reicht er nicht: Dort klickt ein Mensch auf „Verbinden",
und dahinter muss OAuth 2.1 mit Dynamic Client Registration stehen — der
Client registriert sich selbst, unaufgefordert, ohne dass jemand von uns
etwas eingetragen hätte. Die Fleet-Spec (§4.2) verlangt das ausdrücklich als
wiederverwendbares Modul: „einmal richtig, viermal portieren, nicht fünfmal
erfinden."

**Hier stehen die Entscheidungen, nicht die Endpunkte.** Dieselbe Teilung wie
bei `api_schluessel`: Was eine gültige Rücksprungadresse ist, wann ein Code
verfällt, ob ein Prüfwert passt, wie weit ein Geltungsbereich reichen darf.
Die Endpunkte, die Speicherung und der Zustimmungsdialog gehören in die App —
sie unterscheiden sich, die Regeln nicht.

```python
from oauth_regeln import (
    client_metadaten_pruefen, rueckspruch_erlaubt,
    code_erzeugen, code_gueltig, pruefwert_passt, scopes_eingrenzen,
)

# /oauth/register (RFC 7591) — offen, deshalb streng geprüft.
client = client_metadaten_pruefen(await request.json())

# /oauth/authorize — vor dem Zustimmungsdialog.
if not rueckspruch_erlaubt(params.redirect_uri, client.redirect_uris):
    return fehlerseite()          # NICHT dorthin zurückleiten
bereiche = scopes_eingrenzen(angefragt=..., erlaubt=..., zugestimmt=...)
code = code_erzeugen()            # gespeichert wird nur code.hash

# /oauth/token — beim Einlösen.
if code_gueltig(...) and pruefwert_passt(verifier=..., challenge=...):
    ...
```

Vier Entscheidungen, die im Code begründet sind — es sind genau die vier
Stellen, an denen OAuth aufbricht, und keine davon fällt im Betrieb auf:

**Die Rücksprungadresse wird exakt verglichen, nach Normalisierung.** Kein
Präfix, keine Teilzeichenkette, kein Platzhalter. Wer „beginnt mit" prüft,
lässt `https://claude.ai.angreifer.test/…` durch und verschenkt den
Autorisierungscode. Normalisiert wird trotzdem, weil `https://Claude.AI:443/cb`
dieselbe Adresse ist wie `https://claude.ai/cb` und der Kunde sonst stundenlang
sucht. Fünf Angriffsschreibweisen stehen als Gegenprobe im Test.

**`plain` wird abgelehnt, nicht durchgewinkt.** OAuth 2.1 hat die Methode
gestrichen, weil die Challenge dort der Verifier ist — sie schützt gegen
niemanden, der den Autorisierungsaufruf mitliest. Ein Server, der `plain`
annimmt, hat PKCE eingebaut und nicht eingeschaltet: Es genügt,
`code_challenge_method` umzubiegen.

**Ein Code gilt einmal und eine Minute.** Zweimal wäre ein zweiter Zugang;
lange wäre ein Zugang für jeden, der die Browser-Historie sieht. RFC 6749
erlaubt zehn Minuten — das ist die Obergrenze für langsame Menschen, nicht für
Maschinen.

**Aus der Registrierung wird nur das Geprüfte übernommen.** DCR ist ein offener
Endpunkt; jeder darf sich eintragen. Was durchkommt, steht später in einem
Zustimmungsdialog vor einem Menschen, der dem Namen glaubt — deshalb kein
Zeilenumbruch im `client_name` (der kann dort etwas anderes vortäuschen, als er
ist) und kein `http` außer auf Loopback (Claude Desktop hat kein Zertifikat,
ein fremder Host hätte den Code im Klartext).

## `gutschein_regeln.py` — wann ein Code gilt, was er wert ist

Regel und Begründung: [`docs/FLEET_CODES_SPEC.md`](../../docs/FLEET_CODES_SPEC.md).

Wie bei `refresh_rotation`: **das Modul besitzt die Regel, die App besitzt ihre
Tabellen.** Die Codes-Tabelle hängt an der `workspaces`-Tabelle der jeweiligen
App, und die heisst überall anders — survey kennt Mandanten, aufträge kennt
Auftragnehmer, paperball kennt Organisationen. Ein gemeinsames Speichermodul
wäre in jeder App ein bisschen falsch.

Die Entscheidungen dagegen sind überall dieselben, und sie sind die Stelle, an
der Geld entsteht:

| Funktion | Entscheidet |
|---|---|
| `pruefen(stand, …)` | ob der Code hier und jetzt gilt — mit Maschinencode als Grund (Regel #23) |
| `coupon_dauer(interval, perioden)` | welche Stripe-Coupon-Dauer daraus wird |
| `beteiligung_ende(erstkauf, …)` | wann die Beteiligung an diesem Kunden endet |
| `provision(basis, satz)` | wie viel — **kaufmännisch** gerundet |
| `reifezeitpunkt` / `ist_auszahlbar` | ab wann auszahlbar |

Fünf Fallen, die dieses Modul für alle sieben Apps auf einmal schliesst:

1. **Leere Einschränkungsliste heisst „überall", nicht „nirgends".** Ein
   vergessenes `if not erlaubte` und kein Code gilt mehr — überall gleichzeitig.
2. **Der letzte Tag des Einlösefensters zählt noch**, sonst endet jede Kampagne
   einen Tag früher als angekündigt.
3. **Eine Periode jährlich ist `once`, nicht `repeating`.** Sonst fällt die
   zweite Jahresrechnung exakt auf den Ablauf des Fensters, und ob sie noch
   rabattiert wird, hängt an Sekunden.
4. **Kaufmännisch runden, nicht bankers.** Pythons Standard rundet 0,5 zur
   geraden Zahl; über tausend Rechnungen landet die halbe Provision
   systematisch beim Haus.
5. **Die eigene, schon bestehende Einlösung umgeht Neukunden-Sperre und
   Kontingent** — sonst scheitert jeder Netzwerk-Retry desselben Kunden.

Nur stdlib. Kein SQLAlchemy, kein Stripe, keine App-Importe — testbar ohne
Datenbank, und genau deshalb mit **einem** Testsatz für die ganze Flotte
(`tests/test_gutschein_regeln.py`, 22 Fälle).



## `webhook_ziel.py` — wohin ein Webhook gehen darf

Die Lücke in §6 der Fleet-Spec. Der Kanon beschreibt Signatur, Wiederholung
und Abschaltung — die **Zieladresse** kommt darin nicht vor, und die ist das
gefährliche Stück: Sie gibt der Kunde vor, aufgerufen wird sie von unserem
Server, aus dem Rechenzentrum heraus, hinter jeder Firewall.

Das ist die Lehrbuchform von Server-Side Request Forgery. Der Angriff besteht
darin, **dass** wir die Adresse aufrufen, nicht darin, was zurückkommt:

| Adresse | Was sie hergibt |
|---|---|
| `169.254.169.254` | Metadaten des Hosters, bei vielen samt Zugangsdaten |
| `localhost:8000/api/admin/…` | die eigene Verwaltung, von innen, ohne Anmeldung davor |
| `db:5432` | Portscan über Antwortzeiten, gratis |

| Funktion | Entscheidet |
|---|---|
| `pruefen(url, …)` | Schema, Zugangsdaten in der URL, Länge, und dann jede aufgelöste Adresse |
| `adresse_pruefen(host, …)` | ob **jede** IP hinter dem Namen öffentlich ist |
| `nicht_erreichbar_von_aussen(ip)` | ob eine einzelne IP nur von innen erreichbar ist |

Vier Fallen, die das Modul für alle Apps auf einmal schliesst:

1. **Nur die erste aufgelöste Adresse prüfen.** Ein Name darf auf mehrere IPs
   zeigen. Wer eine öffentliche und eine private hinterlegt, kommt spätestens
   beim zweiten Versuch durch — wenn der Resolver anders sortiert.
2. **Nur beim Anlegen prüfen.** Zwischen Anlegen und Zustellen kann ein
   DNS-Eintrag umziehen; das ist der Rebinding-Angriff. Ein Türsteher, der nur
   beim Einlass hinsieht, hält ihn nicht auf — deshalb **vor jedem Versand**
   erneut.
3. **`is_private` statt `is_global`.** Die naheliegende Aufzählung
   (`is_private or is_loopback or is_link_local or is_reserved or
   is_multicast or is_unspecified`) sieht vollständig aus und lässt
   `100.64.0.0/10` durch — Carrier-Grade-NAT (RFC 6598), in Pythons Sinn nicht
   privat, im Rechenzentrum aber das Providernetz mit realen Nachbarn. Genauso
   `198.18.0.0/15` (Benchmarking). Aufgefallen ist das erst in der
   Testtabelle hier, **nachdem** die Aufzählung in paperball schon
   ausgeliefert war.
4. **Ein Auflösungsfehler als Durchwinken.** Was wir nicht prüfen können,
   rufen wir nicht auf.

Fehlercodes sind Maschinencodes (Regel #23): `webhook:scheme_not_allowed`,
`webhook:host_missing`, `webhook:credentials_in_url`, `webhook:url_too_long`,
`webhook:host_unresolvable`, `webhook:host_not_public`. Die Sätze dazu gehören
in die Sprachdateien der App — in **allen** Sprachen (Regel #7).


## `platzhalter.py` — warum es das gibt

`t('watchlist.count', '{count} Wertpapiere', {count: 3})` ersetzt streng nach
**Namen**. Ein Übersetzer sieht in `{count}` aber ein Wort und übersetzt es mit.
Danach greift die Ersetzung nie mehr, und der Nutzer liest wörtlich
„{compte} cours" statt „2.417 cours".

Gemessen am 01.09.2026 auf der Produktion von paperball-finance: **1949 Zeilen
in neun Sprachen** waren so kaputt.

    fr {compte}   nl {geteld}   pl {liczba}   pt {contagem}
    es {contar}   no {telling}  da {antal}    it {conteggio}

**Die Ursache war eine Zuständigkeitslücke, kein Tippfehler.** Der E-Mail-Pfad
schützte seine Platzhalter von Anfang an mechanisch — `{x}` →
`@@PLACEHOLDER_x@@` → zurück. Der Oberflächen-Pfad im selben Repo hatte
stattdessen einen Satz im Prompt stehen: *„Preserve any placeholders like
{count}"*. Beide Pfade waren von denselben Leuten gebaut, im selben Verzeichnis,
mit demselben Ziel. Der eine hat es garantiert, der andere darum gebeten — und
der Unterschied steht in der Zahl oben.

Deshalb liegt der Baustein hier: **paperball-news hat exakt denselben
Übersetzungspfad**, denselben halben Schutz und dieselbe `t()`-Mechanik im
Frontend. Ohne diesen Baustein wäre die Behebung dort Kopie Nummer zwei
gewesen (Regel #24).

### Drei Dinge, die den Fehler so lange getragen haben

**Deutsch war sauber — und geprüft wird auf Deutsch.** Der Fehler sitzt
naturgemäß in den Sprachen, die niemand im Team liest. Eine Stichprobe auf der
Pivot-Sprache beweist bei i18n gar nichts. Englisch sah dabei ebenfalls sauber
aus und war es nicht: `${favoritesCount}` wurde zu `${favouritesCount}` —
dieselbe Mechanik, nur in britischer Rechtschreibung.

**Kaputt heißt nicht laut.** Ein `{compte}` wirft keine Ausnahme, füllt kein
Log und bricht kein Rendering. Es steht einfach da.

**Der Prompt sah wie eine Lösung aus.** Regel 3 im Prompt war explizit, korrekt
formuliert und stand seit dem ersten Tag da. Wer den Code las, sah einen
behandelten Fall.

### Benutzung

```python
from platzhalter import pruefen, schuetzen, wiederherstellen

antwort = uebersetzen(schuetzen(quelltext), ziel="fr")   # Anbieter sieht @@PLACEHOLDER_count@@
text = pruefen(quelltext, wiederherstellen(antwort), key, "fr")
```

Beides gehört zusammen: `schuetzen()` allein ist ein Schutz ohne Gegenprobe.
`pruefen()` vergleicht die Platzhalter-**Namen** (nicht ihre Reihenfolge — beim
Übersetzen darf sich die Stellung im Satz ändern) und gibt bei Abweichung den
Quelltext zurück, mit ERROR im Log. Kein stiller Rückfall (Regel #7): sichtbarer
Quelltext ist besser als ein `{compte}`, das nie ersetzt wird — aber niemand
soll es erst am Kunden merken.

**Warum dieses Modul protokolliert, wo die anderen nur entscheiden:** Der
Rückfall ist hier die Regel selbst, und ein stiller Rückfall wäre genau der
Fehler, den der Baustein verhindern soll. Wer nur die Entscheidung braucht,
ruft `platzhalter_von()` zweimal und vergleicht.

### Der Unterstrich in der Schutzhülle ist kein Zufall

`@@PLACEHOLDER_count@@` enthält das englische Wort `count` weiterhin im
Klartext. Dass ein Übersetzer es trotzdem nicht anfasst, liegt am Unterstrich:
für eine Wortgrenze ist `_count@` kein eigenes Wort. Der Testsatz friert genau
das ein — mit einem absichtlich gierigen Übersetzer, der jedes Wort ersetzt,
das er kennt (`tests/test_platzhalter.py`, 35 Fälle).


## `support_zugriff` und `zugangs_token` — warum es das gibt

In paperball-finance (PR #604, 17.09.2026) darf der Plattform-Support ein Konto
nur noch mit Einwilligung des Nutzers öffnen. Dabei fiel auf, dass die
Schreibsperre der Impersonation seit der Cookie-Umstellung **nie** gegriffen
hatte: Sie las das Token nur aus dem `Authorization`-Header, die
Auth-Dependency auch aus dem Cookie. Der Flottenabgleich danach: survey und
support haben gar keine Sperre, paperball-news hat eine und registriert sie
nicht, aufträge sperrt den eigenen Stop-Endpunkt — und keine App außer finance
fragt den Nutzer.

**Die Regel des Moduls `support_zugriff`:** ohne laufende Freigabe keine
Impersonation; Anfrage und Selbst-Erteilung sind eine Zeile; höchstens eine
offene Anfrage oder laufende Freigabe; die Sitzung endet spätestens mit der
Freigabe; Widerruf wirkt sofort; im Zweifel zu. Speicher und Router bleiben in
der App, die Entscheidung kommt von hier:

```python
from apps121_core.support_zugriff import darf_impersonieren, laeuft, sitzungsende

freigabe_laeuft = zeile is not None and laeuft(
    status=zeile.status, gueltig_bis=zeile.valid_until, jetzt=jetzt
)
if (fehler := darf_impersonieren(freigabe_laeuft=freigabe_laeuft)) is not None:
    audit("impersonate.denied", reason=fehler.value)
    raise HTTPException(403, detail=user_error(f"errors.support_access.{fehler.value}", admin))
ablauf = sitzungsende(gueltig_bis=zeile.valid_until, gewuenscht=jetzt + IMPERSONATION_TTL)
```

**Die Regel des Moduls `zugangs_token`:** Wer ein Token ansieht, fragt
`token_der_anfrage(request.headers.get("authorization"), request.cookies.get(ACCESS_COOKIE))`
— die Dependency genauso wie jede Middleware. Header vor Cookie; ein Header,
der kein Bearer ist, verdeckt das Cookie nicht.

**Warum kein geteilter Guard-Test als Datei:** Die fünf Sperren unterscheiden
sich in Token-Claims (`imp`, `impersonator`, `imp_session_uuid`),
Cookie-Namen, Präfixen und Blocktiefe; ein Test, der das alles über
Platzhalter abfragt, wäre in jeder App halb ausgefüllt und damit still grün.
Geteilt ist stattdessen die Funktion, die den Fehler unmöglich macht, plus die
Pflicht aus FLEET_ADMIN_SPEC §2.2 Punkt 6: vier Fälle gegen die **ganze** App.
