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
GEOJSON_GEMEINDEN_BG = BASE_DIR / "nrw_gemeinden_bg.geojson"
GEOJSON_LV = BASE_DIR / "landschaftsverband_rheinland.geojson"

GITHUB_KREISE_RAW_URL = "https://raw.githubusercontent.com/<DEIN_GITHUB_USER>/<DEIN_REPO>/main/nrw_kreise.geojson"
GITHUB_GEMEINDEN_BG_RAW_URL = "https://raw.githubusercontent.com/<DEIN_GITHUB_USER>/<DEIN_REPO>/main/nrw_gemeinden_bg.geojson"
GITHUB_LV_RAW_URL = "https://raw.githubusercontent.com/<DEIN_GITHUB_USER>/<DEIN_REPO>/main/landschaftsverband_rheinland.geojson"

# ==============================================================================
# Custom CSS für Vollbildkarte & vergrößertes schwebendes Overlay (Live-Übersicht)
# ==============================================================================
st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 100% !important;
    }
    .map-container {
        position: relative;
        width: 100%;
    }
    .floating-overlay-top-right {
        position: absolute;
        top: 20px;
        right: 20px;
        z-index: 99999;
        background: rgba(255, 255, 255, 0.96);
        padding: 16px 20px;
        border-radius: 10px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.25);
        border: 1px solid #cbd5e1;
        width: 320px;
        pointer-events: auto;
    }
    </style>
