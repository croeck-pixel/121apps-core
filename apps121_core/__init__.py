"""Geteilte Regel-Module der 121-Apps-Flotte.

Installiert als ``apps121_core``; im Fundament-Repo liegen dieselben Dateien
flach unter ``packages/core-py/``, weil mehrere Apps sie noch als
CI-geprüfte Kopie führen (siehe ``pyproject.toml``).

    from apps121_core.gutschein_regeln import pruefen, provision

Hier steht **nur Logik** — kein SQLAlchemy, kein Stripe, kein FastAPI. Die App
besitzt ihre Tabellen, dieses Paket besitzt die Entscheidungen.
"""
