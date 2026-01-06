from ast import Not
import json
import os
import time as systime
from tkinter import FALSE
import paho.mqtt.client as mqtt
from datetime import datetime, time, timedelta
import threading
from apscheduler.schedulers.background import BackgroundScheduler

import re


# --- Klassen Komposition -------------------------------------------------
OFFLINE_TIMEOUT_MIN = 20

class Module:
    def __init__(self, module_id, name):
        self.module_id = module_id
        self.name = name
        self.wat_event_time = time(9,0)
        self.tankLvl = None
        self.tankLvlThresh = 10
        self.tankLvlMax = 100
        self.tankLvlMin = 0
        self.tankCalib = False
        self.lastSeen = None
        self.tankOK = False
        self.moduleOnline = False
        self.forcePaused = False
        self.MQTT_buffer = []
        self.MQTT_lock = threading.Lock()
        self.pots = {}
        self.app_log = [] 

    # --- Create Pots, module function -----------------------
    # region 
    def AddPot(self, module_pos, name, control_mode, water_amount, wat_event_cyc, moist_thresh):
        pot = Pot(
            module = self,
            module_pos=module_pos,
            name=name,
            control_mode=control_mode,
            wat_amount=int(water_amount),
            wat_event_cyc=float(wat_event_cyc),
            moist_thresh=int(moist_thresh)
        )
        self.pots[pot.module_pos] = pot
        print(f"Pot {pot.name} added to Module {self.module_id} at position {pot.module_pos}.")

        job_id = f"j_M{self.module_id}P{pot.module_pos}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        scheduler.add_job(
            pot.WaterThePot,
            'interval',
            minutes = pot.wat_event_cyc,
            id = job_id,
            replace_existing = True,
            misfire_grace_time = 1800)  
        print(f"Scheduler-Job erstellt für Pot {pot.module_pos} (Intervall: {pot.wat_event_cyc} min)")

        return pot
    # endregion


    # region 
    def DeletePot(self,module_pos):
        job_id = f"j_M{self.module_id}P{module_pos}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            
        if module_pos in self.pots:
            del self.pots[module_pos]
            print(f"Pot {module_pos} deleted from Module {self.module_id}.")
    # endregion



class Pot:
    def __init__(self, module, module_pos, name, control_mode, wat_amount, wat_event_cyc, moist_thresh):
        self.module=module
        self.module_pos = module_pos
        self.control_mode = control_mode
        self.name = name
        self.wat_amount = wat_amount
        self.wat_event_cyc = wat_event_cyc
        self.moist_thresh = moist_thresh
        self.last_wat_event = None
        self.moist_value = 0
        self.moist_max = 100
        self.moist_min = 0
        self.moistCalib = False
        self.forcePaused = False
   
    def WaterThePot(self): 
        trigger = False
        if self.control_mode == "time":
            trigger = True
        elif self.control_mode == "moist" and self.moist_value <= self.moist_thresh:
            trigger = True
            
        if trigger:
            cur_cmd_timestamp = datetime.now()
            payload = json.dumps({"Type": "RequestWatering", "time_stamp": cur_cmd_timestamp.isoformat(), "Pot": self.module_pos, "Amount": self.wat_amount})
            topic = f"{MQTT_SuperTOPIC}/Module{self.module.module_id}/cmd"
            result = client.publish(topic, payload, qos=1)

            status = result[0]
            if status == 0:
                print(f"[{datetime.now().isoformat()}] MQTT → {payload}")
            else:
                print(f"Fehler beim Senden an MQTT: {status}")
                
        elif self.control_mode == "moist" and self.moist_value > self.moist_thresh:
            print(f"Pot {self.module_pos} not watered due to moisture value")
        else: print(f"wtf happened here!?")

    def SavePreset(self, preset_name):
        os.makedirs("Presets", exist_ok=True)

        data = {
            "control_mode": self.control_mode,
            "wat_amount": self.wat_amount,
            "wat_event_cyc": self.wat_event_cyc,
            "moist_thresh": self.moist_thresh
        }

        filename = f"Presets/preset_{preset_name}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

        print(f"Preset saved: {filename}")

    def LoadPreset(self, preset_name):
        filename = f"Presets/preset_{preset_name}.json"

        if not os.path.isfile(filename):
            print(f"Preset not found: {filename}")
            return False

        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.control_mode  = data.get("control_mode",  self.control_mode)
            self.wat_amount    = data.get("wat_amount",    self.wat_amount)
            self.wat_event_cyc = data.get("wat_event_cyc", self.wat_event_cyc)
            self.moist_thresh  = data.get("moist_thresh",  self.moist_thresh)

            print(f"Preset loaded: {filename}")
            return True
        
        except Exception as e:
            print(f"Error loading preset '{preset_name}': {e}")
            return False
        

