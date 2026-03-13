import json
from collections import Counter, defaultdict
from pathlib import Path


TARGET_MUNICIPALITIES = [
    "Stockholm",
    "Lidingö",
    "Huddinge",
    "Sundbyberg",
    "Haninge",
]
ALLOWED_CATEGORIES = {"food", "office", "public_transport"}


BASE_DIR = Path(__file__).resolve().parents[1]
BOUNDARIES_PATH = BASE_DIR / "data" / "boundaries" / "regso.geojson"
FEATURES_PATH = BASE_DIR / "data" / "store" / "features.geojsonl"
OUT_DIR = BASE_DIR / "data" / "store" / "municipalities"
SUMMARY_PATH = OUT_DIR / "summary.json"


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    if n < 4:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, polygon_coords: list) -> bool:
    if not polygon_coords:
        return False
    outer = polygon_coords[0]
    if not point_in_ring(lon, lat, outer):
        return False
    holes = polygon_coords[1:]
    for hole in holes:
        if point_in_ring(lon, lat, hole):
            return False
    return True


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return point_in_polygon(lon, lat, coords)
    if gtype == "MultiPolygon":
        for poly in coords:
            if point_in_polygon(lon, lat, poly):
                return True
        return False
    return False


def load_municipality_geometries() -> dict[str, list[dict]]:
    with open(BOUNDARIES_PATH, "r", encoding="utf-8") as f:
        regso = json.load(f)

    geometries_by_muni: dict[str, list[dict]] = defaultdict(list)
    wanted = {name.lower(): name for name in TARGET_MUNICIPALITIES}

    for feature in regso.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry")
        if not geom:
            continue

        kommunnamn = str(props.get("kommunnamn", "")).strip()
        if not kommunnamn:
            continue

        match_key = kommunnamn.lower()
        if match_key in wanted:
            geometries_by_muni[wanted[match_key]].append(geom)

    return geometries_by_muni


def ensure_output_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def slugify(name: str) -> str:
    repl = (
        ("å", "a"),
        ("ä", "a"),
        ("ö", "o"),
        ("Å", "a"),
        ("Ä", "a"),
        ("Ö", "o"),
        (" ", "_"),
    )
    out = name
    for a, b in repl:
        out = out.replace(a, b)
    return out.lower()


def run() -> None:
    ensure_output_dir()
    geometries_by_muni = load_municipality_geometries()

    output_files = {}
    counters = {}
    category_counters = {}
    for muni in TARGET_MUNICIPALITIES:
        path = OUT_DIR / f"{slugify(muni)}.geojsonl"
        output_files[muni] = open(path, "w", encoding="utf-8")
        counters[muni] = 0
        category_counters[muni] = Counter()

    scanned = 0
    with open(FEATURES_PATH, "r", encoding="utf-8") as source:
        for line in source:
            raw = line.strip()
            if not raw:
                continue
            scanned += 1
            feature = json.loads(raw)
            coords = feature.get("geometry", {}).get("coordinates", [])
            if len(coords) != 2:
                continue
            lon, lat = coords
            category = feature.get("properties", {}).get("category", "unknown")
            if category not in ALLOWED_CATEGORIES:
                continue

            for muni in TARGET_MUNICIPALITIES:
                geoms = geometries_by_muni.get(muni, [])
                if not geoms:
                    continue
                hit = any(point_in_geometry(lon, lat, geom) for geom in geoms)
                if hit:
                    output_files[muni].write(raw + "\n")
                    counters[muni] += 1
                    category_counters[muni][category] += 1

    for f in output_files.values():
        f.close()

    summary = {
        "source_features_scanned": scanned,
        "municipalities": [],
    }
    for muni in TARGET_MUNICIPALITIES:
        summary["municipalities"].append(
            {
                "name": muni,
                "regso_parts_used": len(geometries_by_muni.get(muni, [])),
                "features_written": counters[muni],
                "categories": dict(category_counters[muni]),
                "file": str((OUT_DIR / f"{slugify(muni)}.geojsonl").resolve()),
            }
        )

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
