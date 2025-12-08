import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime
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
    div[row-widget="radio"] > div {
        flex-direction: row;
        gap: 20px;
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

# --- UMRECHNUNGSLOGIK ---

def get_time_display_values(minutes_val, selected_unit):
    """Rechnet Minuten (Backend) in die UI-Einheit um."""
    if selected_unit == "Tage":
        return float(minutes_val / 1440.0) 
    else: # Stunden
        return float(minutes_val / 60.0)

def get_time_backend_minutes(ui_value, selected_unit):
    """Rechnet UI-Eingabe zurück in Minuten."""
    if selected_unit == "Tage":
        return int(ui_value * 1440)
    else: # Stunden
        return int(ui_value * 60)

def get_water_display_values(ml_val, selected_unit):
    """Rechnet ml (Backend) in die UI-Einheit um."""
    if selected_unit == "Liter":
        return float(ml_val / 1000.0)
    else: # ml
        return float(ml_val)

def get_water_backend_ml(ui_value, selected_unit):
    """Rechnet UI-Eingabe zurück in ml."""
    if selected_unit == "Liter":
        return float(ui_value * 1000.0)
    else: # ml
        return float(ui_value)

# --- 3. VISUALISIERUNG ------------------------------------------------------

def draw_water_tank_graphic(current, min_val, max_val):
    if current is None:
        st.warning("Keine Sensordaten...")
        return

    pct = max(0, min(100, current))
    
    if pct <= 20:
        color_top, color_bot = "#ef4444", "#fca5a5"
        status_text = "⚠️ NACHFÜLLEN"
        text_color = "#b91c1c"
    else:
        color_top, color_bot = "#3b82f6", "#93c5fd"
        status_text = "✅ Füllstand OK"
        text_color = "#1f2937"
    
    html_code = f"""
    <div style="text-align:center; font-weight:bold; color:#555; margin-bottom:5px;">Wassertank</div>
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
                c_a.metric("Füllstand", f"{level:.0f}%" if level is not None else "?")
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
        draw_water_tank_graphic(getattr(mod, 'TankLvl', None), getattr(mod, 'TankLvlMin', '?'), getattr(mod, 'TankLvlMax', '?'))
        
    with col_calib:
        st.markdown("#### Kalibrierung")
        st.caption("Füllstandssensor:")
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
                        # Initiale Werte: 1 Stunde (60 min), 500 ml
                        mod.AddPot(p_pos, p_name, "time", 500, 60, 20)
                        log_event(m_id, f"Pflanze {p_name} hinzugefügt", "SETUP")
                        st.rerun()
    
    if not mod.pots: st.caption("Keine Pflanzen konfiguriert.")
    
    for pos, pot in mod.pots.items():
        with st.container(border=True):
            cols = st.columns([1, 2, 1])
            
            # SPALTE 1: Live Werte
            with cols[0]:
                st.markdown(f"**{pot.name}** (Pos {pos})")
                moist = getattr(pot, 'moist_value', 0)
                status_moist = "Trocken" if moist <= pot.moist_thresh else "Feucht"
                delta_color = "inverse" if moist <= pot.moist_thresh else "normal"
                
                st.metric(
                    label="Bodenfeuchtigkeit", 
                    value=f"{moist}%", 
                    delta=f"Status: {status_moist}",
                    delta_color=delta_color
                )
                st.caption(f"Grenzwert: {pot.moist_thresh}%")

            # SPALTE 2: Einstellungen
            with cols[1]:
                with st.expander("⚙️ Einstellungen"):
                    # Presets
                    st.caption("Vorlage laden")
                    c_pr1, c_pr2 = st.columns([2,1])
                    sel_preset = c_pr1.selectbox("Preset", [""] + get_presets(), key=f"ps_sel_{pos}", label_visibility="collapsed")
                    if c_pr2.button("Laden", key=f"ps_ld_{pos}") and sel_preset:
                        if pot.LoadPreset(sel_preset):
                            backend.scheduler.add_job(pot.WaterThePot, 'interval', minutes=pot.wat_event_cyc, id=f"j_M{m_id}P{pos}", replace_existing=True)
                            st.toast("Preset geladen!", icon="💾")
                            st.rerun()
                    
                    st.divider()
                    
                    # --- ZEIT EINSTELLUNG ---
                    st.markdown("**Intervall (Gieß-Zyklus)**")
                    t_unit_sel = st.radio("Zeiteinheit", ["Stunden", "Tage"], key=f"tu_sel_{pos}", label_visibility="collapsed")
                    
                    # Backend-Wert (Minuten) holen
                    current_t_val = get_time_display_values(pot.wat_event_cyc, t_unit_sel)
                    
                    # Min-Werte festlegen (1 Stunde ist das Minimum)
                    if t_unit_sel == "Stunden":
                        min_t_input = 1.0
                    else:
                        min_t_input = 1.0 / 24.0 # Entspricht 1 Stunde in Tagen
                    
                    # FIX: Verhindere Absturz, falls Backend-Wert < Minimum ist
                    # Wenn Backend 0.1h sagt, aber Min 1.0h ist, zeige 1.0h an.
                    safe_time_val = max(min_t_input, float(current_t_val))
                    
                    new_time_val = st.number_input(
                        f"Alle ({t_unit_sel})", 
                        min_value=min_t_input, 
                        value=safe_time_val, 
                        step=0.5, 
                        key=f"ntv_{pos}"
                    )

                    # --- WASSERMENGE EINSTELLUNG ---
                    st.markdown("**Wassermenge**")
                    w_unit_sel = st.radio("Wassereinheit", ["ml", "Liter"], key=f"wu_sel_{pos}", label_visibility="collapsed")
                    
                    current_w_val = get_water_display_values(pot.wat_amount, w_unit_sel)
                    
                    new_amount_val = st.number_input(
                        f"Menge ({w_unit_sel})", 
                        min_value=0.1, 
                        value=float(current_w_val), 
                        step=10.0 if w_unit_sel == "ml" else 0.1, 
                        key=f"nam_{pos}"
                    )
                    
                    st.divider()
                    st.markdown("**Bedingung**")
                    new_mode = st.radio("Modus", ["time", "moist"], index=0 if pot.control_mode=="time" else 1, key=f"md_{pos}", horizontal=True, format_func=lambda x: "Immer (Zeit)" if x=="time" else "Nur wenn trocken (Sensor)")
                    
                    if new_mode == "moist":
                        new_thresh = st.slider("Schwellwert (%)", 0, 100, pot.moist_thresh, key=f"th_{pos}")
                    else:
                        new_thresh = pot.moist_thresh

                    if st.button("Speichern", key=f"sv_{pos}", type="primary"):
                        calc_minutes = get_time_backend_minutes(new_time_val, t_unit_sel)
                        calc_ml = get_water_backend_ml(new_amount_val, w_unit_sel)
                        
                        pot.control_mode = new_mode
                        pot.moist_thresh = new_thresh
                        pot.wat_amount = calc_ml
                        pot.wat_event_cyc = calc_minutes
                        
                        backend.scheduler.add_job(pot.WaterThePot, 'interval', minutes=pot.wat_event_cyc, id=f"j_M{m_id}P{pos}", replace_existing=True)
                        log_event(m_id, f"Settings {pot.name}: Alle {new_time_val} {t_unit_sel}, {new_amount_val} {w_unit_sel}", "CONFIG")
                        st.toast("Gespeichert!", icon="✅")
                        st.rerun()

            # SPALTE 3: Aktionen
            with cols[2]:
                st.write("")
                if st.button("💦 Gießen", key=f"wat_{pos}", use_container_width=True):
                    pot.WaterThePot()
                    st.toast("Gießbefehl gesendet", icon="💦")
                st.write("")
                with st.popover("Sensor Kalibrieren"):
                    if st.button("Trocken (Min)", key=f"cdry_{pos}"):
                        backend.ReqestCalibration(m_id, "Moist", pos, "min")
                    if st.button("Nass (Max)", key=f"cwet_{pos}"):
                        backend.ReqestCalibration(m_id, "Moist", pos, "max")
                st.write("")
                if st.button("Preset speichern", key=f"ps_sv_{pos}", use_container_width=True):
                     pot.SavePreset(pot.name)
                     st.toast(f"Gespeichert: {pot.name}", icon="💾")

# --- 5. MAIN ----------------------------------------------------------------

if 'page' not in st.session_state:
    st.session_state.page = 'overview'
    init_logs()

process_backend_data()
render_sidebar()

if st.session_state.page == 'overview': page_overview()
elif st.session_state.page == 'detail': page_detail()
