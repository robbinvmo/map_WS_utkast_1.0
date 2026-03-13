import { useEffect, useMemo, useState } from "react";
import { Circle, CircleMarker, GeoJSON, MapContainer, Pane, Popup, TileLayer, ZoomControl, useMap, useMapEvents } from "react-leaflet";

const MAP_THEMES = {
  light: {
    label: "Ljus",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  },
  dark: {
    label: "Mörk",
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, &copy; <a href="https://carto.com/attributions">CARTO</a>'
  },
  satellite: {
    label: "Satellit",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community"
  }
};

function scoreColor(score) {
  const clamped = Math.max(0, Math.min(1, score || 0));
  const hue = 220 - clamped * 220;
  return `hsl(${hue}, 82%, 52%)`;
}

function RecenterOnChange({ center }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center);
  }, [map, center]);
  return null;
}

function ZoomListener({ onZoomChange }) {
  const map = useMapEvents({
    zoomend: () => onZoomChange(map.getZoom())
  });

  useEffect(() => {
    onZoomChange(map.getZoom());
  }, [map, onZoomChange]);

  return null;
}

function ClickCenterPicker({ onPickCenter }) {
  useMapEvents({
    click: (event) => {
      if (!onPickCenter) return;
      onPickCenter([event.latlng.lat, event.latlng.lng]);
    }
  });
  return null;
}

