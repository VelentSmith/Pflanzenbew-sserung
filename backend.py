import json
import os
import time as systime
import paho.mqtt.client as mqtt
from datetime import datetime, time
import threading
from apscheduler.schedulers.background import BackgroundScheduler


# --- Klassen Komposition -------------------------------------------------

class Module:
    def __init__(self, module_id, name):
        self.module_id = module_id
        self.name = name
        self.wat_event_time = time(9,0)
        # ÄNDERUNG 1: Variablen initialisiert (vorher Syntaxfehler)
        self.TankLvl = None
        self.TankLvlMax = 100
        self.TankLvlMin = 0
        self.MQTT_buffer = []
        self.pots = {}
        # ÄNDERUNG 2: Log-Liste für Streamlit hinzugefügt
        self.app_log = [] 

            # --- Create Pots, module function -----------------------
    # region 
    def AddPot(self, module_pos, name, control_mode, water_amount, wat_event_cyc, moist_thresh):
        # ÄNDERUNG 3: Explizite Umwandlung in Zahlen (float/int), damit Streamlit nicht abstürzt
        pot = Pot(
            module = self,
            module_pos=module_pos,
            name=name,
            control_mode=control_mode,
            wat_amount=float(water_amount),
            wat_event_cyc=float(wat_event_cyc),
            moist_thresh=int(moist_thresh)
        )
        self.pots[pot.module_pos] = pot
        print(f"Pot {pot.name} added to Module {self.module_id} at position {pot.module_pos}.")

        # Job-ID prüfen, um Fehler bei Neuladen zu vermeiden
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
        # Job-Existenz prüfen vor dem Löschen
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
        # ÄNDERUNG 1: Variablen initialisiert
        self.moist_max = 100
        self.moist_min = 0
"""
    def CheckMoisture(self):
        cur_cmd_timestamp = datetime.now().isoformat()
        found_entry = False
        wat_clearance = False
        payload = json.dumps({"Type": "RequestMoisture", "time_stamp": cur_cmd_timestamp, "Pot": self.module_pos})
        topic = f"{MQTT_SuperTOPIC}/Module{self.module.module_id}/cmd"
        result = client.publish(topic, payload, qos=1)
        status = result[0]
        
        if status == 0:
            print(f"[{datetime.now().isoformat()}] MQTT → {payload}")
            start_time = systime.time()
            while (systime.time()-start_time < 7):
                for i, msg in enumerate(MQTT_data_buffer):
                    #print(f"msg{msg.get("ModuleID")}, object:{self.module.module_id}")

                    if (msg.get("time_stamp") == cur_cmd_timestamp) and (msg.get("ModuleID") == self.module.module_id):
                        self.moist_value = msg.get("moist_value")
                        del MQTT_data_buffer[i]
                        if self.moist_value <= self.moist_thresh: wat_clearance = True
                        found_entry = True
                        print(f"found answer from ESP module{self.module.module_id}, pot{self.module_pos}")
                        break
                if found_entry:
                    break
                systime.sleep(0.1)
            if found_entry ==False: print(f"no answer from ESP moduel{self.module.module_id}, pot{self.module_pos}")
                
        else:
            print(f"Fehler beim Senden an MQTT: {status}")

        return wat_clearance     
 
    """
    def WaterThePot(self): 
        # Vereinfachte Logik, damit MQTT Befehl sicher rausgeht
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

        # Prüfen ob Datei existiert
        if not os.path.isfile(filename):
            print(f"Preset not found: {filename}")
            return False

        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Werte ins Objekt laden
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
MQTT_BROKER = "mqtt.croku.at"
MQTT_PORT = 1883
MQTT_SuperTOPIC = "Greenthumb"
MQTT_data_buffer = []


client = mqtt.Client()

def on_connect(c, u, flags, rc): print("MQTT connected:", rc)
def on_disconnect(c, u, rc):      print("MQTT disconnected:", rc)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())    
        
        # ÄNDERUNG 4: Korrektur Tippfehler und Parsing-Logik
        # Original war: msg.topic.replac("Greenthumb/Modul", "") -> Tippfehler 'replac' und Logikfehler 'Modul' vs 'Module'
        parts = msg.topic.split('/')
        if len(parts) >= 2 and "Module" in parts[1]:
            mod_id_str = parts[1].replace("Module", "")
            if mod_id_str.isdigit():
                mod_id = int(mod_id_str)
                module = Modules.get(mod_id)
                if module:
                    MQTT_data_buffer.append(data)
                    # ÄNDERUNG 5: Tippfehler abbend -> append
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

# --- Create Modules, global function -----------------------
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

def ProcessBufferData(module, msg):
    # ÄNDERUNG: Typ sicherstellen
    m_type = msg.get("Type")
    if m_type == "CycSensorValues":
        ProcessSensorData(module, msg)
    elif m_type == "RespCalibration":
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

def ProcessCalibrationData(module, msg):
    match msg["sensor"]:
        case "Plvl":
            if msg["minORmax"] == "min":
                module.TankLvlMin = int(msg["value"])
            elif msg["minORmax"] == "max":
                module.TankLvlMax = int(msg["value"])
            else:
                print(f"minORmax unknown")
        case "Moist":
            pot = module.pots[int(msg["Pot"])] 
            if msg["minORmax"] == "min":
                pot.moist_min = int(msg["value"])
            elif msg["minORmax"] == "max":
                pot.moist_max = int(msg["value"])
            else:
                print(f"minORmax unknown")
       

    
def ProcessSensorData(module, msg):
    try:
        # ÄNDERUNG: Fehlerbehandlung falls Keys fehlen
        p_lvl = int(msg.get("PLvl", 0))
        p_ref = int(msg.get("PRef", 0))
        LvlRaw = p_lvl - p_ref
        
        # Vermeidung Division durch Null
        denom = module.TankLvlMax if module.TankLvlMax != 0 else 100
        module.TankLvl = (LvlRaw - module.TankLvlMin)*100/denom

        for i in range(1, 5):
            key = f"MPot{i}"
            if key in msg and i in module.pots:
                module.pots[i].moist_value = int(msg[key])
    except Exception as e:
        print(f"Fehler in SensorData: {e}")


# --- instantiate objects, TO BE REPLACED BY UI INPUT!!! -----------------------
# region 
AddModule(1, "Fensterbank")
AddModule(2, "Regal")

Modules[1].AddPot(1, "Orchidee", "time", 250, 60, 15)
Modules[1].AddPot(2, "Kaktus", "moist", 100, 20, 0)
Modules[2].AddPot(3, "Monstera", "moist", 1400, 10, 15)
# endregion

# --- Main ------------------------------------------------------------
if __name__ == "__main__":
    print("Bewässerungssystem gestartet...")

    try:
        while True:
            for module in Modules.values():
                while module.MQTT_buffer:
                    msg = module.MQTT_buffer.pop(0)
                    ProcessBufferData(module, msg)
            systime.sleep(1)


    except KeyboardInterrupt:
        print("Beende...")
        client.disconnect()

    except Exception as e:
        print(f"Fehler in main loop: {e}")

