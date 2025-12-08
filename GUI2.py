import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

# Wir importieren dein unveränderbares Backend als Modul
# Voraussetzung: PythonApplication1.py liegt im selben Ordner!
import PythonApplication1.py as backend

# --- 1. KONFIGURATION & STYLING ---------------------------------------------

st.set_page_config(
    page_title="GreenThumb Control",
    page_icon="🌿",
    layout="wide"
)

# CSS für schönere Optik (Karten-Look, farbige Balken, Metriken)
st.markdown("""
    <style>
    /* Karten-Design für Container */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 8px;
        border-left: 5px solid #4CAF50;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    /* Anpassung der Expander-Header */
    .streamlit-expanderHeader {
        font-weight: bold;
        color: #333;
    }
    /* Toast Anpassung */
    div[data-testid="stToast"] {
        background-color: #e6fffa;
        border: 1px solid #4CAF50;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. HILFSFUNKTIONEN (LOGIK) ---------------------------------------------

def process_backend_data():
    """
    WICHTIG: Simuliert die Loop aus dem originalen 'if __name__ == "__main__"'.
    Da wir das Backend importieren, läuft dessen Loop nicht. Wir müssen
    die MQTT-Buffer hier leeren und verarbeiten, damit die Werte aktuell bleiben.
    """
    if hasattr(backend, 'Modules'):
        for module in backend.Modules.values():
            while module.MQTT_buffer:
                msg = module.MQTT_buffer.pop(0)
                backend.ProcessBufferData(module, msg)

def init_logs():
    """Fügt nachträglich ein Logbuch zu den existierenden Modul-Objekten hinzu."""
    for module in backend.Modules.values():
        if not hasattr(module, 'app_log'):
            module.app_log = []
            log_event(module.module_id, "System verbunden", "SYSTEM")

def log_event(module_id, message, type="INFO"):
    """Schreibt in das modulspezifische Logbuch."""
    module = backend.Modules.get(module_id)
    if module:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if not hasattr(module, 'app_log'):
            module.app_log = []
        # Füge neues Event vorne an (für Anzeige oben)
        module.app_log.insert(0, {"Zeit": timestamp, "Typ": type, "Nachricht": message})

def get_presets():
    """Liest alle JSON-Dateien im Presets-Ordner."""
    if not os.path.exists("Presets"):
        return []
    return [f.replace("preset_", "").replace(".json", "") for f in os.listdir("Presets") if f.endswith(".json")]

# --- 3. HILFSFUNKTIONEN (VISUALISIERUNG) ------------------------------------

def draw_water_tank_graphic(current, min_val, max_val):
    """Zeichnet einen modernen, barrierefreien Wassertank."""
    if current is None:
        st.warning("Keine Sensordaten (Warte auf MQTT...)")
        return

    # Wert begrenzen
    pct = max(0, min(100, current))
    
    # Farben: Blau (>20%) oder Orange/Warnung (<=20%)
    color_top = "#3b82f6" if pct > 20 else "#f97316"
    color_bot = "#93c5fd" if pct > 20 else "#fdba74"
    
    html_code = f"""
    <div style="border: 2px solid #e5e7eb; border-radius: 12px; height: 180px; width: 100%; position: relative; background: #f3f4f6; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);">
        <div style="
            position: absolute; bottom: 0; left: 0; right: 0;
            height: {pct}%;
            background: linear-gradient(to top, {color_top}, {color_bot});
            transition: height 0.8s ease-in-out;
            opacity: 0.9;">
        </div>
        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-weight: bold; font-size: 1.2rem; text-shadow: 0 1px 2px white; color: #1f2937;">
            {pct:.1f} %
        </div>
        <div style="position: absolute; top: 15%; right: 10px; font-size: 0.7rem; color: #6b7280; border-top: 1px dashed #9ca3af; width: 30px; text-align:right;">MAX</div>
        <div style="position: absolute; bottom: 15%; right: 10px; font-size: 0.7rem; color: #6b7280; border-bottom: 1px dashed #9ca3af; width: 30px; text-align:right;">MIN</div>
    </div>
    <div style="display:flex; justify-content:space-between; font-size:0.8rem; color:#6b7280; margin-top:5px;">
        <span>Kalibriert Min: {min_val}</span>
        <span>Kalibriert Max: {max_val}</span>
    </div>
    """
    st.markdown(html_code, unsafe_allow_html=True)

# --- 4. SEITEN-LAYOUTS ------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ Steuerung")
        
        # Auto-Refresh Toggle
        if 'auto_refresh' not in st.session_state:
            st.session_state.auto_refresh = False
            
        st.session_state.auto_refresh = st.toggle("Live-Daten (Auto-Refresh)", value=st.session_state.auto_refresh)
        
        if st.session_state.auto_refresh:
            st.caption("Aktualisiert alle 2 Sekunden...")
            time.sleep(2)
            st.rerun()
            
        st.divider()
        st.info("Systemstatus: MQTT verbunden\nScheduler läuft.")

def page_overview():
    st.title("🌱 Dashboard Übersicht")
    
    # Neues Modul erstellen
    with st.expander("➕ Neues Modul hinzufügen"):
        with st.form("new_mod"):
            c1, c2 = st.columns([1, 3])
            new_id = c1.number_input("ID", min_value=1, step=1)
            new_name = c2.text_input("Bezeichnung")
            if st.form_submit_button("Modul erstellen"):
                if new_id in backend.Modules:
                    st.error("ID existiert bereits!")
                else:
                    backend.AddModule(new_id, new_name)
                    log_event(new_id, "Modul manuell erstellt", "SETUP")
                    st.toast(f"Modul '{new_name}' erstellt!", icon="✅")
                    st.rerun()

    st.markdown("### Meine Module")
    if not backend.Modules:
        st.info("Keine Module vorhanden.")
        return

    # Grid-Layout für Module
    cols = st.columns(2)
    for idx, (m_id, mod) in enumerate(backend.Modules.items()):
        with cols[idx % 2]:
            with st.container(border=True):
                st.subheader(f"{mod.name} (ID: {m_id})")
                
                # Mini-Info
                c_a, c_b = st.columns(2)
                level = getattr(mod, 'TankLvl', 0)
                c_a.metric("Tank", f"{level:.0f}%" if level is not None else "?")
                c_b.metric("Pflanzen", f"{len(mod.pots)} / 4")
                
                if st.button(f"Verwalten & Details >", key=f"btn_mod_{m_id}", use_container_width=True):
                    st.session_state.selected_module = m_id
                    st.session_state.page = 'detail'
                    st.rerun()

def page_detail():
    if 'selected_module' not in st.session_state or st.session_state.selected_module not in backend.Modules:
        st.session_state.page = 'overview'
        st.rerun()
        
    m_id = st.session_state.selected_module
    mod = backend.Modules[m_id]
    
    # Header Navigation
    c_back, c_head = st.columns([1, 6])
    if c_back.button("🔙 Zurück"):
        st.session_state.page = 'overview'
        st.rerun()
    c_head.title(f"Details: {mod.name}")
    
    st.divider()

    # --- OBERER BEREICH: TANK & LOGS ---
    col_tank, col_calib, col_log = st.columns([1.5, 1, 2.5])
    
    with col_tank:
        st.markdown("#### 💧 Wassertank")
        draw_water_tank_graphic(
            getattr(mod, 'TankLvl', None),
            getattr(mod, 'TankLvlMin', '?'),
            getattr(mod, 'TankLvlMax', '?')
        )
        
    with col_calib:
        st.markdown("#### Kalibrierung")
        st.caption("Füllstandssensor kalibrieren:")
        if st.button("Setze MIN (Leer)", key="cal_min", use_container_width=True):
            backend.ReqestCalibration(m_id, "Plvl", 0, "min")
            log_event(m_id, "Kalibrierung Tank MIN angefordert", "CALIB")
            st.toast("Kalibrierung MIN gesendet", icon="📡")
            
        st.write("")
        if st.button("Setze MAX (Voll)", key="cal_max", use_container_width=True):
            backend.ReqestCalibration(m_id, "Plvl", 0, "max")
            log_event(m_id, "Kalibrierung Tank MAX angefordert", "CALIB")
            st.toast("Kalibrierung MAX gesendet", icon="📡")

    with col_log:
        st.markdown("#### 📝 Logbuch")
        if hasattr(mod, 'app_log') and mod.app_log:
            df = pd.DataFrame(mod.app_log)
            st.dataframe(df, height=200, hide_index=True, use_container_width=True)
        else:
            st.info("Noch keine Einträge.")

    st.divider()
    
    # --- UNTERER BEREICH: PFLANZEN ---
    st.markdown("### 🌿 Pflanzenverwaltung")
    
    # Pflanzen hinzufügen (Max 4)
    if len(mod.pots) < 4:
        with st.expander("➕ Pflanze hinzufügen"):
            with st.form("add_pot"):
                c_p1, c_p2 = st.columns(2)
                p_name = c_p1.text_input("Name")
                p_pos = c_p2.number_input("Position (1-4)", 1, 4, step=1)
                
                if st.form_submit_button("Hinzufügen"):
                    if p_pos in mod.pots:
                        st.error(f"Position {p_pos} ist belegt!")
                    else:
                        mod.AddPot(p_pos, p_name, "time", 0.5, 60, 20)
                        log_event(m_id, f"Pflanze {p_name} (Pos {p_pos}) hinzugefügt", "SETUP")
                        st.rerun()
    
    # Pflanzen Liste (Grid Layout)
    if not mod.pots:
        st.caption("Keine Pflanzen konfiguriert.")
        
    for pos, pot in mod.pots.items():
        # Rahmen um jede Pflanze
        with st.container(border=True):
            cols = st.columns([1, 2, 1])
            
            # SPALTE 1: Sensorwert (Live)
            with cols[0]:
                st.markdown(f"**{pot.name}** (Pos {pos})")
                moist = getattr(pot, 'moist_value', 0)
                st.metric("Feuchtigkeit", f"{moist}%", delta=f"Soll: <{pot.moist_thresh}%")
                
            # SPALTE 2: Einstellungen (Aufklappbar für Clean Look)
            with cols[1]:
                with st.expander("⚙️ Einstellungen & Kalibrierung"):
                    # 1. Presets
                    st.markdown("**Vorlage (Preset)**")
                    presets = get_presets()
                    c_pr1, c_pr2 = st.columns([2,1])
                    sel_preset = c_pr1.selectbox("Wählen", [""] + presets, key=f"ps_sel_{pos}")
                    if c_pr2.button("Laden", key=f"ps_ld_{pos}") and sel_preset:
                        if pot.LoadPreset(sel_preset):
                            # Scheduler Update Hack (Job neu erstellen)
                            backend.scheduler.add_job(pot.WaterThePot, 'interval', minutes=pot.wat_event_cyc, id=f"j_M{m_id}P{pos}", replace_existing=True)
                            log_event(m_id, f"Preset '{sel_preset}' für {pot.name} geladen", "CONFIG")
                            st.toast("Preset geladen!", icon="💾")
                            st.rerun()
                    
                    if st.button("Aktuelle Werte als Preset speichern", key=f"ps_sv_{pos}"):
                         pot.SavePreset(pot.name) # Speichert unter dem Pflanzennamen
                         st.toast(f"Gespeichert als '{pot.name}'", icon="💾")

                    st.markdown("---")
                    
                    # 2. Werte ändern
                    new_mode = st.radio("Modus", ["time", "moist"], index=0 if pot.control_mode=="time" else 1, key=f"md_{pos}", horizontal=True, format_func=lambda x: "Zeitplan" if x=="time" else "Zeit + Sensor")
                    new_thresh = st.slider("Schwelle (%)", 0, 100, pot.moist_thresh, key=f"th_{pos}")
                    new_amount = st.number_input("Menge (L)", 0.1, 5.0, pot.wat_amount, key=f"am_{pos}")
                    
                    if st.button("Speichern", key=f"sv_{pos}"):
                        pot.control_mode = new_mode
                        pot.moist_thresh = new_thresh
                        pot.wat_amount = new_amount
                        # Scheduler update
                        backend.scheduler.add_job(pot.WaterThePot, 'interval', minutes=pot.wat_event_cyc, id=f"j_M{m_id}P{pos}", replace_existing=True)
                        log_event(m_id, f"Settings für {pot.name} aktualisiert", "CONFIG")
                        st.toast("Gespeichert!", icon="✅")

                    st.markdown("---")
                    
                    # 3. Kalibrierung Sensor
                    st.caption("Sensor Kalibrierung:")
                    cb1, cb2 = st.columns(2)
                    if cb1.button("Trocken (Min)", key=f"cdry_{pos}"):
                        backend.ReqestCalibration(m_id, "Moist", pos, "min")
                        st.toast("Calib MIN gesendet", icon="🌵")
                    if cb2.button("Nass (Max)", key=f"cwet_{pos}"):
                        backend.ReqestCalibration(m_id, "Moist", pos, "max")
                        st.toast("Calib MAX gesendet", icon="💧")

            # SPALTE 3: Aktionen
            with cols[2]:
                st.write("") # Spacer
                if st.button("💦 Jetzt Gießen", key=f"wat_{pos}", use_container_width=True):
                    pot.WaterThePot()
                    log_event(m_id, f"Manuelles Gießen: {pot.name}", "ACTION")
                    st.toast("Gießbefehl gesendet", icon="💦")
                
                st.write("")
                if st.button("🗑️ Löschen", key=f"del_{pos}", type="primary", use_container_width=True):
                    mod.DeletePot(pos)
                    log_event(m_id, f"Pflanze {pos} gelöscht", "SETUP")
                    st.rerun()

# --- 5. MAIN LOOP -----------------------------------------------------------

# Initialisierung beim ersten Start
if 'page' not in st.session_state:
    st.session_state.page = 'overview'
    init_logs()

# Daten vom Backend verarbeiten (MQTT Puffer leeren)
process_backend_data()

# UI Rendern
render_sidebar()

if st.session_state.page == 'overview':
    page_overview()
elif st.session_state.page == 'detail':
    page_detail()
