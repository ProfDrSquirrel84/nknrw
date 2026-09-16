import json
from pathlib import Path
import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="NRW Kommunen-Monitoring", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "daten.csv"
GEOJSON_GEMEINDEN = BASE_DIR / "nrw_gemeinden.geojson"
GEOJSON_KREISE = BASE_DIR / "nrw_kreise.geojson"

# GitHub Fallback-URL (wird nur verwendet, falls nrw_kreise.geojson lokal fehlen sollte)
GITHUB_KREISE_RAW_URL = "https://raw.githubusercontent.com/<DEIN_GITHUB_USER>/<DEIN_REPO>/main/nrw_kreise.geojson"


def clean_val(val, default="-"):
    """Bereinigt NaN/None/Leerwerte, damit Leaflet/Folium nicht abstürzt."""
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    return default if s in ("", "nan", "None", "<NA>") else s


# ==============================================================================
# 1. Daten laden & bereinigen
# ==============================================================================
@st.cache_data
def load_data():
    if not DATA_PATH.is_file():
        st.error(f"Datei 'daten.csv' nicht gefunden: {DATA_PATH}")
        st.stop()

    try:
        # utf-8-sig fängt das Windows-BOM sauber ab
        df = pd.read_csv(DATA_PATH, sep=";", dtype=str, encoding="utf-8-sig")
        if df.shape[1] == 1:
            df = pd.read_csv(
                DATA_PATH, sep=None, engine="python", dtype=str, encoding="utf-8-sig"
            )
    except Exception:
        df = pd.read_csv(
            DATA_PATH, sep=None, engine="python", dtype=str, encoding="utf-8-sig"
        )

    df.columns = df.columns.astype(str).str.strip()

    ags_col = next((c for c in df.columns if "AGS" in c.upper()), None)
    if not ags_col:
        st.error(f"Keine AGS-Spalte gefunden! Spalten: {list(df.columns)}")
        st.stop()

    df = df.rename(columns={ags_col: "AGS"})
    # Bereinigter Match-Key ohne führende Nullen
    df["AGS_MATCH"] = (
        df["AGS"].astype(str).str.extract(r"(\d+)")[0].dropna().str.lstrip("0")
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

    bev_col = next(
        (
            c
            for c in df.columns
            if any(x in c.upper() for x in ["BEVÖLKERUNG", "BEVOELKERUNG", "EINWOHNER"])
        ),
        None,
    )
    if bev_col and bev_col != "Bevölkerung":
        df["Bevölkerung"] = df[bev_col]

    def parse_pop(val):
        digits = "".join(filter(str.isdigit, str(val)))
        return int(digits) if digits else None

    if "Bevölkerung" in df.columns:
        df["Bevoelkerung_Num"] = df["Bevölkerung"].apply(parse_pop)

    beschluss_col = next(
        (c for c in df.columns if "BESCHLUSS" in c.upper()),
        None,
    )
    if beschluss_col and beschluss_col != "Beschluss NKNRW":
        df["Beschluss NKNRW"] = df[beschluss_col]

    return df


@st.cache_data
def load_geojsons():
    if not GEOJSON_GEMEINDEN.is_file():
        st.error(f"Datei 'nrw_gemeinden.geojson' fehlt: {GEOJSON_GEMEINDEN}")
        st.stop()
    with open(GEOJSON_GEMEINDEN, "r", encoding="utf-8") as f:
        gemeinden_data = json.load(f)

    # Nur Features mit gültiger Geometrie übernehmen
    gemeinden_data["features"] = [
        f for f in gemeinden_data.get("features", []) if f.get("geometry")
    ]

    kreise_data = None
    if GEOJSON_KREISE.is_file():
        with open(GEOJSON_KREISE, "r", encoding="utf-8") as f:
            kreise_data = json.load(f)
    elif "<DEIN_GITHUB_USER>" not in GITHUB_KREISE_RAW_URL:
        try:
            resp = requests.get(GITHUB_KREISE_RAW_URL, timeout=10)
            if resp.status_code == 200:
                kreise_data = resp.json()
        except Exception:
            kreise_data = None

    if kreise_data:
        kreise_data["features"] = [
            f for f in kreise_data.get("features", []) if f.get("geometry")
        ]

    return gemeinden_data, kreise_data


df = load_data()
geojson_data, geojson_kreise = load_geojsons()

st.title("🗺️ NRW-Kommunen: Übersicht & Beteiligung")

# ==============================================================================
# 2. Aggregation & Semikolon-Paarung
# ==============================================================================
data_by_match_key = {}
total_applications_count = 0

for _, row in df.iterrows():
    match_key = str(row["AGS_MATCH"]).strip()

    raw_ang = clean_val(row.get("Angebot"))
    raw_start = clean_val(row.get("Einstiegszeitpunkt"))

    ang_list = [
        a.strip()
        for a in raw_ang.split(";")
        if a.strip() and a.strip() not in ("-", "nan")
    ]
    start_list = [
        s.strip()
        for s in raw_start.split(";")
        if s.strip() and s.strip() not in ("-", "nan")
    ]

    paired_offers = []

    if len(ang_list) == 1 and len(start_list) > 1:
        alt_starts = " oder ".join(start_list)
        paired_offers.append({
            "angebot": ang_list[0],
            "start": f"{alt_starts} (alternativ)",
        })
        total_applications_count += 1
    elif len(ang_list) > 1 and len(start_list) == len(ang_list):
        for ang, st_time in zip(ang_list, start_list):
            paired_offers.append({
                "angebot": ang,
                "start": st_time,
            })
        total_applications_count += len(ang_list)
    elif ang_list:
        for idx, ang in enumerate(ang_list):
            st_val = (
                start_list[idx]
                if idx < len(start_list)
                else (", ".join(start_list) if start_list else "-")
            )
            paired_offers.append({
                "angebot": ang,
                "start": st_val,
            })
        total_applications_count += len(ang_list)
    else:
        total_applications_count += 1

    data_by_match_key[match_key] = {
        "Kommune": clean_val(row.get("Kommune")),
        "Kreis": clean_val(row.get("Kreis")),
        "Typ": clean_val(row.get("Typ")),
        "Regierungsbezirk": clean_val(row.get("Regierungsbezirk")),
        "Bevölkerung": clean_val(row.get("Bevölkerung")),
        "Bevoelkerung_Num": row.get("Bevoelkerung_Num"),
        "Gemeindegrößenklasse": clean_val(row.get("Gemeindegrößenklasse")),
        "Partei": clean_val(row.get("Partei")),
        "Zentralörtliche Einstufung": clean_val(row.get("Zentralörtliche Einstufung")),
        "Beschluss NKNRW": clean_val(row.get("Beschluss NKNRW")),
        "Vorerfahrung": clean_val(row.get("Vorerfahrung")),
        "Info_Angebot": " | ".join(ang_list) if ang_list else "-",
        "Info_Einstieg": " / ".join(start_list) if start_list else "-",
        "Angebote_Paare": paired_offers,
        "Anzahl_Projekte": len(paired_offers) if paired_offers else 1,
        "Row_Data": {k: clean_val(v) for k, v in row.to_dict().items()},
    }

recorded_keys_set = set(data_by_match_key.keys())

# ==============================================================================
# 3. Variablenauswahl für Diagramm & synchrone Kartenfärbung
# ==============================================================================
allowed_vars = [
    "Kreis",
    "Typ",
    "Regierungsbezirk",
    "Gemeindegrößenklasse",
    "Partei",
    "Zentralörtliche Einstufung",
    "Beschluss NKNRW",
    "Angebot",
    "Einstiegszeitpunkt",
    "Vorerfahrung",
]

chart_candidates = [v for v in allowed_vars if v in df.columns]

selected_chart_col = st.sidebar.selectbox(
    "📊 Variable für Diagramm & Kartenfärbung:",
    options=chart_candidates,
    index=(
        chart_candidates.index("Angebot") if "Angebot" in chart_candidates else 0
    ),
    key="sb_selected_variable",
)

PALETTE = [
    "#00689D",  # Blau
    "#4C9F38",  # Grün
    "#FD9D24",  # Orange
    "#DD1367",  # Magenta
    "#26BDE2",  # Cyan
    "#FCC30B",  # Gelb
    "#A21942",  # Weinrot
    "#FD6925",  # Dunkelorange
    "#3F7E44",  # Waldgrün
    "#8B5CF6",  # Violett
    "#06B6D4",  # Türkis
    "#64748B",  # Schiefergrau
]

all_vals = (
    df[selected_chart_col]
    .dropna()
    .astype(str)
    .str.split(";")
    .explode()
    .str.strip()
)
unique_categories = sorted([v for v in all_vals.unique() if v and v not in ("nan", "-")])
color_map = {
    val: PALETTE[i % len(PALETTE)] for i, val in enumerate(unique_categories)
}

# ==============================================================================
# 4. GeoJSON-Properties absichern & anreichern
# ==============================================================================
def enrich_features(features):
    for feat in features:
        props = feat.setdefault("properties", {})

        props["GEN"] = clean_val(
            props.get("GEN") or props.get("NAME") or props.get("BEZ"), "Unbekannt"
        )

        raw_code = str(props.get("AGS") or props.get("AGS_0") or "")
        match_key = "".join(filter(str.isdigit, raw_code)).lstrip("0")
        props["MATCH_KEY"] = match_key

        if match_key in data_by_match_key:
            info = data_by_match_key[match_key]
            props["Im_Projekt"] = (
                f"Ja ({info['Anzahl_Projekte']} Modul{'e' if info['Anzahl_Projekte'] > 1 else ''})"
            )
            props["Info_Status"] = clean_val(info.get("Beschluss NKNRW"))
            props["Info_Angebot"] = clean_val(info.get("Info_Angebot"))
            props["Info_Einstieg"] = clean_val(info.get("Info_Einstieg"))
            props["Info_Typ"] = clean_val(info.get("Typ"))
            props["Info_RB"] = clean_val(info.get("Regierungsbezirk"))
            props["Info_Partei"] = clean_val(info.get("Partei"))
            props["Info_Klasse"] = clean_val(info.get("Gemeindegrößenklasse"))
            props["Info_Zentral"] = clean_val(info.get("Zentralörtliche Einstufung"))

            pop_num = info.get("Bevoelkerung_Num")
            if pd.notnull(pop_num):
                props["Info_Bevoelkerung"] = f"{int(pop_num):,}".replace(",", ".")
            else:
                props["Info_Bevoelkerung"] = clean_val(info.get("Bevölkerung"))

            raw_val = clean_val(info["Row_Data"].get(selected_chart_col))
            first_val = (
                [x.strip() for x in raw_val.split(";") if x.strip()][0]
                if ";" in raw_val
                else raw_val
            )
            props["Selected_Category"] = first_val
        else:
            props["Im_Projekt"] = "Nein"
            props["Info_Status"] = "Nicht erfasst"
            props["Info_Angebot"] = "-"
            props["Info_Einstieg"] = "-"
            props["Info_Typ"] = "-"
            props["Info_RB"] = "-"
            props["Info_Partei"] = "-"
            props["Info_Klasse"] = "-"
            props["Info_Zentral"] = "-"
            props["Info_Bevoelkerung"] = "-"
            props["Selected_Category"] = ""


enrich_features(geojson_data["features"])
if geojson_kreise:
    enrich_features(geojson_kreise["features"])

# Such- und Zentrierfunktion
kommune_list = sorted(
    list(dict.fromkeys(
        v["Kommune"] for v in data_by_match_key.values() if v.get("Kommune")
    ))
)
search_kommune = st.sidebar.selectbox(
    "🔍 Kommune / Kreis suchen & zentrieren:",
    options=["(NRW Übersicht)"] + kommune_list,
    index=0,
    key="sb_search_kommune_kreis",
)

center_loc = [51.45, 7.50]
zoom_lvl = 8

if search_kommune != "(NRW Übersicht)":
    target_entry = next(
        (v for v in data_by_match_key.values() if v.get("Kommune") == search_kommune),
        None,
    )
    if target_entry:
        target_key = str(target_entry["Row_Data"].get("AGS_MATCH", "")).strip()
        all_features = (geojson_kreise["features"] if geojson_kreise else []) + geojson_data["features"]
        for feat in all_features:
            if feat.get("properties", {}).get("MATCH_KEY") == target_key:
                geom = feat.get("geometry", {})
                coords = geom.get("coordinates", [])
                if coords:
                    poly_pts = coords[0] if geom.get("type") == "Polygon" else coords[0][0]
                    avg_lat = sum(pt[1] for pt in poly_pts) / len(poly_pts)
                    avg_lon = sum(pt[0] for pt in poly_pts) / len(poly_pts)
                    center_loc = [avg_lat, avg_lon]
                    zoom_lvl = 9 if "kreis" in str(target_entry.get("Typ", "")).lower() else 11
                break

# ==============================================================================
# 5. Styling & Map
# ==============================================================================
def style_fn_gemeinden(feature):
    props = feature.get("properties", {})
    key = props.get("MATCH_KEY")

    if key in recorded_keys_set:
        target_info = data_by_match_key.get(key)
        is_highlighted = (
            search_kommune != "(NRW Übersicht)"
            and target_info
            and target_info.get("Kommune") == search_kommune
        )
        cat = props.get("Selected_Category")
        fill = color_map.get(cat, "#00689D")

        return {
            "fillColor": fill,
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


def style_fn_kreise(feature):
    props = feature.get("properties", {})
    key = props.get("MATCH_KEY")

    # Nur teilnehmende Landkreise hervorheben, restliche Kreise unsichtbar halten
    if key in recorded_keys_set:
        target_info = data_by_match_key.get(key)
        is_highlighted = (
            search_kommune != "(NRW Übersicht)"
            and target_info
            and target_info.get("Kommune") == search_kommune
        )
        cat = props.get("Selected_Category")
        fill = color_map.get(cat, "#00689D")

        return {
            "fillColor": fill,
            "color": "#FFD700" if is_highlighted else "#1E293B",
            "weight": 3.2 if is_highlighted else 2.2,
            "fillOpacity": 0.80,
        }

    return {
        "fillColor": "#000000",
        "color": "#000000",
        "weight": 0,
        "fillOpacity": 0,
        "opacity": 0,
    }


def highlight_fn_gemeinden(feature):
    return {
        "fillColor": "#26BDE2",
        "color": "#0F2942",
        "weight": 2.8,
        "fillOpacity": 0.95,
    }


def highlight_fn_kreise(feature):
    props = feature.get("properties", {})
    key = props.get("MATCH_KEY")
    if key in recorded_keys_set:
        return {
            "fillColor": "#26BDE2",
            "color": "#0F2942",
            "weight": 3.5,
            "fillOpacity": 0.95,
        }
    return {
        "fillColor": "#000000",
        "color": "#000000",
        "weight": 0,
        "fillOpacity": 0,
        "opacity": 0,
    }


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

# Fabrik-Funktion verhindert die fehlerhafte Tooltip-Wiederverwendung
def create_tooltip():
    return folium.GeoJsonTooltip(
        fields=[
            "GEN",
            "Im_Projekt",
            "Info_Bevoelkerung",
            "Info_Klasse",
            "Info_Partei",
            "Info_Status",
            "Info_Angebot",
            "Info_Einstieg",
            "Info_Zentral",
            "Info_Typ",
            "Info_RB",
        ],
        aliases=[
            "Kommune / Kreis:",
            "Projektbeteiligung:",
            "Bevölkerung:",
            "Größenklasse:",
            "Partei:",
            "Beschluss NKNRW:",
            "Angebot(e):",
            "Wunschstart(e):",
            "Zentralörtlich:",
            "Typ:",
            "Regierungsbezirk:",
        ],
        style=tooltip_style,
        localize=True,
        sticky=False,
    )

# 1. Gemeinde-Layer
folium.GeoJson(
    geojson_data,
    name="Gemeinden",
    style_function=style_fn_gemeinden,
    highlight_function=highlight_fn_gemeinden,
    tooltip=create_tooltip(),
).add_to(m)

# 2. Kreis-Layer mit separatem Tooltip
if geojson_kreise:
    folium.GeoJson(
        geojson_kreise,
        name="Landkreise",
        style_function=style_fn_kreise,
        highlight_function=highlight_fn_kreise,
        tooltip=create_tooltip(),
    ).add_to(m)

# ==============================================================================
# 6. Layout: Karte & Dashboard
# ==============================================================================
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
        '<div style="background-color:#00689D; width:15px; height:15px;'
        ' border-radius:3px; margin-right:8px; flex-shrink:0;"></div><span'
        ' style="font-size:13px; line-height:1.2;"><b>Erfasste Einheit (Kommune / Kreis)</b></span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="display:flex; align-items:center; margin-bottom:10px;">'
        '<div style="background-color:#CBD5E1; border:1px solid #94A3B8;'
        ' width:15px; height:15px; border-radius:3px; margin-right:8px;'
        ' flex-shrink:0;"></div><span style="font-size:13px; color:#475569;'
        ' line-height:1.2;">Nicht erfasst</span></div>',
        unsafe_allow_html=True,
    )

    kpi1, kpi2 = st.columns(2)
    kpi1.metric("Bewerber", len(data_by_match_key))
    kpi2.metric("Projektanträge", total_applications_count)

    unique_pop = (
        df.drop_duplicates(subset=["AGS_MATCH"])["Bevoelkerung_Num"].dropna().sum()
    )
    if unique_pop > 0:
        st.metric("Erfasste Einwohner", f"{int(unique_pop):,}".replace(",", "."))

    st.markdown("---")
    st.markdown(f"##### 📊 Verteilung: {selected_chart_col}")

    series_split = (
        df[selected_chart_col]
        .dropna()
        .astype(str)
        .str.split(";")
        .explode()
        .str.strip()
    )
    series_split = series_split[series_split != ""]

    counts = series_split.value_counts().reset_index()
    counts.columns = [selected_chart_col, "Anzahl"]
    counts = counts.sort_values(by="Anzahl", ascending=True)

    fig = px.bar(
        counts,
        x="Anzahl",
        y=selected_chart_col,
        orientation="h",
        text="Anzahl",
        color=selected_chart_col,
        color_discrete_map=color_map,
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        showlegend=False,
        height=max(320, len(counts) * 34),
        margin=dict(l=0, r=30, t=10, b=10),
        xaxis_title="Fallzahl / Nennungen",
        yaxis_title="",
        yaxis=dict(tickfont=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# 7. Factsheet bei Klick auf ein Polygon
# ==============================================================================
clicked_feature = map_output.get("last_active_drawing") if map_output else None
if clicked_feature:
    clicked_props = clicked_feature.get("properties", {})
    key = clicked_props.get("MATCH_KEY")

    if key and key in data_by_match_key:
        details = data_by_match_key[key]

        st.info(f"### 📍 Factsheet: {details.get('Kommune')}")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"<span style='font-size: 13px;'><b>Typ:</b> {details.get('Typ', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Regierungsbezirk:</b> {details.get('Regierungsbezirk', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Kreis:</b> {details.get('Kreis', '-')}</span>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<span style='font-size: 13px;'><b>Bevölkerung:</b> {details.get('Bevölkerung', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Größenklasse:</b> {details.get('Gemeindegrößenklasse', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Partei:</b> {details.get('Partei', '-')}</span>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<span style='font-size: 13px;'><b>Zentralörtlich:</b> {details.get('Zentralörtliche Einstufung', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Beschluss NKNRW:</b> {details.get('Beschluss NKNRW', '-')}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='font-size: 13px;'><b>Vorerfahrung:</b> {details.get('Vorerfahrung', '-')}</span>", unsafe_allow_html=True)
        with c4:
            st.markdown(f"<span style='font-size: 13px;'><b>Bewerbungen ({details['Anzahl_Projekte']}):</b></span>", unsafe_allow_html=True)
            if details["Angebote_Paare"]:
                for item in details["Angebote_Paare"]:
                    st.markdown(
                        f"<span style='font-size: 12px;'>• <b>{item['angebot']}</b><br>&nbsp;&nbsp;<i>Start: {item['start']}</i></span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown("<span style='font-size: 12px;'>-</span>", unsafe_allow_html=True)
