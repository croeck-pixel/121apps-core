"""Ordner: wie eine App Dinge gruppiert — und was beim Entfernen passiert.

Umsetzung von `docs/FLEET_FOLDERS_SPEC.md`. Der Anlass ist eine Messung vom
30.08.2026: nutzer-anlegbare Ordner gibt es **viermal in drei Apps**, im
Fundament gar nicht, und keine zwei Fassungen sind gleich.

    survey_folders        survey-app     workspace, flach, position, mode
    presentation_folders  survey-app     zweite Kopie IN DERSELBEN APP
    widget_folders        support-app    Kopf sagt selbst: "1:1 aus survey-app"
    portfolio_lists       pb-finance/-news  user statt workspace, ohne position

Der Kopf von `widget_folders` nennt die Herkunft ausdrücklich — das Muster
wurde also bewusst kopiert statt geteilt. Der fünfte Bedarf (Wertpapier-Ordner
in paperball) war der Anlass, es hierher zu ziehen.

**Was hier steht und was nicht.** Hier stehen die Entscheidungen: wie viele
Ordner ein Objekt haben darf, was ein Entfernen bedeutet, wann überhaupt
gefragt werden muss, wo ein Objekt lebt, das in keinem Ordner liegt, und wer
einen geteilten Ordner ändern darf. Nicht hier steht die Speicherung — die
Apps haben verschiedene Mandanten-Modelle (`workspace_id`, `user_id`,
`organization_id`) und verschiedene Session-Factories. Sie sollen sich gleich
*entscheiden*, nicht gleich ablegen. Dasselbe Prinzip wie bei
`locale_resolver` und `teilen_link`.

Die sechs Entscheidungen, die mehr zählen als der Code
------------------------------------------------------

1. **Ordner sind flach.** Kein `parent_id`, keine Unterordner. Alle vier
   bestehenden Fassungen sind flach, und das ist kein Zufall: Verschachtelung
   verlangt eine Antwort auf "zählt das Kind zum Elternordner?" bei jeder
   Zählung, jeder Auswahl und jedem Löschen. Zusammen mit Mehrfachzuordnung
   (Punkt 2) wird daraus ein Graph, den niemand mehr im Kopf hat. Wer
   Hierarchie braucht, nimmt zwei Ordner und einen längeren Namen.

2. **Mehrfachzuordnung ist eine Entscheidung der App, keine des Objekts.**
   Vier Apps wollen "ein Ordner je Objekt", paperball will "ein Wertpapier in
   mehreren Ordnern". Beides ist richtig — aber die Wahl fällt einmal je
   Objektart, nicht je Objekt. Sonst gibt es innerhalb einer Liste Zeilen, die
   sich beim Entfernen verschieden verhalten, und das kann niemand vorhersehen.

3. **Der Löschdialog erscheint nur, wenn es wirklich zwei Möglichkeiten gibt.**
   Liegt ein Objekt in genau einem Ordner, ist "nur hier" identisch mit
   "überall" — die Frage wäre Ritual, kein Erkenntnisgewinn. Dialoge, die
   nichts entscheiden, werden weggeklickt, und dann wird auch der weggeklickt,
   der etwas entscheidet. Statt Rückfrage: ausführen und `rueckgaengig`
   anbieten.

4. **Ein Ordner zu löschen löscht niemals seinen Inhalt.** Ein Ordner ist ein
   Etikett, kein Behälter. Wer ihn wegwirft, wirft das Etikett weg. Der Dialog
   muss trotzdem sagen, wie viele Objekte danach in keinem Ordner mehr liegen —
   sonst wirkt das Verschwinden aus der Ansicht wie ein Datenverlust.

5. **Wo ein ordnerloses Objekt lebt, hängt an Punkt 2.** Bei "ein Ordner je
   Objekt" ist "ohne Ordner" ein Sonderfall und heißt entsprechend
   ("Nicht einsortiert"). Bei Mehrfachzuordnung ist er der Normalfall: Ordner
   sind dort Sichten, der Bestand liegt darunter — die Wurzel heißt dann
   "Alle", nicht "Nicht einsortiert". Derselbe Kasten mit dem falschen Namen
   erzählt dem Nutzer eine falsche Geschichte über sein eigenes Datenmodell.

6. **Wer teilt, gibt das Löschrecht nicht mit.** In einem geteilten Ordner darf
   jedes Mitglied Objekte hinzufügen und entfernen — das ist der Zweck. Den
   Ordner umbenennen, die Freigabe ändern oder ihn löschen darf nur, wem er
   gehört, plus die Verwaltung der Organisation. Sonst kann ein Mitglied die
   Arbeit aller anderen in einem Klick entfernen.
"""

