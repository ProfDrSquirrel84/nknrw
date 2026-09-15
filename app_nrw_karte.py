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
        st.error(f"Keine AGS-Spalte gefunden! Vorhanden: {list(df.columns)}")
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

# 1. Variablen- und Ausprägungsfilter
ignore_patterns = [
    "AGS",
    "ARS",
    "BEVÖLKERUNG",
    "BEVOELKERUNG",
    "KOMMUNE",
    "DETAILS",
]
available_vars = [
    c for c in df.columns if not any(p in c.upper() for p in ignore_patterns)
]
if not available_vars:
    available_vars = [c for c in df.columns if c not in ["AGS", "Kommune"]]

selected_var = st.sidebar.selectbox("Variable auswählen:", available_vars, index=0)

val_counts = df[selected_var].dropna().value_counts().to_dict()
all_unique_vals = sorted(val_counts.keys())

selected_values = st.sidebar.multiselect(
    "Ausprägungen filtern:",
    options=all_unique_vals,
    default=all_unique_vals,
    format_func=lambda x: f"{x} ({val_counts.get(x, 0)} Fälle)",
)

df_filtered = df[df[selected_var].isin(selected_values)].copy()

# 2. Farbpalette
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
color_map = {val: PALETTE[i % len(PALETTE)] for i, val in enumerate(all_unique_vals)}

# Schnelles Nachschlagen: AGS -> Datenzeile
data_by_ags = df.set_index("AGS").to_dict(orient="index")
active_ags_set = set(df_filtered["AGS"])

# 3. GeoJSON-Properties dynamisch anreichern für aussagekräftige Tooltips
for feat in geojson_data["features"]:
    props = feat["properties"]
    ags = str(props.get("AGS", "")).strip().zfill(8)
    row = data_by_ags.get(ags)
    if row:
        props["Info_Status"] = row.get("Status_Beschluss", "-")
        props["Info_Angebot"] = row.get("Angebot", "-")
        props["Info_Einstieg"] = row.get("Einstiegszeitpunkt", "-")
        props["Info_Partei"] = row.get("Partei", "-")
        props["Info_Aktiv"] = "Ja" if ags in active_ags_set else "Ausgefiltert"
    else:
        props["Info_Status"] = "Nicht im Projekt"
        props["Info_Angebot"] = "-"
        props["Info_Einstieg"] = "-"
        props["Info_Partei"] = "-"
        props["Info_Aktiv"] = "Nein"

# 4. Such- und Zoomfunktion
kommune_list = sorted(df["Kommune"].dropna().unique().tolist())
search_kommune = st.sidebar.selectbox(
    "🔍 Kommune suchen & zentrieren:",
    ["(NRW Übersicht)"] + kommune_list,
    index=0,
)

# Koordinatenberechnung bei Einzelsuche
center_loc = [51.45, 7.50]
zoom_lvl = 8

if search_kommune != "(NRW Übersicht)":
    target_row = df[df["Kommune"] == search_kommune]
    if not target_row.empty:
        target_ags = target_row.iloc[0]["AGS"]
        for feat in geojson_data["features"]:
            if str(feat["properties"].get("AGS", "")).zfill(8) == target_ags:
                geom = feat["geometry"]
                coords = (
                    geom["coordinates"][0]
                    if geom["type"] == "Polygon"
                    else geom["coordinates"][0][0]
                )
                avg_lat = sum(pt[1] for pt in coords) / len(coords)
                avg_lon = sum(pt[0] for pt in coords) / len(coords)
                center_loc = [avg_lat, avg_lon]
                zoom_lvl = 11
                break