function latLonToPixel(lat, lon, zoom) {
  const sinLat = Math.sin((lat * Math.PI) / 180);
  const scale = 256 * 2 ** zoom;
  const x = ((lon + 180) / 360) * scale;
  const y = (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale;
  return { x, y };
}

function categoryColor(category, subtype, isCluster = false) {
  if (category === "office") return isCluster ? "#22d3ee" : "#5eead4";
  if (category === "food") {
    if (subtype === "cafe") return "#facc15";
    if (subtype === "restaurant") return "#f59e0b";
    if (subtype === "fast_food") return "#fb7185";
    return "#fde68a";
  }
  if (category === "public_transport") {
    if (subtype === "subway") return "#c084fc";
    if (subtype === "train") return "#60a5fa";
    if (subtype === "bus_stop") return "#f87171";
    return "#fca5a5";
  }
  return "#94a3b8";
}

function clusterByCategory(points, zoom) {
  if (zoom >= 14) {
    return points.map((p) => ({
      id: p.id,
      lat: p.lat,
      lon: p.lon,
      category: p.category,
      subtype: p.subtype,
      count: 1,
      names: [p.name]
    }));
  }

  const gridSizePx = zoom <= 10 ? 90 : zoom <= 12 ? 70 : 55;
  const buckets = new Map();

  for (const p of points) {
    const px = latLonToPixel(p.lat, p.lon, zoom);
    const gx = Math.floor(px.x / gridSizePx);
    const gy = Math.floor(px.y / gridSizePx);
    const key = `${p.category}_${gx}_${gy}`;

    if (!buckets.has(key)) {
      buckets.set(key, {
        id: key,
        latSum: 0,
        lonSum: 0,
        count: 0,
        category: p.category,
        subtype: p.subtype,
        names: []
      });
    }

    const b = buckets.get(key);
    b.latSum += p.lat;
    b.lonSum += p.lon;
    b.count += 1;
    if (b.names.length < 5) b.names.push(p.name);
  }

  return Array.from(buckets.values()).map((b) => ({
    id: b.id,
    lat: b.latSum / b.count,
    lon: b.lonSum / b.count,
    category: b.category,
    subtype: b.subtype,
    count: b.count,
    names: b.names
  }));
}

function clusterRadius(count) {
  if (count <= 1) return 6;
  if (count <= 5) return 10;
  if (count <= 15) return 14;
  if (count <= 40) return 18;
  return 22;
}

function distanceMetersLatLon(lat1, lon1, lat2, lon2) {
  const dLat = (lat1 - lat2) * 111320;
  const dLon = (lon1 - lon2) * 111320 * Math.cos(((lat1 + lat2) / 2) * (Math.PI / 180));
  return Math.sqrt(dLat * dLat + dLon * dLon);
}

export default function MapPanel({
  center,
  points,
  mapTheme,
  scoredBoundaries,
  regionRenderKey,
  layerMode,
  clusterEnabled,
  onPickCenter,
  onSelectSearchPoint,
  accessCircle,
  travelTimePolygon,
  travelTimeRenderKey,
  forceShowMarkers,
  forcedMarkerCategory
}) {
  const theme = MAP_THEMES[mapTheme] || MAP_THEMES.light;
  const [zoom, setZoom] = useState(13);

  const showMarkers = layerMode === "markers" || layerMode === "both" || Boolean(forceShowMarkers);
  const showRegions = layerMode === "regions" || layerMode === "both";
  const markerSource = useMemo(() => {
    let next = points;
    if (forcedMarkerCategory) {
      next = next.filter((p) => p.category === forcedMarkerCategory);
    }
    if (accessCircle?.enabled && accessCircle?.center && Number.isFinite(accessCircle?.radius_m)) {
      next = next.filter(
        (p) =>
          distanceMetersLatLon(p.lat, p.lon, accessCircle.center[0], accessCircle.center[1]) <= accessCircle.radius_m
      );
    }
    return next;
  }, [points, forcedMarkerCategory, accessCircle]);
  const markerClusters = useMemo(() => {
    if (!showMarkers) return [];
    if (!clusterEnabled) {
      return markerSource.map((p) => ({
        id: p.id,
        lat: p.lat,
        lon: p.lon,
        category: p.category,
        subtype: p.subtype,
        count: 1,
        names: [p.name]
      }));
    }
    return clusterByCategory(markerSource, zoom);
  }, [markerSource, zoom, showMarkers, clusterEnabled]);

  return (
    <MapContainer center={center} zoom={13} zoomControl={false} className="map-root" scrollWheelZoom>
      <RecenterOnChange center={center} />
      <ZoomListener onZoomChange={setZoom} />
      <ClickCenterPicker onPickCenter={onPickCenter} />
      <TileLayer attribution={theme.attribution} url={theme.url} />
      <ZoomControl position="bottomleft" />

      {showRegions && scoredBoundaries?.features?.length > 0 && (
        <GeoJSON
          key={regionRenderKey || "regions"}
          data={scoredBoundaries}
          style={(feature) => {
            const score = feature?.properties?.score || 0;
            return {
              color: scoreColor(score),
              fillColor: scoreColor(score),
              fillOpacity: 0.22 + score * 0.45,
              weight: 2
            };
          }}
          onEachFeature={(feature, layer) => {
            const props = feature.properties || {};
            const regionName = props.region_name || props.regso || props.name || props.omrade || "Område";
            const popupHtml = `
              <div class="popup-card">
                <div class="popup-kicker">Område</div>
                <div class="popup-title">${regionName}</div>
                <div class="popup-row">Intensitet <strong>${((props.score || 0) * 100).toFixed(1)}%</strong></div>
                <div class="popup-row">Service <strong>${props.serviceCount || 0}</strong></div>
                <div class="popup-row">Klusterffekt <strong>${props.officeCount || 0}</strong></div>
                <div class="popup-row">Tillgänglighet <strong>${props.trafficCount || 0}</strong></div>
              </div>
            `;
            layer.bindPopup(popupHtml, { className: "city-popup", maxWidth: 420 });
          }}
        />
      )}

      {travelTimePolygon?.features?.length > 0 && (
        <GeoJSON
          key={`timemap_${travelTimeRenderKey || 0}`}
          data={travelTimePolygon}
          style={() => ({
            color: "#22d3ee",
            fillColor: "#06b6d4",
            fillOpacity: 0.16,
            weight: 2
          })}
        />
      )}

      {accessCircle?.enabled && (
        <Circle
          center={accessCircle.center}
          radius={accessCircle.radius_m}
          pathOptions={{
            color: "#f59e0b",
            fillColor: "#f59e0b",
            fillOpacity: 0.1,
            weight: 2
          }}
        />
      )}

      <Pane name="search-point-pane" style={{ zIndex: 800 }}>
        <CircleMarker
          center={center}
          radius={13}
          pathOptions={{ color: "#0ea5e9", fillColor: "#22d3ee", fillOpacity: 0.95, weight: 3 }}
          eventHandlers={{
            click: () => {
              if (!onSelectSearchPoint) return;
              onSelectSearchPoint({ lat: center[0], lon: center[1], name: "Sökpunkt" });
            }
          }}
        >
          <Popup className="city-popup" maxWidth={420}>
            <div className="popup-card">
              <div className="popup-kicker">Sökpunkt</div>
              <div className="popup-title">Vald plats</div>
            </div>
          </Popup>
        </CircleMarker>
      </Pane>

      {showMarkers &&
        markerClusters.map((item) => (
          <CircleMarker
            key={item.id}
            center={[item.lat, item.lon]}
            radius={clusterRadius(item.count)}
            pathOptions={{
              color: categoryColor(item.category, item.subtype, item.count > 1),
              fillColor: categoryColor(item.category, item.subtype, item.count > 1),
              fillOpacity: item.count > 1 ? 0.65 : 0.85,
              weight: item.count > 1 ? 2 : 1.4
            }}
          >
            <Popup className="city-popup" maxWidth={420}>
              <div className="popup-card">
                <div className="popup-kicker">{item.count > 1 ? "Kluster" : "Objekt"}</div>
                <div className="popup-title">
                  {item.count > 1 ? `${item.count} objekt` : item.names?.[0] || "Objekt"}
                </div>
                <div className="popup-row">Kategori <strong>{item.category}</strong></div>
                <div className="popup-row">
                  {item.count > 1 ? "Klusterniva" : "Typ"}
                  {" "}
                  <strong>{item.count > 1 ? `z${zoom}` : item.subtype || "okand"}</strong>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
    </MapContainer>
  );
}

