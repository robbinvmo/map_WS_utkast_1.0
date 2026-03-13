import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.boundaries_service import REGSO_GEOJSON_PATH, save_regso_geojson

LAYER_QUERY_URL = (
    "https://karta.kalix.se/arcgis/rest/services/"
    "Myndighetsdata/Underlagsdata_myndigheter_webb_extern/MapServer/117/query"
)


def chunked(values: list[int], size: int):
    for i in range(0, len(values), size):
        yield values[i : i + size]


def fetch_object_ids() -> list[int]:
    params = {"where": "1=1", "returnIdsOnly": "true", "f": "json"}
    response = requests.get(LAYER_QUERY_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    return payload.get("objectIds", [])


def fetch_geojson_for_ids(ids: list[int]) -> dict:
    params = {
        "objectIds": ",".join(str(x) for x in ids),
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    response = requests.get(LAYER_QUERY_URL, params=params, timeout=120)
    response.raise_for_status()
    return response.json()


def main() -> None:
    object_ids = fetch_object_ids()
    if not object_ids:
        raise RuntimeError("Inga objekt-ID:n hittades för RegSO-lagret.")

    all_features = []
    for batch in chunked(object_ids, 200):
        geojson = fetch_geojson_for_ids(batch)
        all_features.extend(geojson.get("features", []))

    feature_collection = {"type": "FeatureCollection", "features": all_features}
    target_path = save_regso_geojson(feature_collection)

    print(f"Sparade {len(all_features)} features till {target_path}")


if __name__ == "__main__":
    main()
