import streamlit as st


def render_sidebar():
    st.sidebar.header("Analysinställningar")

    place_name = st.sidebar.text_input("Sök plats", value="Stockholm Centralstation")
    radius_m = st.sidebar.slider("Sökradie (meter)", 300, 5000, 1500, 100)

    st.sidebar.subheader("Lager")
    show_offices = st.sidebar.checkbox("Kontor", value=True)
    show_food = st.sidebar.checkbox("Fik / café / restaurang", value=True)
    show_transport = st.sidebar.checkbox("Kollektivtrafik", value=True)

    st.sidebar.subheader("Karta")
    map_mode = st.sidebar.radio("Visningsläge", options=["Punkter", "Kluster"], horizontal=True)
    show_heatmap = st.sidebar.checkbox("Visa intensitetskarta", value=True)

    st.sidebar.subheader("TravelTime")
    use_traveltime = st.sidebar.checkbox("Visa restid till kontor", value=False)

    run_search = st.sidebar.button("Hämta data", use_container_width=True)

    return {
        "place_name": place_name,
        "radius_m": radius_m,
        "show_offices": show_offices,
        "show_food": show_food,
        "show_transport": show_transport,
        "map_mode": map_mode.lower(),
        "show_heatmap": show_heatmap,
        "use_traveltime": use_traveltime,
        "run_search": run_search,
    }
