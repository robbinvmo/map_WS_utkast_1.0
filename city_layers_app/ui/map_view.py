import folium
from folium.plugins import HeatMap, MarkerCluster
from streamlit_folium import st_folium


def _category_color(category: str) -> str:
    if category == "office":
        return "#5eead4"
    if category == "food":
        return "#f59e0b"
    if category == "public_transport":
        return "#f87171"
    return "#94a3b8"


def filter_layers(data: list[dict], show_offices: bool, show_food: bool, show_transport: bool) -> list[dict]:
    filtered = []
    for item in data:
        cat = item["category"]
        if cat == "office" and show_offices:
            filtered.append(item)
        elif cat == "food" and show_food:
            filtered.append(item)
        elif cat == "public_transport" and show_transport:
            filtered.append(item)
    return filtered


def _add_legend(map_obj: folium.Map) -> None:
    legend = """
    <div style="
        position: fixed;
        bottom: 20px;
        left: 20px;
        z-index: 9999;
        background: rgba(10, 16, 30, 0.88);
        color: #e2e8f0;
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 12px;
        padding: 12px 14px;
        min-width: 180px;
        font-size: 12px;
        line-height: 1.5;
    ">
      <div style="font-weight:700;letter-spacing:.04em;margin-bottom:8px;">TECKENFÖRKLARING</div>
      <div><span style="color:#5eead4;">●</span> Kontor</div>
      <div><span style="color:#f59e0b;">●</span> Service (fik/restaurang)</div>
      <div><span style="color:#f87171;">●</span> Kollektivtrafik</div>
    </div>
    """
    map_obj.get_root().html.add_child(folium.Element(legend))


def render_map(
    center_lat: float,
    center_lon: float,
    data: list[dict],
    map_mode: str = "punkter",
    show_heatmap: bool = True,
):
    map_obj = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=14,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    folium.CircleMarker(
        [center_lat, center_lon],
        radius=8,
        tooltip="Sökt plats",
        popup="Sökt plats",
        color="#ffffff",
        weight=2,
        fill=True,
        fill_color="#38bdf8",
        fill_opacity=0.95,
    ).add_to(map_obj)

    layer = map_obj
    if map_mode == "kluster":
        layer = MarkerCluster(name="Kluster").add_to(map_obj)

    for item in data:
        travel_text = ""
        if item.get("travel_time_sec") is not None:
            mins = round(item["travel_time_sec"] / 60)
            travel_text = f"<br>Restid: {mins} min"

        popup_html = f"""
        <b>{item['name']}</b><br>
        Kategori: {item['category']}
        {travel_text}
        """

        folium.CircleMarker(
            [item["lat"], item["lon"]],
            radius=5,
            tooltip=item["name"],
            popup=popup_html,
            color=_category_color(item["category"]),
            weight=1,
            fill=True,
            fill_color=_category_color(item["category"]),
            fill_opacity=0.88,
        ).add_to(layer)

    if show_heatmap and data:
        heat_data = [[x["lat"], x["lon"], 1.0] for x in data]
        HeatMap(
            heat_data,
            radius=18,
            blur=15,
            min_opacity=0.35,
            gradient={
                0.2: "#1e293b",
                0.4: "#0ea5e9",
                0.6: "#22d3ee",
                0.8: "#f59e0b",
                1.0: "#fb7185",
            },
        ).add_to(map_obj)

    _add_legend(map_obj)
    folium.LayerControl(position="topright").add_to(map_obj)
    st_folium(map_obj, width=None, height=760, use_container_width=True)