from __future__ import annotations

import enum
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Grenzen
# ---------------------------------------------------------------------------

#: Längste erlaubte Ordnerbezeichnung. Entspricht dem `String(255)` aller vier
#: bestehenden Fassungen — kein neuer Wert, damit eine Angleichung bestehender
#: Daten nie an der Länge scheitert.
NAME_MAX = 255

#: Abstand zwischen zwei Positionen bei der Neuvergabe. Lücken erlauben es,
#: ein Element dazwischenzuschieben, ohne alle folgenden neu zu schreiben.
POSITION_SCHRITT = 10


class Zuordnung(enum.Enum):
    """Wie viele Ordner ein Objekt gleichzeitig haben darf.

    Die Wahl fällt je Objektart und ist Teil des App-Vertrags, nicht des
    Datensatzes (siehe Entscheidung 2 im Modulkopf).
    """

    #: Höchstens ein Ordner je Objekt. Speicherform: Fremdschlüsselspalte am
    #: Objekt. So arbeiten survey_folders, presentation_folders, widget_folders
    #: und portfolio_lists.
    EINDEUTIG = "eindeutig"

    #: Beliebig viele Ordner je Objekt. Speicherform: eigene Zuordnungstabelle
    #: mit einer Zeile je Paar. So arbeiten die Wertpapier-Ordner in paperball.
    MEHRFACH = "mehrfach"


class Wurzel(enum.Enum):
    """Wie der Bereich unterhalb der Ordner heißt und was er zeigt."""

    #: Nur Objekte ohne Ordner. Beschriftung in der App: "Nicht einsortiert".
    UNGEORDNET = "ungeordnet"

    #: Alle Objekte, auch die in Ordnern. Beschriftung: "Alle …".
    ALLE = "alle"


class Entfernen(enum.Enum):
    """Was ein Klick auf "Entfernen" innerhalb eines Ordners auslöst."""

    #: Ohne Rückfrage aus diesem Ordner nehmen; die App bietet "Rückgängig" an.
    AUS_ORDNER_STILL = "aus_ordner_still"

    #: Rückfrage nötig: nur aus diesem Ordner, oder ganz aus dem Bestand.
    FRAGEN = "fragen"

    #: Ohne Rückfrage ganz aus dem Bestand — das Objekt lag in keinem Ordner,
    #: es gibt also nichts, woraus man es sonst nehmen könnte.
    AUS_BESTAND_STILL = "aus_bestand_still"


class Rolle(enum.Enum):
    """Verhältnis der handelnden Person zu einem Ordner."""

    #: Hat den Ordner angelegt.
    EIGENTUEMER = "eigentuemer"

    #: Verwaltet die Organisation, der ein geteilter Ordner gehört.
    ORG_ADMIN = "org_admin"

    #: Gehört zur Organisation, verwaltet sie aber nicht.
    MITGLIED = "mitglied"

    #: Weder noch — darf den Ordner gar nicht sehen.
    FREMD = "fremd"


class Zuordnen(enum.Enum):
    """Was „diese Objekte in jenen Ordner" bedeutet."""

    #: Der Ordner kommt dazu, die bestehenden bleiben. Nur bei
    #: Mehrfachzuordnung möglich.
    HINZUFUEGEN = "hinzufuegen"

    #: Der bisherige Ordner wird ersetzt. Bei eindeutiger Zuordnung ist das
    #: die einzige Lesart — ein Objekt hat dort genau einen Platz.
    VERSCHIEBEN = "verschieben"


# ---------------------------------------------------------------------------
# Zuordnen
# ---------------------------------------------------------------------------


def entscheide_zuordnen(zuordnung: Zuordnung) -> Zuordnen:
    """Was eine Zuordnung mehrerer Objekte in EINEN Ordner tut.

    Die Frage ist keine Geschmacksfrage, sondern folgt aus der Kardinalität:

    * `EINDEUTIG` — ein Objekt hat höchstens einen Ordner. „Dazulegen" gibt es
      nicht; die Aktion **ersetzt** den bisherigen. Die Oberfläche muss das so
      benennen („verschieben"), sonst wundert sich, wer sein Objekt im alten
      Ordner sucht.
    * `MEHRFACH` — ein Objekt darf in vielen Ordnern liegen. Dann ist
      **Hinzufügen** die einzige Lesart, die ohne Raten auskommt: „verschieben"
      müsste entscheiden, aus welchem der bestehenden Ordner das Objekt
      verschwindet, und diese Angabe steht nirgends. Wer es woanders
      herausnehmen will, sagt das eigens.

    Diese Regel gilt für JEDEN Weg, der Objekte einsortiert — das Zielmenü
    einer Auswahl genauso wie das Ziehen auf einen Ordner. Zwei Wege mit zwei
    Bedeutungen wären die schlimmste Antwort.
    """
    if zuordnung is Zuordnung.EINDEUTIG:
        return Zuordnen.VERSCHIEBEN
    return Zuordnen.HINZUFUEGEN


