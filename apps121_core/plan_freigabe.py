"""Wann ein bezahlter Plan freischaltet — die Regeln als Code.

Anlass (14.10.2026): In 121vendors setzten Registrierung, Social-Registrierung
und der bloße Checkout-Start das Feld, das die Freischaltung liest, sofort auf
die gewählte bezahlte Stufe. Wer sich mit Einzel/Team/Mandant anmeldete, bekam
deren Funktionen ohne Zahlung. Die Closed Beta verdeckte das nur, solange nicht
verkauft wird. Die Prüfung der übrigen Apps fand denselben Fehler nicht, aber
seine Verwandten: Webhooks, die den Plan auch bei unbezahltem Abo heben, ein
`checkout.session.completed`, das `payment_status` nicht ansieht, und eine
Social-Anmeldung ohne Plan (NULL = unbegrenzte Limits). Und 121vendors
forderte nach einer Kündigung zur Zahlung der alten Stufe auf.

Die Apps speichern Plan und Abo unterschiedlich. Gleich *entscheiden* sollen
sie trotzdem:

1. **Wirksam ist, was bezahlt ist.** Bei der Anmeldung ist der wirksame Plan
   immer ``KOSTENLOSER_PLAN`` — auch ohne Stufenwahl, nie NULL (NULL heißt in
   den Entitlement-Resolvern der Flotte „kein Grant" = unbegrenzte Limits).
   Eine gewählte bezahlte Stufe wird vorgemerkt (offenes Abo oder
   ``pending_plan``), schaltet aber nichts frei.

2. **Nur der Webhook hebt den Plan**, und nur wenn bezahlt ist:
   ``checkout.session.completed`` mit ``checkout_bezahlt(payment_status)``,
   ``customer.subscription.updated`` mit ``schaltet_frei(status)``. Der
   Checkout-Start schreibt nur die Vormerkung. Kommt ein Checkout mit
   ``payment_status='unpaid'`` (SEPA, Überweisung), wartet die Freischaltung
   auf ``checkout.session.async_payment_succeeded`` bzw. das Abo-Update.

3. **``past_due`` behält den Plan** während Stripes Mahnlauf — wie die
   Paket-Grants in allen Resolvern. Erst ``canceled`` (Webhook „deleted")
   stellt auf ``KOSTENLOSER_PLAN`` zurück.

4. **Manuell vergebene Pläne fasst kein Webhook an** (``plan_source`` =
   ``manual`` für Comp, ``invoice`` für Rechnungskunden — Fleet-Admin-Spec
   §6.3). Ein unbekannter ``plan_source`` wirft: still „Stripe" wäre genau
   der Weg, auf dem ein Comp-Konto beim nächsten Webhook seinen Plan verliert.

5. **Zur Zahlung auffordern** (``braucht_checkout``) nur, wer eine bezahlte
   Stufe gewählt, sie nicht bezahlt hat und selbst kauft: kein Comp-Konto,
   kein laufendes oder im Mahnlauf befindliches Abo (dort hilft das
   Kundenportal, ein zweiter Checkout legte ein zweites Abo an), und kein
   gekündigtes — dessen Stufe hat niemand gerade gewählt.

Benutzung: siehe ``README.md`` (Abschnitt ``plan_freigabe``).
"""

from __future__ import annotations

from typing import Optional

KOSTENLOSER_PLAN = "test"

# Abo-Status (Stripe-Wortlaut), unter denen der bezahlte Plan wirkt.
FREISCHALTENDE_STATUS = frozenset({"active", "trialing", "past_due"})

# `payment_status` einer Checkout-Session, unter denen bezahlt ist. Ein Abo mit
# Probezeit kommt als `no_payment_required`.
BEZAHLTE_CHECKOUTS = frozenset({"paid", "no_payment_required"})

PLAN_QUELLEN = frozenset({"stripe", "manual", "invoice"})


def schaltet_frei(abo_status: Optional[str]) -> bool:
    """Ob ein Abo mit diesem Status den bezahlten Plan wirken lässt."""
    return abo_status in FREISCHALTENDE_STATUS


def checkout_bezahlt(payment_status: Optional[str]) -> bool:
    """Ob ``checkout.session.completed`` eine Zahlung bestätigt (Regel 2)."""
    return payment_status in BEZAHLTE_CHECKOUTS


def webhook_darf_plan_setzen(plan_source: str) -> bool:
    """Ob ein Stripe-Webhook den Plan dieses Kontos ändern darf (Regel 4)."""
    if plan_source not in PLAN_QUELLEN:
        raise ValueError(f"unbekannte plan_source {plan_source!r} (erwartet: {sorted(PLAN_QUELLEN)})")
    return plan_source == "stripe"


def braucht_checkout(*, ist_bezahlplan: bool, abo_status: Optional[str], plan_source: str) -> bool:
    """Ob die App zur Zahlung der vorgemerkten Stufe auffordern soll (Regel 5).

    ``ist_bezahlplan`` gilt für die Stufe, die die App anzeigt: die vorgemerkte
    bei offenem Abo, sonst die wirksame. ``abo_status`` ist None ohne Abo.
    """
    if not ist_bezahlplan or not webhook_darf_plan_setzen(plan_source):
        return False
    return abo_status not in FREISCHALTENDE_STATUS and abo_status != "canceled"
