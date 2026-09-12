"""Die Testdateien importieren die Module flach (`import gutschein_regeln`).

So liegen sie im Fundament-Repo, und so bleiben sie hier: eine Umstellung auf
`from apps121_core import …` wäre eine Abweichung, die bei jeder Übernahme aus
dem Fundament von Hand nachgezogen werden müsste — und genau solche
Handarbeit ist der Anfang jeder Drift.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps121_core"))