""", unsafe_allow_html=True)


def clean_val(val, default="-"):
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    return default if s in ("", "nan", "None", "<NA>", "#NV") else s


# ==============================================================================
# 1. Daten laden & bereinigen
# ==============================================================================
@st.cache_data
def load_data():
    if not DATA_PATH.is_file():
        st.error(f"Datei 'daten.csv' nicht gefunden: {DATA_PATH}")
        st.stop()

    try:
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

    # Flexibles Mapping für die Spalte "Teilnahme NKNRW" (egal ob mit Unterstrich oder Leerzeichen)
    teilnahme_col = next((c for c in df.columns if "TEILNAHME" in c.upper() and "NKNRW" in c.upper()), None)
    if teilnahme_col and teilnahme_col != "Teilnahme NKNRW":
        df = df.rename(columns={teilnahme_col: "Teilnahme NKNRW"})
    elif "Teilnahme NKNRW" not in df.columns:
        df["Teilnahme NKNRW"] = "1"

    if "Projekthistorie_id" not in df.columns:
        df["Projekthistorie_id"] = "0"
    if "Projekthistorie_Name" not in df.columns:
        df["Projekthistorie_Name"] = ""

    return df


df_raw = load_data()

# ==============================================================================
# 2. Interaktive Auswahlfilter in der Sidebar
# ==============================================================================
st.sidebar.markdown("### 🎯 Filter & Steuerung")

status_filter = st.sidebar.radio(
    "Datenansicht:",
    options=["Alle Einheiten (Bewerber & Historie)", "Nur NKNRW-Bewerber (Teilnahme = 1)", "Nur Projekthistorie (Frühere Projekte)"],
    index=0,
    key="rb_status_filter"
)

all_available_units = sorted(list(df_raw["Kommune"].dropna().unique()))
selected_units = st.sidebar.multiselect(
    "Kommunen / Kreise auswählen:",
    options=all_available_units,
    default=[],
    help="Leer = alle Einheiten anzeigen.",
    key="ms_selected_units",
)

all_offers_raw = (
    df_raw["Angebot"]
    .dropna()
    .astype(str)
    .str.split(";")
    .explode()
    .str.strip()
)
all_available_offers = sorted([o for o in all_offers_raw.unique() if o and o != "nan" and o != "#NV"])

selected_offers = st.sidebar.multiselect(
    "Angebote auswählen:",
    options=all_available_offers,
    default=[],
    help="Filtert Einheiten, die mindestens eines dieser Angebote gewählt haben.",
    key="ms_selected_offers",
)

df = df_raw.copy()

if status_filter == "Nur NKNRW-Bewerber (Teilnahme = 1)":
    df = df[df["Teilnahme NKNRW"].astype(str).str.strip() == "1"]
elif status_filter == "Nur Projekthistorie (Frühere Projekte)":
    df = df[df["Projekthistorie_id"].astype(str).str.strip() == "1"]

if selected_units:
    df = df[df["Kommune"].isin(selected_units)]

if selected_offers:
    mask = df["Angebot"].apply(
        lambda x: any(offer in [a.strip() for a in str(x).split(";")] for offer in selected_offers)
    )
    df = df[mask]

# ==============================================================================
# 3. Aggregation & Mehrfachangaben-Erkennung
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
        if a.strip() and a.strip() not in ("-", "nan", "#NV")
    ]
    start_list = [
        s.strip()
        for s in raw_start.split(";")
        if s.strip() and s.strip() not in ("-", "nan", "#NV")
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
        if clean_val(row.get("Teilnahme NKNRW")) == "1":
            total_applications_count += 1

    is_multi = (len(ang_list) > 1 or len(start_list) > 1)
    multi_badge = f"🔄 Mehrfachangabe ({len(ang_list)} Angebote / {len(start_list)} Starttermine)" if is_multi else "Standard"

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
        "Teilnahme NKNRW": clean_val(row.get("Teilnahme NKNRW")),
        "Projekthistorie_id": clean_val(row.get("Projekthistorie_id")),
        "Projekthistorie_Name": clean_val(row.get("Projekthistorie_Name")),
        "Info_Angebot": " | ".join(ang_list) if ang_list else "-",
        "Info_Einstieg": " / ".join(start_list) if start_list else "-",
        "Angebote_Paare": paired_offers,
        "Anzahl_Projekte": len(paired_offers) if paired_offers else (1 if clean_val(row.get("Teilnahme NKNRW")) == "1" else 0),
        "Is_Multi": is_multi,
        "Multi_Badge": multi_badge,
        "Row_Data": {k: clean_val(v) for k, v in row.to_dict().items()},
    }

recorded_keys_set = set(data_by_match_key.keys())

# ==============================================================================
# 4. GeoJSONs laden & filtern
# ==============================================================================
@st.cache_data
def load_base_geojsons():
    if not GEOJSON_GEMEINDEN.is_file():
        st.error(f"Datei 'nrw_gemeinden.geojson' fehlt: {GEOJSON_GEMEINDEN}")
        st.stop()
    with open(GEOJSON_GEMEINDEN, "r", encoding="utf-8") as f:
        gemeinden_data = json.load(f)

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

    gemeinden_bg_data = None
    if GEOJSON_GEMEINDEN_BG.is_file():
        with open(GEOJSON_GEMEINDEN_BG, "r", encoding="utf-8") as f:
            gemeinden_bg_data = json.load(f)
    elif "<DEIN_GITHUB_USER>" not in GITHUB_GEMEINDEN_BG_RAW_URL:
        try:
            resp = requests.get(GITHUB_GEMEINDEN_BG_RAW_URL, timeout=10)
            if resp.status_code == 200:
                gemeinden_bg_data = resp.json()
        except Exception:
            gemeinden_bg_data = None

    lv_data = None
    if GEOJSON_LV.is_file():
        with open(GEOJSON_LV, "r", encoding="utf-8") as f:
            lv_data = json.load(f)
    elif "<DEIN_GITHUB_USER>" not in GITHUB_LV_RAW_URL:
        try:
            resp = requests.get(GITHUB_LV_RAW_URL, timeout=10)
            if resp.status_code == 200:
                lv_data = resp.json()
        except Exception:
            lv_data = None

    return gemeinden_data, kreise_data, gemeinden_bg_data, lv_data


base_gemeinden, base_kreise, base_gemeinden_bg, base_lv = load_base_geojsons()


def filter_features(geojson_dict, allowed_keys):
    if not geojson_dict:
        return None
    filtered = []
    for feat in geojson_dict.get("features", []):
        if not feat.get("geometry"):
            continue
        props = feat.setdefault("properties", {})
        raw_code = str(props.get("AGS") or props.get("AGS_0") or "")
        key = "".join(filter(str.isdigit, raw_code)).lstrip("0")
        if key in allowed_keys:
            filtered.append(feat)
    return {"type": "FeatureCollection", "features": filtered}


geojson_data = filter_features(base_gemeinden, recorded_keys_set)
geojson_kreise = filter_features(base_kreise, recorded_keys_set) if base_kreise else None
geojson_gemeinden_bg = base_gemeinden_bg
geojson_lv = filter_features(base_lv, recorded_keys_set) if base_lv else None

# ==============================================================================
# 5. GeoJSON-Properties anreichern
# ==============================================================================
def enrich_features(features, layer_type="gemeinde"):
    if not features:
        return
    for feat in features:
        props = feat.setdefault("properties", {})
        props["GEN"] = clean_val(
            props.get("GEN") or props.get("name") or props.get("NAME") or props.get("BEZ"), "Landschaftsverband Rheinland" if layer_type == "lv" else "Unbekannt"
        )
        
        if layer_type == "lv":
            match_key = "5999999"
        else:
            raw_code = str(props.get("AGS") or props.get("ags") or props.get("AGS_0") or "")
            match_key = "".join(filter(str.isdigit, raw_code)).lstrip("0")
            
        props["MATCH_KEY"] = match_key

        info = data_by_match_key.get(match_key, {})
        
        teilnahme = info.get("Teilnahme NKNRW", "0")
        historie_id = info.get("Projekthistorie_id", "0")
        
        if teilnahme == "1" and historie_id == "1":
            status_text = "Bewerber & Historie"
        elif teilnahme == "1":
            status_text = "NKNRW-Bewerber"
        elif historie_id == "1":
            status_text = "Frühere Projekte (Historie)"
        else:
            status_text = "Kein NKNRW-Bewerber"

        props["Status_Art"] = status_text
        props["Im_Projekt"] = status_text
        props["Info_Status"] = clean_val(info.get("Beschluss NKNRW"))
        props["Info_Angebot"] = clean_val(info.get("Info_Angebot"))
        props["Info_Einstieg"] = clean_val(info.get("Info_Einstieg"))
        props["Info_Typ"] = clean_val(info.get("Typ"))
        props["Info_RB"] = clean_val(info.get("Regierungsbezirk"))
        props["Info_Partei"] = clean_val(info.get("Partei"))
        props["Info_Klasse"] = clean_val(info.get("Gemeindegrößenklasse"))
        props["Info_Zentral"] = clean_val(info.get("Zentralörtliche Einstufung"))
        props["Projekthistorie_Name"] = clean_val(info.get("Projekthistorie_Name"))

        pop_num = info.get("Bevoelkerung_Num")
        if pd.notnull(pop_num):
            props["Info_Bevoelkerung"] = f"{int(pop_num):,}".replace(",", ".")
        else:
            props["Info_Bevoelkerung"] = clean_val(info.get("Bevölkerung"))


if geojson_data:
    enrich_features(geojson_data["features"], layer_type="gemeinde")
if geojson_kreise:
    enrich_features(geojson_kreise["features"], layer_type="kreis")
if geojson_lv and geojson_lv.get("features"):
    enrich_features(geojson_lv["features"], layer_type="lv")

# Such- und Zentrierfunktion
current_kommune_list = sorted(
    list(dict.fromkeys(
        v["Kommune"] for v in data_by_match_key.values() if v.get("Kommune")
    ))
)
search_kommune = st.sidebar.selectbox(
    "🔍 In Auswahl zentrieren:",
    options=["(Übersicht)"] + current_kommune_list,
    index=0,
    key="sb_search_kommune_kreis",
)

center_loc = [51.45, 7.50]
zoom_lvl = 8

if search_kommune != "(Übersicht)":
    target_entry = next(
        (v for v in data_by_match_key.values() if v.get("Kommune") == search_kommune),
        None,
    )
    if target_entry:
        target_key = str(target_entry["Row_Data"].get("AGS_MATCH", "")).strip()
        all_features = (base_kreise.get("features", []) if base_kreise else []) + (geojson_data["features"] if geojson_data else []) + (geojson_lv["features"] if geojson_lv and geojson_lv.get("features") else [])
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
# 6. Styling & Leaflet-Karte
# ==============================================================================
def style_fn_gemeinden_bg(feature):
    return {
        "fillColor": "transparent",
        "color": "#000000",
        "weight": 0.5,
        "fillOpacity": 0.0,
    }

def style_fn_lv(feature):
    return {
        "fillColor": "#00689D",
        "color": "#1e293b",
        "weight": 2.0,
        "dashArray": "4, 4",
        "fillOpacity": 0.25,
    }

def highlight_fn_lv(feature):
    return {
        "fillColor": "#26BDE2",
        "color": "#0F2942",
        "weight": 2.5,
        "dashArray": "4, 4",
        "fillOpacity": 0.45,
    }

def style_fn_kreise(feature):
    props = feature.get("properties", {})
    key = props.get("MATCH_KEY")
    target_info = data_by_match_key.get(key, {})
    is_highlighted = (
        search_kommune != "(Übersicht)"
        and target_info
        and target_info.get("Kommune") == search_kommune
    )
    
    is_applicant = target_info.get("Teilnahme NKNRW") == "1"
    fill_color = "#00689D" if is_applicant else "#64748B"
    fill_opacity = 0.50 if is_applicant else 0.25

    weight = 2.5
    if is_highlighted:
        weight = 3.5

    return {
        "fillColor": fill_color,
        "color": "#FFD700" if is_highlighted else "#475569",
        "weight": weight,
        "dashArray": "4, 4",
        "fillOpacity": fill_opacity,
    }

def highlight_fn_kreise(feature):
    return {
        "fillColor": "#26BDE2",
        "color": "#0F2942",
        "weight": 3.0,
        "dashArray": "4, 4",
        "fillOpacity": 0.60,
    }

def style_fn_gemeinden(feature):
    props = feature.get("properties", {})
    key = props.get("MATCH_KEY")
    target_info = data_by_match_key.get(key, {})
    is_highlighted = (
        search_kommune != "(Übersicht)"
        and target_info
        and target_info.get("Kommune") == search_kommune
    )
    
    is_applicant = target_info.get("Teilnahme NKNRW") == "1"
    fill_color = "#00689D" if is_applicant else "#64748B"
    fill_opacity = 0.75 if is_applicant else 0.35

    is_multi = target_info.get("Is_Multi", False)
    weight = 2.8 if is_multi else 1.3
    if is_highlighted:
        weight = 4.5

    return {
        "fillColor": fill_color,
        "color": "#FFD700" if is_highlighted else "#0F2942",
        "weight": weight,
        "fillOpacity": fill_opacity,
    }

def highlight_fn_gemeinden(feature):
    props = feature.get("properties", {})
    return {
        "fillColor": "#26BDE2",
        "color": "#0F2942",
        "weight": 3.5,
        "fillOpacity": 0.90,
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
            "Status / Projekt:",
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

# 1. ALLERERSTER LAYER: Statische Gemeindegrenzen im Hintergrund (ohne Interaktion)
if geojson_gemeinden_bg and geojson_gemeinden_bg.get("features"):
    folium.GeoJson(
        geojson_gemeinden_bg,
        name="Gemeindegrenzen (Hintergrund)",
        style_function=style_fn_gemeinden_bg,
        interactive=False,
    ).add_to(m)

# 2. ZWEITER LAYER: Landschaftsverband
if geojson_lv and geojson_lv.get("features"):
    folium.GeoJson(
        geojson_lv,
        name="Landschaftsverband",
        style_function=style_fn_lv,
        highlight_function=highlight_fn_lv,
        tooltip=create_tooltip(),
    ).add_to(m)

# 3. DRITTER LAYER: Aktive Landkreise aus der Datentabelle
if geojson_kreise and geojson_kreise["features"]:
    folium.GeoJson(
        geojson_kreise,
        name="Landkreise",
        style_function=style_fn_kreise,
        highlight_function=highlight_fn_kreise,
        tooltip=create_tooltip(),
    ).add_to(m)

# 4. VIERTER LAYER: Aktive Gemeinden (Oberster Layer)
if geojson_data and geojson_data["features"]:
    folium.GeoJson(
        geojson_data,
        name="Gemeinden",
        style_function=style_fn_gemeinden,
        highlight_function=highlight_fn_gemeinden,
        tooltip=create_tooltip(),
    ).add_to(m)

# ==============================================================================
# 7. Vollbildkarte mit Live-Übersicht (Overlay)
# ==============================================================================
st.title("🗺️ NRW-Kommunen: Übersicht & Beteiligung")

st.markdown('<div class="map-container">', unsafe_allow_html=True)

active_filters = []
if selected_units:
    active_filters.append(f"{len(selected_units)} Einheiten")
if selected_offers:
    active_filters.append(f"{len(selected_offers)} Angebote")
filter_label = f"Aktiv: {', '.join(active_filters)}" if active_filters else "(Alle Einheiten)"

applicants_count = sum(1 for v in data_by_match_key.values() if v.get("Teilnahme NKNRW") == "1")

if "Teilnahme NKNRW" in df.columns and "Bevoelkerung_Num" in df.columns:
    unique_pop = (
        df[df["Teilnahme NKNRW"].astype(str).str.strip() == "1"].drop_duplicates(subset=["AGS_MATCH"])["Bevoelkerung_Num"].dropna().sum()
    )
else:
    unique_pop = 0

pop_str = f"{int(unique_pop):,}".replace(",", ".") if unique_pop > 0 else "-"

st.markdown(f"""
    <div class="floating-overlay-top-right">
        <b style="font-size:15px; color:#0F2942;">📊 Live-Übersicht</b><br>
        <span style="font-size:12px; color:#64748B;">{filter_label}</span>
        <hr style="margin: 6px 0; border-color:#cbd5e1;">
        <div style="display:flex; justify-content:space-between; font-size:13px;">
            <span>NKNRW-Bewerber: <b>{applicants_count}</b></span>
            <span>Anträge: <b>{total_applications_count}</b></span>
        </div>
        <div style="font-size:13px; margin-top:4px;">
            Erfasste Einwohner (Bewerber): <b>{pop_str}</b>
        </div>
    </div>
