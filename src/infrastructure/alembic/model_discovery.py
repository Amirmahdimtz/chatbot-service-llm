"""Import all persistence models before Alembic inspects Base.metadata."""

from __future__ import annotations

import importlib
from pathlib import Path


def load_models() -> None:
    models_dir = Path(__file__).resolve().parents[1] / "models"
    for model_file in sorted(models_dir.glob("*.py")):
        if model_file.name.startswith("_"):
            continue
        module_name = f"src.infrastructure.models.{model_file.stem}"
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"Failed importing Alembic model {module_name}: {exc}") from exc