# ---------------------------------------------------------------------------
# Entfernen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntfernenPlan:
    """Was beim Entfernen zu tun ist, plus die Zahlen für den Dialogtext."""

    aktion: Entfernen

    #: Wie viele Ordner das Objekt nach einem "nur aus diesem Ordner" noch hat.
    #: Genau die Zahl, die der Dialog nennen muss, damit "bleibt in 2 Ordnern"
    #: nicht geraten ist.
    verbleibende_ordner: int

    #: Ob der Ordner, aus dem entfernt wird, geteilt ist — dann betrifft die
    #: Aktion auch andere Personen und der Dialog muss das sagen.
    betrifft_andere: bool = False


def entscheide_entfernen(
    zuordnung: Zuordnung,
    ordner_des_objekts: int,
    *,
    aus_ordner: bool = True,
    geteilter_ordner: bool = False,
) -> EntfernenPlan:
    """Wie auf "Entfernen" zu reagieren ist.

    Args:
        zuordnung: Kardinalität der Objektart (siehe `Zuordnung`).
        ordner_des_objekts: In wie vielen Ordnern das Objekt aktuell liegt.
        aus_ordner: True, wenn aus der Ansicht eines Ordners heraus entfernt
            wird; False, wenn aus der Wurzelansicht heraus — dort gibt es
            keinen Ordner, aus dem man nehmen könnte, also ist immer der
            Bestand gemeint.
        geteilter_ordner: Ob der Ordner der Organisation gehört.

    Die Rückfrage entsteht an genau einer Stelle: Mehrfachzuordnung, Aktion aus
    einem Ordner heraus, und das Objekt liegt in mehr als einem Ordner. Überall
    sonst ist die Handlung eindeutig (Entscheidung 3 im Modulkopf).
    """
    if ordner_des_objekts < 0:
        raise ValueError("ordner_des_objekts darf nicht negativ sein")

    # Aus der Wurzelansicht heraus gibt es keinen Ordner, aus dem man nehmen
    # könnte — gemeint ist immer der Bestand.
    if not aus_ordner or ordner_des_objekts == 0:
        return EntfernenPlan(
            aktion=Entfernen.AUS_BESTAND_STILL,
            verbleibende_ordner=0,
            betrifft_andere=False,
        )

    if zuordnung is Zuordnung.EINDEUTIG or ordner_des_objekts == 1:
        return EntfernenPlan(
            aktion=Entfernen.AUS_ORDNER_STILL,
            verbleibende_ordner=0,
            betrifft_andere=geteilter_ordner,
        )

    return EntfernenPlan(
        aktion=Entfernen.FRAGEN,
        verbleibende_ordner=ordner_des_objekts - 1,
        betrifft_andere=geteilter_ordner,
    )


# ---------------------------------------------------------------------------
# Ordner löschen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoeschPlan:
    """Folgen des Löschens eines Ordners — für den Bestätigungstext."""

    #: Wie viele Objekte der Ordner enthält.
    objekte: int

    #: Wie viele davon danach in keinem Ordner mehr liegen. Nur diese
    #: verschwinden aus der Ordneransicht; der Rest bleibt anderswo sichtbar.
    danach_ohne_ordner: int

    #: Immer False. Existiert als Feld, damit ein Aufrufer, der später einen
    #: kaskadierenden Modus sucht, hier auf die Begründung stößt statt einen
    #: zu bauen (Entscheidung 4 im Modulkopf).
    inhalt_wird_geloescht: bool = False


