# ==============================================================================
# 7. Vollbildkarte mit integrierter Live-Übersicht & Legende (oben rechts)
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
        <hr style="margin: 8px 0; border-color:#cbd5e1;">
        <b style="font-size:12px; color:#0F2942;">🎨 Legende</b>
        <div style="display: flex; align-items: center; margin-top: 5px; font-size: 11px;">
            <div style="width: 12px; height: 12px; background: #338398; border-radius: 2px; margin-right: 6px; flex-shrink: 0;"></div>
            <span>NKNRW-Bewerber</span>
        </div>
        <div style="display: flex; align-items: center; margin-top: 4px; font-size: 11px;">
            <div style="width: 12px; height: 12px; background: #6f6f6e; border-radius: 2px; margin-right: 6px; flex-shrink: 0;"></div>
            <span>Nur Projekthistorie</span>
        </div>
        <div style="display: flex; align-items: center; margin-top: 4px; font-size: 11px;">
            <div style="width: 12px; height: 12px; background: #c00d0d; border-radius: 2px; margin-right: 6px; flex-shrink: 0;"></div>
            <span>Bewerber & Historie</span>
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
