# app.py
# Streamlit-Oberfläche: Modulares Pflanzenbewässerungssystem
# ANFORDERUNGEN (angepasst 2025-11-16):
# - (Feature 4) Pflanzen-Vorlagen implementiert
# - (Feature 1) Intervall wieder in Stunden (2h-Schritt) und Tagen (1d-Schritt)
# - (Feature 2) Logik für Einheiten-Wechsel (Intervall/Menge) korrigiert
# - (Feature 3) Gauge-Chart (Füllstand) in Übersicht UND Details

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts # WICHTIG: Muss installiert sein

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
        "modules": [],       # Liste von Modulen
        "next_module_id": 1,
        "templates": [],     # (Feature 4) NEU: Pflanzen-Vorlagen
    }

def save_db(db: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

# ---------- Hilfsfunktionen: Einheiten (Aktualisiert) ----------

def interval_to_days(value: float, unit: str) -> float:
    # (Feature 1) Wieder "Tage" hinzugefügt
    if unit == "Stunden":
        return float(value) / 24.0
    if unit == "Tage":
        return float(value)
    return float(value)

def days_to_value_unit(days: float) -> (float, str):
    # (Feature 1) Logik für Standard-Anzeige
    # Bevorzugt Tage, außer Intervall ist < 1 Tag
    if days < 1:
        return days * 24.0, "Stunden"
    return days, "Tage"

def amount_to_ml(value: float, unit: str) -> float:
    if unit == "ml":
        return float(value)
    if unit == "L":
        return float(value) * 1000.0
    return float(value)

def ml_to_value_unit(ml: float) -> (float, str):
    if ml >= 1000 and abs(ml % 1000) < 1e-9:
        return ml / 1000.0, "L"
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
    if interval_days <= 1e-9: return now 
    if last > now: return last
        
    interval_seconds = interval_days * 86400.0
    diff_seconds = (now - last).total_seconds()
    intervals_since = diff_seconds / interval_seconds
    next_interval_num = np.ceil(intervals_since)
    if abs(intervals_since) < 1e-9: next_interval_num = 0.0
    return last + timedelta(days=(next_interval_num * interval_days))


# ---------- DB-Operationen ----------

def add_module(db: Dict[str, Any], name: str) -> None:
    mid = db["next_module_id"]
    module = {
        "id": mid,
        "name": name,
        "esp32_addr": "",
        "pump_relay": 0,
        "flowmeter_id": 0,
        "tank_level_percent": 75.0,
        "plants": [],
        "logs": [],
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

# (Feature 4) add_plant erweitert, um Vorlagen zu akzeptieren
def add_plant(module: Dict[str, Any], name: str, template: Dict[str, Any] = None) -> None:
    if len(module["plants"]) >= 5:
        st.error("Maximum von 5 Pflanzen für dieses Modul erreicht.")
        return
        
    pid = 1
    if module["plants"]:
        pid = max([p["id"] for p in module["plants"]]) + 1
        
    plant = {
        "id": pid,
        "name": name,
        "valve_relay": pid,
        "soil_sensor_id": pid,
        "enabled": True,
        "last_watered": now_iso(),
        "current_moisture": 40.0,
        "pump_state": False,
        "valve_state": False,
        "flow_ml_total": 0.0,
        
        # (Feature 4) Werte aus Vorlage oder Standard
        "mode": "Zeit",
        "interval_days": 1.0,
        "amount_ml": 250.0,
        "moisture_threshold": 30.0,
    }

    if template:
        plant["mode"] = template.get("mode", "Zeit")
        plant["interval_days"] = float(template.get("interval_days", 1.0))
        plant["amount_ml"] = float(template.get("amount_ml", 250.0))
        plant["moisture_threshold"] = float(template.get("moisture_threshold", 30.0))

    module["plants"].append(plant)
    add_log(module, f"Pflanze '{name}' hinzugefügt (Vorlage: {template.get('name', 'Standard') if template else 'Standard'})")

def remove_plant(module: Dict[str, Any], plant_id: int) -> None:
    module["plants"] = [p for p in module["plants"] if p["id"] != plant_id]
    add_log(module, f"Pflanze entfernt: ID {plant_id}")

def manual_water(module: Dict[str, Any], plant: Dict[str, Any], simulate_ml: float = 100.0) -> None:
    plant["last_watered"] = now_iso() 
    plant["flow_ml_total"] = float(plant.get("flow_ml_total", 0.0)) + float(simulate_ml)
    add_log(module, f"Manuelle Bewässerung: Pflanze {plant['name']} +{simulate_ml:.0f} ml")

# ---------- Hilfsfunktion: Gauge Chart ----------

def get_gauge_options(value: float) -> Dict[str, Any]:
    """Erzeugt die Konfiguration für die E-Charts Tacho-Anzeige."""
    return {
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
                    "formatter": f"{value:.0f}%", 
                    "color": "auto",
                    "offsetCenter": [0, '60%']
                },
                "data": [{"value": value, "name": "Tank"}],
            }
        ]
    }

