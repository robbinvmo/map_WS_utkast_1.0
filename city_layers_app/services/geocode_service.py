import requests

from config import NOMINATIM_URL, USER_AGENT


def geocode_place(place_name: str) -> dict | None:
    params = {
        "q": place_name,
        "format": "json",
        "limit": 1
    }
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    first = results[0]
    return {
        "display_name": first.get("display_name"),
        "lat": float(first["lat"]),
        "lon": float(first["lon"]),
    }
