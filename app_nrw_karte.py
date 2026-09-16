import json
from pathlib import Path
import folium
import pandas as pd
import plotly.express as px
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

    # Spalten für Bevölkerung und Partei matchen
    bev_col = next(
        (
            c
            for c in df.columns
            if any(x in c.upper() for x in ["BEVÖLKERUNG", "BEVOELKERUNG", "EINWOHNER"])
        ),
        None,
    )
    if bev_col and bev_col != "Bevoelkerung":
        df["Bevoelkerung"] = df[bev_col]

    partei_col = next(
        (c for c in df.columns if "PARTEI" in c.upper()),
        None,
    )
    if partei_col and partei_col != "Partei":
        df["Partei"] = df[partei_col]

    def parse_pop(val):
        digits = "".join(filter(str.isdigit, str(val)))
        return int(digits) if digits else None

    if "Bevoelkerung" in df.columns:
        df["Bevoelkerung_Num"] = df["Bevoelkerung"].apply(parse_pop)

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

st.title("🗺️ NRW-Kommunen: Übersicht & Beteiligung")

# Schneller Daten-Lookup per AGS
data_by_ags = df.set_index("AGS").to_dict(orient="index")
recorded_ags_set = set(df["AGS"])

# GeoJSON-Properties für den Tooltip vorbereiten
for feat in geojson_data["features"]:
    props = feat["properties"]
    ags = str(props.get("AGS", "")).strip().zfill(8)
    row = data_by_ags.get(ags)

    if row:
        props["Info_Status"] = row.get("Status_Beschluss", "-")
        props["Info_Angebot"] = row.get("Angebot", "-")
        props["Info_Einstieg"] = row.get("Einstiegszeitpunkt", "-")
        props["Info_Typ"] = row.get("Typ", "-")
        props["Info_RB"] = row.get("Regierungsbezirk", "-")
        props["Info_Partei"] = row.get("Partei", "-")

        pop_num = row.get("Bevoelkerung_Num")
        if pd.notnull(pop_num):
            props["Info_Bevoelkerung"] = f"{int(pop_num):,}".replace(",", ".")
        else:
            props["Info_Bevoelkerung"] = row.get("Bevoelkerung", "-")

        props["Im_Projekt"] = "Ja"
    else:
        props["Info_Status"] = "Nicht erfasst"
        props["Info_Angebot"] = "-"
        props["Info_Einstieg"] = "-"
        props["Info_Typ"] = "-"
        props["Info_RB"] = "-"
        props["Info_Partei"] = "-"
        props["Info_Bevoelkerung"] = "-"
        props["Im_Projekt"] = "Nein"

# Such- und Zentrierfunktion
kommune_list = sorted(df["Kommune"].dropna().unique().tolist())
search_kommune = st.sidebar.selectbox(
    "🔍 Kommune suchen & zentrieren:",
    ["(NRW Übersicht)"] + kommune_list,
    index=0,
)

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

    if ags in recorded_ags_set:
        is_highlighted = (
            search_kommune != "(NRW Übersicht)"
            and data_by_ags[ags].get("Kommune") == search_kommune
        )
        return {
            "fillColor": "#00689D",
            "color": "#FFD700" if is_highlighted else "#0F2942",
            "weight": 3.0 if is_highlighted else 1.2,
            "fillOpacity": 0.85,
        }

    return {
        "fillColor": "#CBD5E1",
        "color": "#94A3B8",
        "weight": 0.5,
        "fillOpacity": 0.2,
    }


def highlight_fn(feature):
    props = feature.get("properties", {})
    ags = str(props.get("AGS", "")).strip().zfill(8)

    if ags in recorded_ags_set:
        return {
            "fillColor": "#26BDE2",
            "color": "#0F2942",
            "weight": 2.8,
            "fillOpacity": 0.95,
        }
    return {
        "fillColor": "#94A3B8",
        "color": "#475569",
        "weight": 1.8,
        "fillOpacity": 0.45,
    }


# Folium-Karte (OpenStreetMap ohne API-Key)
m = folium.Map(location=center_loc, zoom_start=zoom_lvl, tiles="OpenStreetMap")

tooltip_style = """
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 11px;
    line-height: 1.35;
    padding: 6px 10px;
    background-color: #ffffff;
    color: #1a202c;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12);
"""

tooltip = folium.GeoJsonTooltip(
    fields=[
        "GEN",
        "Im_Projekt",
        "Info_Bevoelkerung",
        "Info_Partei",
        "Info_Status",
        "Info_Angebot",
        "Info_Einstieg",
        "Info_Typ",
        "Info_RB",
    ],
    aliases=[
        "Kommune:",
        "Projektteilnahme:",
        "Bevölkerung:",
        "Partei:",
        "Beschluss:",
        "Angebot:",
        "Start:",
        "Typ:",
        "Regierungsbezirk:",
    ],
    style=tooltip_style,
    localize=True,
    sticky=False,
)

folium.GeoJson(
    geojson_data,
    name="Gemeinden",
    style_function=style_fn,
    highlight_function=highlight_fn,
    tooltip=tooltip,
).add_to(m)

# Layout: 65% Karte, 35% Dashboard & Diagramm
col_map, col_side = st.columns([65, 35])

with col_map:
    map_output = st_folium(
        m,
        width="100%",
        height=740,
        returned_objects=["last_active_drawing"],
    )