# --- MQTT Setup -----------------------------------------------------
# region MQTT Setup 
MQTT_BROKER = "localhost"   # "mqtt.croku.at" for testing or "localhost" for mqtt on raspi
MQTT_PORT = 1883
MQTT_SuperTOPIC = "Greenthumb"
MQTT_data_buffer = []


client = mqtt.Client()

def on_connect(c, u, flags, rc): 
    print("MQTT connected:", rc)

def on_disconnect(c, u, rc):      
    print("MQTT disconnected:", rc)

def on_message(client, userdata, msg):
    if msg.retain:
        # ignoring retained msgs to not process old data
        print(f"Ignore retained message from topic {msg.topic}: {msg.payload!r}")
        return

    try:

        data = json.loads(msg.payload.decode())    
        
        parts = msg.topic.split('/')
        if len(parts) >= 2 and "Module" in parts[1]:
            mod_id_str = parts[1].replace("Module", "")
            if mod_id_str.isdigit():
                mod_id = int(mod_id_str)
                module = Modules.get(mod_id)
                if module:
                    MQTT_data_buffer.append(data)
                    with module.MQTT_lock:
                        module.MQTT_buffer.append(data)
                    print(f"Antwort empfangen: {data}")

    except Exception as e:
        print(f"Fehler beim Verarbeiten der MQTT-Nachricht: {e}")
'''
rc	Bedeutung	Erklärung
0	Erfolg	Verbindung erfolgreich hergestellt 
1	Verbindungsfehler – falsche Protokollversion	Der Broker unterstützt die verwendete MQTT-Version nicht
2	Verbindungsfehler – ungültige Client-ID	Die Client-ID ist nicht erlaubt oder doppelt
3	Server nicht verfügbar	Der Broker ist erreichbar, akzeptiert aber keine Verbindungen
4	Falscher Benutzername oder Passwort	Authentifizierungsfehler
5	Nicht autorisiert	Keine Berechtigung für die Verbindung
'''
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
except Exception as e:
    print(f"MQTT Connection failed: {e}")
# endregion

# --- Global Scheduler ------------------------------------------------
# region 
scheduler = BackgroundScheduler()
scheduler.start()
# endregion

# --- Global functions -----------------------


def GatekeeperCheckAllModules():
    for module in Modules.values():
        if module.lastSeen is None:
            is_online = False
        else:
            is_online = (datetime.now() - module.lastSeen) <= timedelta(minutes=OFFLINE_TIMEOUT_MIN)

        if module.tankLvl is None or module.tankLvl < module.tankLvlThresh or not module.tankCalib:
            tank_ok = False 
        else:
            tank_ok = module.tankLvl >= module.tankLvlThresh


        module.moduleOnline = is_online
        module.tankOK = tank_ok

        if is_online and tank_ok and not module.forcePaused:
            for pot_id, pot in module.pots.items():
                if not pot.forcePaused:
                    SetSchedulerActive(True, module.module_id, pot_id)
                else:
                    SetSchedulerActive(False, module.module_id, pot_id)

        else:
            SetSchedulerActive(False, module.module_id, None)

            reason = [] #possibly add not calibrated 
            if not is_online: reason.append("offline/timeout")
            if not tank_ok:   reason.append("tank low")
            print(f"Module {module.module_id} jobs paused: {', '.join(reason)}")

