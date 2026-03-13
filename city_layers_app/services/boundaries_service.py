import json
from pathlib import Path
from typing import Any

from config import BOUNDARIES_DIR

REGSO_GEOJSON_PATH = BOUNDARIES_DIR / "regso.geojson"


def regso_geojson_exists() -> bool:
    return REGSO_GEOJSON_PATH.exists()


def load_regso_geojson() -> dict[str, Any]:
    with open(REGSO_GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_regso_geojson(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or REGSO_GEOJSON_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return target
