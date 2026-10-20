"""
Versioned model artifacts on disk.

Layout:
  data/models/<task>/<version>/model.joblib
  data/models/<task>/<version>/metadata.json   (config, label set, metrics, data hash)
  data/models/active.json                      ({task: version})
"""

import json
from pathlib import Path
from typing import Optional

import joblib

from backend.app.config import PROJECT_ROOT, get_settings

TASKS = ("intent", "awareness_gap", "gap_type")


def models_root() -> Path:
    p = Path(get_settings().MODELS_DIR)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _active_file() -> Path:
    return models_root() / "active.json"


def read_active() -> dict:
    f = _active_file()
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def set_active(task: str, version: str) -> None:
    active = read_active()
    active[task] = version
    models_root().mkdir(parents=True, exist_ok=True)
    _active_file().write_text(json.dumps(active, indent=2), encoding="utf-8")


def save(task: str, version: str, model, metadata: dict) -> Path:
    d = models_root() / task / version
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib")
    (d / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return d


def save_reference(version: str, records: list[dict]) -> None:
    """Labelled training records shipped with the gap model (evidence + OOD guard)."""
    d = models_root() / "awareness_gap" / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "reference.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def load_reference(version: Optional[str] = None) -> list[dict]:
    version = version or read_active().get("awareness_gap")
    f = models_root() / "awareness_gap" / (version or "") / "reference.json"
    return json.loads(f.read_text(encoding="utf-8")) if version and f.exists() else []


def load(task: str, version: Optional[str] = None):
    """Return (model, metadata) for the active (or given) version, or (None, None)."""
    version = version or read_active().get(task)
    if not version:
        return None, None
    d = models_root() / task / version
    if not (d / "model.joblib").exists():
        return None, None
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    return joblib.load(d / "model.joblib"), meta
