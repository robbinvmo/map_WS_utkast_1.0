import streamlit as st

from services.cache_service import build_cache_path, load_json, save_json
from services.geocode_service import geocode_place
from services.osm_service import fetch_osm_data, normalize_osm_elements
from services.traveltime_service import (
    attach_traveltime_to_destinations,
    get_traveltime_one_to_many,
    has_traveltime_credentials,
)
from ui.controls import render_sidebar
from ui.map_view import filter_layers, render_map

DEFAULT_STOCKHOLM_CENTER = (59.3293, 18.0686)


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(1200px 400px at 10% -10%, rgba(56, 189, 248, 0.18), transparent 55%),
                radial-gradient(900px 360px at 100% 0%, rgba(20, 184, 166, 0.14), transparent 55%),
                linear-gradient(180deg, #050a14 0%, #070d18 100%);
            color: #e2e8f0;
        }
        .stSidebar {
            background: linear-gradient(180deg, #0b1220 0%, #111827 100%);
        }
        .dashboard-title {
            padding: 16px 20px;
            border-radius: 14px;
            border: 1px solid rgba(94, 234, 212, 0.25);
            background: rgba(15, 23, 42, 0.7);
            margin-bottom: 12px;
        }
        .dashboard-title h1 {
            margin: 0;
            font-size: 1.9rem;
            font-weight: 700;
            color: #dbeafe;
            letter-spacing: .02em;
        }
        .dashboard-title p {
            margin: 6px 0 0;
            color: #94a3b8;
            font-size: 0.95rem;
        }
        .metric-card {
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.25);
            background: rgba(15, 23, 42, 0.7);
            padding: 12px 14px;
            min-height: 96px;
        }
        .metric-label {
            color: #94a3b8;
            font-size: 0.8rem;
            letter-spacing: .06em;
            text-transform: uppercase;
        }
        .metric-value {
            color: #e2e8f0;
            font-size: 1.9rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 4px;
        }
        .metric-sub {
            color: #67e8f9;
            font-size: 0.85rem;
            margin-top: 2px;
        }
        .insight-card {
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.2);
            background: rgba(15, 23, 42, 0.74);
            padding: 16px;
            margin-bottom: 12px;
        }
        .insight-card h3 {
            margin: 0 0 8px;
            color: #67e8f9;
            font-size: 1rem;
            letter-spacing: .04em;
        }
        .insight-card p {
            margin: 0;
            color: #cbd5e1;
            font-size: 0.93rem;
            line-height: 1.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, subtext: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{label}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-sub">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def count_by_category(data: list[dict]) -> dict:
    counts = {"office": 0, "food": 0, "public_transport": 0, "other": 0}
    for item in data:
        category = item.get("category", "other")
        if category not in counts:
            category = "other"
        counts[category] += 1
    return counts


def avg_travel_minutes(data: list[dict]) -> float | None:
    travel_minutes = [x["travel_time_sec"] / 60 for x in data if x.get("travel_time_sec") is not None]
    if not travel_minutes:
        return None
    return sum(travel_minutes) / len(travel_minutes)


def potential_score(data: list[dict]) -> tuple[int, str]:
    counts = count_by_category(data)
    avg_tt = avg_travel_minutes(data)

    office_signal = min(counts["office"] / 45, 1) * 40
    service_signal = min(counts["food"] / 60, 1) * 25
    transport_signal = min(counts["public_transport"] / 60, 1) * 25

    if avg_tt is None:
        travel_signal = 5
    else:
        travel_signal = max(0, 10 - min(avg_tt, 60) / 6)

    score = round(office_signal + service_signal + transport_signal + travel_signal)

    if score >= 75:
        return score, "Stark indikation"
    if score >= 50:
        return score, "Mellanindikation"
    return score, "Svag indikation"


st.set_page_config(page_title="City Layers - Kontorspotential", layout="wide")
inject_theme()

st.markdown(
    """
    <div class="dashboard-title">
      <h1>City Layers - Kontorspotential</h1>
      <p>Kombinerad analys av kontor, service, kollektivtrafik och restid för att identifiera transformationsmöjligheter.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

controls = render_sidebar()

if "data" not in st.session_state:
    st.session_state["data"] = []
if "center" not in st.session_state:
    st.session_state["center"] = DEFAULT_STOCKHOLM_CENTER
if "last_place" not in st.session_state:
    st.session_state["last_place"] = "Stockholm"
if "last_radius" not in st.session_state:
    st.session_state["last_radius"] = 0

if controls["run_search"]:
    place_name = controls["place_name"]
    radius_m = controls["radius_m"]

    geo = geocode_place(place_name)
    if not geo:
        st.error("Kunde inte hitta platsen.")
        st.stop()

    st.session_state["center"] = (geo["lat"], geo["lon"])
    st.session_state["last_place"] = geo["display_name"] or place_name
    st.session_state["last_radius"] = radius_m

    cache_path = build_cache_path(place_name, radius_m)
    cached = load_json(cache_path)

    if cached is not None:
        data = cached
        st.info(f"Laddade cache: {cache_path.name}")
    else:
        raw = fetch_osm_data(geo["lat"], geo["lon"], radius_m)
        data = normalize_osm_elements(raw)
        save_json(data, cache_path)
        st.success(f"Sparade cache: {cache_path.name}")

    if controls["use_traveltime"]:
        offices = [x for x in data if x["category"] == "office"][:30]

        if has_traveltime_credentials():
            tt = get_traveltime_one_to_many(
                origin_lat=geo["lat"],
                origin_lon=geo["lon"],
                destinations=offices,
                transportation_type="public_transport",
            )
            offices_enriched = attach_traveltime_to_destinations(offices, tt)

            office_lookup = {o["id"]: o for o in offices_enriched}
            merged = []
            for item in data:
                if item["id"] in office_lookup:
                    merged.append(office_lookup[item["id"]])
                else:
                    merged.append(item)
            data = merged
        else:
            st.warning("TravelTime-nycklar saknas i .env.")

    st.session_state["data"] = data

data = st.session_state["data"]
center = st.session_state["center"]

filtered = filter_layers(
    data,
    show_offices=controls["show_offices"],
    show_food=controls["show_food"],
    show_transport=controls["show_transport"],
)
counts = count_by_category(filtered)
avg_tt = avg_travel_minutes(filtered)
score, score_label = potential_score(filtered)

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    metric_card("Total synliga", str(len(filtered)), "objekt i kartvy")
with m2:
    metric_card("Kontor", str(counts["office"]), "kärnlager")
with m3:
    metric_card("Service", str(counts["food"]), "fik/café/restaurang")
with m4:
    metric_card("Kollektivtrafik", str(counts["public_transport"]), "buss/tåg/tunnelbana")
with m5:
    tt_text = f"{avg_tt:.1f} min" if avg_tt is not None else "saknas"
    metric_card("Restid", tt_text, "TravelTime")

left_col, right_col = st.columns([2.6, 1.1])

with left_col:
    render_map(
        center[0],
        center[1],
        filtered,
        map_mode=controls["map_mode"],
        show_heatmap=controls["show_heatmap"],
    )
    if not filtered:
        st.info("Visar Stockholm som standard. Hämta data för att se lager och kluster.")

with right_col:
    st.markdown(
        f"""
        <div class="insight-card">
          <h3>TRANSFORMATIONSPOTENTIAL</h3>
          <p>
            <strong>Index: {score}/100</strong><br>
            {score_label}<br><br>
            Område: {st.session_state["last_place"]}<br>
            Radie: {st.session_state["last_radius"]} meter
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="insight-card">
          <h3>ANALYSLOGIK</h3>
          <p>
            Högre signal uppstår när kontorskärna, service och kollektivtrafik
            sammanfaller. Restidslagret nyanserar den faktiska tillgängligheten.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.dataframe(
        [
            {
                "name": x["name"],
                "category": x["category"],
                "travel_time_min": round(x["travel_time_sec"] / 60, 1) if x.get("travel_time_sec") else None,
            }
            for x in filtered
        ],
        use_container_width=True,
        height=340,
    )

with st.expander("Målbild för verktyget", expanded=False):
    st.write(
        "Målet är att identifiera urbana områden med potential för kontorsetablering "
        "eller kontorstransformation genom att kombinera kontor, service, kollektivtrafik "
        "och restid i en gemensam klusteranalys. Hämtad data sparas lokalt för snabb återanvändning."
    )
