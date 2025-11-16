# app.py
# Streamlit-Oberfläche: Modulares Pflanzenbewässerungssystem
# Anforderungen:
# - Module (ESP32) zentral via Raspberry visualisieren/parametrieren
# - Pro Modul: 1 Pumpe (Relais), 1 Durchflussmesser, 4 Ventile (Relais), 4 Bodenfeuchtesensoren, max. 4 Pflanzen
# - Zwei Modi:
#   (1) Zeitbasiert: Intervall konfigurierbar in Stunden/Tagen/Wochen, Menge in ml/L. Intern IMMER in Tagen (Intervall) und ml (Menge) speichern.
#   (2) Zeit + Feuchte: wie (1), zusätzlich giessen nur, wenn Feuchte-Threshold (%) unterschritten.
# - Hauptfenster: Übersicht aller Module, Module hinzufügen. Klick auf Modul öffnet Details. In Details: Pflanzen hinzufügen/bearbeiten, Sensorwerte, manuelle Steuerung.

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import streamlit as st

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

# ---------- Hilfsfunktionen: Einheiten ----------

def interval_to_days(value: float, unit: str) -> float:
    if unit == "Stunden":
        return float(value) / 24.0
    if unit == "Tage":
        return float(value)
    if unit == "Wochen":
        return float(value) * 7.0
    return float(value)

def days_to_value_unit(days: float) -> (float, str):
    # Darstellung bevorzugt in Tagen, bei <1 Tag in Stunden, bei >=7 in Wochen
    if days >= 7 and abs(days % 7) < 1e-9:
        return days / 7.0, "Wochen"
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
    return parse_iso(last_iso) + timedelta(days=interval_days)

# ---------- DB-Operationen ----------