scheduler.add_job(GatekeeperCheckAllModules, "interval", minutes=1, id="gatekeeper", replace_existing=True)

# region 
Modules = {}
def AddModule(module_id, name):
    module = Module(module_id, name)
    Modules[module_id] = module
    topic = f"{MQTT_SuperTOPIC}/Module{module_id}/resp"
    client.subscribe(topic)
    print(f"Module{module_id} added. subscribed to topic {topic}")


    return module
#endregion

def DeleteModule(module_id):
    module = Modules.get(module_id)

    if module is None:
        print(f"Module{module_id} does not exist.")
        return False

    for job in scheduler.get_jobs():
        if job.id.startswith(f"j_M{module_id}"):
            scheduler.remove_job(job.id)

    topic = f"{MQTT_SuperTOPIC}/Module{module_id}/resp"
    client.unsubscribe(topic)

    del Modules[module_id]

    print(f"Module{module_id} deleted and unsubscribed from topic {topic}")
    return True


def SetSchedulerActive(active: bool, module_id=None, pot=None):
 
    for job in scheduler.get_jobs():
        
        if module_id is None and pot is None:
            job.resume() if active else job.pause()
        elif module_id is not None and pot is None:
            prefix = f"j_M{module_id}P"
            if job.id.startswith(prefix):
                job.resume() if active else job.pause()
        else:
            if job.id == f"j_M{module_id}P{pot}":
                job.resume() if active else job.pause()
    
    if module_id is None and pot is None:
        print(f"All scheduler-jobs {'active' if active else 'paused'}.")
    elif module_id is not None and pot is None:
        print(f"All scheduler-jobs for module {module_id} {'active' if active else 'paused'}.")
    else:
        print(f"Scheduler-job for module {module_id} pot {pot} {'active' if active else 'paused'}.")

def ProcessBufferData(module, msg):
    module.lastSeen = datetime.now()
    module.moduleOnline = True
    m_type = msg.get("Type")
    if m_type == "CycSensorValues":
        print(f"Processing Cyclic Data")
        ProcessSensorData(module, msg)
    elif m_type == "RespCalibration":
        print(f"Processing Calibration Data")
        ProcessCalibrationData(module, msg)
    else:
        print(f"unknown message type: {m_type}")


def ReqestCalibration(module_id, sensor, pot, minORmax):
    cur_cmd_timestamp = datetime.now()
    payload = json.dumps({"Type": "RequestCalibration", "time_stamp": cur_cmd_timestamp.isoformat(), "sensor": sensor, "pot": pot, "minORmax": minORmax})
    topic = f"{MQTT_SuperTOPIC}/Module{module_id}/cmd"
    result = client.publish(topic, payload, qos=1)

    status = result[0]
    if status == 0:
        print(f"[{datetime.now().isoformat()}] calibration values requested for {sensor}")
    else:
        print(f"Fehler beim Senden an MQTT: {status}")

def ProcessCalibrationData(module, msg): #Modulzugriff to be teste with prototype
    match msg["sensor"]:
        case "P":
            if msg["minORmax"] == "min":
                if  module.tankLvlMax is None or module.tankLvlMax > float(msg["value"]):
                    module.tankLvlMin = float(msg["value"])
                    print(f"Plvl min set to {module.tankLvlMin}")
                elif module.tankLvlMax and module.tankLvlMax <= float(msg["value"]):
                    print(f"Plvl min value must be smaller than max value")

            elif msg["minORmax"] == "max":
                if  module.tankLvlMin is None or module.tankLvlMin < float(msg["value"]):
                    module.tankLvlMax = float(msg["value"])
                    print(f"Plvl max set to {module.tankLvlMax}")
                elif module.tankLvlMin and module.tankLvlMin >= float(msg["value"]):
                    print(f"Plvl min value must be smaller than max value")
            else:
                print(f"minORmax unknown")
            
            if module.tankLvlMin and module.tankLvlMax:
                module.tankCalib = True

        case "M":
            pot = module.pots[int(msg["pot"])] 
            if msg["minORmax"] == "min":
                if pot.moist_max is None or pot.moist_max > int(msg["value"]):
                    pot.moist_min = int(msg["value"])
                    print(f"Mlvl min of pot {msg['pot']} set to {pot.moist_min}")
                elif pot.moist_max and pot.moist_max <= float(msg["value"]):
                    print(f"Moisture min value must be smaller than max value")
            elif msg["minORmax"] == "max":
                if pot.moist_min is None or pot.moist_min < int(msg["value"]):
                    pot.moist_max = int(msg["value"])
                    print(f"Mlvl max of pot {msg['pot']} set to {pot.moist_max}")
                elif pot.moist_min and pot.moist_min >= float(msg["value"]):
                    print(f"Moisture min value must be smaller than max value")    
            else:
                print(f"minORmax unknown")
            
            if pot.moist_min and pot.moist_max:
                pot.moistCalib = True
       

    
