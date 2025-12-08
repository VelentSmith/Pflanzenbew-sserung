import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

# Wir importieren dein unveränderbares Backend als Modul
import backend

# --- 1. KONFIGURATION & STYLING ---------------------------------------------

st.set_page_config(
    page_title="GreenThumb Control",
    page_icon="🌿",
    layout="wide"
)

st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 8px;
        border-left: 5px solid #4CAF50;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    div[data-testid="stToast"] {
        background-color: #e6fffa;
        border: 1px solid #4CAF50;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. LOGIK-HELFER --------------------------------------------------------

def process_backend_data():
    if hasattr(backend, 'Modules'):
        for module in backend.Modules.values():
            while module.MQTT_buffer:
                msg = module.MQTT_buffer.pop(0)
                backend.ProcessBufferData(module, msg)

def init_logs():
    for module in backend.Modules.values():
        if not hasattr(module, 'app_log'):
            module.app_log = []
            log_event(module.module_id, "System verbunden", "SYSTEM")

def log_event(module_id, message, type="INFO"):
    module = backend.Modules.get(module_id)
    if module:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if not hasattr(module, 'app_log'): module.app_log = []
        module.app_log.insert(0, {"Zeit": timestamp, "Typ": type, "Nachricht": message})

def get_presets():
    if not os.path.exists("Presets"): return []
    return [f.replace("preset_", "").replace(".json", "") for f in os.listdir("Presets") if f.endswith(".json")]

def convert_minutes_to_ui(minutes):
    """Wandelt Minuten intelligent in Stunden/Tage für die Anzeige um."""
    if minutes == 0: return 0, "Minuten"
    if minutes % 1440 == 0: return int(minutes / 1440), "Tage"
    if minutes % 60 == 0: return int(minutes / 60), "Stunden"
    return int(minutes), "Minuten"

def convert_ui_to_minutes(value, unit):
    """Wandelt die UI-Eingabe zurück in Minuten für das Backend."""
    if unit == "Tage": return int(value * 1440)
    if unit == "Stunden": return int(value * 60)
    return int(value)

# --- 3. VISUALISIERUNG ------------------------------------------------------

