import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

const MapPanel = dynamic(() => import("../components/MapPanel"), { ssr: false });

const STOCKHOLM_CENTER = [59.3293, 18.0686];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const TEMP_CACHE_KEY = "city_layers_temp_session_cache_v3";
const MUNICIPALITY_OPTIONS = [
  { id: "stockholm", label: "Stockholm", kommun: "stockholm" },
  { id: "lidingo", label: "Lidingo", kommun: "lidingo" },
  { id: "huddinge", label: "Huddinge", kommun: "huddinge" },
  { id: "sundbyberg", label: "Sundbyberg", kommun: "sundbyberg" },
  { id: "haninge", label: "Haninge", kommun: "haninge" }
];

function categoryCounts(items) {
  return items.reduce(
    (acc, item) => {
      acc.total += 1;
      if (item.category in acc) acc[item.category] += 1;
      return acc;
    },
    { total: 0, office: 0, food: 0, public_transport: 0 }
  );
}

function averageTravelMinutes(items) {
  const values = items.filter((x) => x.travel_time_sec != null).map((x) => x.travel_time_sec / 60);
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function potentialScore(items) {
  const counts = categoryCounts(items);
  const avgTravel = averageTravelMinutes(items);
  const office = Math.min(counts.office / 45, 1) * 40;
  const service = Math.min(counts.food / 60, 1) * 25;
  const transport = Math.min(counts.public_transport / 60, 1) * 25;
  const travel = avgTravel == null ? 5 : Math.max(0, 10 - Math.min(avgTravel, 60) / 6);
  return Math.round(office + service + transport + travel);
}

function allowByFilters(item, filters) {
  if (item.category === "food") {
    if (item.subtype === "cafe") return filters.foodCafe;
    if (item.subtype === "restaurant") return filters.foodRestaurant;
    if (item.subtype === "fast_food") return filters.foodFastFood;
    if (item.subtype === "food_court") return filters.foodCourt;
    return false;
  }
  if (item.category === "office") {
    if (item.subtype === "office_tag" || item.subtype.startsWith("office_")) return filters.officeTag;
    if (item.subtype === "building_office") return filters.officeBuilding;
    if (item.subtype === "building_office_potential" || item.subtype === "landuse_commercial") return filters.officePotential;
    return false;
  }
  if (item.category === "public_transport") {
    if (item.subtype === "bus_stop") return filters.transportBus;
    if (item.subtype === "subway") return filters.transportSubway;
    if (item.subtype === "train") return filters.transportTrain;
    return false;
  }
  return false;
}

function normalizeWeights(weights, enabled) {
  const service = enabled.service ? weights.service : 0;
  const cluster = enabled.cluster ? weights.cluster : 0;
  const accessibility = enabled.accessibility ? weights.accessibility : 0;
  const sum = service + cluster + accessibility;
  if (sum <= 0) return { service: 0.42, cluster: 0.25, accessibility: 0.33 };
  return {
    service: service / sum,
    cluster: cluster / sum,
    accessibility: accessibility / sum
  };
}

function normalizeAreaName(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function pointInRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / ((yj - yi) || 1e-12) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointInPolygonCoordinates(lon, lat, polygonCoordinates) {
  if (!polygonCoordinates?.length) return false;
  if (!pointInRing(lon, lat, polygonCoordinates[0])) return false;
  for (let i = 1; i < polygonCoordinates.length; i += 1) {
    if (pointInRing(lon, lat, polygonCoordinates[i])) return false;
  }
  return true;
}

function pointInGeometry(lon, lat, geometry) {
  if (!geometry) return false;
  if (geometry.type === "Polygon") return pointInPolygonCoordinates(lon, lat, geometry.coordinates);
  if (geometry.type === "MultiPolygon") return geometry.coordinates.some((poly) => pointInPolygonCoordinates(lon, lat, poly));
  return false;
}

function distanceMetersLatLon(lat1, lon1, lat2, lon2) {
  const dLat = (lat1 - lat2) * 111320;
  const dLon = (lon1 - lon2) * 111320 * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180));
  return Math.sqrt(dLat * dLat + dLon * dLon);
}

