from datetime import datetime, timezone

import requests

from config import TRAVELTIME_APP_ID, TRAVELTIME_API_KEY


def has_traveltime_credentials() -> bool:
    return bool(TRAVELTIME_APP_ID and TRAVELTIME_API_KEY)


def get_traveltime_one_to_many(
    origin_lat: float,
    origin_lon: float,
    destinations: list[dict],
    transportation_type: str = "public_transport"
) -> dict | None:
    if not has_traveltime_credentials():
        return None

    if not destinations:
        return None

    url = "https://api.traveltimeapp.com/v4/time-filter"
    headers = {
        "Content-Type": "application/json",
        "X-Application-Id": TRAVELTIME_APP_ID,
        "X-Api-Key": TRAVELTIME_API_KEY,
    }

    payload = {
        "locations": [
            {
                "id": "origin",
                "coords": {"lat": origin_lat, "lng": origin_lon}
            }
        ] + [
            {
                "id": d["id"],
                "coords": {"lat": d["lat"], "lng": d["lon"]}
            }
            for d in destinations
        ],
        "departure_searches": [
            {
                "id": "search_offices",
                "departure_location_id": "origin",
                "arrival_location_ids": [d["id"] for d in destinations],
                "transportation": {"type": transportation_type},
                "travel_time": 7200,
                "departure_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT08:00:00Z"),
                "properties": ["travel_time"]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def attach_traveltime_to_destinations(destinations: list[dict], tt_response: dict | None) -> list[dict]:
    if not tt_response:
        return destinations

    results = {}
    for res in tt_response.get("results", []):
        for loc in res.get("locations", []):
            results[loc["id"]] = loc.get("properties", [{}])[0].get("travel_time")

    enriched = []
    for d in destinations:
        item = d.copy()
        item["travel_time_sec"] = results.get(d["id"])
        enriched.append(item)

    return enriched


def _close_ring(coords: list[list[float]]) -> list[list[float]]:
    if not coords:
        return coords
    if coords[0] != coords[-1]:
        return [*coords, coords[0]]
    return coords


def _timemap_result_to_geojson(tt_response: dict) -> dict:
    # Handles common v4 response shape:
    # {"results":[{"search_id":"...", "shapes":[{"shell":[{"lat":..,"lng":..}], "holes":[...]}]}]}
    features = []
    for res in tt_response.get("results", []):
        shapes = res.get("shapes", [])
        for idx, shape in enumerate(shapes):
            shell = shape.get("shell", [])
            if not shell:
                continue

            outer = _close_ring([[pt["lng"], pt["lat"]] for pt in shell if "lat" in pt and "lng" in pt])
            holes_out = []
            for hole in shape.get("holes", []):
                ring = _close_ring([[pt["lng"], pt["lat"]] for pt in hole if "lat" in pt and "lng" in pt])
                if ring:
                    holes_out.append(ring)

            if not outer:
                continue

            features.append(
                {
                    "type": "Feature",
                    "id": f'{res.get("search_id", "search")}_{idx}',
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [outer, *holes_out],
                    },
                    "properties": {
                        "search_id": res.get("search_id"),
                    },
                }
            )

    return {"type": "FeatureCollection", "features": features}


def get_traveltime_timemap(
    origin_lat: float,
    origin_lon: float,
    *,
    max_minutes: int = 30,
    transportation_type: str = "public_transport",
) -> dict | None:
    if not has_traveltime_credentials():
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Application-Id": TRAVELTIME_APP_ID,
        "X-Api-Key": TRAVELTIME_API_KEY,
    }

    departure_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT08:00:00Z")
    travel_time = max(60, int(max_minutes) * 60)

    attempts = [
        (
            "https://api.traveltimeapp.com/v4/time-map/fast",
            {
                "departure_searches": [
                    {
                        "id": "iso",
                        "coords": {"lat": origin_lat, "lng": origin_lon},
                        "transportation": {"type": transportation_type},
                        "travel_time": travel_time,
                        "departure_time": departure_time,
                    }
                ]
            },
        ),
        (
            "https://api.traveltimeapp.com/v4/time-map",
            {
                "departure_searches": [
                    {
                        "id": "iso",
                        "coords": {"lat": origin_lat, "lng": origin_lon},
                        "transportation": {"type": transportation_type},
                        "travel_time": travel_time,
                        "departure_time": departure_time,
                    }
                ]
            },
        ),
        (
            "https://api.traveltimeapp.com/v4/time-map/fast",
            {
                "arrival_searches": [
                    {
                        "id": "iso",
                        "coords": {"lat": origin_lat, "lng": origin_lon},
                        "transportation": {"type": transportation_type},
                        "travel_time": travel_time,
                        "arrival_time": departure_time,
                    }
                ]
            },
        ),
    ]

    last_error = None
    for url, payload in attempts:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            json_payload = response.json()
            # Some plans can return GeoJSON directly; preserve if present.
            if json_payload.get("type") == "FeatureCollection":
                return json_payload
            return _timemap_result_to_geojson(json_payload)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    raise RuntimeError(f"TravelTime time-map misslyckades: {last_error}")
