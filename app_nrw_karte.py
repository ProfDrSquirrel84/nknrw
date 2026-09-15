import json
from pathlib import Path
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="NRW Kommunen-Monitoring", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "daten.csv"
GEOJSON_PATH = BASE_DIR / "nrw_gemeinden.geojson"


@st.cache_data
def load_data():
    if not DATA_PATH.is_file():
        st.error(f"Datei 'daten.csv' nicht gefunden: {DATA_PATH}")
        st.stop()

    df = pd.read_csv(DATA_PATH, sep=None, engine="python", dtype=str)
    df.columns = df.columns.str.strip()

    # AGS-Spalte flexibel ermitteln
    ags_col = next((c for c in df.columns if "AGS" in c.upper()), None)
    if not ags_col:
        st.error(f"Keine AGS-Spalte gefunden! Vorhanden: {list(df.columns)}")
        st.stop()

    df = df.rename(columns={ags_col: "AGS"})
    df["AGS"] = df["AGS"].astype(str).str.extract(r"(\d+)")[0].str.zfill(8)
    return df


@st.cache_data
def load_geojson():
    if not GEOJSON_PATH.is_file():
        st.error(
            f"Datei 'nrw_gemeinden.geojson' fehlt. Bitte erst die Konvertierung ausführen!"
        )
        st.stop()

    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


df = load_data()
geojson_data = load_geojson()

st.title("🗺️ NRW-Kommunen: Projektübersicht & Einstufung")

# Variablenauswahl für Einfärbung
ignore_cols = ["AGS", "ARS", "ARS (12-stellig)", "Bevölkerung", "Bevoelkerung"]
available_vars = [c for c in df.columns if c not in ignore_cols]
selected_var = st.sidebar.selectbox(
    "Färbung nach Variable:", available_vars, index=0
)

# Farbpalette erzeugen
unique_vals = sorted(df[selected_var].dropna().unique().tolist())
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
color_map = {
    val: PALETTE[i % len(PALETTE)] for i, val in enumerate(unique_vals)
}

# Lookup-Dictionary: AGS -> Wert
lookup_dict = dict(zip(df["AGS"], df[selected_var]))


def get_ags_from_props(props):
    # Geobasis NRW verwendet in DVG meist 'AGS', 'SCH', 'SCHLUESSEL' oder 'GMD'
    for k in ["AGS", "SCH", "SCHLUESSEL", "GMD", "ARS"]:
        val = props.get(k)
        if val:
            digits = "".join(filter(str.isdigit, str(val)))
            if len(digits) >= 8:
                return digits[:8]
            elif digits:
                return digits.zfill(8)
    return ""


def get_name_from_props(props):
    # Geobasis NRW nutzt in DVG meist 'GN' (Gemeindename) oder 'GEN'
    for k in ["GN", "GEN", "NAME", "GMD_NAME"]:
        if props.get(k):
            return props[k]
    return "Gemeinde"


# Kartenstyling
def style_fn(feature):
    props = feature.get("properties", {})
    ags = get_ags_from_props(props)

    if ags in lookup_dict:
        val = lookup_dict[ags]
        return {
            "fillColor": color_map.get(val, "#3182ce"),
            "color": "#1A202C",
            "weight": 1.5,
            "fillOpacity": 0.85,
        }
    return {
        "fillColor": "#F7FAFC",
        "color": "#CBD5E0",
        "weight": 0.4,
        "fillOpacity": 0.2,
    }


# Folium Map zentriert auf NRW
m = folium.Map(location=[51.45, 7.50], zoom_start=8, tiles="CartoDB positron")

# Tooltip-Eigenschaft dynamisch identifizieren (GN oder GEN)
sample_props = geojson_data["features"][0].get("properties", {})
tooltip_field = next(
    (k for k in ["GN", "GEN", "NAME", "GMD_NAME"] if k in sample_props), None
)

tooltip = (
    folium.GeoJsonTooltip(fields=[tooltip_field], aliases=["Kommune:"])
    if tooltip_field
    else None
)

folium.GeoJson(
    geojson_data, name="Gemeinden", style_function=style_fn, tooltip=tooltip
).add_to(m)

# Layout
c_map, c_leg = st.columns([3, 1])

with c_map:
    st_folium(m, width="100%", height=650)

with c_leg:
    st.subheader("Legende")
    for val, color in color_map.items():
        st.markdown(
            f'<div style="display:flex; align-items:center; margin-bottom:6px;">'
            f'<div style="background-color:{color}; width:18px; height:18px; border-radius:3px; margin-right:8px;"></div>'
            f'<span style="font-size:14px;">{val}</span></div>',
            unsafe_allow_html=True,
        )
    st.divider()
    st.metric("Erfasste Kommunen", len(df["Kommune"].unique()))

with st.expander("Tabellarische Übersicht"):
    st.dataframe(df, use_container_width=True)
