import requests

from config import OVERPASS_URL, USER_AGENT


def build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    return f"""
    [out:json][timeout:90];
    (
      // lunch / service (amenity)
      node(around:{radius_m},{lat},{lon})["amenity"~"cafe|restaurant|fast_food|food_court"];
      way(around:{radius_m},{lat},{lon})["amenity"~"cafe|restaurant|fast_food|food_court"];
      relation(around:{radius_m},{lat},{lon})["amenity"~"cafe|restaurant|fast_food|food_court"];

      // offices (direct + likely office-containing areas/buildings)
      node(around:{radius_m},{lat},{lon})["office"];
      way(around:{radius_m},{lat},{lon})["office"];
      relation(around:{radius_m},{lat},{lon})["office"];

      node(around:{radius_m},{lat},{lon})["building"="office"];
      way(around:{radius_m},{lat},{lon})["building"="office"];
      relation(around:{radius_m},{lat},{lon})["building"="office"];

      node(around:{radius_m},{lat},{lon})["building"~"commercial|civic|government|mixed_use"];
      way(around:{radius_m},{lat},{lon})["building"~"commercial|civic|government|mixed_use"];
      relation(around:{radius_m},{lat},{lon})["building"~"commercial|civic|government|mixed_use"];

      node(around:{radius_m},{lat},{lon})["landuse"="commercial"];
      way(around:{radius_m},{lat},{lon})["landuse"="commercial"];
      relation(around:{radius_m},{lat},{lon})["landuse"="commercial"];

      // public transport: bus, subway, train
      node(around:{radius_m},{lat},{lon})["highway"="bus_stop"];
      way(around:{radius_m},{lat},{lon})["highway"="bus_stop"];
      relation(around:{radius_m},{lat},{lon})["highway"="bus_stop"];

      node(around:{radius_m},{lat},{lon})["amenity"="bus_station"];
      way(around:{radius_m},{lat},{lon})["amenity"="bus_station"];
      relation(around:{radius_m},{lat},{lon})["amenity"="bus_station"];

      node(around:{radius_m},{lat},{lon})["station"~"subway|train"];
      way(around:{radius_m},{lat},{lon})["station"~"subway|train"];
      relation(around:{radius_m},{lat},{lon})["station"~"subway|train"];

      node(around:{radius_m},{lat},{lon})["railway"~"station|halt|subway_entrance"];
      way(around:{radius_m},{lat},{lon})["railway"~"station|halt|subway_entrance"];
      relation(around:{radius_m},{lat},{lon})["railway"~"station|halt|subway_entrance"];

      node(around:{radius_m},{lat},{lon})["public_transport"~"platform|stop_position|station"];
      way(around:{radius_m},{lat},{lon})["public_transport"~"platform|stop_position|station"];
      relation(around:{radius_m},{lat},{lon})["public_transport"~"platform|stop_position|station"];

    );
    out center tags;
    """


def fetch_osm_data(lat: float, lon: float, radius_m: int) -> dict:
    query = build_overpass_query(lat, lon, radius_m)
    headers = {"User-Agent": USER_AGENT}
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers=headers,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def build_overpass_bbox_query(south: float, west: float, north: float, east: float) -> str:
    return f"""
    [out:json][timeout:90][bbox:{south},{west},{north},{east}];
    (
      // lunch / service (amenity)
      node["amenity"~"cafe|restaurant|fast_food|food_court"];
      way["amenity"~"cafe|restaurant|fast_food|food_court"];
      relation["amenity"~"cafe|restaurant|fast_food|food_court"];

      // offices (direct + likely office-containing areas/buildings)
      node["office"];
      way["office"];
      relation["office"];

      node["building"="office"];
      way["building"="office"];
      relation["building"="office"];

      node["building"~"commercial|civic|government|mixed_use"];
      way["building"~"commercial|civic|government|mixed_use"];
      relation["building"~"commercial|civic|government|mixed_use"];

      node["landuse"="commercial"];
      way["landuse"="commercial"];
      relation["landuse"="commercial"];

      // public transport
      node["highway"="bus_stop"];
      way["highway"="bus_stop"];
      relation["highway"="bus_stop"];

      node["amenity"="bus_station"];
      way["amenity"="bus_station"];
      relation["amenity"="bus_station"];

      node["station"~"subway|train"];
      way["station"~"subway|train"];
      relation["station"~"subway|train"];

      node["railway"~"station|halt|subway_entrance"];
      way["railway"~"station|halt|subway_entrance"];
      relation["railway"~"station|halt|subway_entrance"];

      node["public_transport"~"platform|stop_position|station"];
      way["public_transport"~"platform|stop_position|station"];
      relation["public_transport"~"platform|stop_position|station"];

    );
    out center tags;
    """


def fetch_osm_data_bbox(south: float, west: float, north: float, east: float) -> dict:
    query = build_overpass_bbox_query(south, west, north, east)
    headers = {"User-Agent": USER_AGENT}
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers=headers,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def normalize_osm_elements(osm_json: dict) -> list[dict]:
    elements = osm_json.get("elements", [])
    normalized = []

    for el in elements:
        tags = el.get("tags", {})
        lat = el.get("lat")
        lon = el.get("lon")

        if lat is None or lon is None:
            center = el.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")

        if lat is None or lon is None:
            continue

        category, subtype = classify_element(tags)
        if category == "other":
            continue

        normalized.append(
            {
                "id": f"{el.get('type', 'x')}_{el.get('id', 'unknown')}",
                "type": el.get("type"),
                "lat": lat,
                "lon": lon,
                "name": tags.get("name", "Unnamed"),
                "category": category,
                "subtype": subtype,
                "tags": tags,
            }
        )

    return normalized


def classify_element(tags: dict) -> tuple[str, str]:
    amenity = tags.get("amenity", "")
    office = tags.get("office", "")
    building = tags.get("building", "")
    landuse = tags.get("landuse", "")
    public_transport = tags.get("public_transport", "")
    railway = tags.get("railway", "")
    station = tags.get("station", "")
    highway = tags.get("highway", "")

    if amenity in {"cafe", "restaurant", "fast_food", "food_court"}:
        return "food", amenity

    if office in {"coworking", "company", "government", "association", "insurance", "lawyer", "it"}:
        return "office", f"office_{office}"
    if office:
        return "office", "office_tag"
    if building == "office":
        return "office", "building_office"
    if building in {"commercial", "civic", "government", "mixed_use"}:
        return "office", "building_office_potential"
    if landuse == "commercial":
        return "office", "landuse_commercial"

    if highway == "bus_stop" or amenity == "bus_station":
        return "public_transport", "bus_stop"
    if station == "subway" or railway == "subway_entrance":
        return "public_transport", "subway"
    if station == "train" or railway in {"station", "halt"}:
        return "public_transport", "train"
    if public_transport in {"platform", "stop_position", "station"}:
        return "public_transport", "pt_stop"

    return "other", "other"