function formatMeters(meters) {
  if (meters == null || Number.isNaN(meters)) return "-";
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(2)} km`;
}

function geometryCentroid(geometry) {
  if (!geometry) return null;
  const points = [];
  const pushCoords = (coords) => {
    for (const item of coords) {
      if (Array.isArray(item[0])) pushCoords(item);
      else points.push(item);
    }
  };
  pushCoords(geometry.coordinates || []);
  if (!points.length) return null;
  return {
    lat: points.reduce((s, p) => s + p[1], 0) / points.length,
    lon: points.reduce((s, p) => s + p[0], 0) / points.length
  };
}

function buildScoredBoundaries(boundaryGeoJson, items, normalizedWeights, center, radiusMeters) {
  if (!boundaryGeoJson?.features?.length) return null;
  const candidateFeatures =
    center && radiusMeters
      ? boundaryGeoJson.features.filter((feature) => {
          const centroid = geometryCentroid(feature.geometry);
          if (!centroid) return false;
          return distanceMetersLatLon(centroid.lat, centroid.lon, center[0], center[1]) <= radiusMeters;
        })
      : boundaryGeoJson.features;

  const enriched = candidateFeatures.map((feature) => {
    let serviceCount = 0;
    let officeCount = 0;
    let trafficCount = 0;
    for (const point of items) {
      if (!pointInGeometry(point.lon, point.lat, feature.geometry)) continue;
      if (point.category === "food") serviceCount += 1;
      if (point.category === "office") officeCount += 1;
      if (point.category === "public_transport") trafficCount += 1;
    }
    return { feature, serviceCount, officeCount, trafficCount };
  });

  const maxService = Math.max(1, ...enriched.map((x) => x.serviceCount));
  const maxOffice = Math.max(1, ...enriched.map((x) => x.officeCount));
  const maxTraffic = Math.max(1, ...enriched.map((x) => x.trafficCount));

  return {
    type: "FeatureCollection",
    features: enriched
      .map(({ feature, serviceCount, officeCount, trafficCount }) => {
        const s = serviceCount / maxService;
        const o = officeCount / maxOffice;
        const t = trafficCount / maxTraffic;
        return {
          ...feature,
          properties: {
            ...feature.properties,
            score: normalizedWeights.service * s + normalizedWeights.cluster * o + normalizedWeights.accessibility * t,
            serviceCount,
            officeCount,
            trafficCount,
            region_name: feature.properties?.regso || feature.properties?.name || "Område"
          }
        };
      })
      .filter((feature) => feature.properties.score > 0)
  };
}

function mergeItemsFromDatasets(datasets) {
  const seen = new Set();
  const merged = [];
  for (const ds of datasets) {
    for (const item of ds.items || []) {
      if (!item?.id || seen.has(item.id)) continue;
      seen.add(item.id);
      merged.push(item);
    }
  }
  return merged;
}

function averageCenterFromItems(items) {
  if (!items.length) return STOCKHOLM_CENTER;
  return [
    items.reduce((sum, i) => sum + i.lat, 0) / items.length,
    items.reduce((sum, i) => sum + i.lon, 0) / items.length
  ];
}

export default function HomePage() {
  const [placeName, setPlaceName] = useState("Stockholm Centralstation");
  const [dataMode, setDataMode] = useState("local");
  const [selectedMunicipalities, setSelectedMunicipalities] = useState(["stockholm"]);
  const [markerRadius, setMarkerRadius] = useState(10000);
  const [center, setCenter] = useState(STOCKHOLM_CENTER);
  const [mapTheme, setMapTheme] = useState("dark");
  const [layerMode, setLayerMode] = useState("regions");
  const [clusterEnabled, setClusterEnabled] = useState(true);
  const [data, setData] = useState([]);
  const [allBoundaries, setAllBoundaries] = useState(null);
  const [boundariesAvailable, setBoundariesAvailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [localLoadError, setLocalLoadError] = useState("");
  const [weights, setWeights] = useState({ service: 0.42, cluster: 0.25, accessibility: 0.33 });
  const [categoryEnabled, setCategoryEnabled] = useState({ service: true, cluster: true, accessibility: true });
  const [showSearchPointPanel, setShowSearchPointPanel] = useState(false);
  const [accessRadiusEnabled, setAccessRadiusEnabled] = useState(false);
  const [accessRadiusM, setAccessRadiusM] = useState(500);
  const [travelTimeEnabled, setTravelTimeEnabled] = useState(false);
  const [travelTimeMinutes, setTravelTimeMinutes] = useState(30);
  const [travelTimePolygon, setTravelTimePolygon] = useState(null);
  const [travelTimeRenderKey, setTravelTimeRenderKey] = useState(0);
  const [intensityRange, setIntensityRange] = useState({ min: 0, max: 100 });
  const [travelTimeState, setTravelTimeState] = useState({
    loading: false,
    enabled: false,
    error: ""
  });
  const hasBootstrapped = useRef(false);
  const lastFetchKeyRef = useRef("");
  const radiusTimerRef = useRef(null);

  const [showDataSource, setShowDataSource] = useState(true);
  const [showService, setShowService] = useState(true);
  const [showCluster, setShowCluster] = useState(true);
  const [showAccessibility, setShowAccessibility] = useState(true);
  const [showRegionsSelector, setShowRegionsSelector] = useState(true);

  const [filters, setFilters] = useState({
    foodCafe: true,
    foodRestaurant: true,
    foodFastFood: true,
    foodCourt: true,
    officeTag: true,
    officeBuilding: true,
    officePotential: true,
    transportBus: true,
    transportSubway: true,
    transportTrain: true
  });

  const normalizedWeights = useMemo(() => normalizeWeights(weights, categoryEnabled), [weights, categoryEnabled]);
  const selectedKommunNames = useMemo(
    () => MUNICIPALITY_OPTIONS.filter((x) => selectedMunicipalities.includes(x.id)).map((x) => normalizeAreaName(x.kommun)),
    [selectedMunicipalities]
  );
  const allRegionsSelected = selectedMunicipalities.length === MUNICIPALITY_OPTIONS.length;
  const activeFetchRadius = markerRadius;

  const filtered = useMemo(() => {
    return data
      .filter((item) => allowByFilters(item, filters))
      .filter((item) => {
        if (item.category === "food") return categoryEnabled.service;
        if (item.category === "office") return categoryEnabled.cluster;
        if (item.category === "public_transport") return categoryEnabled.accessibility;
        return false;
      })
      .filter((item) => distanceMetersLatLon(item.lat, item.lon, center[0], center[1]) <= markerRadius);
  }, [data, filters, center, markerRadius, categoryEnabled]);

  const visibleBoundaries = useMemo(() => {
    if (!allBoundaries?.features?.length) return null;
    if (!selectedKommunNames.length || allRegionsSelected) return allBoundaries;
    return {
      ...allBoundaries,
      features: allBoundaries.features.filter((feature) =>
        selectedKommunNames.includes(normalizeAreaName(feature?.properties?.kommunnamn))
      )
    };
  }, [allBoundaries, selectedKommunNames, allRegionsSelected]);

  const scoredBoundaries = useMemo(() => {
    const base = buildScoredBoundaries(
      visibleBoundaries,
      data
        .filter((item) => allowByFilters(item, filters))
        .filter((item) => {
          if (item.category === "food") return categoryEnabled.service;
          if (item.category === "office") return categoryEnabled.cluster;
          if (item.category === "public_transport") return categoryEnabled.accessibility;
          return false;
        }),
      normalizedWeights,
      center,
      null
    );
    if (!base?.features?.length) return base;

    const minScore = intensityRange.min / 100;
    const maxScore = intensityRange.max / 100;
    return {
      ...base,
      features: base.features.filter((feature) => {
        const s = Number(feature?.properties?.score || 0);
        return s >= minScore && s <= maxScore;
      })
    };
  }, [visibleBoundaries, data, filters, normalizedWeights, center, dataMode, categoryEnabled, intensityRange]);

  const counts = useMemo(() => categoryCounts(filtered), [filtered]);
  const avgTravel = useMemo(() => averageTravelMinutes(filtered), [filtered]);
  const score = useMemo(() => potentialScore(filtered), [filtered]);
  const centerTransitInsights = useMemo(() => {
    let nearestBus = null;
    let nearestSubway = null;
    let withinRadius = 0;

    for (const item of data) {
      if (item.category !== "public_transport") continue;
      const meters = distanceMetersLatLon(center[0], center[1], item.lat, item.lon);
      if (item.subtype === "bus_stop") {
        if (!nearestBus || meters < nearestBus.distance) nearestBus = { item, distance: meters };
      }
      if (item.subtype === "subway") {
        if (!nearestSubway || meters < nearestSubway.distance) nearestSubway = { item, distance: meters };
      }
      if (meters <= accessRadiusM) withinRadius += 1;
    }

    return { nearestBus, nearestSubway, withinRadius };
  }, [center, data, accessRadiusM]);

  function setFilter(name, value) {
    setFilters((prev) => ({ ...prev, [name]: value }));
  }

  function saveTempCache(payload) {
    if (typeof window === "undefined") return;
    sessionStorage.setItem(TEMP_CACHE_KEY, JSON.stringify(payload));
  }

  function loadTempCache() {
    if (typeof window === "undefined") return null;
    const raw = sessionStorage.getItem(TEMP_CACHE_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  async function fetchByLatLon(lat, lon, selectedRadius, selectedPlaceName) {
    const fetchKey = `${lat.toFixed(5)}_${lon.toFixed(5)}_${selectedRadius}`;
    if (fetchKey === lastFetchKeyRef.current) return;
    lastFetchKeyRef.current = fetchKey;

    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        lat: String(lat),
        lon: String(lon),
        radius_m: String(selectedRadius),
        place_name: selectedPlaceName
      });
      const osmRes = await fetch(`${API_BASE}/osm/search?${params.toString()}`);
      const osmJson = await osmRes.json();
      if (!osmRes.ok || !Array.isArray(osmJson.items)) throw new Error("Kunde inte hamta OSM-data.");
      setCenter([lat, lon]);
      setData(osmJson.items);
      saveTempCache({
        fetchedAt: new Date().toISOString(),
        dataMode: "live",
        selectedMunicipalities,
        placeName: selectedPlaceName,
        markerRadius,
        center: [lat, lon],
        items: osmJson.items
      });
    } catch {
      setError("Failed to fetch. Kontrollera att backend kor pa port 8000.");
    } finally {
      setLoading(false);
    }
  }

  async function loadLocalDatasets(municipalityIds) {
    if (!municipalityIds.length) {
      setData([]);
      return;
    }

    setLoading(true);
    setError("");
    setLocalLoadError("");
    try {
      const responses = await Promise.allSettled(
        municipalityIds.map(async (id) => {
          const res = await fetch(`${API_BASE}/store/dataset?name=${encodeURIComponent(id)}`);
          const json = await res.json();
          if (!res.ok || !Array.isArray(json.items)) throw new Error(`Kunde inte lasa dataset ${id}.`);
          return json;
        })
      );
      const successful = responses
        .filter((r) => r.status === "fulfilled")
        .map((r) => r.value);
      if (!successful.length) throw new Error("Kunde inte ladda vald lokal data.");

      const failedCount = responses.filter((r) => r.status === "rejected").length;
      if (failedCount > 0) {
        setLocalLoadError(`${failedCount} lokala dataset kunde inte laddas.`);
      }
      const mergedItems = mergeItemsFromDatasets(successful);
      const nextCenter = averageCenterFromItems(mergedItems);
      setCenter(nextCenter);
      setData(mergedItems);
      setPlaceName(
        municipalityIds.length === 1
          ? MUNICIPALITY_OPTIONS.find((x) => x.id === municipalityIds[0])?.label || "Kommun"
          : `${municipalityIds.length} kommuner`
      );
      saveTempCache({
        fetchedAt: new Date().toISOString(),
        dataMode: "local",
        selectedMunicipalities: municipalityIds,
        markerRadius,
        center: nextCenter,
        items: mergedItems
      });
    } catch {
      setLocalLoadError("Kunde inte ladda lokal fil.");
    } finally {
      setLoading(false);
    }
  }

  async function goToPlace() {
    setLoading(true);
    setError("");
    try {
      const geoRes = await fetch(`${API_BASE}/geocode?place=${encodeURIComponent(placeName)}`);
      const geoJson = await geoRes.json();
      if (!geoRes.ok || geoJson.error || geoJson.lat == null || geoJson.lon == null) throw new Error("Kunde inte geokoda platsen.");
      const nextCenter = [geoJson.lat, geoJson.lon];
      setCenter(nextCenter);
      if (dataMode === "live") await fetchByLatLon(geoJson.lat, geoJson.lon, activeFetchRadius, placeName);
      else setLoading(false);
    } catch {
      setError("Failed to fetch. Kontrollera att backend kor pa port 8000.");
      setLoading(false);
    }
  }

  async function handleMapPickCenter(nextCenter) {
    setCenter(nextCenter);
    if (dataMode !== "live") return;
    await fetchByLatLon(nextCenter[0], nextCenter[1], activeFetchRadius, `Kartklick ${nextCenter[0].toFixed(5)}, ${nextCenter[1].toFixed(5)}`);
  }

  function handleSelectSearchPoint() {
    setShowSearchPointPanel(true);
  }

  function resetSearchPointOverrides() {
    setAccessRadiusEnabled(false);
    setTravelTimeEnabled(false);
    setAccessRadiusM(500);
    setTravelTimeMinutes(30);
    setTravelTimePolygon(null);
    setTravelTimeState({ loading: false, enabled: false, error: "" });
  }

  function toggleMunicipality(id, checked) {
    setSelectedMunicipalities((prev) => {
      if (checked) return Array.from(new Set([...prev, id]));
      const next = prev.filter((x) => x !== id);
      return next.length ? next : ["stockholm"];
    });
  }

  function toggleAllMunicipalities(checked) {
    if (checked) setSelectedMunicipalities(MUNICIPALITY_OPTIONS.map((x) => x.id));
    else setSelectedMunicipalities(["stockholm"]);
  }

  useEffect(() => {
    const loadBoundaries = async () => {
      try {
        const res = await fetch(`${API_BASE}/boundaries/regso`);
        if (!res.ok) {
          setBoundariesAvailable(false);
          return;
        }
        const geo = await res.json();
        if (geo?.type === "FeatureCollection" && Array.isArray(geo.features)) {
          setAllBoundaries(geo);
          setBoundariesAvailable(geo.features.length > 0);
        }
      } catch {
        setBoundariesAvailable(false);
      }
    };
    loadBoundaries();
  }, []);

  useEffect(() => {
    if (hasBootstrapped.current) return;
    hasBootstrapped.current = true;
    const cached = loadTempCache();
    if (cached?.center && Array.isArray(cached.items)) {
      setCenter(cached.center);
      setData(cached.items);
      if (cached.placeName) setPlaceName(cached.placeName);
      if (cached.dataMode) setDataMode(cached.dataMode);
      if (Array.isArray(cached.selectedMunicipalities) && cached.selectedMunicipalities.length) setSelectedMunicipalities(cached.selectedMunicipalities);
      if (cached.markerRadius) setMarkerRadius(cached.markerRadius);
      return;
    }
    loadLocalDatasets(["stockholm"]);
  }, []);

  useEffect(() => {
    if (!hasBootstrapped.current || dataMode !== "local") return;
    loadLocalDatasets(selectedMunicipalities);
  }, [dataMode, selectedMunicipalities]);

  useEffect(() => {
    if (!hasBootstrapped.current || dataMode !== "live") return;
    if (radiusTimerRef.current) clearTimeout(radiusTimerRef.current);
    radiusTimerRef.current = setTimeout(() => {
      fetchByLatLon(center[0], center[1], activeFetchRadius, placeName);
    }, 320);
    return () => {
      if (radiusTimerRef.current) clearTimeout(radiusTimerRef.current);
    };
  }, [markerRadius, layerMode, dataMode]);

  useEffect(() => {
    let cancelled = false;

    async function runTimeMap() {
      if (!travelTimeEnabled) {
        setTravelTimePolygon(null);
        setTravelTimeState({ loading: false, enabled: false, error: "" });
        return;
      }

      setTravelTimeState((prev) => ({ ...prev, loading: true, error: "" }));
      try {
        const res = await fetch(`${API_BASE}/analysis/traveltime/timemap`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            origin_lat: center[0],
            origin_lon: center[1],
            max_minutes: travelTimeMinutes,
            transportation_type: "public_transport"
          })
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json?.detail || "TravelTime time-map misslyckades.");
        if (cancelled) return;
        setTravelTimePolygon(json.feature_collection || { type: "FeatureCollection", features: [] });
        setTravelTimeRenderKey((k) => k + 1);
        setTravelTimeState({
          loading: false,
          enabled: Boolean(json.enabled),
          error: json.enabled ? "" : "TravelTime-nycklar saknas i backend."
        });
      } catch (err) {
        if (cancelled) return;
        setTravelTimePolygon(null);
        setTravelTimeRenderKey((k) => k + 1);
        setTravelTimeState({
          loading: false,
          enabled: false,
          error: err?.message || "Kunde inte hamta TravelTime polygon."
        });
      }
    }

    runTimeMap();
    return () => {
      cancelled = true;
    };
  }, [travelTimeEnabled, travelTimeMinutes, center]);

  return (
    <main className="layout">
      <section className="topbar">
        <div>
          <h1>City Layers - Kontorspotential</h1>
          <p>Klickbara polygonomraden med viktad intensitet for Service, Kluster och Tillgänglighet.</p>
        </div>
        <div className="kpi-inline">
          <strong>{counts.total}</strong>
          <span>synliga objekt</span>
        </div>
      </section>

      <section className="content-grid">
        <aside className="panel left">
          <h2>Kontroller</h2>

          <div className="section-row">
            <div className="section-left">
              <button
                type="button"
                className="chevron-btn"
                aria-label="Toggle datakalla"
                onClick={() => setShowDataSource((v) => !v)}
              >
                {showDataSource ? "v" : ">"}
              </button>
              <h3>Datakalla</h3>
            </div>
          </div>
          {showDataSource && (
            <>
              <div className="theme-switch two-col">
                <button type="button" className={dataMode === "local" ? "theme-btn active" : "theme-btn"} onClick={() => setDataMode("local")}>Lokal fil</button>
                <button type="button" className={dataMode === "live" ? "theme-btn active" : "theme-btn"} onClick={() => setDataMode("live")}>Live sok</button>
              </div>
              <p className="small-note">
                {dataMode === "live" ? "Live-lage: andrad radie laddar om data automatiskt." : "Lokal fil-lage: data laddas direkt fran valda kommunfiler utan ny OSM-hamtning."}
              </p>
              {localLoadError && dataMode === "local" && <p className="small-note">{localLoadError}</p>}
            </>
          )}

          <div className="section-row">
            <div className="section-left">
              <button
                type="button"
                className="chevron-btn"
                aria-label="Toggle regioner"
                onClick={() => setShowRegionsSelector((v) => !v)}
              >
                {showRegionsSelector ? "v" : ">"}
              </button>
              <h3>Regioner</h3>
            </div>
          </div>
          {showRegionsSelector && (
            <div className="checkboxes">
              <label><input type="checkbox" checked={allRegionsSelected} onChange={(e) => toggleAllMunicipalities(e.target.checked)} />Visa alla regioner</label>
              {MUNICIPALITY_OPTIONS.map((m) => (
                <label key={m.id}>
                  <input type="checkbox" checked={selectedMunicipalities.includes(m.id)} onChange={(e) => toggleMunicipality(m.id, e.target.checked)} />
                  {m.label}
                </label>
              ))}
            </div>
          )}

          <label>Plats</label>
          <input value={placeName} onChange={(e) => setPlaceName(e.target.value)} />
          <button className="primary" onClick={goToPlace} disabled={loading}>{loading ? "Hamtar..." : "Sök plats"}</button>
          <p className="small-note">Tips: Klicka pa kartan for att flytta centrum och rakna om utifran den punkten.</p>
          {!boundariesAvailable && <p className="small-note">Polygonfil saknas. Kor `python scripts/fetch_regso_geojson.py` for riktiga omradesgranser.</p>}

          <h3>Områdesvikter</h3>
          <label>Service: {weights.service.toFixed(2)}</label>
          <input type="range" min={0} max={1} step={0.01} value={weights.service} onChange={(e) => setWeights((prev) => ({ ...prev, service: Number(e.target.value) }))} />
          <label>Kluster: {weights.cluster.toFixed(2)}</label>
          <input type="range" min={0} max={1} step={0.01} value={weights.cluster} onChange={(e) => setWeights((prev) => ({ ...prev, cluster: Number(e.target.value) }))} />
          <label>Tillgänglighet: {weights.accessibility.toFixed(2)}</label>
          <input type="range" min={0} max={1} step={0.01} value={weights.accessibility} onChange={(e) => setWeights((prev) => ({ ...prev, accessibility: Number(e.target.value) }))} />
          <p className="small-note">
            Normaliserade bidrag: Service {(normalizedWeights.service * 100).toFixed(0)}%, Kluster {(normalizedWeights.cluster * 100).toFixed(0)}%, Tillgänglighet {(normalizedWeights.accessibility * 100).toFixed(0)}%.
          </p>

          <h3>Lagervisning</h3>
          <div className="theme-switch">
            <button type="button" className={layerMode === "markers" ? "theme-btn active" : "theme-btn"} onClick={() => setLayerMode("markers")}>Markorer</button>
            <button type="button" className={layerMode === "regions" ? "theme-btn active" : "theme-btn"} onClick={() => setLayerMode("regions")}>Regioner</button>
            <button type="button" className={layerMode === "both" ? "theme-btn active" : "theme-btn"} onClick={() => setLayerMode("both")}>Båda</button>
          </div>
          <label><input type="checkbox" checked={clusterEnabled} onChange={(e) => setClusterEnabled(e.target.checked)} />Auto-klustra markorer vid utzoomning</label>

          {(layerMode === "markers" || layerMode === "both") && (
            <>
              <label>Marker-radie (meter): {markerRadius} ({(markerRadius / 1000).toFixed(1)} km)</label>
              <input type="range" min={1000} max={20000} step={250} value={markerRadius} onChange={(e) => setMarkerRadius(Number(e.target.value))} />
            </>
          )}
          <div className="section-row">
            <div className="section-left">
              <button
                type="button"
                className="chevron-btn"
                aria-label="Toggle service"
                onClick={() => setShowService((v) => !v)}
              >
                {showService ? "v" : ">"}
              </button>
              <h3>Service</h3>
            </div>
            <input
              className="switch-only"
              aria-label="Toggle Service"
              type="checkbox"
              checked={categoryEnabled.service}
              onChange={(e) => setCategoryEnabled((p) => ({ ...p, service: e.target.checked }))}
            />
          </div>
          {showService && (
            <div className="checkboxes">
              <label><input type="checkbox" checked={filters.foodCafe} onChange={(e) => setFilter("foodCafe", e.target.checked)} />Cafe</label>
              <label><input type="checkbox" checked={filters.foodRestaurant} onChange={(e) => setFilter("foodRestaurant", e.target.checked)} />Restaurang</label>
              <label><input type="checkbox" checked={filters.foodFastFood} onChange={(e) => setFilter("foodFastFood", e.target.checked)} />Fast food</label>
              <label><input type="checkbox" checked={filters.foodCourt} onChange={(e) => setFilter("foodCourt", e.target.checked)} />Food court</label>
            </div>
          )}

          <div className="section-row">
            <div className="section-left">
              <button
                type="button"
                className="chevron-btn"
                aria-label="Toggle kluster"
                onClick={() => setShowCluster((v) => !v)}
              >
                {showCluster ? "v" : ">"}
              </button>
              <h3>Kluster</h3>
            </div>
            <input
              className="switch-only"
              aria-label="Toggle Kluster"
              type="checkbox"
              checked={categoryEnabled.cluster}
              onChange={(e) => setCategoryEnabled((p) => ({ ...p, cluster: e.target.checked }))}
            />
          </div>
          {showCluster && (
            <div className="checkboxes">
              <label><input type="checkbox" checked={filters.officeTag} onChange={(e) => setFilter("officeTag", e.target.checked)} />Office-taggar</label>
              <label><input type="checkbox" checked={filters.officeBuilding} onChange={(e) => setFilter("officeBuilding", e.target.checked)} />Building office</label>
              <label><input type="checkbox" checked={filters.officePotential} onChange={(e) => setFilter("officePotential", e.target.checked)} />Kommersiella kontorslika byggnader</label>
            </div>
          )}

          <div className="section-row">
            <div className="section-left">
              <button
                type="button"
                className="chevron-btn"
                aria-label="Toggle tillgänglighet"
                onClick={() => setShowAccessibility((v) => !v)}
              >
                {showAccessibility ? "v" : ">"}
              </button>
              <h3>Tillgänglighet</h3>
            </div>
            <input
              className="switch-only"
              aria-label="Toggle Tillgänglighet"
              type="checkbox"
              checked={categoryEnabled.accessibility}
              onChange={(e) => setCategoryEnabled((p) => ({ ...p, accessibility: e.target.checked }))}
            />
          </div>
          {showAccessibility && (
            <div className="checkboxes">
              <label><input type="checkbox" checked={filters.transportBus} onChange={(e) => setFilter("transportBus", e.target.checked)} />Busshallplats / busstation</label>
              <label><input type="checkbox" checked={filters.transportSubway} onChange={(e) => setFilter("transportSubway", e.target.checked)} />Tunnelbana</label>
              <label><input type="checkbox" checked={filters.transportTrain} onChange={(e) => setFilter("transportTrain", e.target.checked)} />Tag / station</label>
            </div>
          )}

          {error && <p className="error">{error}</p>}
        </aside>

        <section className="map-panel">
          <div className="map-theme-floating">
            <div className="theme-switch">
              <button type="button" className={mapTheme === "dark" ? "theme-btn active" : "theme-btn"} onClick={() => setMapTheme("dark")}>Mörk</button>
              <button type="button" className={mapTheme === "light" ? "theme-btn active" : "theme-btn"} onClick={() => setMapTheme("light")}>Ljus</button>
              <button type="button" className={mapTheme === "satellite" ? "theme-btn active" : "theme-btn"} onClick={() => setMapTheme("satellite")}>Satellit</button>
            </div>
          </div>
          <MapPanel
            center={center}
            points={filtered}
            mapTheme={mapTheme}
            scoredBoundaries={scoredBoundaries}
            regionRenderKey={`r_${intensityRange.min}_${intensityRange.max}_${scoredBoundaries?.features?.length || 0}`}
            layerMode={layerMode}
            clusterEnabled={clusterEnabled}
            onPickCenter={handleMapPickCenter}
            onSelectSearchPoint={handleSelectSearchPoint}
            accessCircle={{ enabled: accessRadiusEnabled, center, radius_m: accessRadiusM }}
            travelTimePolygon={travelTimePolygon}
            travelTimeRenderKey={travelTimeRenderKey}
            forceShowMarkers={accessRadiusEnabled}
            forcedMarkerCategory={accessRadiusEnabled ? "public_transport" : null}
          />
          {showSearchPointPanel && (
            <div className="marker-flyout">
              <div className="marker-flyout-header">
                <strong>Sökpunkt</strong>
                <button type="button" className="close-flyout" onClick={() => setShowSearchPointPanel(false)}>X</button>
              </div>
              <p className="small-note">Radie- och restidsfunktioner fran vald sokpunkt.</p>
              <div className="metric compact"><span>Center</span><strong>{center[0].toFixed(5)}, {center[1].toFixed(5)}</strong></div>
              <label className="small-note">
                <input type="checkbox" checked={accessRadiusEnabled} onChange={(e) => setAccessRadiusEnabled(e.target.checked)} />
                {" "}Närhet till tillgänglighet
              </label>
              <label className="small-note">Närhetsradie: {accessRadiusM} m</label>
              <input
                type="range"
                min={10}
                max={3000}
                step={10}
                value={accessRadiusM}
                onChange={(e) => setAccessRadiusM(Number(e.target.value))}
              />
              <div className="metric compact">
                <span>Närmaste tunnelbana</span>
                <strong>
                  {centerTransitInsights.nearestSubway
                    ? `${formatMeters(centerTransitInsights.nearestSubway.distance)} ${centerTransitInsights.nearestSubway.distance <= accessRadiusM ? "OK" : ""}`
                    : "Saknas"}
                </strong>
              </div>
              <div className="metric compact">
                <span>Närmaste buss</span>
                <strong>
                  {centerTransitInsights.nearestBus
                    ? `${formatMeters(centerTransitInsights.nearestBus.distance)} ${centerTransitInsights.nearestBus.distance <= accessRadiusM ? "OK" : ""}`
                    : "Saknas"}
                </strong>
              </div>
              <div className="metric compact"><span>Tillgänglighet inom radie</span><strong>{centerTransitInsights.withinRadius}</strong></div>

              <label className="small-note">
                <input type="checkbox" checked={travelTimeEnabled} onChange={(e) => setTravelTimeEnabled(e.target.checked)} />
                {" "}TravelTime distance map
              </label>
              <label className="small-note">Restid: {travelTimeMinutes} min</label>
              <input
                type="range"
                min={5}
                max={90}
                step={5}
                value={travelTimeMinutes}
                onChange={(e) => setTravelTimeMinutes(Number(e.target.value))}
              />
              <div className="metric compact">
                <span>TravelTime polygon</span>
                <strong>
                  {travelTimeState.loading ? "Beraknar..." : travelTimeState.enabled ? "Visas pa karta" : "Inaktiv"}
                </strong>
              </div>
              <button type="button" className="range-reset-btn" onClick={resetSearchPointOverrides}>
                Återställ sökpunkt
              </button>
              {travelTimeState.error && <p className="small-note">{travelTimeState.error}</p>}
            </div>
          )}
        </section>

        <aside className="panel right">
          <h2>Analys</h2>
          <div className="metric"><span>Transformationsindex</span><strong>{score}/100</strong></div>
          <div className="metric"><span>Kluster</span><strong>{counts.office}</strong></div>
          <div className="metric"><span>Service</span><strong>{counts.food}</strong></div>
          <div className="metric"><span>Tillgänglighet</span><strong>{counts.public_transport}</strong></div>
          <div className="metric"><span>Områden med signal</span><strong>{scoredBoundaries?.features?.length || 0}</strong></div>
          <div className="metric"><span>Snittrestid</span><strong>{avgTravel == null ? "saknas" : `${avgTravel.toFixed(1)} min`}</strong></div>
          <div className="metric">
            <span>Fargskala intensitet</span>
            <div className="intensity-bar" />
            <div className="intensity-labels">
              <small>Svag (0%)</small>
              <small>Medium (50%)</small>
              <small>Stark (100%)</small>
            </div>
            <div className="range-values">
              <small>{intensityRange.min}%</small>
              <small>{intensityRange.max}%</small>
            </div>
            <button
              type="button"
              className="range-reset-btn"
              onClick={() => setIntensityRange({ min: 0, max: 100 })}
              disabled={intensityRange.min === 0 && intensityRange.max === 100}
            >
              Återställ
            </button>
            <p className="small-note">Visar regioner inom {intensityRange.min}% - {intensityRange.max}%.</p>
            <div className="dual-range">
              <div className="dual-range-track" />
              <div
                className="dual-range-fill"
                style={{
                  left: `${intensityRange.min}%`,
                  width: `${Math.max(0, intensityRange.max - intensityRange.min)}%`
                }}
              />
              <input
                className="dual-range-input"
                type="range"
                min={0}
                max={100}
                step={1}
                value={intensityRange.min}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  setIntensityRange((prev) => ({ ...prev, min: Math.min(next, prev.max) }));
                }}
              />
              <input
                className="dual-range-input"
                type="range"
                min={0}
                max={100}
                step={1}
                value={intensityRange.max}
                onChange={(e) => {
                  const next = Number(e.target.value);
                  setIntensityRange((prev) => ({ ...prev, max: Math.max(next, prev.min) }));
                }}
              />
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}


