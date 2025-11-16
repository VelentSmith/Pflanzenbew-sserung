# app.py
# Streamlit-Oberfläche: Modulares Pflanzenbewässerungssystem
# ANFORDERUNGEN (angepasst 2025-11-16):
# - Module (ESP32) zentral via Raspberry visualisieren/parametrieren
# - Pro Modul: 1 Pumpe, 1 Durchflussmesser, max. 5 Pflanzen/Ventile/Sensoren
# - Inkl. Füllstandsanzeige (Gauge) und Kalibrier-Buttons (Platzhalter)
# - Zwei Modi:
#   (1) Zeitbasiert: Intervall konfigurierbar (nur in 2h-Schritten), Menge in ml/L.
#   (2) Zeit + Feuchte: wie (1), zusätzlich giessen nur, wenn Feuchte-Threshold (%) unterschritten.

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts # NEU: Import für Gauge Chart

# ---------- Persistenz ----------

DB_FILE = "watering_state.json"

def load_db() -> Dict[str, Any]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Initiale Struktur
    return {
        "modules": [],  # Liste von Modulen
        "next_module_id": 1,
    }

def save_db(db: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

# ---------- Hilfsfunktionen: Einheiten (Aktualisiert) ----------

def interval_to_days(value: float, unit: str) -> float:
    # Interne Speicherung ist immer Tage.
    # Input ist jetzt *nur* noch "Stunden" (gemäß 2h-Schritt-Anforderung)
    if unit == "Stunden":
        return float(value) / 24.0
    return float(value) / 24.0 # Fallback

def days_to_value_unit(days: float) -> (float, str):
    # Darstellung ist jetzt *nur* noch "Stunden"
    return days * 24.0, "Stunden"

def amount_to_ml(value: float, unit: str) -> float:
    if unit == "ml":
        return float(value)
    if unit == "L":
        return float(value) * 1000.0
    return float(value)

def ml_to_value_unit(ml: float) -> (float, str):
    # Bevorzugt ml, außer es sind glatte L
    if ml >= 1000 and abs(ml % 1000) < 1e-9:
        return ml / 1000.0, "L"
    # Fallback, wenn User L wählt (z.B. 1.5 L)
    if ml >= 1000 and ml % 1000 >= 0:
        return ml / 1000.0, "L"
    return ml, "ml"

def now_iso() -> str:
    return datetime.utcnow().isoformat()

def parse_iso(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.utcnow()

def next_due_time(last_iso: str, interval_days: float) -> datetime:
    """
    (KORRIGIERTE LOGIK)
    Berechnet den nächsten Fälligkeitszeitpunkt basierend auf UTC-Now,
    um verpasste Slots korrekt zu handhaben.
    """
    last = parse_iso(last_iso)
    now = datetime.utcnow()

    # Safety check
    if interval_days <= 1e-9: 
        return now 
    
    # Wenn der Startpunkt in der Zukunft liegt, ist das die Fälligkeit
    if last > now: 
        return last
        
    interval_seconds = interval_days * 86400.0
    diff_seconds = (now - last).total_seconds()
    
    # Wie viele Intervalle sind seit 'last' vergangen?
    intervals_since = diff_seconds / interval_seconds
    
    # Nächster voller Intervall-Slot (Decke)
    next_interval_num = np.ceil(intervals_since)

    # Wenn wir exakt auf 0.0 sind (Startzeit = Now), ist 0 der nächste Slot.
    if abs(intervals_since) < 1e-9:
         next_interval_num = 0.0

    return last + timedelta(days=(next_interval_num * interval_days))


# ---------- DB-Operationen ----------

def add_module(db: Dict[str, Any], name: str) -> None:
    mid = db["next_module_id"]
    module = {
        "id": mid,
        "name": name,
        "esp32_addr": "",      # optional
        "pump_relay": 0,       # Relais-Index
        "flowmeter_id": 0,     # ID
        "tank_level_percent": 75.0, # NEU: Füllstand
        "plants": [],          # bis zu 5 Pflanzen (Update)
        "logs": [],            # simple Ereignislogs
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    db["modules"].append(module)
    db["next_module_id"] = mid + 1
    save_db(db)

def remove_module(db: Dict[str, Any], module_id: int) -> None:
    db["modules"] = [m for m in db["modules"] if m["id"] != module_id]
    save_db(db)

def find_module(db: Dict[str, Any], module_id: int) -> Dict[str, Any]:
    for m in db["modules"]:
        if m["id"] == module_id:
            return m
    return {}

def add_log(module: Dict[str, Any], text: str) -> None:
    module["logs"].insert(0, {"ts": now_iso(), "text": text})
    module["updated_at"] = now_iso()

def add_plant(module: Dict[str, Any], name: str) -> None:
    # (Update) Limit auf 5
    if len(module["plants"]) >= 5:
        st.error("Maximum von 5 Pflanzen für dieses Modul erreicht.")
        return
        
    pid = 1
    if module["plants"]:
        pid = max([p["id"] for p in module["plants"]]) + 1
        
    plant = {
        "id": pid,
        "name": name,
        "valve_relay": pid,           # 1..5
        "soil_sensor_id": pid,        # 1..5
        "mode": "Zeit",               # "Zeit" oder "Zeit+Feuchte"
        "interval_days": 1.0,         # intern Tage
        "amount_ml": 250.0,           # intern ml
        "moisture_threshold": 30.0,   # %
        "enabled": True,
        "last_watered": now_iso(),    # Wichtig für 'next_due_time'
        # Live-/Sim-Werte (UI-Set oder aus Sensoren):
        "current_moisture": 40.0,     # %
        "pump_state": False,
        "valve_state": False,
        "flow_ml_total": 0.0,
    }
    module["plants"].append(plant)
    add_log(module, f"Pflanze hinzugefügt: {name}")

def remove_plant(module: Dict[str, Any], plant_id: int) -> None:
    module["plants"] = [p for p in module["plants"] if p["id"] != plant_id]
    add_log(module, f"Pflanze entfernt: ID {plant_id}")

def manual_water(module: Dict[str, Any], plant: Dict[str, Any], simulate_ml: float = 100.0) -> None:
    # Manuelles Gießen setzt den Timer zurück (last_watered = now)
    plant["last_watered"] = now_iso() 
    plant["flow_ml_total"] = float(plant.get("flow_ml_total", 0.0)) + float(simulate_ml)
    add_log(module, f"Manuelle Bewässerung: Pflanze {plant['name']} +{simulate_ml:.0f} ml")

# ---------- Streamlit-Setup ----------

st.set_page_config(page_title="Bewässerungssystem", layout="wide")

if "db" not in st.session_state:
    st.session_state.db = load_db()

if "selected_module_id" not in st.session_state:
    st.session_state.selected_module_id = None

db = st.session_state.db

# ---------- Sidebar: Navigation / Module hinzufügen ----------

st.sidebar.header("Navigation")
# Setzt "Übersicht" als Standard, wenn keine Modul-ID ausgewählt ist
default_view_index = 0
if st.session_state.selected_module_id:
    default_view_index = 1

view = st.sidebar.radio("Ansicht", ["Übersicht", "Modul-Details"], index=default_view_index)

st.sidebar.markdown("---")
st.sidebar.subheader("Neues Modul")
new_mod_name = st.sidebar.text_input("Modulname", value="")
if st.sidebar.button("Modul hinzufügen", use_container_width=True, type="primary"):
    if new_mod_name.strip():
        add_module(db, new_mod_name.strip())
        st.session_state.selected_module_id = db["modules"][-1]["id"]
        # Automatisch zur Detailansicht wechseln
        st.rerun() 

st.sidebar.markdown("---")
if db["modules"]:
    ids = [m["id"] for m in db["modules"]]
    names = [f"#{m['id']} — {m['name']}" for m in db["modules"]]
    
    # Finde den Index der aktuell ausgewählten ID
    current_sel_index = 0
    if st.session_state.selected_module_id in ids:
        current_sel_index = ids.index(st.session_state.selected_module_id)

    sel = st.sidebar.selectbox(
        "Modul wählen", 
        list(zip(names, ids)), 
        index=current_sel_index,
        format_func=lambda x: x[0] if isinstance(x, tuple) else x
    )
    
    if isinstance(sel, tuple):
        st.session_state.selected_module_id = sel[1]
    else:
        st.session_state.selected_module_id = sel

# ---------- Ansicht: Übersicht ----------

def render_overview():
    st.title("Module — Übersicht")
    if not db["modules"]:
        st.info("Keine Module vorhanden. Bitte in der Sidebar ein Modul hinzufügen.")
        return

    cols = st.columns(3, gap="large")
    idx = 0
    for m in db["modules"]:
        with cols[idx % 3]:
            st.subheader(f"Modul #{m['id']} — {m['name']}")
            
            # --- NEU: Gauge Chart für Füllstand ---
            tank_level = m.get("tank_level_percent", 0.0)

            echarts_options = {
                "series": [
                    {
                        "type": "gauge",
                        "startAngle": 180,
                        "endAngle": 0,
                        "min": 0,
                        "max": 100,
                        "splitNumber": 10,
                        "axisLine": {
                            "lineStyle": {
                                "width": 6,
                                "color": [
                                    [0.3, "#fd666d"], # Rot (0-30%)
                                    [0.7, "#ff9900"], # Orange (30-70%)
                                    [1, "#67e0e3"]    # Grün (70-100%)
                                ]
                            }
                        },
                        "pointer": {"width": 5},
                        "axisLabel": {"show": False}, 
                        "detail": {
                            "valueAnimation": True,
                            "formatter": f"{tank_level:.0f}%", 
                            "color": "auto",
                            "offsetCenter": [0, '60%']
                        },
                        "data": [{"value": tank_level, "name": "Tank"}],
                    }
                ]
            }
            st_echarts(options=echarts_options, height="150px", key=f"gauge_{m['id']}")
            # --- ENDE NEU ---

            st.caption(f"Erstellt: {parse_iso(m.get('created_at','')).strftime('%Y-%m-%d')}")
            st.caption(f"Aktualisiert: {parse_iso(m.get('updated_at','')).strftime('%Y-%m-%d %H:%M')}")
            
            # (Update) Limit auf 5
            plant_count = len(m["plants"])
            st.write(f"Pflanzen: {plant_count}/5")
            
            if m["plants"]:
                df_data = []
                for p in m["plants"]:
                    due = next_due_time(p["last_watered"], p["interval_days"])
                    df_data.append({
                        "Pflanze": p["name"],
                        "Modus": p["mode"],
                        "Feuchte [%]": p.get("current_moisture", 0),
                        "Nächste Fälligkeit": due.strftime("%Y-%m-%d %H:%M")
                    })
                df = pd.DataFrame(df_data)
                st.dataframe(df, hide_index=True, use_container_width=True)

            if st.button("Modul entfernen", key=f"rm_{m['id']}", use_container_width=True):
                remove_module(db, m["id"])
                st.session_state.selected_module_id = None
                idx-=1
                st.rerun()
        idx += 1

# ---------- Ansicht: Modul-Details ----------

def render_module_details():
    mod_id = st.session_state.selected_module_id
    module = find_module(db, mod_id) if mod_id else {}
    if not module:
        st.title("Modul-Details")
        st.info("Kein Modul ausgewählt. Bitte in der Sidebar ein Modul wählen oder erstellen.")
        return

    st.title(f"Modul #{module['id']} — {module['name']}")

    with st.expander("Modul-Einstellungen", expanded=True): # Standardmäßig geöffnet
        c1, c2, c3 = st.columns(3)
        with c1:
            new_name = st.text_input("Name", value=module["name"], key=f"name_{module['id']}")
        with c2:
            esp32 = st.text_input("ESP32-Adresse/ID", value=module.get("esp32_addr",""), key=f"addr_{module['id']}")
        with c3:
            pump_relay = st.number_input("Pumpen-Relais (Index)", min_value=0, max_value=8, value=int(module.get("pump_relay",0)), step=1, key=f"pump_{module['id']}")
        
        c4, c5 = st.columns(2)
        with c4:
            flow_id = st.number_input("Durchflussmesser-ID", min_value=0, max_value=255, value=int(module.get("flowmeter_id",0)), step=1, key=f"flow_{module['id']}")
        
        with c5:
            tank_level_ui = st.slider(
                "Tank-Füllstand [%] (Sensorwert)", 
                min_value=0.0, 
                max_value=100.0, 
                value=float(module.get("tank_level_percent", 75.0)), 
                step=1.0, 
                key=f"tank_{module['id']}"
            )
        
        # --- NEU: Tank-Kalibrierung ---
        c6, c7, c8 = st.columns([2,1,1])
        with c6:
            if st.button("Speichern (Modul)", key=f"save_mod_{module['id']}", use_container_width=True, type="primary"):
                module["name"] = new_name
                module["esp32_addr"] = esp32
                module["pump_relay"] = int(pump_relay)
                module["flowmeter_id"] = int(flow_id)
                module["tank_level_percent"] = float(tank_level_ui) # Wert speichern
                module["updated_at"] = now_iso()
                add_log(module, "Modulparameter aktualisiert")
                save_db(db)
                st.rerun()
        with c7:
            if st.button("Tank 'leer' kalibrieren", key=f"cal_tank_min_{module['id']}", use_container_width=True):
                # PLATZHALTER: Hier würde die Logik zum Speichern des 'min' Rohwerts hinkommen
                add_log(module, "Aktion: Tank 'leer' kalibriert (Platzhalter)")
                save_db(db)
                st.rerun()
        with c8:
            if st.button("Tank 'voll' kalibrieren", key=f"cal_tank_max_{module['id']}", use_container_width=True):
                # PLATZHALTER: Hier würde die Logik zum Speichern des 'max' Rohwerts hinkommen
                add_log(module, "Aktion: Tank 'voll' kalibriert (Platzhalter)")
                save_db(db)
                st.rerun()
        # --- ENDE NEU ---

    st.markdown("---")
    st.subheader("Pflanzen")

    c_add1, c_add2 = st.columns([2,1])
    with c_add1:
        pname = st.text_input("Name der neuen Pflanze", value="", key=f"pname_{module['id']}")
    with c_add2:
        # (Update) Limit auf 5
        add_disabled = len(module["plants"]) >= 5
        if st.button("Pflanze hinzufügen", key=f"add_plant_{module['id']}", use_container_width=True, disabled=add_disabled):
            if pname.strip():
                add_plant(module, pname.strip())
                save_db(db)
                st.rerun()
            else:
                st.warning("Pflanzenname darf nicht leer sein.")

    if not module["plants"]:
        st.info("Keine Pflanzen konfiguriert.")
    else:
        for p in module["plants"]:
            st.markdown("---")
            st.markdown(f"### Pflanze #{p['id']} — {p['name']}")
            top1, top2, top3, top4 = st.columns([2,1,1,1])
            with top1:
                p_name = st.text_input("Name", value=p["name"], key=f"pn_{module['id']}_{p['id']}")
            with top2:
                enabled = st.toggle("Aktiv", value=bool(p["enabled"]), key=f"en_{module['id']}_{p['id']}")
            with top3:
                # (Update) Limit auf 5
                valve_idx = st.number_input("Ventil-Relais", min_value=1, max_value=5, value=int(p["valve_relay"]), step=1, key=f"vr_{module['id']}_{p['id']}")
            with top4:
                # (Update) Limit auf 5
                sensor_idx = st.number_input("Feuchte-Sensor ID", min_value=1, max_value=5, value=int(p["soil_sensor_id"]), step=1, key=f"sr_{module['id']}_{p['id']}")

            cA, cB, cC = st.columns(3)
            with cA:
                mode = st.selectbox("Modus", ["Zeit", "Zeit+Feuchte"], index=0 if p["mode"]=="Zeit" else 1, key=f"md_{module['id']}_{p['id']}")
            
            with cB:
                # (Update) Nur noch 2-Stunden-Schritte
                iv_val, _ = days_to_value_unit(float(p["interval_days"]))
                iv_in = st.number_input(
                    "Intervall (Stunden)", 
                    min_value=2.0, 
                    value=float(iv_val), 
                    step=2.0, 
                    key=f"iv_{module['id']}_{p['id']}"
                )
                # Interne Umrechnung in Tage
                interval_days = interval_to_days(iv_in, "Stunden")

            with cC:
                # (FIX) Logik korrigiert, um den Wert bei Einheiten-Wechsel anzupassen
                amt_ml_db = float(p["amount_ml"])
                _, amt_unit_default = ml_to_value_unit(amt_ml_db)
                unit_amt = st.selectbox(
                    "Mengen-Einheit", 
                    ["ml","L"], 
                    index=["ml","L"].index(amt_unit_default), 
                    key=f"amtunit_{module['id']}_{p['id']}"
                )
                if unit_amt == "L":
                    display_val = amt_ml_db / 1000.0
                    step_val = 0.1
                else: # ml
                    display_val = amt_ml_db
                    step_val = 10.0
                amt_in = st.number_input(
                    "Menge", 
                    min_value=0.0, 
                    value=display_val, 
                    step=step_val, 
                    key=f"amt_{module['id']}_{p['id']}"
                )
                amount_ml = amount_to_ml(amt_in, unit_amt)


            cD, cE, cF = st.columns(3)
            with cD:
                moisture = st.slider("Aktuelle Feuchte [%] (Sensorwert)", 0.0, 100.0, float(p.get("current_moisture", 40.0)), key=f"mo_{module['id']}_{p['id']}")
            with cE:
                thr = st.number_input("Feuchte-Threshold [%] (nur Modus 2)", min_value=0.0, max_value=100.0, value=float(p["moisture_threshold"]), step=1.0, key=f"thr_{module['id']}_{p['id']}")
            with cF:
                last = parse_iso(p["last_watered"]).strftime("%Y-%m-%d %H:%M")
                st.text(f"Zuletzt bewässert: {last}")

            # (FIX) Berechnung nutzt neue next_due_time Funktion
            due = next_due_time(p["last_watered"], interval_days)
            st.caption(f"Nächste Zeit-Fälligkeit: {due.strftime('%Y-%m-%d %H:%M')} UTC")

            # Bedingung, ob bei Modus 2 gegossen würde
            would_water_now = True
            if mode == "Zeit+Feuchte":
                would_water_now = moisture < thr
                
            # --- NEU: Feuchte-Kalibrierung ---
            cK1, cK2, cK_spacer = st.columns([1,1,2])
            with cK1:
                if st.button("Trocken kalibrieren", key=f"cal_soil_min_{module['id']}_{p['id']}", use_container_width=True):
                    add_log(module, f"Aktion: Pflanze {p['name']} 'trocken' kalibriert (Platzhalter)")
                    save_db(db)
                    st.rerun()
            with cK2:
                if st.button("Feucht kalibrieren", key=f"cal_soil_max_{module['id']}_{p['id']}", use_container_width=True):
                    add_log(module, f"Aktion: Pflanze {p['name']} 'feucht' kalibriert (Platzhalter)")
                    save_db(db)
                    st.rerun()
            # --- ENDE NEU ---

            st.markdown("---") # Visueller Trenner vor den Aktions-Buttons
            
            cG, cH, cI, cJ = st.columns([1,1,1,1])
            with cG:
                if st.button("Speichern (Pflanze)", key=f"savep_{module['id']}_{p['id']}", use_container_width=True):
                    p["name"] = p_name
                    p["enabled"] = bool(enabled)
                    p["valve_relay"] = int(valve_idx)
                    p["soil_sensor_id"] = int(sensor_idx)
                    p["mode"] = mode
                    p["interval_days"] = float(interval_days)   # intern Tage
                    p["amount_ml"] = float(amount_ml)           # intern ml
                    p["moisture_threshold"] = float(thr)
                    p["current_moisture"] = float(moisture)
                    
                    module["updated_at"] = now_iso()
                    add_log(module, f"Pflanze aktualisiert: {p['name']}")
                    save_db(db)
                    st.rerun()
            with cH:
                if st.button("Manuell giessen", key=f"man_{module['id']}_{p['id']}", use_container_width=True):
                    # Manuelles Gießen setzt 'last_watered' auf 'jetzt'
                    manual_water(module, p, simulate_ml=p["amount_ml"]) 
                    save_db(db)
                    st.rerun()
            with cI:
                st.metric("Bedingung erfüllt?", "Ja" if would_water_now else "Nein")
            with cJ:
                if st.button("Pflanze entfernen", key=f"del_{module['id']}_{p['id']}", use_container_width=True):
                    remove_plant(module, p["id"])
                    save_db(db)
                    st.rerun()

    st.markdown("---")
    st.subheader("Logs")
    if module["logs"]:
        # Zeige nur die letzten 20 Logs
        df_log = pd.DataFrame(module["logs"][:20])
        df_log["ts"] = pd.to_datetime(df_log["ts"])
        # Formatieren für bessere Lesbarkeit
        df_log["Zeitstempel"] = df_log["ts"].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_log["Ereignis"] = df_log["text"]
        st.dataframe(df_log[["Zeitstempel", "Ereignis"]], use_container_width=True, hide_index=True)
    else:
        st.info("Keine Ereignisse protokolliert.")

# ---------- Render ----------

if view == "Übersicht" or not st.session_state.selected_module_id:
    render_overview()
else:
    render_module_details()