""", unsafe_allow_html=True)

map_output = st_folium(
    m,
    width="100%",
    height=750,
    returned_objects=["last_active_drawing"],
)
st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================================
# 8. Factsheet bei Klick auf ein Polygon (inkl. Projekthistorie)
# ==============================================================================
clicked_feature = map_output.get("last_active_drawing") if map_output else None
if clicked_feature:
    clicked_props = clicked_feature.get("properties", {})
    key = clicked_props.get("MATCH_KEY")

    if key and key in data_by_match_key:
        details = data_by_match_key[key]
        
        teilnahme_txt = "Ja" if details.get('Teilnahme NKNRW') == "1" else "Nein (nur Historie)"

        st.info(f"### 📍 Factsheet: {details.get('Kommune')} | NKNRW-Teilnahme: **{teilnahme_txt}**")
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
            st.markdown(f"<span style='font-size: 13px;'><b>Projekthistorie:</b></span>", unsafe_allow_html=True)
            hist_name = details.get('Projekthistorie_Name', '-')
            if hist_name and hist_name != "-":
                for proj in hist_name.split(";"):
                    st.markdown(f"<span style='font-size: 11px;'>• {proj.strip()}</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='font-size: 11px;'>Keine frühere Historie</span>", unsafe_allow_html=True)

# ==============================================================================
# 9. Diagramme in Tabs unterteilt unterhalb der Karte
# ==============================================================================
st.markdown("---")
st.subheader("📊 Auswertungen im Überblick")

sorting_orders = {
    "Gemeindegrößenklasse": [
        "Kommunalverband / Gemeindeverband",
        "Kreis",
        "Kleinstadt",
        "Mittelstadt",
        "Großstadt",       
    ],
    "Zentralörtliche Einstufung": [
        "Kommunalverband / Gemeindeverband",
        "Kreis",
        "keine zentralörtliche Einstufung",
        "Unterzentrum",
        "Mittelzentrum",
        "Oberzentrum",
   ],
    "Vorerfahrung": [
        "Beginner",
        "First Stepper",
        "Performer",
        "Professionals",
    ],
}

tab_content_config = {
    "Inhaltliche Auswertungen": [
        ("Angebot", "Angebot"),
        ("Gemeindegrößenklasse", "Gemeindegrößenklassen"),
        ("Zentralörtliche Einstufung", "Zentralörtliche Einstufung"),
    ],
    "Organisatorisches & Status": [
        ("Beschluss NKNRW", "Beschluss NKNRW"),
        ("Einstiegszeitpunkt", "Einstiegszeitpunkt"),
        ("Vorerfahrung", "Vorerfahrung"),
    ],
}

tabs = st.tabs(list(tab_content_config.keys()))

for tab_idx, (tab_name, configs) in enumerate(tab_content_config.items()):
    with tabs[tab_idx]:
        cols = st.columns(3)
        for idx, (col_name, title) in enumerate(configs):
            if idx < len(cols):
                with cols[idx]:
                    st.markdown(f"<div style='font-size: 14px; font-weight: 600; text-align: center; margin-bottom: 5px;'>{title}</div>", unsafe_allow_html=True)
                    
                    target_field_map = {
                        "Angebot": "Info_Angebot",
                        "Einstiegszeitpunkt": "Info_Einstieg",
                    }
                    lookup_key = target_field_map.get(col_name, col_name)
                    
                    extracted_values = []
                    for item in data_by_match_key.values():
                        if item.get("Teilnahme NKNRW") == "1":
                            if lookup_key in ("Info_Angebot", "Info_Einstieg"):
                                val_str = item.get(lookup_key, "-")
                                if val_str and val_str != "-":
                                    parts = [p.strip() for p in val_str.replace("/", "|").split("|") if p.strip() and p.strip() != "-"]
                                    extracted_values.extend(parts)
                            else:
                                val_str = item.get(col_name, "-")
                                if val_str and val_str != "-":
                                    parts = [p.strip() for p in val_str.split(";") if p.strip() and p.strip() != "-"]
                                    extracted_values.extend(parts)

                    if extracted_values:
                        series_split = pd.Series(extracted_values)
                        counts = series_split.value_counts().reset_index()
                        counts.columns = [col_name, "Anzahl"]

                        if col_name in sorting_orders:
                            custom_order = sorting_orders[col_name]
                            counts[col_name] = pd.Categorical(counts[col_name], categories=custom_order, ordered=True)
                            counts = counts.sort_values(by=col_name, ascending=False).dropna(subset=[col_name])
                        else:
                            counts = counts.sort_values(by="Anzahl", ascending=True)

                        fig = px.bar(
                            counts,
                            x="Anzahl",
                            y=col_name,
                            orientation="h",
                            text="Anzahl",
                            color=col_name,
                            color_discrete_sequence=px.colors.qualitative.Bold,
                        )
                        fig.update_traces(textposition="outside")
                        fig.update_layout(
                            showlegend=False,
                            height=320,
                            margin=dict(l=0, r=30, t=5, b=5),
                            xaxis_title="",
                            yaxis_title="",
                            xaxis=dict(showticklabels=False, showgrid=False),
                            yaxis=dict(tickfont=dict(size=11)),
                        )
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("Keine Daten")