# ---------- Streamlit-Setup ----------

st.set_page_config(page_title="Bewässerungssystem", layout="wide")

if "db" not in st.session_state:
    st.session_state.db = load_db()

if "selected_module_id" not in st.session_state:
    st.session_state.selected_module_id = None

db = st.session_state.db

# ---------- Sidebar: Navigation / Module hinzufügen ----------

st.sidebar.header("Navigation")
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
        st.rerun() 

st.sidebar.markdown("---")
if db["modules"]:
    ids = [m["id"] for m in db["modules"]]
    names = [f"#{m['id']} — {m['name']}" for m in db["modules"]]
    
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
            
            # (Feature 3) Gauge Chart für Füllstand
            tank_level = m.get("tank_level_percent", 0.0)
            echarts_options = get_gauge_options(tank_level)
            st_echarts(options=echarts_options, height="150px", key=f"gauge_ov_{m['id']}")

            st.caption(f"Erstellt: {parse_iso(m.get('created_at','')).strftime('%Y-%m-%d')}")
            st.caption(f"Aktualisiert: {parse_iso(m.get('updated_at','')).strftime('%Y-%m-%d %H:%M')}")
            
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

    # (Feature 3) Gauge-Chart auch in den Details anzeigen
    tank_level = module.get("tank_level_percent", 0.0)
    echarts_options = get_gauge_options(tank_level)
    st_echarts(options=echarts_options, height="150px", key=f"gauge_detail_{module['id']}")

    # (Feature 2) Modul-Einstellungen in ein Formular packen
    with st.expander("Modul-Einstellungen", expanded=False):
        with st.form(key=f"form_mod_{module['id']}", clear_on_submit=False):
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
                # Dieser Slider SETZT den Wert (Sensor-Simulation/Eingabe)
                tank_level_ui = st.slider(
                    "Tank-Füllstand [%] (Sensorwert setzen)", 
                    min_value=0.0, 
                    max_value=100.0, 
                    value=float(module.get("tank_level_percent", 75.0)), 
                    step=1.0, 
                    key=f"tank_{module['id']}"
                )
            
            c6, c7, c8 = st.columns([2,1,1])
            with c6:
                # Der Submit-Button für das Modul-Formular
                submitted_mod = st.form_submit_button("Speichern (Modul)", use_container_width=True, type="primary")
            with c7:
                if st.form_submit_button("Tank 'leer' kalibrieren", use_container_width=True):
                    add_log(module, "Aktion: Tank 'leer' kalibriert (Platzhalter)")
                    # Hier würde Logik zum Speichern des Min-Rohwerts ausgelöst
                    st.rerun() # Neu laden, um Log anzuzeigen
            with c8:
                if st.form_submit_button("Tank 'voll' kalibrieren", use_container_width=True):
                    add_log(module, "Aktion: Tank 'voll' kalibriert (Platzhalter)")
                    # Hier würde Logik zum Speichern des Max-Rohwerts ausgelöst
                    st.rerun() # Neu laden, um Log anzuzeigen

            if submitted_mod:
                module["name"] = new_name
                module["esp32_addr"] = esp32
                module["pump_relay"] = int(pump_relay)
                module["flowmeter_id"] = int(flow_id)
                module["tank_level_percent"] = float(tank_level_ui) # Wert aus Slider speichern
                module["updated_at"] = now_iso()
                add_log(module, "Modulparameter aktualisiert")
                save_db(db)
                st.rerun()


    st.markdown("---")
    st.subheader("Pflanzen")

    # (Feature 4) Sektion "Pflanze hinzufügen" mit Vorlagen-Auswahl
    c_add1, c_add2, c_add3 = st.columns([2, 1, 1])
    with c_add1:
        pname = st.text_input("Name der neuen Pflanze", value="", key=f"pname_{module['id']}")
    with c_add2:
        template_names = ["Standard"] + [t["name"] for t in db.get("templates", [])]
        selected_template_name = st.selectbox(
            "Vorlage", 
            template_names, 
            key=f"tpl_select_{module['id']}",
            help="Wählt voreingestellte Werte für Modus, Intervall, Menge und Threshold."
        )
    with c_add3:
        add_disabled = len(module["plants"]) >= 5
        if st.button("Pflanze hinzufügen", key=f"add_plant_{module['id']}", use_container_width=True, disabled=add_disabled):
            if pname.strip():
                # Vorlage suchen und an add_plant übergeben
                template_to_use = None
                if selected_template_name != "Standard":
                    template_to_use = next((t for t in db.get("templates", []) if t["name"] == selected_template_name), None)
                
                add_plant(module, pname.strip(), template=template_to_use)
                save_db(db)
                st.rerun()
            else:
                st.warning("Pflanzenname darf nicht leer sein.")

    # --- ANZEIGE DER PFLANZEN ---
    if not module["plants"]:
        st.info("Keine Pflanzen konfiguriert.")
    else:
        for p in module["plants"]:
            st.markdown("---")
            
            # (Feature 2) Jede Pflanze ist ein eigenes Formular
            with st.form(key=f"form_plant_{module['id']}_{p['id']}", clear_on_submit=False):
                st.markdown(f"### Pflanze #{p['id']} — {p['name']}")
                
                top1, top2, top3, top4 = st.columns([2,1,1,1])
                with top1:
                    p_name = st.text_input("Name", value=p["name"], key=f"pn_{module['id']}_{p['id']}")
                with top2:
                    enabled = st.toggle("Aktiv", value=bool(p["enabled"]), key=f"en_{module['id']}_{p['id']}")
                with top3:
                    valve_idx = st.number_input("Ventil-Relais", min_value=1, max_value=5, value=int(p["valve_relay"]), step=1, key=f"vr_{module['id']}_{p['id']}")
                with top4:
                    sensor_idx = st.number_input("Feuchte-Sensor ID", min_value=1, max_value=5, value=int(p["soil_sensor_id"]), step=1, key=f"sr_{module['id']}_{p['id']}")

                cA, cB, cC = st.columns(3)
                with cA:
                    mode = st.selectbox("Modus", ["Zeit", "Zeit+Feuchte"], index=0 if p["mode"]=="Zeit" else 1, key=f"md_{module['id']}_{p['id']}")
                
                with cB:
                    # (Feature 1 + 2) KORRIGIERTE Intervall-Logik
                    iv_days_db = float(p["interval_days"])
                    _, iv_unit_default = days_to_value_unit(iv_days_db)
                    
                    unit_iv = st.selectbox(
                        "Intervall-Einheit", 
                        ["Stunden", "Tage"], 
                        index=["Stunden","Tage"].index(iv_unit_default), 
                        key=f"ivunit_{module['id']}_{p['id']}"
                    )
                    
                    if unit_iv == "Tage":
                        display_val_iv = iv_days_db
                        step_iv = 1.0
                    else: # "Stunden"
                        display_val_iv = iv_days_db * 24.0
                        step_iv = 2.0
                        
                    iv_in = st.number_input(
                        "Intervall", 
                        min_value=step_iv, # Min. 2h oder 1 Tag
                        value=display_val_iv, 
                        step=step_iv, 
                        key=f"iv_{module['id']}_{p['id']}"
                    )
                    # Konvertierung für die Speicherung
                    interval_days = interval_to_days(iv_in, unit_iv)

                with cC:
                    # (Feature 2) KORRIGIERTE Mengen-Logik (war bereits korrekt)
                    amt_ml_db = float(p["amount_ml"])
                    _, amt_unit_default = ml_to_value_unit(amt_ml_db)
                    unit_amt = st.selectbox(
                        "Mengen-Einheit", 
                        ["ml","L"], 
                        index=["ml","L"].index(amt_unit_default), 
                        key=f"amtunit_{module['id']}_{p['id']}"
                    )
                    if unit_amt == "L":
                        display_val_amt = amt_ml_db / 1000.0
                        step_val_amt = 0.1
                    else: # ml
                        display_val_amt = amt_ml_db
                        step_val_amt = 10.0
                    amt_in = st.number_input(
                        "Menge", 
                        min_value=0.0, 
                        value=display_val_amt, 
                        step=step_val_amt, 
                        key=f"amt_{module['id']}_{p['id']}"
                    )
                    # Konvertierung für die Speicherung
                    amount_ml = amount_to_ml(amt_in, unit_amt)


                cD, cE, cF = st.columns(3)
                with cD:
                    moisture = st.slider("Aktuelle Feuchte [%] (Sensorwert)", 0.0, 100.0, float(p.get("current_moisture", 40.0)), key=f"mo_{module['id']}_{p['id']}")
                with cE:
                    thr = st.number_input("Feuchte-Threshold [%] (nur Modus 2)", min_value=0.0, max_value=100.0, value=float(p["moisture_threshold"]), step=1.0, key=f"thr_{module['id']}_{p['id']}")
                with cF:
                    last = parse_iso(p["last_watered"]).strftime("%Y-%m-%d %H:%M")
                    st.text(f"Zuletzt bewässert: {last}")

                due = next_due_time(p["last_watered"], interval_days)
                st.caption(f"Nächste Zeit-Fälligkeit: {due.strftime('%Y-%m-%d %H:%M')} UTC")

                would_water_now = True
                if mode == "Zeit+Feuchte":
                    would_water_now = moisture < thr
                    
                st.markdown("<h6>Sensor-Kalibrierung</h6>", unsafe_allow_html=True)
                cK1, cK2, cK_spacer = st.columns([1,1,2])
                with cK1:
                    if st.form_submit_button("Trocken kalibrieren", use_container_width=True):
                        add_log(module, f"Aktion: Pflanze {p['name']} 'trocken' kalibriert (Platzhalter)")
                        # Hier würde die Kalibrierungslogik ausgelöst
                        st.rerun()
                with cK2:
                    if st.form_submit_button("Feucht kalibrieren", use_container_width=True):
                        add_log(module, f"Aktion: Pflanze {p['name']} 'feucht' kalibriert (Platzhalter)")
                        st.rerun()

                # (Feature 4) Sektion "Als Vorlage speichern"
                st.markdown("<h6>Vorlage</h6>", unsafe_allow_html=True)
                cT1, cT2 = st.columns([2,1])
                with cT1:
                    template_name_in = st.text_input("Vorlagenname", key=f"tpl_name_{module['id']}_{p['id']}")
                with cT2:
                    if st.form_submit_button("Als Vorlage speichern", use_container_width=True):
                        if template_name_in.strip():
                            new_template = {
                                "name": template_name_in.strip(),
                                # WICHTIG: Nimmt die *gespeicherten* Werte (p["..."]),
                                # nicht die UI-Werte (z.B. p_name, mode, etc.)
                                "mode": p["mode"],
                                "interval_days": p["interval_days"],
                                "amount_ml": p["amount_ml"],
                                "moisture_threshold": p["moisture_threshold"]
                            }
                            # Überschreibt, falls Name existiert
                            db["templates"] = [t for t in db.get("templates", []) if t["name"] != new_template["name"]]
                            db["templates"].append(new_template)
                            add_log(module, f"Vorlage gespeichert: {new_template['name']}")
                            save_db(db)
                            st.rerun()
                        else:
                            st.warning("Bitte einen Vorlagennamen eingeben.")
                
                
                st.markdown("---") # Visueller Trenner vor den Aktions-Buttons
                
                cG, cH, cI, cJ = st.columns([1,1,1,1])
                with cG:
                    # Der Haupt-Speicher-Button für diese Pflanze
                    submitted_plant = st.form_submit_button("Speichern (Pflanze)", use_container_width=True)
                
                with cH:
                    if st.form_submit_button("Manuell giessen", use_container_width=True):
                        manual_water(module, p, simulate_ml=p["amount_ml"])
                        save_db(db)
                        st.rerun()
                with cI:
                    st.metric("Bedingung erfüllt?", "Ja" if would_water_now else "Nein")
                with cJ:
                    # (Feature 2) Entfernen-Button ist jetzt auch ein Submit-Button
                    if st.form_submit_button("Pflanze entfernen", use_container_width=True):
                        remove_plant(module, p["id"])
                        save_db(db)
                        st.rerun()

                # (Feature 2) Speicherlogik wird HIER ausgelöst
                if submitted_plant:
                    p["name"] = p_name
                    p["enabled"] = bool(enabled)
                    p["valve_relay"] = int(valve_idx)
                    p["soil_sensor_id"] = int(sensor_idx)
                    p["mode"] = mode
                    p["interval_days"] = float(interval_days)   # aus korrigierter Logik
                    p["amount_ml"] = float(amount_ml)           # aus korrigierter Logik
                    p["moisture_threshold"] = float(thr)
                    p["current_moisture"] = float(moisture)
                    
                    module["updated_at"] = now_iso()
                    add_log(module, f"Pflanze aktualisiert: {p['name']}")
                    save_db(db)
                    st.rerun()

    st.markdown("---")
    st.subheader("Logs")
    if module["logs"]:
        df_log = pd.DataFrame(module["logs"][:20])
        df_log["ts"] = pd.to_datetime(df_log["ts"])
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