def plane_ordner_loeschen(objekte_im_ordner: int, davon_nur_hier: int) -> LoeschPlan:
    """Was das Löschen eines Ordners für seinen Inhalt bedeutet.

    Args:
        objekte_im_ordner: Anzahl Objekte im Ordner.
        davon_nur_hier: Wie viele davon in keinem weiteren Ordner liegen.

    Bei eindeutiger Zuordnung sind beide Zahlen gleich — dort ist jedes Objekt
    per Definition nur hier. Der Aufrufer muss das nicht unterscheiden.
    """
    if objekte_im_ordner < 0 or davon_nur_hier < 0:
        raise ValueError("Anzahlen dürfen nicht negativ sein")
    if davon_nur_hier > objekte_im_ordner:
        raise ValueError("davon_nur_hier kann nicht größer als objekte_im_ordner sein")

    return LoeschPlan(objekte=objekte_im_ordner, danach_ohne_ordner=davon_nur_hier)


# ---------------------------------------------------------------------------
# Wurzelansicht
# ---------------------------------------------------------------------------


def wurzel_fuer(zuordnung: Zuordnung) -> Wurzel:
    """Was unterhalb der Ordner steht — und damit, wie es heißen muss.

    Siehe Entscheidung 5 im Modulkopf: Bei eindeutiger Zuordnung ist
    "ohne Ordner" ein Sonderfall, bei Mehrfachzuordnung ist der Bestand die
    Grundlage und die Ordner sind Sichten darauf.
    """
    return Wurzel.UNGEORDNET if zuordnung is Zuordnung.EINDEUTIG else Wurzel.ALLE


# ---------------------------------------------------------------------------
# Rechte
# ---------------------------------------------------------------------------


def darf_sehen(rolle: Rolle, *, geteilt: bool) -> bool:
    """Ob die Rolle den Ordner überhaupt zu sehen bekommt."""
    if rolle is Rolle.EIGENTUEMER:
        return True
    if not geteilt:
        # Ein privater Ordner ist auch für die Organisations-Verwaltung privat.
        # Administrieren heißt Mandanten verwalten, nicht in fremde Ablagen
        # sehen.
        return False
    return rolle in (Rolle.ORG_ADMIN, Rolle.MITGLIED)


def darf_inhalt_aendern(rolle: Rolle, *, geteilt: bool) -> bool:
    """Ob die Rolle Objekte in den Ordner legen und daraus entfernen darf.

    Das ist der Zweck des Teilens — wer nur zusehen darf, braucht keinen
    geteilten Ordner, sondern einen Teilen-Link (`teilen_link.py`).
    """
    return darf_sehen(rolle, geteilt=geteilt)


def darf_ordner_verwalten(rolle: Rolle, *, geteilt: bool) -> bool:
    """Ob die Rolle umbenennen, sortieren, freigeben und löschen darf.

    Enger als `darf_inhalt_aendern`: siehe Entscheidung 6 im Modulkopf.
    """
    if not darf_sehen(rolle, geteilt=geteilt):
        return False
    return rolle in (Rolle.EIGENTUEMER, Rolle.ORG_ADMIN)


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------


class NameFehler(enum.Enum):
    """Warum eine Ordnerbezeichnung abgelehnt wurde."""

    LEER = "leer"
    ZU_LANG = "zu_lang"
    BELEGT = "belegt"


@dataclass(frozen=True)
class NamePruefung:
    """Ergebnis der Namensprüfung."""

    #: Die zu speichernde Fassung — außen beschnitten, innen normalisiert.
    #: Bei einem Fehler leer.
    name: str = ""
    fehler: NameFehler | None = None

    @property
    def ok(self) -> bool:
        return self.fehler is None


def _vergleichsform(name: str) -> str:
    """Wie zwei Bezeichnungen auf Gleichheit geprüft werden.

    Kleinschreibung und Unicode-Normalform: "Kern-ETFs" und "kern-etfs" sind
    für einen Menschen derselbe Ordner, und zwei Ordner, die sich nur in der
    Groß-/Kleinschreibung unterscheiden, sind in einer Liste nicht
    auseinanderzuhalten. `casefold` statt `lower`, damit auch "STRASSE" und
    "straße" zusammenfallen.
    """
    return unicodedata.normalize("NFKC", name).casefold()


def pruefe_name(roh: str, *, vergebene_namen: list[str] | None = None) -> NamePruefung:
    """Bezeichnung säubern und prüfen.

    Args:
        roh: Eingabe des Nutzers.
        vergebene_namen: Bezeichnungen der Ordner im selben Geltungsbereich.
            Beim Umbenennen die eigene alte Bezeichnung **nicht** mitgeben,
            sonst kollidiert der Ordner mit sich selbst.

    Innere Mehrfach-Leerzeichen werden zu einem zusammengezogen: "Kern  ETFs"
    und "Kern ETFs" sind sonst zwei Ordner, die in der Liste identisch aussehen
    — der klassische Weg zu einem Duplikat, das niemand erklären kann.
    """
    name = " ".join(roh.split())

    if not name:
        return NamePruefung(fehler=NameFehler.LEER)
    if len(name) > NAME_MAX:
        return NamePruefung(fehler=NameFehler.ZU_LANG)

    if vergebene_namen:
        belegt = {_vergleichsform(v) for v in vergebene_namen}
        if _vergleichsform(name) in belegt:
            return NamePruefung(fehler=NameFehler.BELEGT)

    return NamePruefung(name=name)