def ProcessSensorData(module, msg): #Modulzugriff to be testet with prototype
    try:
        if msg.get("PLvl") is None:
            module.tankLvl = None
            module.tankOk = False
        else:
            LvlRaw = float(msg.get("PLvl", 0))
        
        if module.tankCalib:
            module.tankLvl = (LvlRaw - module.tankLvlMin)*100/(module.tankLvlMax - module.tankLvlMin)
            module.tankOK = module.tankLvl > module.tankLvlThresh
            print(f"[{datetime.now().isoformat()}] cyclic sensor data processed.")
            print(f"[{datetime.now().isoformat()}] new value tank lvl: {module.tankLvl}")
        else:
            print(f"[{datetime.now().isoformat()}] cyclic tank lvl data not processed. tank lvl not calibrated")

        for i in range(1, 5):
            key = f"MPot{i}"
            if key in msg and i in module.pots:
                if module.pots[i].moistCalib:
                    module.pots[i].moist_value = (int(msg[key] - module.pots[i].moist_min))*100/(module.pots[i].moist_max - module.pots[i].moist_min)
                    print(f"[{datetime.now().isoformat()}] new value moist {i}: {module.pots[i].moist_value}")
                else:
                    print(f"[{datetime.now().isoformat()}] cyclic moist data not processed. pot{i} not connected or not calibrated")

    except Exception as e:
        print(f"Fehler in SensorData: {e}")




_processing_thread = None
_processing_stop = threading.Event()

def _processing_loop():
    while not _processing_stop.is_set():
        try:
            for module in Modules.values():
                while True:
                    with module.MQTT_lock:
                        if not module.MQTT_buffer:
                            break
                        msg = module.MQTT_buffer.pop(0)
                    ProcessBufferData(module, msg)
            systime.sleep(0.2)
        except Exception as e:
            print(f"Fehler in processing loop: {e}")
            systime.sleep(0.5)

def start_processing_worker():
    global _processing_thread
    if _processing_thread and _processing_thread.is_alive():
        return
    _processing_stop.clear()
    _processing_thread = threading.Thread(target=_processing_loop, daemon=True)
    _processing_thread.start()

def stop_processing_worker():
    _processing_stop.set()





# --- instantiate objects, TO BE REPLACED BY UI INPUT!!! -----------------------
# region 
AddModule(1, "Fensterbank")
AddModule(2, "Regal")

#AddPot(self, module_pos, name, control_mode, water_amount, wat_event_cyc, moist_thresh):

Modules[1].AddPot(1, "Orchidee", "time", 25,0.33, 15)
Modules[1].AddPot(2, "Kaktus", "time", 10, 0.5, 0)
Modules[1].AddPot(3, "Monstera", "time", 50, 1, 15)
Modules[1].AddPot(4, "Testplant", "moist", 50, 5, 15)
# endregion

GatekeeperCheckAllModules()

# --- Main ------------------------------------------------------------
if __name__ == "__main__":
    print("Bewässerungssystem gestartet...")

    start_processing_worker()

    try:
        while True:
            systime.sleep(1)

    except KeyboardInterrupt:
        print("Beende...")
        stop_processing_worker()
        client.disconnect()

    except Exception as e:
        print(f"Fehler in main loop: {e}")
        stop_processing_worker()
        client.disconnect()





