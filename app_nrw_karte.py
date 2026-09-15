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

    try:
        df = pd.read_csv(DATA_PATH, sep=";", dtype=str, encoding="utf-8")
        if df.shape[1] == 1:
            df = pd.read_csv(
                DATA_PATH,
                sep=None,
                engine="python",
                dtype=str,
                encoding="utf-8",
            )
    except Exception:
        df = pd.read_csv(
            DATA_PATH, sep=None, engine="python", dtype=str, encoding="utf-8"
        )

    df.columns = df.columns.astype(str).str.strip()
    ags_col = next((c for c in df.columns if "AGS" in c.upper()), None)
    if not ags_col:
        st.error(
            f"Keine AGS-Spalte gefunden! Vorhanden: {list(df.columns)}"
        )
        st.stop()

    df = df.rename(columns={ags_col: "AGS"})
    df["AGS"] = (
        df["AGS"].astype(str).str.extract(r"(\d+)")[0].dropna().str.zfill(8)
    )

    if "Kommune" not in df.columns:
        kom_col = next(
            (
                c
                for c in df.columns
                if any(
                    x in c.upper() for x in ["KOMMUNE", "NAME", "STADT", "GEMEINDE"]
                )
            ),
            None,
        )
        df["Kommune"] = df[kom_col] if kom_col else df["AGS"]

    return df


@st.cache_data
def load_geojson():
    if not GEOJSON_PATH.is_file():
        st.error(f"Datei 'nrw_gemeinden.geojson' fehlt: {GEOJSON_PATH}")
        st.stop()
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


df = load_data()
geojson_data = load_geojson()

st.title("🗺️ NRW-Kommunen: Projektübersicht & Einstufung")

# Sidebar
ignore_patterns = [
    "AGS",
    "ARS",
    "BEVÖLKERUNG",
    "BEVOELKERUNG",
    "KOMMUNE",
    "DETAILS",
]
available_vars = [
    c
    for c in df.columns
    if not any(p in c.upper() for p in ignore_patterns)
]
if not available_vars:
    available_vars = [c for c in df.columns if c not in ["AGS", "Kommune"]]

selected_var = st.sidebar.selectbox("Färbung nach Variable:", available_vars, index=0)

# Kategoriale Farbpalette
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
color_map = {val: PALETTE[i % len(PALETTE)] for i, val in enumerate(unique_vals)}

# Direktes Lookup: 8-stelliger AGS -> Wert (inkl. 5-stelligem Kreisfallback)
lookup_dict = {}
for _, row in df.iterrows():
    val = row[selected_var]
    ags = str(row["AGS"]).strip()
    lookup_dict[ags] = val
    if len(ags) >= 5:
        lookup_dict[ags[:5]] = val


def style_fn(feature):
    props = feature.get("properties", {})
    ags = str(props.get("AGS", "")).strip()

    # Match auf 8 Ziffern oder 5 Ziffern (Kreis)
    val = lookup_dict.get(ags) or lookup_dict.get(ags[:5])

    if val is not None:
        return {
            "fillColor": color_map.get(val, "#3182ce"),
            "color": "#1A202C",
            "weight": 1.6,
            "fillOpacity": 0.85,
        }
    return {
        "fillColor": "#F7FAFC",
        "color": "#CBD5E0",
        "weight": 0.4,
        "fillOpacity": 0.15,
    }


m = folium.Map(location=[51.45, 7.50], zoom_start=8, tiles="OpenStreetMap")

tooltip = folium.GeoJsonTooltip(fields=["GEN"], aliases=["Kommune:"])

folium.GeoJson(
    geojson_data,
    name="Gemeinden",
    style_function=style_fn,
    tooltip=tooltip,
).add_to(m)

# Layout
col_map, col_legend = st.columns([3, 1])

with col_map:
    st_folium(m, width="100%", height=680)

with col_legend:
    st.subheader("Legende")
    for val, color in color_map.items():
        st.markdown(
            f'<div style="display:flex; align-items:center; margin-bottom:8px;">'
            f'<div style="background-color:{color}; width:18px; height:18px; border-radius:3px; margin-right:8px; flex-shrink:0;"></div>'
            f'<span style="font-size:14px; line-height:1.2;">{val}</span></div>',
            unsafe_allow_html=True,
        )
    st.divider()
    st.metric("Erfasste Kommunen", len(df["Kommune"].unique()))
    st.metric("Gesamtanträge", len(df))

with st.expander("Tabellarische Übersicht"):
    st.dataframe(df, use_container_width=True)
