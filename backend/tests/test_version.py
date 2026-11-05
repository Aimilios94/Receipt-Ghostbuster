"""The backend and frontend must report the same app version."""
import json
from pathlib import Path

from app import __version__
from app.services import monitoring

REPO = Path(__file__).resolve().parents[2]


def test_version_is_the_same_everywhere():
    package = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == __version__
    assert monitoring._RELEASE.endswith(__version__)
    # Read as text: importing app.main would initialise Sentry from the developer's .env.
    assert "version=__version__" in (REPO / "backend" / "app" / "main.py").read_text(encoding="utf-8")
