from datetime import datetime, timezone
import json
import os
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from services.boundaries_service import load_regso_geojson, regso_geojson_exists
from services.cache_service import build_viewport_cache_path, load_json, save_json
from services.geocode_service import geocode_place
from services.osm_service import fetch_osm_data, fetch_osm_data_bbox, normalize_osm_elements
from services.store_service import get_store_stats, persist_search_results
from services.traveltime_service import (
    attach_traveltime_to_destinations,
    get_traveltime_one_to_many,
    get_traveltime_timemap,
    has_traveltime_credentials,
)

app = FastAPI(title="City Layers API")

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3004",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "http://127.0.0.1:3003",
    "http://127.0.0.1:3004",
]

extra_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_ALLOWED_ORIGINS + extra_origins,
    allow_origin_regex=os.getenv("CORS_ALLOW_ORIGIN_REGEX", r"https://.*\.netlify\.app"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MUNICIPALITY_DATASET_DIR = Path(__file__).resolve().parents[1] / "data" / "store" / "municipalities"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/geocode")
def geocode(place: str = Query(...)):
    result = geocode_place(place)
    if not result:
        return {"error": "Place not found"}
    return result


@app.get("/osm/search")
def osm_search(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: int = Query(1500),
    place_name: str | None = Query(default=None),
):
    raw = fetch_osm_data(lat, lon, radius_m)
    normalized = normalize_osm_elements(raw)
    store_result = persist_search_results(
        normalized,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        place_name=place_name,
        source="osm_search",
    )
    return {
        "count": len(normalized),
        "items": normalized,
        "store": store_result,
    }


@app.get("/osm/viewport")
def osm_viewport(
    south: float = Query(...),
    west: float = Query(...),
    north: float = Query(...),
    east: float = Query(...),
    zoom: int = Query(13),
):
    cache_path = build_viewport_cache_path(south, west, north, east, zoom)
    cached = load_json(cache_path)
    if cached is not None:
        return cached

    raw = fetch_osm_data_bbox(south=south, west=west, north=north, east=east)
    normalized = normalize_osm_elements(raw)
    payload = {
        "source": "live",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "viewport": {
            "south": south,
            "west": west,
            "north": north,
            "east": east,
            "zoom": zoom,
        },
        "count": len(normalized),
        "items": normalized,
    }
    save_json(payload, cache_path)
    return payload


@app.get("/store/stats")
def store_stats():
    return get_store_stats()


@app.get("/boundaries/regso")
def boundaries_regso():
    if not regso_geojson_exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "regso.geojson saknas i data/boundaries. "
                "Kör scripts/fetch_regso_geojson.py för att hämta filen."
            ),
        )
    return load_regso_geojson()


def _dataset_path(name: str) -> Path:
    safe = name.strip().lower().replace(" ", "_")
    return MUNICIPALITY_DATASET_DIR / f"{safe}.geojsonl"


@app.get("/store/datasets")
def store_datasets():
    if not MUNICIPALITY_DATASET_DIR.exists():
        return {"datasets": []}

    datasets = []
    for path in sorted(MUNICIPALITY_DATASET_DIR.glob("*.geojsonl")):
        datasets.append(
            {
                "id": path.stem,
                "file": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {"datasets": datasets}


@app.get("/store/dataset")
def store_dataset(name: str = Query(...)):
    path = _dataset_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset '{name}' hittades inte.")

    items = []
    lat_sum = 0.0
    lon_sum = 0.0
    min_lat = 90.0
    max_lat = -90.0
    min_lon = 180.0
    max_lon = -180.0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            feature = json.loads(raw)
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) != 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            props = feature.get("properties", {})
            items.append(
                {
                    "id": feature.get("id"),
                    "type": props.get("source_type"),
                    "lat": lat,
                    "lon": lon,
                    "name": props.get("name", "Unnamed"),
                    "category": props.get("category"),
                    "subtype": props.get("subtype"),
                    "tags": props.get("tags", {}),
                }
            )
            lat_sum += lat
            lon_sum += lon
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)

    if not items:
        return {
            "name": name,
            "count": 0,
            "items": [],
            "center": None,
            "bounds": None,
        }

    return {
        "name": name,
        "count": len(items),
        "items": items,
        "center": {"lat": lat_sum / len(items), "lon": lon_sum / len(items)},
        "bounds": {
            "south": min_lat,
            "west": min_lon,
            "north": max_lat,
            "east": max_lon,
        },
    }


@app.post("/analysis/traveltime/reachable")
def analysis_traveltime_reachable(payload: dict = Body(...)):
    origin_lat = payload.get("origin_lat")
    origin_lon = payload.get("origin_lon")
    max_minutes = int(payload.get("max_minutes", 30))
    transportation_type = payload.get("transportation_type", "public_transport")
    destinations = payload.get("destinations", [])

    if origin_lat is None or origin_lon is None:
        raise HTTPException(status_code=400, detail="origin_lat och origin_lon kravs.")

    if not isinstance(destinations, list) or not destinations:
        return {
            "enabled": has_traveltime_credentials(),
            "reachable_count": 0,
            "total_destinations": 0,
            "max_minutes": max_minutes,
            "transportation_type": transportation_type,
            "items": [],
        }

    # Keep the request lightweight for UI interactions.
    sample = destinations[:200]

    if not has_traveltime_credentials():
        return {
            "enabled": False,
            "reachable_count": 0,
            "total_destinations": len(sample),
            "max_minutes": max_minutes,
            "transportation_type": transportation_type,
            "items": sample,
        }

    try:
        tt_response = get_traveltime_one_to_many(
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            destinations=sample,
            transportation_type=transportation_type,
        )
        enriched = attach_traveltime_to_destinations(sample, tt_response)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TravelTime-anrop misslyckades: {exc}") from exc

    max_sec = max_minutes * 60
    reachable = [item for item in enriched if item.get("travel_time_sec") is not None and item["travel_time_sec"] <= max_sec]

    return {
        "enabled": True,
        "reachable_count": len(reachable),
        "total_destinations": len(enriched),
        "max_minutes": max_minutes,
        "transportation_type": transportation_type,
        "items": enriched,
    }


@app.post("/analysis/traveltime/timemap")
def analysis_traveltime_timemap(payload: dict = Body(...)):
    origin_lat = payload.get("origin_lat")
    origin_lon = payload.get("origin_lon")
    max_minutes = int(payload.get("max_minutes", 30))
    transportation_type = payload.get("transportation_type", "public_transport")

    if origin_lat is None or origin_lon is None:
        raise HTTPException(status_code=400, detail="origin_lat och origin_lon kravs.")

    if not has_traveltime_credentials():
        return {
            "enabled": False,
            "feature_collection": {"type": "FeatureCollection", "features": []},
            "max_minutes": max_minutes,
            "transportation_type": transportation_type,
        }

    try:
        geojson = get_traveltime_timemap(
            origin_lat=float(origin_lat),
            origin_lon=float(origin_lon),
            max_minutes=max_minutes,
            transportation_type=transportation_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TravelTime time-map misslyckades: {exc}") from exc

    return {
        "enabled": True,
        "feature_collection": geojson or {"type": "FeatureCollection", "features": []},
        "max_minutes": max_minutes,
        "transportation_type": transportation_type,
    }