def add_module(db: Dict[str, Any], name: str) -> None:
    mid = db["next_module_id"]
    module = {
        "id": mid,
        "name": name,
        "esp32_addr": "",      # optional
        "pump_relay": 0,       # Relais-Index
        "flowmeter_id": 0,     # ID
        "plants": [],          # bis zu 4 Pflanzen
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
    if len(module["plants"]) >= 4:
        return
    pid = 1
    if module["plants"]:
        pid = max([p["id"] for p in module["plants"]]) + 1
    plant = {
        "id": pid,
        "name": name,
        "valve_relay": pid,            # 1..4
        "soil_sensor_id": pid,         # 1..4
        "mode": "Zeit",                # "Zeit" oder "Zeit+Feuchte"
        "interval_days": 1.0,          # intern Tage
        "amount_ml": 250.0,            # intern ml
        "moisture_threshold": 30.0,    # %
        "enabled": True,
        "last_watered": now_iso(),
        # Live-/Sim-Werte (UI-Set oder aus Sensoren):
        "current_moisture": 40.0,      # %
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
view = st.sidebar.radio("Ansicht", ["Übersicht", "Modul-Details"])

st.sidebar.markdown("---")
st.sidebar.subheader("Neues Modul")
new_mod_name = st.sidebar.text_input("Modulname", value="")
if st.sidebar.button("Modul hinzufügen", use_container_width=True, type="primary"):
    if new_mod_name.strip():
        add_module(db, new_mod_name.strip())
        st.session_state.selected_module_id = db["modules"][-1]["id"]

st.sidebar.markdown("---")
if db["modules"]:
    ids = [m["id"] for m in db["modules"]]
    names = [f"#{m['id']} — {m['name']}" for m in db["modules"]]
    sel = st.sidebar.selectbox("Modul wählen", list(zip(names, ids)), format_func=lambda x: x[0] if isinstance(x, tuple) else x)
    if isinstance(sel, tuple):
        st.session_state.selected_module_id = sel[1]
    else:
        st.session_state.selected_module_id = sel

# ---------- Ansicht: Übersicht ----------

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
            st.caption(f"Erstellt: {m.get('created_at','')}")
            st.caption(f"Aktualisiert: {m.get('updated_at','')}")
            plant_count = len(m["plants"])
            st.write(f"Pflanzen: {plant_count}/4")
            if m["plants"]:
                df = pd.DataFrame([
                    {
                        "Pflanze": p["name"],
                        "Modus": p["mode"],
                        "Intervall [Tage]": p["interval_days"],
                        "Menge [ml]": p["amount_ml"],
                        "Feuchte [%]": p["current_moisture"],
                        "Zuletzt": parse_iso(p["last_watered"]).strftime("%Y-%m-%d %H:%M")
                    }
                    for p in m["plants"]
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)
            c2 = st.columns([1])
            with c1:
                if st.button("Details öffnen", key=f"open_{m['id']}", use_container_width=True):
                    st.session_state.selected_module_id = m["id"]
                    st.rerun()
            with c2:
                if st.button("Modul entfernen", key=f"rm_{m['id']}", use_container_width=True):
                    remove_module(db, m["id"])
                    st.rerun()
        idx += 1

# ---------- Ansicht: Modul-Details ----------

def render_module_details():
    mod_id = st.session_state.selected_module_id
    module = find_module(db, mod_id) if mod_id else {}
    if not module:
        st.title("Modul-Details")
        st.info("Kein Modul ausgewählt.")
        return

    st.title(f"Modul #{module['id']} — {module['name']}")

    with st.expander("Modul-Einstellungen", expanded=False):
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
            if st.button("Speichern (Modul)", key=f"save_mod_{module['id']}", use_container_width=True):
                module["name"] = new_name
                module["esp32_addr"] = esp32
                module["pump_relay"] = int(pump_relay)
                module["flowmeter_id"] = int(flow_id)
                module["updated_at"] = now_iso()
                add_log(module, "Modulparameter aktualisiert")
                save_db(db)
                st.rerun()

    st.markdown("---")
    st.subheader("Pflanzen")

    c_add1, c_add2 = st.columns([2,1])
    with c_add1:
        pname = st.text_input("Neue Pflanze", value="", key=f"pname_{module['id']}")
    with c_add2:
        if st.button("Pflanze hinzufügen", key=f"add_plant_{module['id']}", use_container_width=True):
            if pname.strip():
                add_plant(module, pname.strip())
                save_db(db)
                st.rerun()

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
                valve_idx = st.number_input("Ventil-Relais", min_value=1, max_value=4, value=int(p["valve_relay"]), step=1, key=f"vr_{module['id']}_{p['id']}")
            with top4:
                sensor_idx = st.number_input("Feuchte-Sensor ID", min_value=1, max_value=4, value=int(p["soil_sensor_id"]), step=1, key=f"sr_{module['id']}_{p['id']}")

            cA, cB, cC = st.columns(3)
            with cA:
                mode = st.selectbox("Modus", ["Zeit", "Zeit+Feuchte"], index=0 if p["mode"]=="Zeit" else 1, key=f"md_{module['id']}_{p['id']}")
            with cB:
                iv_val, iv_unit_default = days_to_value_unit(float(p["interval_days"]))
                unit_iv = st.selectbox("Intervall-Einheit", ["Stunden","Tage","Wochen"], index=["Stunden","Tage","Wochen"].index(iv_unit_default), key=f"ivunit_{module['id']}_{p['id']}")
                iv_in = st.number_input("Intervall", min_value=0.0, value=float(iv_val), step=0.1, key=f"iv_{module['id']}_{p['id']}")
            with cC:
                amt_val, amt_unit_default = ml_to_value_unit(float(p["amount_ml"]))
                unit_amt = st.selectbox("Mengen-Einheit", ["ml","L"], index=["ml","L"].index(amt_unit_default), key=f"amtunit_{module['id']}_{p['id']}")
                amt_in = st.number_input("Menge", min_value=0.0, value=float(amt_val), step=10.0 if unit_amt=="ml" else 0.1, key=f"amt_{module['id']}_{p['id']}")

            cD, cE, cF = st.columns(3)
            with cD:
                moisture = st.slider("Aktuelle Feuchte [%] (Sensorwert)", 0.0, 100.0, float(p.get("current_moisture", 40.0)), key=f"mo_{module['id']}_{p['id']}")
            with cE:
                thr = st.number_input("Feuchte-Threshold [%] (nur Modus 2)", min_value=0.0, max_value=100.0, value=float(p["moisture_threshold"]), step=1.0, key=f"thr_{module['id']}_{p['id']}")
            with cF:
                last = parse_iso(p["last_watered"]).strftime("%Y-%m-%d %H:%M")
                st.text(f"Zuletzt bewässert: {last}")

            # Berechnung nächste Fälligkeit (nur nach Zeit, die Feuchte-Prüfung wird zur Schaltzeit hinzugefügt)
            interval_days = interval_to_days(iv_in, unit_iv)
            due = next_due_time(p["last_watered"], interval_days)
            st.caption(f"Nächste Zeit-Fälligkeit: {due.strftime('%Y-%m-%d %H:%M')} UTC")

            # Bedingung, ob bei Modus 2 gegossen würde (zum Zeitpunkt der Fälligkeit):
            would_water_now = True
            if mode == "Zeit+Feuchte":
                would_water_now = moisture < thr

            cG, cH, cI, cJ = st.columns([1,1,1,1])
            with cG:
                if st.button("Speichern (Pflanze)", key=f"savep_{module['id']}_{p['id']}", use_container_width=True):
                    p["name"] = p_name
                    p["enabled"] = bool(enabled)
                    p["valve_relay"] = int(valve_idx)
                    p["soil_sensor_id"] = int(sensor_idx)
                    p["mode"] = mode
                    p["interval_days"] = float(interval_days)  # intern Tage
                    p["amount_ml"] = float(amount_to_ml(amt_in, unit_amt))  # intern ml
                    p["moisture_threshold"] = float(thr)
                    p["current_moisture"] = float(moisture)
                    module["updated_at"] = now_iso()
                    add_log(module, f"Pflanze aktualisiert: {p['name']}")
                    save_db(db)
                    st.rerun()
            with cH:
                if st.button("Manuell giessen", key=f"man_{module['id']}_{p['id']}", use_container_width=True):
                    manual_water(module, p, simulate_ml=p["amount_ml"])
                    save_db(db)
                    st.rerun()
            with cI:
                st.metric("Würde jetzt giessen?", "Ja" if would_water_now else "Nein")
            with cJ:
                if st.button("Pflanze entfernen", key=f"del_{module['id']}_{p['id']}", use_container_width=True):
                    remove_plant(module, p["id"])
                    save_db(db)
                    st.rerun()

    st.markdown("---")
    st.subheader("Logs")
    if module["logs"]:
        df_log = pd.DataFrame(module["logs"])
        df_log["ts"] = pd.to_datetime(df_log["ts"])
        st.dataframe(df_log, use_container_width=True, hide_index=True)
    else:
        st.info("Keine Ereignisse protokolliert.")

# ---------- Render ----------

if view == "Übersicht":
    render_overview()
else:
    render_module_details()

