import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

# Import Backend (muss im selben Ordner liegen als backend.py)
import backend

# --- 1. KONFIGURATION & STYLING ---------------------------------------------

st.set_page_config(
    page_title="GreenThumb Control",
    page_icon="🌿",
    layout="wide"
)

st.markdown("""
    <style>
    /* Metrik-Boxen Styling */
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
    /* Rote Umrandung für Lösch-Bereiche optional */
    .delete-zone {
        border: 1px solid #ffcccc;
        background-color: #fff5f5;
        padding: 10px;
        border-radius: 5px;
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

def delete_module_safe(mod_id):
    """Löscht ein Modul und bereinigt vorher alle Scheduler-Jobs."""
    if mod_id in backend.Modules:
        mod = backend.Modules[mod_id]
        # 1. Alle Pflanzen löschen (entfernt Scheduler Jobs)
        # Wir nutzen list(), um eine Kopie der Keys zu haben, da wir während der Iteration löschen
        for pot_pos in list(mod.pots.keys()):
            mod.DeletePot(pot_pos)
        
        # 2. Modul aus dem globalen Dictionary entfernen
        del backend.Modules[mod_id]
        return True
    return False

# --- UMRECHNUNGSLOGIK ---

def get_time_display_values(minutes_val, selected_unit):
    if selected_unit == "Tage":
        return float(minutes_val / 1440.0) 
    else: # Stunden
        return float(minutes_val / 60.0)

def get_time_backend_minutes(ui_value, selected_unit):
    if selected_unit == "Tage":
        return int(ui_value * 1440)
    else: # Stunden
        return int(ui_value *