# ---------------------------------------------------------------------------
# Reihenfolge
# ---------------------------------------------------------------------------


def naechste_position(vergebene_positionen: list[int]) -> int:
    """Position für einen neu angelegten Ordner: hinten anstellen."""
    if not vergebene_positionen:
        return 0
    return max(vergebene_positionen) + POSITION_SCHRITT


def neu_ordnen(ids: list[str]) -> dict[str, int]:
    """Positionen für eine vom Nutzer gezogene Reihenfolge.

    Nimmt die Liste in der gewünschten Reihenfolge und gibt je Kennung die zu
    speichernde Position zurück. Bewusst werden **alle** neu vergeben statt nur
    die verschobene angepasst: Das ist ein Schreibvorgang mehr und dafür
    lückenlos reproduzierbar. Teilweise Neuvergabe erzeugt über Monate
    Positions-Kollisionen, deren Reihenfolge dann von der Kennung abhängt — und
    damit scheinbar zufällig ist.

    Doppelte Kennungen sind ein Programmierfehler des Aufrufers und werden
    nicht stillschweigend zusammengefasst.
    """
    if len(set(ids)) != len(ids):
        raise ValueError("Kennungen in der Reihenfolge müssen eindeutig sein")
    return {kennung: i * POSITION_SCHRITT for i, kennung in enumerate(ids)}


# ---------------------------------------------------------------------------
# Antwort-Form
# ---------------------------------------------------------------------------


@dataclass
class OrdnerAnsicht:
    """Ein Ordner samt Inhalt, wie die Liste ihn braucht."""

    id: str
    name: str
    position: int
    objekte: list = field(default_factory=list)
    geteilt: bool = False


def baue_antwort(
    ordner: list[OrdnerAnsicht],
    wurzel_objekte: list,
    zuordnung: Zuordnung,
    wurzel: Wurzel | None = None,
) -> dict:
    """Die flottenweite Antwortform von `GET /folders`.

    ```
    {
      "zuordnung": "eindeutig" | "mehrfach",
      "wurzel":    "ungeordnet" | "alle",
      "ordner":    [{"id", "name", "position", "geteilt", "objekte": [...]}],
      "wurzel_objekte": [...]
    }
    ```

    `zuordnung` und `wurzel` stehen **in der Antwort**, nicht nur in der
    Dokumentation. Die Oberfläche muss beides wissen, um die Wurzel richtig zu
    beschriften und zu entscheiden, ob ein Entfernen fragen muss — und wenn sie
    es aus einer eigenen Konstante zieht, driftet genau diese Konstante von der
    Wahrheit im Backend weg. Das ist billiger als der Fehlerbericht
    "warum fragt der Dialog nicht?".

    Die Ordner kommen nach Position sortiert, bei Gleichstand nach
    Vergleichsform der Bezeichnung — ohne zweites Kriterium ist die Reihenfolge
    gleicher Positionen die der Datenbank, also von Lauf zu Lauf verschieden.

    `wurzel` überschreibt die Ableitung aus der Kardinalität (siehe
    `wurzel_fuer` und Regel 5). Wer bei Mehrfachzuordnung `Wurzel.UNGEORDNET`
    wählt, bekommt eine Wurzel, die nur zeigt, was in KEINEM Ordner liegt —
    dann erscheint kein Objekt gleichzeitig im Ordner und darunter. Das Feld
    muss dann auch nur diese Objekte enthalten; der Baustein filtert nicht, er
    beschriftet.
    """
    sortiert = sorted(ordner, key=lambda o: (o.position, _vergleichsform(o.name)))
    return {
        "zuordnung": zuordnung.value,
        "wurzel": (wurzel or wurzel_fuer(zuordnung)).value,
        "ordner": [
            {
                "id": o.id,
                "name": o.name,
                "position": o.position,
                "geteilt": o.geteilt,
                "objekte": o.objekte,
            }
            for o in sortiert
        ],
        "wurzel_objekte": wurzel_objekte,
    }
