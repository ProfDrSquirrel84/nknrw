import json
from pathlib import Path
import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="NRW Kommunen-Monitoring", layout="wide")

DATA_PATH = Path(__file__).resolve().parent / "daten.csv"

@st.cache_data
def load_data():
    if not DATA_PATH.is_file():
        st.error(f"Datei 'daten.csv' nicht gefunden unter: {DATA_PATH}")
        st.stop()
    
    # Trennzeichen automatisch erkennen (Semikolon, Tab oder Komma)
    df = pd.read_csv(DATA_PATH, sep=None, engine="python", dtype=str)
    
    # Spaltennamen bereinigen: Führende/nachlaufende Leerzeichen entfernen
    df.columns = df.columns.str.strip()
    
    # Finde die Spalte, die 'AGS' enthält (z. B. 'AGS (8-stellig)' oder 'AGS')
    ags_col = next((c for c in df.columns if "AGS" in c.upper()), None)
    if not ags_col:
        st.error(f"Keine AGS-Spalte gefunden! Vorhandene Spalten: {list(df.columns)}")
        st.stop()
        
    df = df.rename(columns={ags_col: "AGS"})
    
    # Bereinigung: Reine Ziffern extrahieren und auf 8 Stellen mit führenden Nullen bringen
    df["AGS"] = df["AGS"].astype(str).str.extract(r"(\d+)")[0]
    df = df.dropna(subset=["AGS"])
    df["AGS"] = df["AGS"].str.zfill(8)
    return df

@st.cache_data
def load_geojson():
    # Saubere NRW-Gemeindegrenzen mit amtlichem AGS
    url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/4_gemeinden/4_nordrhein-westfalen.geo.json"
    r = requests.get(url, timeout=30)
    return r.json()

df = load_data()
geojson_data = load_geojson()

st.title("🗺️ NRW-Kommunen: Monitoring & Strategieprozesse")

# Spaltenauswahl für die farbliche Kategorisierung
ignore_cols = ["AGS", "ARS", "ARS (12-stellig)", "Bevölkerung", "Bevoelkerung"]
available_vars = [c for c in df.columns if c not in ignore_cols]

selected_var = st.sidebar.selectbox("Färbung nach Variable:", available_vars, index=0)

# Farbpalette erzeugen
unique_vals = sorted(df[selected_var].dropna().unique().tolist())
PALETTE = [
    "#E5243B", "#4C9F38", "#FD9D24", "#00689D", "#DD1367", 
    "#26BDE2", "#FCC30B", "#A21942", "#FD6925", "#3F7E44"
]
color_map = {val: PALETTE[i % len(PALETTE)] for i, val in enumerate(unique_vals)}

# Schnelles Mapping via Dictionary: AGS -> Attributwert
lookup_dict = dict(zip(df["AGS"], df[selected_var]))

# Karte initialisieren
m = folium.Map(location=[51.45, 7.50], zoom_start=8, tiles="CartoDB positron")

def get_feature_ags(props):
    """Ermittelt den 8-stelligen AGS unabhängig vom Attributnamen im GeoJSON."""
    for key in ["AGS", "id", "AGS_8", "cca_2", "schluessel"]:
        if key in props and props[key]:
            clean = "".join(filter(str.isdigit, str(props[key])))
            if clean:
                return clean.zfill(8)
    return ""

def style_fn(feature):
    props = feature.get("properties", {})
    ags_geo = get_feature_ags(props)
    
    if ags_geo in lookup_dict:
        val = lookup_dict[ags_geo]
        color = color_map.get(val, "#3182ce")
        return {
            "fillColor": color,
            "color": "#1A202C",
            "weight": 1.5,
            "fillOpacity": 0.85,
        }
    return {
        "fillColor": "#EDF2F7",
        "color": "#CBD5E0",
        "weight": 0.5,
        "fillOpacity": 0.25,
    }

folium.GeoJson(
    geojson_data,
    name="NRW-Gemeinden",
    style_function=style_fn,
    tooltip=folium.GeoJsonTooltip(
        fields=["GEN"],
        aliases=["Kommune:"],
        localize=True
    )
).add_to(m)

# Layout
col_map, col_info = st.columns([3, 1])

with col_map:
    st_folium(m, width="100%", height=650)

with col_info:
    st.subheader("Legende")
    for val, color in color_map.items():
        st.markdown(
            f'<div style="display:flex; align-items:center; margin-bottom:6px;">'
            f'<div style="background-color:{color}; width:18px; height:18px; border-radius:3px; margin-right:8px;"></div>'
            f'<span style="font-size:14px;">{val}</span></div>',
            unsafe_allow_html=True
        )
    st.divider()
    st.metric("Erfasste Datensätze", len(df))

with st.expander("Tabellendaten anzeigen"):
    st.dataframe(df, use_container_width=True)
