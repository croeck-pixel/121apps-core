# apps121-core

Geteilte Regel-Module der 121-Apps-Flotte. **Reine stdlib** — kein
SQLAlchemy, kein Stripe, kein FastAPI.

```bash
pip install "apps121-core @ git+https://github.com/croeck-pixel/121apps-core.git@main"
```

```python
from apps121_core.gutschein_regeln import pruefen, provision
```

## Warum es das gibt

Die Module beantworten Fragen, die in mehreren Anwendungen **gleich**
beantwortet werden müssen — ob ein Gutscheincode gilt, wie eine Provision
gerechnet wird, wie ein API-Schlüssel aussieht, welches Land zu einer
IP gehört.

Verteilt wurden sie ursprünglich als Kopie. Eine Messung im Juli 2026 hat
gezeigt, wohin das führt: derselbe Locale-Resolver lag in fünf Anwendungen,
und kein einziges Paar war identisch. Wo Geld an der Logik hängt — Rabatt,
Beteiligung, Auszahlung — ist das keine Option: eine Anwendung, die eine
halbe Korrektur mitnimmt, rechnet ab da anders ab als die anderen, und
niemand sieht es.

## Der Zuschnitt

**Hier stehen Entscheidungen, nicht Speicher.** Die Tabellen bleiben in der
jeweiligen Anwendung — sie heißen überall anders, und ein gemeinsames
Speichermodul wäre in jeder zweiten falsch. Ein Modul bekommt die Tatsachen
übergeben und gibt eine Entscheidung zurück.

Ablehnungsgründe sind **Maschinencodes**, keine Sätze (`code_expired`,
nicht „Dieser Code ist abgelaufen"): diese Schicht kennt weder Sprache noch
Tonfall des Kunden.

## Module

Beschreibung je Modul in [`MODULE.md`](MODULE.md).

## Tests

```bash
python -m pytest tests/ -q
```