def draw_water_tank_graphic(current, min_val, max_val):
    """Zeichnet Tank mit Rot/Blau Logik."""
    if current is None:
        st.warning("Warte auf Sensordaten...")
        return

    pct = max(0, min(100, current))
    
    # NEU: Deutliche Farben (Rot bei <= 20%, sonst Blau)
    if pct <= 20:
        color_top, color_bot = "#ef4444", "#fca5a5" # Rot / Hellrot
        status_text = "KRITISCH"
        text_color = "#b91c1c"
    else:
        color_top, color_bot = "#3b82f6", "#93c5fd" # Blau / Hellblau
        status_text = "OK"
        text_color = "#1f2937"
    
    html_code = f"""
    <div style="border: 2px solid #e5e7eb; border-radius: 12px; height: 180px; width: 100%; position: relative; background: #f3f4f6; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);">
        <div style="
            position: absolute; bottom: 0; left: 0; right: 0;
            height: {pct}%;
            background: linear-gradient(to top, {color_top}, {color_bot});
            transition: height 0.8s ease-in-out;
            opacity: 0.9;">
        </div>
        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; font-size: 1.2rem; text-shadow: 0 1px 2px white; color: {text_color}; text-align: center;">
            {pct:.1f} %<br><span style="font-size:0.8rem">{status_text}</span>
        </div>
        <div style="position: absolute; top: 10%; right: 10px; font-size: 0.7rem; color: #6b7280; border-top: 1px dashed #9ca3af; width: 30px; text-align:right;">MAX</div>
        <div style="position: absolute; bottom: 10%; right: 10px; font-size: 0.7rem; color: #6b7280; border-bottom: 1px dashed #9ca3af; width: 30px; text-align:right;">MIN</div>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# --- 4. SEITEN --------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ Steuerung")
        if 'auto_refresh' not in st.session_state: st.session_state.auto_refresh = False
        st.session_state.auto_refresh = st.toggle("Live-Daten (Auto-Refresh)", value=st.session_state.auto_refresh)
        if st.session_state.auto_refresh:
            time.sleep(2)
            st.rerun()
        st.divider()
        st.info("Systemstatus: Online")

def page_overview():
    st.title("🌱 Dashboard Übersicht")
    with st.expander("➕ Neues Modul hinzufügen"):
        with st.form("new_mod"):
            c1, c2 = st.columns([1, 3])
            new_id = c1.number_input("ID", min_value=1, step=1)
            new_name = c2.text_input("Bezeichnung")
            if st.form_submit_button("Modul erstellen"):
                if new_id in backend.Modules: st.error("ID existiert bereits!")
                else:
                    backend.AddModule(new_id, new_name)
                    log_event(new_id, "Modul manuell erstellt", "SETUP")
                    st.rerun()

    if not backend.Modules:
        st.info("Keine Module vorhanden.")
        return

    cols = st.columns(2)
    for idx, (m_id, mod) in enumerate(backend.Modules.items()):
        with cols[idx % 2]:
            with st.container(border=True):
                st.subheader(f"{mod.name} (ID: {m_id})")
                c_a, c_b = st.columns(2)
                level = getattr(mod, 'TankLvl', 0)
                c_a.metric("Tank", f"{level:.0f}%" if level is not None else "?")
                c_b.metric("Pflanzen", f"{len(mod.pots)} / 4")
                if st.button(f"Verwalten >", key=f"btn_mod_{m_id}", use_container_width=True):
                    st.session_state.selected_module = m_id
                    st.session_state.page = 'detail'
                    st.rerun()

def page_detail():
    if 'selected_module' not in st.session_state or st.session_state.selected_module not in backend.Modules:
        st.session_state.page = 'overview'
        st.rerun()
        
    m_id = st.session_state.selected_module
    mod = backend.Modules[m_id]
    
    c_back, c_head = st.columns([1, 6])
    if c_back.button("🔙 Zurück"):
        st.session_state.page = 'overview'
        st.rerun()
    c_head.title(f"Details: {mod.name}")
    st.divider()

    # --- OBERER BEREICH ---
    col_tank, col_calib, col_log = st.columns([1.5, 1, 2.5])
    with col_tank:
        st.markdown("#### 💧 Wassertank")
        draw_water_tank_graphic(getattr(mod, 'TankLvl', None), getattr(mod, 'TankLvlMin', '?'), getattr(mod, 'TankLvlMax', '?'))
        
    with col_calib:
        st.markdown("#### Kalibrierung")
        if st.button("Setze MIN (Leer)", key="cal_min", use_container_width=True):
            backend.ReqestCalibration(m_id, "Plvl", 0, "min")
            st.toast("Kalibrierung MIN gesendet", icon="📡")
        st.write("")
        if st.button("Setze MAX (Voll)", key="cal_max", use_container_width=True):
            backend.ReqestCalibration(m_id, "Plvl", 0, "max")
            st.toast("Kalibrierung MAX gesendet", icon="📡")

    with col_log:
        st.markdown("#### 📝 Logbuch")
        if hasattr(mod, 'app_log') and mod.app_log:
            df = pd.DataFrame(mod.app_log)
            st.dataframe(df, height=200, hide_index=True, use_container_width=True)
        else: st.info("Keine Einträge.")

    st.divider()
    
    # --- PFLANZEN BEREICH ---
    st.markdown("### 🌿 Pflanzenverwaltung")
    
    if len(mod.pots) < 4:
        with st.expander("➕ Pflanze hinzufügen"):
            with st.form("add_pot"):
                c_p1, c_p2 = st.columns(2)
                p_name = c_p1.text_input("Name")
                p_pos = c_p2.number_input("Position (1-4)", 1, 4, step=1)
                if st.form_submit_button("Hinzufügen"):
                    if p_pos not in mod.pots:
                        mod.AddPot(p_pos, p_name, "time", 0.5, 60, 20)
                        log_event(m_id, f"Pflanze {p_name} hinzugefügt", "SETUP")
                        st.rerun()
    
    if not mod.pots: st.caption("Keine Pflanzen konfiguriert.")
    
    for pos, pot in mod.pots.items():
        with st.container(border=True):
            cols = st.columns([1, 2, 1])
            
            # Live Werte
            with cols[0]:
                st.markdown(f"**{pot.name}** (Pos {pos})")
                moist = getattr(pot, 'moist_value', 0)
                st.metric("Feuchtigkeit", f"{moist}%", delta=f"Soll: <{pot.moist_thresh}%")

            # Einstellungen
            with cols[1]:
                with st.expander("⚙️ Einstellungen"):
                    # Presets
                    st.caption("Vorlage laden")
                    c_pr1, c_pr2 = st.columns([2,1])
                    sel_preset = c_pr1.selectbox("Preset", [""] + get_presets(), key=f"ps_sel_{pos}", label_visibility="collapsed")
                    if c_pr2.button("Laden", key=f"ps_ld_{pos}") and sel_preset:
                        if pot.LoadPreset(sel_preset):
                            backend.scheduler.add_job(pot.WaterThePot, 'interval', minutes=pot.wat_event_cyc, id=f"j_M{m_
