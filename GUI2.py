# app.py
# Streamlit-Oberfläche: Modulares Pflanzenbewässerungssystem
# ANFORDERUNGEN (Update 2025-11-19):
# - Max. 4 Pflanzen (statt 5)
# - Live-Umrechnung der Zahlenwerte bei Einheitenwechsel (kein st.form mehr)
# - Füllstandsanzeige (Gauge) überall
# - Vorlagen-System

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts 

# ---------- Konstanten ----------
MAX_PLANTS = 4

# ---------- Persistenz ----------

DB_FILE = "watering_state.json"

def load_db() -> Dict[str, Any]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "modules": [],
        "next_module_id": 1,
        "templates": [],
    }

def save_db(db: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

# ---------- Hilfsfunktionen: Einheiten ----------

def interval_to_days(value: float, unit: str) -> float:
    if unit == "Stunden":
        return float(value) / 24.0
    if unit == "Tage":
        return float(value)
    return float(value)

def days_to_value_unit(days: float) -> (float, str):
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

def add_plant(module: Dict[str, Any], name: str, template: Dict[str, Any] = None) -> None:
    # KORREKTUR: Limit auf 4 Pflanzen
    if len(module["plants"]) >= MAX_PLANTS:
        st.error(f"Maximum von {MAX_PLANTS} Pflanzen erreicht.")
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
    add_log(module, f"Pflanze '{name}' hinzugefügt.")

def remove_plant(module: Dict[str, Any], plant_id: int) -> None:
    module["plants"] = [p for p in module["plants"] if p["id"] != plant_id]
    add_log(module, f"Pflanze entfernt: ID {plant_id}")

def manual_water(module: Dict[str, Any], plant: Dict[str, Any], simulate_ml: float = 100.0) -> None:
    plant["last_watered"] = now_iso() 
    plant["flow_ml_total"] = float(plant.get("flow_ml_total", 0.0)) + float(simulate_ml)
    add_log(module, f"Manuelle Bewässerung: Pflanze {plant['name']} +{simulate_ml:.0f} ml")

# ---------- Callbacks für Live-Umrechnung ----------

def update_interval_callback(key_unit, key_val):
    """Wird aufgerufen, wenn sich die Intervall-Einheit ändert."""
    old_unit = st.session_state.get(f"{key_unit}_last", "Stunden")
    new_unit = st.session_state[key_unit]
    current_val = st.session_state[key_val]
    
    # Merken der neuen Einheit für nächsten Wechsel
    st.session_state[f"{key_unit}_last"] = new_unit
    
    if old_unit == new_unit: return

    # Umrechnen
    val_days = interval_to_days(current_val, old_unit)
    new_display_val, _ = days_to_value_unit(val_days)
    
    # Wenn neue Einheit anders ist, müssen wir den Wert anpassen
    if new_unit == "Stunden":
        st.session_state[key_val] = val_days * 24.0
    elif new_unit == "Tage":
        st.session_state[key_val] = val_days

def update_amount_callback(key_unit, key_val):
    """Wird aufgerufen, wenn sich die Mengen-Einheit ändert."""
    old_unit = st.session_state.get(f"{key_unit}_last", "ml")
    new_unit = st.session_state[key_unit]
    current_val = st.session_state[key_val]
    
    st.session_state[f"{key_unit}_last"] = new_unit
    
    if old_unit == new_unit: return

    # Umrechnen
    val_ml = amount_to_ml(current_val, old_unit)
    
    if new_unit == "L":
        st.session_state[key_val] = val_ml / 1000.0
    elif new_unit == "ml":
        st.session_state[key_val] = val_ml

# ---------- Gauge Chart ----------

def get_gauge_options(value: float) -> Dict[str, Any]:
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
                        "color": [[0.3, "#fd666d"], [0.7, "#ff9900"], [1, "#67e0e3"]]
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

# ---------- Sidebar ----------

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
    sel = st.sidebar.selectbox("Modul wählen", list(zip(names, ids)), index=current_sel_index, format_func=lambda x: x[0])
    st.session_state.selected_module_id = sel[1]

# ---------- Übersicht ----------

def render_overview():
    st.title("Module — Übersicht")
    if not db["modules"]:
        st.info("Keine Module vorhanden.")
        return

    cols = st.columns(3, gap="large")
    idx = 0
    for m in db["modules"]:
        with cols[idx % 3]:
            st.subheader(f"Modul #{m['id']} — {m['name']}")
            
            tank_level = m.get("tank_level_percent", 0.0)
            st_echarts(options=get_gauge_options(tank_level), height="150px", key=f"gauge_ov_{m['id']}")

            st.caption(f"Erstellt: {parse_iso(m.get('created_at','')).strftime('%Y-%m-%d')}")
            
            plant_count = len(m["plants"])
            st.write(f"Pflanzen: {plant_count}/{MAX_PLANTS}")
            
            if m["plants"]:
                df_data = []
                for p in m["plants"]:
                    due = next_due_time(p["last_watered"], p["interval_days"])
                    df_data.append({
                        "Pflanze": p["name"],
                        "Modus": p["mode"],
                        "Feuchte [%]": p.get("current_moisture", 0),
                        "Fällig": due.strftime("%Y-%m-%d %H:%M")
                    })
                st.dataframe(pd.DataFrame(df_data), hide_index=True, use_container_width=True)

            if st.button("Modul entfernen", key=f"rm_{m['id']}", use_container_width=True):
                remove_module(db, m["id"])
                st.session_state.selected_module_id = None
                idx-=1
                st.rerun()
        idx += 1

# ---------- Details ----------

def render_module_details():
    mod_id = st.session_state.selected_module_id
    module = find_module(db, mod_id) if mod_id else {}
    if not module:
        st.title("Modul-Details")
        st.info("Kein Modul ausgewählt.")
        return

    st.title(f"Modul #{module['id']} — {module['name']}")

    tank_level = module.get("tank_level_percent", 0.0)
    st_echarts(options=get_gauge_options(tank_level), height="150px", key=f"gauge_detail_{module['id']}")

    with st.expander("Modul-Einstellungen", expanded=False):
        with st.form(key=f"form_mod_{module['id']}"):
            c1, c2, c3 = st.columns(3)
            with c1: new_name = st.text_input("Name", value=module["name"])
            with c2: esp32 = st.text_input("ESP32-Adresse", value=module.get("esp32_addr",""))
            with c3: pump_relay = st.number_input("Pumpen-Relais", value=int(module.get("pump_relay",0)))
            
            c4, c5 = st.columns(2)
            with c4: flow_id = st.number_input("Durchflussmesser-ID", value=int(module.get("flowmeter_id",0)))
            with c5: tank_level_ui = st.slider("Tank-Level setzen", 0.0, 100.0, float(module.get("tank_level_percent", 75.0)))
            
            c6, c7, c8 = st.columns([2,1,1])
            with c6: submit = st.form_submit_button("Modul Speichern", type="primary")
            with c7: cal_min = st.form_submit_button("Tank leer")
            with c8: cal_max = st.form_submit_button("Tank voll")
            
            if submit:
                module.update({"name": new_name, "esp32_addr": esp32, "pump_relay": int(pump_relay), "flowmeter_id": int(flow_id), "tank_level_percent": float(tank_level_ui), "updated_at": now_iso()})
                add_log(module, "Modulparameter gespeichert")
                save_db(db)
                st.rerun()
            if cal_min or cal_max:
                add_log(module, "Tank kalibriert")
                st.rerun()

    st.markdown("---")
    st.subheader("Pflanzen")

    c_add1, c_add2, c_add3 = st.columns([2, 1, 1])
    with c_add1: pname = st.text_input("Name der neuen Pflanze", key=f"pname_{module['id']}")
    with c_add2:
        template_names = ["Standard"] + [t["name"] for t in db.get("templates", [])]
        tpl_name = st.selectbox("Vorlage", template_names, key=f"tpl_s_{module['id']}")
    with c_add3:
        # KORREKTUR: Button deaktivieren wenn >= 4
        disabled = len(module["plants"]) >= MAX_PLANTS
        if st.button("Pflanze hinzufügen", key=f"add_plant_{module['id']}", disabled=disabled, use_container_width=True):
            if pname.strip():
                tpl = next((t for t in db.get("templates", []) if t["name"] == tpl_name), None) if tpl_name != "Standard" else None
                add_plant(module, pname.strip(), tpl)
                save_db(db)
                st.rerun()

    if not module["plants"]:
        st.info("Keine Pflanzen.")
    else:
        for p in module["plants"]:
            st.markdown("---")
            # ACHTUNG: Kein st.form hier, damit Callbacks funktionieren!
            
            st.markdown(f"### Pflanze #{p['id']} — {p['name']}")
            
            # Generiere eindeutige Keys für Session State
            kid = f"{module['id']}_{p['id']}"
            key_iv_unit = f"iv_unit_{kid}"
            key_iv_val = f"iv_val_{kid}"
            key_amt_unit = f"amt_unit_{kid}"
            key_amt_val = f"amt_val_{kid}"

            # Initialisierung der Session State Werte beim ersten Laden
            if key_iv_unit not in st.session_state:
                _, u = days_to_value_unit(p["interval_days"])
                st.session_state[key_iv_unit] = u
                st.session_state[f"{key_iv_unit}_last"] = u # Für Change Detection
            if key_iv_val not in st.session_state:
                v, _ = days_to_value_unit(p["interval_days"])
                st.session_state[key_iv_val] = v

            if key_amt_unit not in st.session_state:
                _, u = ml_to_value_unit(p["amount_ml"])
                st.session_state[key_amt_unit] = u
                st.session_state[f"{key_amt_unit}_last"] = u
            if key_amt_val not in st.session_state:
                v, _ = ml_to_value_unit(p["amount_ml"])
                st.session_state[key_amt_val] = v

            # UI Aufbau
            c1, c2, c3, c4 = st.columns([2,1,1,1])
            p_name = c1.text_input("Name", value=p["name"], key=f"pn_{kid}")
            enabled = c2.toggle("Aktiv", value=bool(p["enabled"]), key=f"en_{kid}")
            valve = c3.number_input("Ventil", 1, 5, int(p["valve_relay"]), key=f"vr_{kid}")
            sensor = c4.number_input("Sensor", 1, 5, int(p["soil_sensor_id"]), key=f"sr_{kid}")

            cA, cB, cC = st.columns(3)
            mode = cA.selectbox("Modus", ["Zeit", "Zeit+Feuchte"], index=0 if p["mode"]=="Zeit" else 1, key=f"md_{kid}")
            
            with cB:
                # Intervall mit Callback für Sofort-Umrechnung
                st.selectbox("Intervall-Einheit", ["Stunden", "Tage"], key=key_iv_unit, on_change=update_interval_callback, args=(key_iv_unit, key_iv_val))
                curr_unit_iv = st.session_state[key_iv_unit]
                step_iv = 2.0 if curr_unit_iv == "Stunden" else 1.0
                st.number_input("Intervall", min_value=step_iv, step=step_iv, key=key_iv_val)

            with cC:
                # Menge mit Callback für Sofort-Umrechnung
                st.selectbox("Mengen-Einheit", ["ml", "L"], key=key_amt_unit, on_change=update_amount_callback, args=(key_amt_unit, key_amt_val))
                curr_unit_amt = st.session_state[key_amt_unit]
                step_amt = 10.0 if curr_unit_amt == "ml" else 0.1
                st.number_input("Menge", min_value=0.0, step=step_amt, key=key_amt_val)

            cD, cE, cF = st.columns(3)
            moisture = cD.slider("Feuchte (Sim)", 0.0, 100.0, float(p.get("current_moisture", 40.0)), key=f"mo_{kid}")
            thr = cE.number_input("Threshold %", 0.0, 100.0, float(p["moisture_threshold"]), key=f"thr_{kid}")
            
            # Berechnungen für Anzeige
            current_iv_days = interval_to_days(st.session_state[key_iv_val], st.session_state[key_iv_unit])
            due = next_due_time(p["last_watered"], current_iv_days)
            cF.caption(f"Zuletzt: {parse_iso(p['last_watered']).strftime('%d.%m %H:%M')}")
            cF.caption(f"Fällig: {due.strftime('%d.%m %H:%M')}")

            # Kalibrierung & Vorlage
            cK1, cK2, cK3 = st.columns([1,1,2])
            if cK1.button("Trocken cal.", key=f"cmin_{kid}"): add_log(module, f"{p_name} trocken cal.")
            if cK2.button("Feucht cal.", key=f"cmax_{kid}"): add_log(module, f"{p_name} feucht cal.")
            
            cT1, cT2 = st.columns([2,1])
            tpl_new = cT1.text_input("Name für Vorlage", key=f"tn_{kid}")
            if cT2.button("Als Vorlage speichern", key=f"ts_{kid}"):
                if tpl_new:
                    # Werte aus Session State nehmen (aktuell angezeigt)
                    iv_d = interval_to_days(st.session_state[key_iv_val], st.session_state[key_iv_unit])
                    amt_m = amount_to_ml(st.session_state[key_amt_val], st.session_state[key_amt_unit])
                    ntpl = {"name": tpl_new, "mode": mode, "interval_days": iv_d, "amount_ml": amt_m, "moisture_threshold": thr}
                    db["templates"] = [t for t in db.get("templates", []) if t["name"] != tpl_new]
                    db["templates"].append(ntpl)
                    save_db(db)
                    st.success(f"Vorlage '{tpl_new}' gespeichert!")
                    st.rerun()

            st.markdown("---")
            cG, cH, cI, cJ = st.columns([1,1,1,1])
            
            # SPEICHERN
            if cG.button("Speichern", key=f"sv_{kid}", type="primary"):
                p["name"] = p_name
                p["enabled"] = enabled
                p["valve_relay"] = valve
                p["soil_sensor_id"] = sensor
                p["mode"] = mode
                # Wichtig: Werte aus Session State holen
                p["interval_days"] = interval_to_days(st.session_state[key_iv_val], st.session_state[key_iv_unit])
                p["amount_ml"] = amount_to_ml(st.session_state[key_amt_val], st.session_state[key_amt_unit])
                p["moisture_threshold"] = thr
                p["current_moisture"] = moisture
                add_log(module, f"Pflanze {p_name} aktualisiert")
                save_db(db)
                st.rerun()
            
            if cH.button("Giessen", key=f"w_{kid}"):
                amt_curr = amount_to_ml(st.session_state[key_amt_val], st.session_state[key_amt_unit])
                manual_water(module, p, amt_curr)
                save_db(db)
                st.rerun()
            
            cI.metric("Giessen?", "Ja" if (mode=="Zeit" or moisture < thr) else "Nein")
            
            if cJ.button("Löschen", key=f"del_{kid}"):
                remove_plant(module, p["id"])
                save_db(db)
                st.rerun()

# ---------- Main ----------
if view == "Übersicht" or not st.session_state.selected_module_id:
    render_overview()
else:
    render_module_details()
