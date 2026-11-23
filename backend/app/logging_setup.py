import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import settings


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_dienstplan_configured", False):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(logging.INFO)
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(fmt)
    root.addHandler(out)
    try:
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(Path(settings.log_dir) / "app.log", maxBytes=5_000_000,
                                 backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        root.warning("Logdatei konnte nicht angelegt werden; es wird nur auf stdout geloggt")
    root._dienstplan_configured = True