def style_fn(feature):
    props = feature.get("properties", {})
    ags = str(props.get("AGS", "")).strip().zfill(8)

    # Kommune ist aktiv im gefilterten Datensatz
    if ags in active_ags_set:
        val = data_by_ags[ags].get(selected_var)
        is_highlighted = (
            search_kommune != "(NRW Übersicht)"
            and data_by_ags[ags].get("Kommune") == search_kommune
        )
        return {
            "fillColor": color_map.get(val, "#3182ce"),
            "color": "#FFD700" if is_highlighted else "#1A202C",
            "weight": 3.0 if is_highlighted else 1.6,
            "fillOpacity": 0.9 if is_highlighted else 0.8,
        }

    # Hintergrund für alle übrigen Kommunen
    return {
        "fillColor": "#F8FAFC",
        "color": "#94A3B8",
        "weight": 0.4,
        "fillOpacity": 0.1,
    }


# Kartenerstellung mit dezenten Tiles (Positron für maximale Kontraste)
m = folium.Map(location=center_loc, zoom_start=zoom_lvl, tiles="CartoDB positron")

tooltip = folium.GeoJsonTooltip(
    fields=["GEN", "Info_Status", "Info_Angebot", "Info_Einstieg", "Info_Partei"],
    aliases=["Kommune:", "Beschluss:", "Angebot:", "Start:", "Partei:"],
    localize=True,
    sticky=False,
)

folium.GeoJson(
    geojson_data,
    name="Gemeinden",
    style_function=style_fn,
    tooltip=tooltip,
).add_to(m)

# 5. Layout & Anzeige
col_map, col_legend = st.columns([3, 1])

with col_map:
    # Nur Klick-Objekte abfangen, um Reruns beim bloßen Verschieben/Zoomen zu verhindern
    map_output = st_folium(
        m,
        width="100%",
        height=680,
        returned_objects=["last_active_drawing"],
    )

with col_legend:
    st.subheader("Legende")
    for val in selected_values:
        color = color_map[val]
        count = len(df_filtered[df_filtered[selected_var] == val])
        st.markdown(
            f'<div style="display:flex; align-items:center; margin-bottom:8px;">'
            f'<div style="background-color:{color}; width:18px; height:18px; border-radius:3px; margin-right:8px; flex-shrink:0;"></div>'
            f'<span style="font-size:14px; line-height:1.2;"><b>{val}</b>: {count}</span></div>',
            unsafe_allow_html=True,
        )
    st.divider()
    st.metric("Ausgewählte Kommunen", len(df_filtered["Kommune"].unique()))
    st.metric("Gefilterte Anträge", len(df_filtered))
    st.caption(f"Gesamtbestand: {len(df)} Einträge")

# 6. Detail-Factsheet bei Klick auf ein Polygon
clicked_feature = map_output.get("last_active_drawing") if map_output else None
if clicked_feature:
    clicked_props = clicked_feature.get("properties", {})
    clicked_ags = str(clicked_props.get("AGS", "")).zfill(8)
    if clicked_ags in data_by_ags:
        details = data_by_ags[clicked_ags]
        st.info(f"### 📍 Factsheet: {details.get('Kommune')}")
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"**Typ:** {details.get('Typ', '-')}")
        c1.markdown(f"**Regierungsbezirk:** {details.get('Regierungsbezirk', '-')}")
        c2.markdown(f"**Bevölkerung:** {details.get('Bevoelkerung', '-')}")
        c2.markdown(f"**Partei (OB/BM):** {details.get('Partei', '-')}")
        c3.markdown(f"**BBSR-Einordnung:** {details.get('BBSR_Einordnung', '-')}")
        c3.markdown(f"**Beschlussstatus:** {details.get('Status_Beschluss', '-')}")
        c4.markdown(f"**Projektangebot:** {details.get('Angebot', '-')}")
        c4.markdown(f"**Einstieg:** {details.get('Einstiegszeitpunkt', '-')}")

# 7. Tabellenübersicht & CSV-Export
with st.expander("Tabellarische Übersicht (Gefiltert)", expanded=False):
    st.dataframe(df_filtered, use_container_width=True)
    csv_bytes = df_filtered.to_csv(sep=";", index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 Gefilterte Tabelle als CSV herunterladen",
        data=csv_bytes,
        file_name="nrw_kommunen_gefiltert.csv",
        mime="text/csv",
    )