with col_side:
    st.subheader("Übersicht")
    st.markdown(
        '<div style="display:flex; align-items:center; margin-bottom:6px;">'
        '<div style="background-color:#00689D; width:15px; height:15px; border-radius:3px; margin-right:8px; flex-shrink:0;"></div>'
        '<span style="font-size:13px; line-height:1.2;"><b>Erfasste Kommune</b></span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="display:flex; align-items:center; margin-bottom:10px;">'
        '<div style="background-color:#CBD5E1; border:1px solid #94A3B8; width:15px; height:15px; border-radius:3px; margin-right:8px; flex-shrink:0;"></div>'
        '<span style="font-size:13px; color:#475569; line-height:1.2;">Nicht erfasst</span></div>',
        unsafe_allow_html=True,
    )

    kpi1, kpi2 = st.columns(2)
    kpi1.metric("Kommunen", len(df["Kommune"].unique()))
    kpi2.metric("Anträge", len(df))

    if "Bevoelkerung_Num" in df.columns:
        total_pop = df["Bevoelkerung_Num"].sum()
        if pd.notnull(total_pop) and total_pop > 0:
            st.metric("Erfasste Einwohner", f"{int(total_pop):,}".replace(",", "."))

    st.markdown("---")

    # Auswahlfeld: Welche Tabellenspalte soll im Diagramm visualisiert werden?
    exclude_from_chart = ["AGS", "ARS", "Bevoelkerung_Num"]
    chart_candidates = [c for c in df.columns if c not in exclude_from_chart]

    # Vorauswahl bevorzugt auf Bevölkerung oder Regierungsbezirk setzen
    default_idx = 0
    if "Bevoelkerung" in chart_candidates:
        default_idx = chart_candidates.index("Bevoelkerung")
    elif "Regierungsbezirk" in chart_candidates:
        default_idx = chart_candidates.index("Regierungsbezirk")

    selected_chart_col = st.selectbox(
        "📊 Diagramm-Inhalt auswählen:",
        options=chart_candidates,
        index=default_idx,
    )

    # 1. Fall: Bevölkerung (metrische Auswertung je Kommune)
    if any(x in selected_chart_col.upper() for x in ["BEVÖLKERUNG", "BEVOELKERUNG", "EINWOHNER"]):
        df_chart = df.dropna(subset=["Bevoelkerung_Num"]).sort_values("Bevoelkerung_Num", ascending=True)
        if not df_chart.empty:
            fig = px.bar(
                df_chart,
                x="Bevoelkerung_Num",
                y="Kommune",
                orientation="h",
                text="Bevoelkerung_Num",
                color_discrete_sequence=["#00689D"],
            )
            fig.update_traces(
                texttemplate="%{text:,.0f}",
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=max(400, len(df_chart) * 20),
                margin=dict(l=0, r=45, t=10, b=10),
                xaxis_title="",
                yaxis_title="",
                xaxis=dict(showticklabels=False, showgrid=False),
                yaxis=dict(tickfont=dict(size=11)),
            )
            st.plotly_chart(fig, use_container_width=True)

    # 2. Fall: Kategoriale Variable (Häufigkeitsverteilung)
    else:
        df_sub = df.dropna(subset=[selected_chart_col]).copy()
        if not df_sub.empty:
            counts = (
                df_sub[selected_chart_col]
                .value_counts()
                .reset_index()
            )
            counts.columns = [selected_chart_col, "Anzahl"]
            counts = counts.sort_values(by="Anzahl", ascending=True)

            fig = px.bar(
                counts,
                x="Anzahl",
                y=selected_chart_col,
                orientation="h",
                text="Anzahl",
                color_discrete_sequence=["#00689D"],
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                height=max(320, len(counts) * 32),
                margin=dict(l=0, r=30, t=10, b=10),
                xaxis_title="Fallzahl",
                yaxis_title="",
                yaxis=dict(tickfont=dict(size=11)),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten für dieses Merkmal vorhanden.")

# Factsheet bei Klick auf ein Polygon
clicked_feature = map_output.get("last_active_drawing") if map_output else None
if clicked_feature:
    clicked_props = clicked_feature.get("properties", {})
    clicked_ags = str(clicked_props.get("AGS", "")).zfill(8)

    if clicked_ags in data_by_ags:
        details = data_by_ags[clicked_ags]
        st.info(f"### 📍 Factsheet: {details.get('Kommune')}")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"<span style='font-size: 13px;'><b>Typ:</b> {details.get('Typ', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Regierungsbezirk:</b> {details.get('Regierungsbezirk', '-')}</span>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<span style='font-size: 13px;'><b>Bevölkerung:</b> {clicked_props.get('Info_Bevoelkerung', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Partei:</b> {details.get('Partei', '-')}</span>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<span style='font-size: 13px;'><b>BBSR-Einordnung:</b> {details.get('BBSR_Einordnung', '-') or '-'}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Beschlussstatus:</b> {details.get('Status_Beschluss', '-')}</span>", unsafe_allow_html=True)
        with c4:
            st.markdown(f"<span style='font-size: 13px;'><b>Projektangebot:</b> {details.get('Angebot', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Einstieg:</b> {details.get('Einstiegszeitpunkt', '-') or '-'}</span>", unsafe_allow_html=True)
