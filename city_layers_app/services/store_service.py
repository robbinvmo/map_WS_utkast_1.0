import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import STORE_DIR

FEATURES_PATH = STORE_DIR / "features.geojsonl"
QUERIES_PATH = STORE_DIR / "queries.jsonl"
FEATURE_IDS_PATH = STORE_DIR / "feature_ids.txt"


def _ensure_store_files() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    for path in (FEATURES_PATH, QUERIES_PATH, FEATURE_IDS_PATH):
        if not path.exists():
            path.touch()


def _load_feature_ids() -> set[str]:
    if not FEATURE_IDS_PATH.exists():
        return set()
    with open(FEATURE_IDS_PATH, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.write("\n")


def _to_geojson_feature(item: dict[str, Any], fetched_at_utc: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": item["id"],
        "geometry": {"type": "Point", "coordinates": [item["lon"], item["lat"]]},
        "properties": {
            "name": item.get("name"),
            "category": item.get("category"),
            "subtype": item.get("subtype"),
            "source_type": item.get("type"),
            "fetched_at_utc": fetched_at_utc,
            "tags": item.get("tags", {}),
        },
    }


def persist_search_results(
    items: list[dict[str, Any]],
    *,
    lat: float,
    lon: float,
    radius_m: int,
    place_name: str | None = None,
    source: str = "osm_search",
) -> dict[str, int]:
    _ensure_store_files()
    fetched_at_utc = datetime.now(timezone.utc).isoformat()

    query_record = {
        "fetched_at_utc": fetched_at_utc,
        "source": source,
        "place_name": place_name,
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "count": len(items),
    }
    _append_jsonl(QUERIES_PATH, query_record)

    known_ids = _load_feature_ids()
    written = 0
    skipped = 0

    with open(FEATURES_PATH, "a", encoding="utf-8") as features_file, open(
        FEATURE_IDS_PATH, "a", encoding="utf-8"
    ) as ids_file:
        for item in items:
            feature_id = item.get("id")
            if not feature_id:
                skipped += 1
                continue
            if feature_id in known_ids:
                skipped += 1
                continue

            feature = _to_geojson_feature(item, fetched_at_utc)
            features_file.write(json.dumps(feature, ensure_ascii=False))
            features_file.write("\n")
            ids_file.write(f"{feature_id}\n")
            known_ids.add(feature_id)
            written += 1

    return {"written": written, "skipped_existing": skipped}


def get_store_stats() -> dict[str, int]:
    _ensure_store_files()

    def count_lines(path: Path) -> int:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    return {
        "features_total": count_lines(FEATURES_PATH),
        "queries_total": count_lines(QUERIES_PATH),
        "unique_feature_ids": count_lines(FEATURE_IDS_PATH),
    }
