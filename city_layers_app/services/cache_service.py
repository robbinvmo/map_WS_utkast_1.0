import json
from pathlib import Path
from typing import Any, Optional

from config import CACHE_DIR


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name.lower())


def build_cache_path(place_name: str, radius_m: int) -> Path:
    filename = f"{_safe_name(place_name)}_{radius_m}.json"
    return CACHE_DIR / filename


def build_viewport_cache_path(
    south: float,
    west: float,
    north: float,
    east: float,
    zoom: int | None = None,
) -> Path:
    viewport_dir = CACHE_DIR / "viewport"
    zoom_part = f"z{zoom}" if zoom is not None else "zna"
    filename = (
        f"s{south:.4f}_w{west:.4f}_n{north:.4f}_e{east:.4f}_{zoom_part}.json"
        .replace("-", "m")
        .replace(".", "p")
    )
    return viewport_dir / filename


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
