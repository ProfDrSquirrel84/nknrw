import json
from pathlib import Path
import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="NRW Kommunen-Monitoring", layout="wide")

# 1. Daten einlesen & AGS formatieren
DATA_PATH = Path(__file__).resolve().parent / "daten.csv"


@st.cache_data
def load_data():
    df = pd.read_csv(DATA_PATH, sep=";", dtype=str)
    # Bereinigung: Führende Nullen auf 8 Stellen auffüllen
    df["AGS"] = df["AGS"].str.extract(r"(\d+)")[0].str.zfill(8)
    return df


# 2. GeoJSON der NRW-Gemeindegrenzen cachen
@st.cache_data
def load_geojson():
    url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/4_gemeinden/4_nordrhein-westfalen.geo.json"
    r = requests.get(url, timeout=20)
    return r.json()


df = load_data()
geojson_data = load_geojson()

st.title("🗺️ NRW-Kommunen: Projektübersicht & Einstufung")

# Sidebar: Dynamische Auswahl der Variable für die Einfärbung/Hervorhebung
st.sidebar.header("Filter & Visualisierung")

variable_options = {
    "Vorerfahrung": "Einstufung Vorerfahrung",
    "Angebot": "Beantragtes Angebot",
    "Status Beschluss": "Status Beschluss",
    "Einstiegszeitpunkt": "Bevorzugter Einstiegszeitpunkt (Standard)",
    "Regierungsbezirk": "Regierungsbezirk",
    "Partei": "Partei BM/OB/LR",
}

# Falls abweichende Spaltenbezeichner vorliegen, anpassen
col_name_mapping = {
    "Vorerfahrung": "Vorerfahrung",
    "Angebot": "Angebot",
    "Status Beschluss": "Status_Beschluss",
    "Einstiegszeitpunkt": "Einstiegszeitpunkt",
    "Regierungsbezirk": "Regierungsbezirk",
    "Partei": "Partei",
}

selected_var_label = st.sidebar.selectbox("Färbung nach Variable:", list(col_name_mapping.keys()))
active_col = col_name_mapping[selected_var_label]

# Farbpalette für Kategorien
PALETTE = [
    "#E5243B",
    "#4C9F38",
    "#FD9D24",
    "#00689D",
    "#DD1367",
    "#26BDE2",
    "#FCC30B",
    "#A21942",
    "#FD6925",
    "#3F7E44",
]
unique_vals = sorted(df[active_col].dropna().unique().tolist())
color_map = {val: PALETTE[i % len(PALETTE)] for i, val in enumerate(unique_vals)}

# Dictionary für schnellen O(1)-Lookup nach AGS (letzten Status nehmen bei Duplikaten)
df_lookup = df.drop_duplicates(subset=["AGS"], keep="last").set_index("AGS")

# 3. Folium Karte initialisieren (Zentrum NRW: ca. 51.45, 7.50)
m = folium.Map(location=[51.45, 7.50], zoom_start=8, tiles="CartoDB positron")


# Style-Funktion für GeoJSON-Polygone
def style_fn(feature):
    # Der AGS im GeoJSON liegt typischerweise unter properties.AGS oder properties.id
    props = feature.get("properties", {})
    ags_geo = str(props.get("AGS") or props.get("id") or "").zfill(8)

    if ags_geo in df_lookup.index:
        val = df_lookup.loc[ags_geo, active_col]
        color = color_map.get(val, "#FD6925")
        return {
            "fillColor": color,
            "color": "#1A202C",
            "weight": 1.5,
            "fillOpacity": 0.85,
        }
    else:
        # Nicht in der Tabelle enthaltene NRW-Gemeinden
        return {
            "fillColor": "#EDF2F7",
            "color": "#CBD5E0",
            "weight": 0.5,
            "fillOpacity": 0.3,
        }


# Interaktive GeoJSON-Ebene hinzufügen
folium.GeoJson(
    geojson_data,
    name="NRW-Kommunen",
    style_function=style_fn,
    tooltip=folium.GeoJsonTooltip(
        fields=["GEN"],  # Im Standard-GeoJSON steht 'GEN' für den Gemeindenamen
        aliases=["Kommune:"],
        localize=True,
    ),
).add_to(m)

# Layout: Karte links, Legende & Details rechts
c_map, c_details = st.columns([3, 1])

with c_map:
    st_folium(m, width="100%", height=650)

with c_details:
    st.subheader("Legende")
    for val, color in color_map.items():
        st.markdown(
            f'<div style="display:flex; align-items:center; margin-bottom:6px;">'
            f'<div style="background-color:{color}; width:20px; height:20px; border-radius:3px; margin-right:8px;"></div>'
            f'<span>{val}</span></div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.metric("Erfasste Kommunen", len(df["Kommune"].unique()))

# Tabelle anzeigen
with st.expander("Vollständige Datentabelle anzeigen"):
    st.dataframe(df, use_container_width=True)