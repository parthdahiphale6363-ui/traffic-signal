# main.py — Complete Fixed Traffic Simulation with Images
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox
import random, time, math, threading, os
from collections import deque, defaultdict
from typing import Optional, Dict, List, Tuple
import statistics

# -------------------------
# CONFIG
# -------------------------
CANVAS_W = 1000
CANVAS_H = 700

GREEN_TIME = 8
YELLOW_TIME = 2
EMERGENCY_HOLD = 6      # seconds to hold after emergency passes
AUTO_GREEN_DIST = 150   # distance threshold to auto-green for approaching emergency
PREEMPTION_DIST = 250   # distance for traffic preemption (clear path)

CHECK_INTERVAL = 200    # ms for controller tick
ANIM_INTERVAL = 16      # ms for animation (~60fps)

# Speeds (pixels per frame base)
CAR_BASE_SPEED = 2.5
AMB_BASE_SPEED = 4.5
FIRE_BASE_SPEED = 4.0
BUS_BASE_SPEED = 2.0

# Distances
STOP_DIST = 140
VEHICLE_SPAWN_DIST = 160
VEHICLE_DESPAWN_DIST = 350
MIN_SPACING = 45

# Colors / UI
ROAD_COLOR = "#333"
CENTER_COLOR = "#222"
BG_COLOR = "#e9eaec"
PANEL_BG = "#f7f9fb"

# Queue Visualization
QUEUE_MAX_VEHICLES = 8
QUEUE_VEHICLE_SIZE = 20
QUEUE_SPACING = 5
QUEUE_COLORS = {
    "car": "#3498db",
    "ambulance": "#e74c3c", 
    "firetruck": "#e67e22",
    "bus": "#2ecc71"
}

# -------------------------
# Statistics Manager
# -------------------------
class StatisticsManager:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.start_time = time.time()
        self.vehicle_stats = defaultdict(lambda: {"count": 0, "passed": 0, "wait_times": []})
        self.signal_changes = []
        self.emergency_events = []
        
    def log_vehicle(self, vehicle_type, passed=False, wait_time=0):
        self.vehicle_stats[vehicle_type]["count"] += 1
        if passed:
            self.vehicle_stats[vehicle_type]["passed"] += 1
        if wait_time > 0:
            self.vehicle_stats[vehicle_type]["wait_times"].append(wait_time)
            
    def log_signal_change(self, from_state, to_state):
        self.signal_changes.append({
            "time": time.time(),
            "from": from_state,
            "to": to_state
        })
        
    def log_emergency(self, vehicle_type, direction, response_time):
        self.emergency_events.append({
            "time": time.time(),
            "type": vehicle_type,
            "direction": direction,
            "response_time": response_time
        })
        
    def get_statistics(self):
        stats = {
            "total_time": time.time() - self.start_time,
            "total_vehicles": sum(v["count"] for v in self.vehicle_stats.values()),
            "vehicle_types": dict(self.vehicle_stats),
            "avg_wait_times": {},
            "emergency_response_avg": 0,
        }
        
        for vtype, data in self.vehicle_stats.items():
            if data["wait_times"]:
                stats["avg_wait_times"][vtype] = statistics.mean(data["wait_times"])
                
        if self.emergency_events:
            stats["emergency_response_avg"] = statistics.mean(e["response_time"] for e in self.emergency_events)
            
        return stats

# -------------------------
# TrafficController
# -------------------------
class TrafficController:
    def __init__(self, ui):
        self.ui = ui
        self.running = False
        
        # signals
        self.signals = {"north": "red", "south": "red", "east": "red", "west": "red"}
        
        # normal cycle
        self.cycle_state = "ns_green"
        self.state_timer = GREEN_TIME
        
        # emergency queue and override
        self.emergency_queue = deque()
        self.override_active = False
        self.override_direction = None
        self.override_timer = 0.0
        
        # statistics
        self.statistics = StatisticsManager()

    def start(self):
        if not self.running:
            self.running = True
            self.set_ns_green()
            self._tick()

    def stop(self):
        self.running = False

    def add_emergency(self, direction: str, vehicle_type: str):
        emergency = {"direction": direction, "type": vehicle_type, "time": time.time()}
        self.emergency_queue.append(emergency)
        self.ui.log_event(f"Emergency queued: {vehicle_type.upper()} from {direction.upper()}")
        
        # Start response timer
        self.statistics.log_emergency(vehicle_type, direction, 0)
        
        if not self.override_active:
            self.serve_next_emergency_if_any()

    def get_next_emergency(self) -> Optional[Dict]:
        if not self.emergency_queue:
            return None
        # Priority: ambulance first, then firetruck
        sorted_q = sorted(self.emergency_queue, key=lambda e: (0 if e["type"]=="ambulance" else 1, e["time"]))
        return sorted_q[0]

    def serve_next_emergency_if_any(self):
        next_em = self.get_next_emergency()
        if next_em:
            try:
                self.emergency_queue.remove(next_em)
            except ValueError:
                pass
            
            self.override_active = True
            self.override_direction = next_em["direction"]
            self.override_timer = EMERGENCY_HOLD
            
            # Apply emergency signals
            self.apply_emergency_signals(self.override_direction)
            
            self.ui.update_signals(self.signals, override=True)
            self.ui.set_status(f"EMERGENCY ACTIVE: {next_em['type'].upper()} from {next_em['direction'].upper()}")
            self.ui.log_event(f"Serving emergency: {next_em['type'].upper()} from {next_em['direction'].upper()}")
            
            # Log response time
            response_time = time.time() - next_em["time"]
            self.statistics.log_emergency(next_em["type"], next_em["direction"], response_time)

    def apply_emergency_signals(self, direction: str):
        if direction in ("north", "south"):
            self.signals.update({"north": "green", "south": "green", "east": "red", "west": "red"})
        else:
            self.signals.update({"east": "green", "west": "green", "north": "red", "south": "red"})

    def end_override(self):
        self.override_active = False
        self.override_direction = None
        self.override_timer = 0.0
        
        if self.get_next_emergency():
            self.serve_next_emergency_if_any()
            return
            
        self.set_ns_green()
        self.ui.log_event("Emergency override ended; returning to normal cycle")

    def auto_green_for_approaching(self):
        cx, cy = CANVAS_W/2, CANVAS_H/2
        
        for v in self.ui.vehicle_manager.vehicles:
            if v.vehicle_type in ("ambulance", "firetruck"):
                dist = math.sqrt((v.x - cx)**2 + (v.y - cy)**2)
                
                if dist < AUTO_GREEN_DIST and not self.override_active:
                    self.override_active = True
                    self.override_direction = v.direction
                    self.override_timer = EMERGENCY_HOLD
                    self.apply_emergency_signals(v.direction)
                    self.ui.update_signals(self.signals, override=True)
                    self.ui.set_status(f"AUTO-GREEN: {v.vehicle_type.upper()} approaching")
                    self.ui.log_event(f"Auto-green triggered for {v.vehicle_type.upper()} from {v.direction.upper()}")
                    return

    def set_ns_green(self):
        self.cycle_state = "ns_green"
        self.state_timer = GREEN_TIME
        self.signals.update({"north": "green", "south": "green", "east": "red", "west": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("Normal: North-South GREEN")

    def set_ns_yellow(self):
        self.cycle_state = "ns_yellow"
        self.state_timer = YELLOW_TIME
        self.signals.update({"north": "yellow", "south": "yellow", "east": "red", "west": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("North-South YELLOW")

    def set_ew_green(self):
        self.cycle_state = "ew_green"
        self.state_timer = GREEN_TIME
        self.signals.update({"east": "green", "west": "green", "north": "red", "south": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("Normal: East-West GREEN")

    def set_ew_yellow(self):
        self.cycle_state = "ew_yellow"
        self.state_timer = YELLOW_TIME
        self.signals.update({"east": "yellow", "west": "yellow", "north": "red", "south": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("East-West YELLOW")

    def _tick(self):
        if not self.running:
            return

        # Emergency handling
        self.auto_green_for_approaching()

        if self.override_active:
            self.override_timer -= CHECK_INTERVAL / 1000.0
            self.ui.update_timer(int(math.ceil(self.override_timer)))
            
            if self.override_timer <= 0:
                self.end_override()
        else:
            self.state_timer -= CHECK_INTERVAL / 1000.0
            self.ui.update_timer(max(0, int(math.ceil(self.state_timer))))
            
            if self.state_timer <= 0:
                if self.cycle_state == "ns_green":
                    self.set_ns_yellow()
                elif self.cycle_state == "ns_yellow":
                    self.set_ew_green()
                elif self.cycle_state == "ew_green":
                    self.set_ew_yellow()
                elif self.cycle_state == "ew_yellow":
                    self.set_ns_green()

        self.ui.root.after(CHECK_INTERVAL, self._tick)

# -------------------------
# VehicleManager
# -------------------------
class VehicleManager:
    def __init__(self, ui, canvas):
        self.ui = ui
        self.canvas = canvas
        self.vehicles: List['Vehicle'] = []
        self.vehicle_count = 0
        
        self.spawn_points = {
            "north": (CANVAS_W/2 - 60, -VEHICLE_SPAWN_DIST),
            "south": (CANVAS_W/2 + 60, CANVAS_H + VEHICLE_SPAWN_DIST),
            "west": (-VEHICLE_SPAWN_DIST, CANVAS_H/2 - 40),
            "east": (CANVAS_W + VEHICLE_SPAWN_DIST, CANVAS_H/2 + 40)
        }

        self.velocities = {"north": (0,1), "south": (0,-1), "west": (1,0), "east": (-1,0)}

    def spawn_vehicle(self, direction: Optional[str]=None, vehicle_type: str="car") -> bool:
        if direction is None:
            direction = random.choice(list(self.spawn_points.keys()))
        if not self.can_spawn_at(direction):
            return False
        v = Vehicle(self.ui, self.canvas, direction, vehicle_type, self.velocities[direction], self.spawn_points[direction])
        self.vehicles.append(v)
        self.vehicle_count += 1
        self.ui.total_var.set(self.vehicle_count)
        
        # Update statistics
        self.ui.controller.statistics.log_vehicle(vehicle_type)
        return True

    def can_spawn_at(self, direction: str) -> bool:
        sx, sy = self.spawn_points[direction]
        for v in self.vehicles:
            if v.direction == direction:
                if abs(v.x - sx) + abs(v.y - sy) < MIN_SPACING:
                    return False
        return True

    def update_vehicles(self, signals: Dict[str,str], speed_multiplier: float):
        for v in self.vehicles[:]:
            v.check_stop_signal(signals)
            if not v.stopped:
                v.move(speed_multiplier)
            if v.vehicle_type in ("ambulance", "firetruck"):
                v.update_siren()
            if self.should_despawn(v):
                self.remove_vehicle(v)

    def should_despawn(self, v: 'Vehicle') -> bool:
        if v.direction in ("north","south"):
            return v.y > CANVAS_H + VEHICLE_DESPAWN_DIST or v.y < -VEHICLE_DESPAWN_DIST
        else:
            return v.x > CANVAS_W + VEHICLE_DESPAWN_DIST or v.x < -VEHICLE_DESPAWN_DIST

    def remove_vehicle(self, v: 'Vehicle'):
        if v in self.vehicles:
            if v.vehicle_type in ("ambulance","firetruck") and v.has_passed_intersection:
                if v.vehicle_type == "ambulance":
                    self.ui.amb_served_var.set(self.ui.amb_served_var.get()+1)
                else:
                    self.ui.fire_served_var.set(self.ui.fire_served_var.get()+1)
                    
                # Update statistics
                wait_time = time.time() - v.spawn_time if hasattr(v, 'spawn_time') else 0
                self.ui.controller.statistics.log_vehicle(v.vehicle_type, passed=True, wait_time=wait_time)
                
            v.destroy()
            self.vehicles.remove(v)
            self.vehicle_count -= 1
            self.ui.total_var.set(self.vehicle_count)

    def clear_all(self):
        for v in self.vehicles[:]:
            v.destroy()
        self.vehicles.clear()
        self.vehicle_count = 0
        self.ui.total_var.set(0)

# -------------------------
# Vehicle class with IMAGES
# -------------------------
class Vehicle:
    id_counter = 0
    vehicle_images = {}  # Cache for vehicle images
    
    def __init__(self, ui, canvas, direction, vehicle_type, velocity, spawn_point):
        self.ui = ui
        self.canvas = canvas
        self.direction = direction
        self.vehicle_type = vehicle_type
        self.vx, self.vy = velocity
        self.x, self.y = spawn_point
        
        # Set speed based on vehicle type
        if vehicle_type == "ambulance":
            self.base_speed = AMB_BASE_SPEED
        elif vehicle_type == "firetruck":
            self.base_speed = FIRE_BASE_SPEED
        else:
            self.base_speed = CAR_BASE_SPEED
            
        self.speed = self.base_speed
        self.stopped = False
        self.has_passed_intersection = False
        self.spawn_time = time.time()
        
        self.canvas_id = None
        self.siren_id = None
        self.blink_counter = 0
        self.tk_image = None  # Keep reference to prevent garbage collection
        
        Vehicle.id_counter += 1
        self.create_visual()

    def create_visual(self):
        try:
            # Load and resize image based on vehicle type
            if self.vehicle_type == "ambulance" and os.path.exists("assets/ambulance.png"):
                img_path = "assets/ambulance.png"
                size = (40, 80)
            elif self.vehicle_type == "firetruck" and os.path.exists("assets/firetruck.png"):
                img_path = "assets/firetruck.png"
                size = (45, 85)
            elif os.path.exists("assets/car_blue.png"):
                # Randomly choose car color if available
                car_files = ["car_blue.png", "car_red.png", "car_green.png", "car_yellow.png"]
                available_files = [f for f in car_files if os.path.exists(f"assets/{f}")]
                if available_files:
                    img_path = f"assets/{random.choice(available_files)}"
                    size = (35, 70)
                else:
                    raise FileNotFoundError("No car images found")
            else:
                raise FileNotFoundError("Image not found")
            
            # Load and process image
            img = Image.open(img_path)
            img = img.resize(size, Image.Resampling.LANCZOS)
            
            # Rotate based on direction
            if self.direction == "north":
                angle = 0
            elif self.direction == "south":
                angle = 180
            elif self.direction == "east":
                angle = 270
            else:  # west
                angle = 90
                
            img = img.rotate(angle, expand=True)
            
            # Convert to PhotoImage
            self.tk_image = ImageTk.PhotoImage(img)
            self.canvas_id = self.canvas.create_image(self.x, self.y, image=self.tk_image)
            
        except Exception as e:
            # Fallback to rectangle if image loading fails
            print(f"Failed to load image: {e}. Using fallback rectangle.")
            color = "white" if self.vehicle_type == "ambulance" else "orange" if self.vehicle_type == "firetruck" else "blue"
            w, h = (28, 16) if self.direction in ("east", "west") else (16, 28)
            self.canvas_id = self.canvas.create_rectangle(
                self.x - w/2, self.y - h/2, 
                self.x + w/2, self.y + h/2, 
                fill=color, outline="black", width=1
            )
        
        # Siren indicator for emergency vehicles
        if self.vehicle_type in ("ambulance", "firetruck"):
            sx, sy = self.x, self.y - 25
            self.siren_id = self.canvas.create_oval(
                sx - 6, sy - 6, sx + 6, sy + 6, 
                fill="red", outline="yellow", width=1
            )

    def move(self, speed_multiplier: float):
        dx = self.vx * self.speed * speed_multiplier
        dy = self.vy * self.speed * speed_multiplier
        self.x += dx
        self.y += dy
        
        # Move vehicle
        if self.canvas_id:
            self.canvas.move(self.canvas_id, dx, dy)
        if self.siren_id:
            self.canvas.move(self.siren_id, dx, dy)

        # Mark passed intersection
        cx, cy = CANVAS_W/2, CANVAS_H/2
        if not self.has_passed_intersection:
            if self.direction == "north" and self.y > cy + 30: 
                self.has_passed_intersection = True
            if self.direction == "south" and self.y < cy - 30: 
                self.has_passed_intersection = True
            if self.direction == "west" and self.x > cx + 30: 
                self.has_passed_intersection = True
            if self.direction == "east" and self.x < cx - 30: 
                self.has_passed_intersection = True

    def check_stop_signal(self, signals: Dict[str,str]):
        # Emergency vehicles ignore signals
        if self.vehicle_type in ("ambulance", "firetruck"):
            self.stopped = False
            return

        cx, cy = CANVAS_W/2, CANVAS_H/2
        if self.direction == "north":
            dist = cy - self.y
            if dist < STOP_DIST and signals["north"] != "green":
                self.stopped = True
                return
        elif self.direction == "south":
            dist = self.y - cy
            if dist < STOP_DIST and signals["south"] != "green":
                self.stopped = True
                return
        elif self.direction == "west":
            dist = cx - self.x
            if dist < STOP_DIST and signals["west"] != "green":
                self.stopped = True
                return
        elif self.direction == "east":
            dist = self.x - cx
            if dist < STOP_DIST and signals["east"] != "green":
                self.stopped = True
                return

        self.stopped = False

    def update_siren(self):
        if not self.siren_id:
            return
        self.blink_counter = (self.blink_counter + 1) % 20
        color = "red" if self.blink_counter < 10 else "blue"
        self.canvas.itemconfig(self.siren_id, fill=color)

    def destroy(self):
        if self.canvas_id:
            self.canvas.delete(self.canvas_id)
        if self.siren_id:
            self.canvas.delete(self.siren_id)

# -------------------------
# TrafficUI
# -------------------------
class TrafficUI:
    def __init__(self, root):
        self.root = root
        root.title("Emergency Priority Traffic Simulation")
        root.geometry(f"{CANVAS_W + 320}x{CANVAS_H + 20}")
        root.resizable(False, False)

        # Canvas
        self.canvas = tk.Canvas(root, width=CANVAS_W, height=CANVAS_H, bg=BG_COLOR, highlightthickness=0)
        self.canvas.place(x=0, y=0)

        # Panel
        self.panel = tk.Frame(root, width=300, height=CANVAS_H, bg=PANEL_BG)
        self.panel.place(x=CANVAS_W + 10, y=10)

        # Managers
        self.vehicle_manager = VehicleManager(self, self.canvas)
        self.controller = TrafficController(self)

        # UI variables
        self.is_running = False
        self.animation_id = None
        self.spawn_id = None

        # Stats
        self.total_var = tk.IntVar(value=0)
        self.amb_served_var = tk.IntVar(value=0)
        self.fire_served_var = tk.IntVar(value=0)
        self.timer_var = tk.StringVar(value="Timer: 0s")
        self.status_var = tk.StringVar(value="Ready - Click Start")

        # Queue visualization
        self.queue_visualizations = {
            "north": {"canvas": None, "items": [], "count": 0},
            "south": {"canvas": None, "items": [], "count": 0},
            "east": {"canvas": None, "items": [], "count": 0},
            "west": {"canvas": None, "items": [], "count": 0}
        }

        # Controls
        self.setup_ui()
        self.draw_intersection()
        self.create_traffic_lights()

    def setup_ui(self):
        ttk.Label(self.panel, text="Status:", background=PANEL_BG, font=("Arial",10,"bold")).place(x=12,y=8)
        ttk.Label(self.panel, textvariable=self.status_var, background=PANEL_BG, wraplength=270).place(x=12,y=30)
        ttk.Label(self.panel, textvariable=self.timer_var, background=PANEL_BG).place(x=180,y=10)

        ttk.Button(self.panel, text="Start", command=self.start_simulation).place(x=12,y=62,width=80)
        ttk.Button(self.panel, text="Stop", command=self.stop_simulation).place(x=102,y=62,width=80)
        ttk.Button(self.panel, text="Reset", command=self.reset_simulation).place(x=192,y=62,width=90)

        ttk.Label(self.panel, text="Spawn Rate (ms):", background=PANEL_BG).place(x=12,y=100)
        self.spawn_rate_var = tk.IntVar(value=1800)
        ttk.Scale(self.panel, from_=400, to=5000, orient="horizontal", variable=self.spawn_rate_var).place(x=12,y=120,width=270)

        ttk.Label(self.panel, text="Speed Multiplier:", background=PANEL_BG).place(x=12,y=150)
        self.speed_var = tk.DoubleVar(value=1.0)
        ttk.Scale(self.panel, from_=0.4, to=2.0, orient="horizontal", variable=self.speed_var).place(x=12,y=170,width=270)

        # Stats
        ttk.Label(self.panel, text="Statistics:", background=PANEL_BG, font=("Arial",10,"bold")).place(x=12,y=210)
        ttk.Label(self.panel, text="Total Vehicles:", background=PANEL_BG).place(x=12,y=236)
        ttk.Label(self.panel, textvariable=self.total_var, background=PANEL_BG).place(x=200,y=236)
        ttk.Label(self.panel, text="Ambulances Served:", background=PANEL_BG).place(x=12,y=262)
        ttk.Label(self.panel, textvariable=self.amb_served_var, background=PANEL_BG).place(x=200,y=262)
        ttk.Label(self.panel, text="Firetrucks Served:", background=PANEL_BG).place(x=12,y=288)
        ttk.Label(self.panel, textvariable=self.fire_served_var, background=PANEL_BG).place(x=200,y=288)

        # Emergency buttons
        y_base = 330
        ttk.Label(self.panel, text="Spawn Emergency:", background=PANEL_BG, font=("Arial",10,"bold")).place(x=12,y=y_base)
        directions = [("N","north"),("S","south"),("E","east"),("W","west")]
        for i,(lbl,dirc) in enumerate(directions):
            ttk.Button(self.panel, text=f"Amb {lbl}", command=lambda d=dirc: self.spawn_emergency_vehicle(d,"ambulance")).place(x=12+i*70,y=y_base+26,width=60)
        for i,(lbl,dirc) in enumerate(directions):
            ttk.Button(self.panel, text=f"Fire {lbl}", command=lambda d=dirc: self.spawn_emergency_vehicle(d,"firetruck")).place(x=12+i*70,y=y_base+60,width=60)
        
        # Queue Visualization
        y_base = 420
        ttk.Label(self.panel, text="Queue Visualization:", background=PANEL_BG, font=("Arial",10,"bold")).place(x=12,y=y_base)
        
        # Create queue visualization frames for each direction
        queue_frame = tk.Frame(self.panel, bg=PANEL_BG, relief=tk.RIDGE, borderwidth=1)
        queue_frame.place(x=12, y=y_base+25, width=270, height=100)
        
        # North queue
        north_label = ttk.Label(queue_frame, text="North:", background=PANEL_BG)
        north_label.place(x=5, y=5)
        north_queue_canvas = tk.Canvas(queue_frame, width=250, height=20, bg=PANEL_BG, highlightthickness=0)
        north_queue_canvas.place(x=50, y=5)
        self.queue_visualizations["north"]["canvas"] = north_queue_canvas
        
        # South queue
        south_label = ttk.Label(queue_frame, text="South:", background=PANEL_BG)
        south_label.place(x=5, y=30)
        south_queue_canvas = tk.Canvas(queue_frame, width=250, height=20, bg=PANEL_BG, highlightthickness=0)
        south_queue_canvas.place(x=50, y=30)
        self.queue_visualizations["south"]["canvas"] = south_queue_canvas
        
        # West queue
        west_label = ttk.Label(queue_frame, text="West:", background=PANEL_BG)
        west_label.place(x=5, y=55)
        west_queue_canvas = tk.Canvas(queue_frame, width=250, height=20, bg=PANEL_BG, highlightthickness=0)
        west_queue_canvas.place(x=50, y=55)
        self.queue_visualizations["west"]["canvas"] = west_queue_canvas
        
        # East queue
        east_label = ttk.Label(queue_frame, text="East:", background=PANEL_BG)
        east_label.place(x=5, y=80)
        east_queue_canvas = tk.Canvas(queue_frame, width=250, height=20, bg=PANEL_BG, highlightthickness=0)
        east_queue_canvas.place(x=50, y=80)
        self.queue_visualizations["east"]["canvas"] = east_queue_canvas
        
        # Move event log down
        y_base = 525
        ttk.Label(self.panel, text="Event Log:", background=PANEL_BG, font=("Arial",10,"bold")).place(x=12,y=y_base)
        log_frame = tk.Frame(self.panel, bg=PANEL_BG)
        log_frame.place(x=12,y=y_base+25,width=270,height=150)
        self.log_list = tk.Listbox(log_frame, height=8, width=38)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_list.config(yscrollcommand=scrollbar.set)
        ttk.Button(self.panel, text="Clear Log", command=self.clear_log).place(x=12,y=y_base+185,width=270)

    def draw_intersection(self):
        c = self.canvas
        road_w = 160
        cx, cy = CANVAS_W/2, CANVAS_H/2
        c.create_rectangle(cx-road_w/2, 0, cx+road_w/2, CANVAS_H, fill=ROAD_COLOR, outline="")
        c.create_rectangle(0, cy-road_w/2, CANVAS_W, cy+road_w/2, fill=ROAD_COLOR, outline="")
        c.create_rectangle(cx-road_w/2, cy-road_w/2, cx+road_w/2, cy+road_w/2, fill=CENTER_COLOR, outline="")

        # labels
        c.create_text(CANVAS_W/2, 20, text="NORTH", fill="white", font=("Arial",12,"bold"))
        c.create_text(CANVAS_W/2, CANVAS_H-20, text="SOUTH", fill="white", font=("Arial",12,"bold"))
        c.create_text(20, CANVAS_H/2, text="WEST", fill="white", font=("Arial",12,"bold"))
        c.create_text(CANVAS_W-20, CANVAS_H/2, text="EAST", fill="white", font=("Arial",12,"bold"))

    def create_traffic_lights(self):
        self.traffic_lights = {}
        positions = {"north": (CANVAS_W/2+120, 60), "south": (CANVAS_W/2-120, CANVAS_H-60), 
                    "west": (70, CANVAS_H/2-120), "east": (CANVAS_W-70, CANVAS_H/2+120)}
        for d,(x,y) in positions.items():
            self.traffic_lights[d] = {
                "red": self.canvas.create_oval(x-12,y-12,x+12,y+12, fill="#440000"),
                "yellow": self.canvas.create_oval(x-12,y+20,x+12,y+44, fill="#444400"),
                "green": self.canvas.create_oval(x-12,y+52,x+12,y+76, fill="#004400"),
                "glow": self.canvas.create_oval(x-24,y-24,x+24,y+24, fill="", state="hidden")
            }

    def update_signals(self, signals: Dict[str,str], override: bool=False):
        for d,state in signals.items():
            lights = self.traffic_lights.get(d)
            if not lights: continue
            self.canvas.itemconfig(lights["red"], fill="#ff0000" if state=="red" else "#440000")
            self.canvas.itemconfig(lights["yellow"], fill="#ffff00" if state=="yellow" else "#444400")
            self.canvas.itemconfig(lights["green"], fill="#00ff00" if state=="green" else "#004400")
            if state=="green" and override:
                self.canvas.itemconfig(lights["glow"], fill="#66ffcc", state="normal")
            else:
                self.canvas.itemconfig(lights["glow"], state="hidden")

    def update_timer(self, seconds: int):
        self.timer_var.set(f"Timer: {seconds}s")

    def set_status(self, text: str):
        self.status_var.set(text)

    def log_event(self, text: str):
        ts = time.strftime("%H:%M:%S")
        self.log_list.insert(0, f"[{ts}] {text}")
        if self.log_list.size() > 200:
            self.log_list.delete(200, tk.END)

    def clear_log(self):
        self.log_list.delete(0, tk.END)
        self.log_event("Log cleared")

    def get_vehicle_distance_to_intersection(self, vehicle):
        """Calculate vehicle's distance to intersection center"""
        cx, cy = CANVAS_W/2, CANVAS_H/2
        return math.sqrt((vehicle.x - cx)**2 + (vehicle.y - cy)**2)

    def update_queue_visualization(self):
        """Update the queue visualization for all directions"""
        for direction in ["north", "south", "east", "west"]:
            self.update_direction_queue(direction)
    
    def update_direction_queue(self, direction: str):
        """Update queue visualization for a specific direction"""
        if direction not in self.queue_visualizations:
            return
            
        queue_info = self.queue_visualizations[direction]
        canvas = queue_info["canvas"]
        if not canvas:
            return
        
        # Clear existing queue items
        for item in queue_info["items"]:
            canvas.delete(item)
        queue_info["items"] = []
        
        # Count vehicles waiting at this signal
        waiting_vehicles = []
        for vehicle in self.vehicle_manager.vehicles:
            if vehicle.direction == direction and vehicle.stopped:
                # Check if vehicle is within stopping distance
                cx, cy = CANVAS_W/2, CANVAS_H/2
                if direction == "north" and cy - vehicle.y < STOP_DIST:
                    waiting_vehicles.append(vehicle)
                elif direction == "south" and vehicle.y - cy < STOP_DIST:
                    waiting_vehicles.append(vehicle)
                elif direction == "west" and cx - vehicle.x < STOP_DIST:
                    waiting_vehicles.append(vehicle)
                elif direction == "east" and vehicle.x - cx < STOP_DIST:
                    waiting_vehicles.append(vehicle)
        
        # Sort by distance to intersection (closest first)
        waiting_vehicles.sort(key=lambda v: self.get_vehicle_distance_to_intersection(v), reverse=True)
        
        # Limit to max display
        display_vehicles = waiting_vehicles[:QUEUE_MAX_VEHICLES]
        queue_info["count"] = len(waiting_vehicles)
        
        # Draw queue visualization
        x_pos = 5
        for i, vehicle in enumerate(display_vehicles):
            color = QUEUE_COLORS.get(vehicle.vehicle_type, "#3498db")
            
            # Draw vehicle rectangle
            rect = canvas.create_rectangle(
                x_pos, 5,
                x_pos + QUEUE_VEHICLE_SIZE, 5 + QUEUE_VEHICLE_SIZE,
                fill=color, outline="black", width=1
            )
            queue_info["items"].append(rect)
            
            # Add vehicle type indicator
            if vehicle.vehicle_type == "ambulance":
                indicator = canvas.create_text(
                    x_pos + QUEUE_VEHICLE_SIZE//2, 5 + QUEUE_VEHICLE_SIZE//2,
                    text="A", fill="white", font=("Arial", 8, "bold")
                )
                queue_info["items"].append(indicator)
            elif vehicle.vehicle_type == "firetruck":
                indicator = canvas.create_text(
                    x_pos + QUEUE_VEHICLE_SIZE//2, 5 + QUEUE_VEHICLE_SIZE//2,
                    text="F", fill="white", font=("Arial", 8, "bold")
                )
                queue_info["items"].append(indicator)
            
            x_pos += QUEUE_VEHICLE_SIZE + QUEUE_SPACING
        
        # If there are more vehicles than we can display, show a count
        if len(waiting_vehicles) > QUEUE_MAX_VEHICLES:
            extra_count = len(waiting_vehicles) - QUEUE_MAX_VEHICLES
            count_text = canvas.create_text(
                x_pos + 10, 5 + QUEUE_VEHICLE_SIZE//2,
                text=f"+{extra_count} more", fill="#666", font=("Arial", 8)
            )
            queue_info["items"].append(count_text)

    # -------------------------
    # Simulation controls
    # -------------------------
    def start_simulation(self):
        if not self.is_running:
            self.is_running = True
            self.controller.start()
            self.start_spawning()
            self.start_animation()
            self.set_status("Simulation running")
            self.log_event("Simulation started")

    def stop_simulation(self):
        if self.is_running:
            self.is_running = False
            self.controller.stop()
            if self.spawn_id:
                self.root.after_cancel(self.spawn_id); self.spawn_id = None
            if self.animation_id:
                self.root.after_cancel(self.animation_id); self.animation_id = None
            self.set_status("Simulation stopped")
            self.log_event("Simulation stopped")

    def reset_simulation(self):
        self.stop_simulation()
        self.vehicle_manager.clear_all()
        self.total_var.set(0); self.amb_served_var.set(0); self.fire_served_var.set(0)
        self.controller.emergency_queue.clear()
        self.controller.override_active = False
        self.controller.override_direction = None
        self.controller.statistics.reset()
        self.controller.set_ns_green()
        
        # Clear queue visualizations
        for direction in self.queue_visualizations:
            queue_info = self.queue_visualizations[direction]
            canvas = queue_info["canvas"]
            if canvas:
                for item in queue_info["items"]:
                    canvas.delete(item)
                queue_info["items"] = []
                queue_info["count"] = 0
        
        self.set_status("Simulation reset")
        self.log_event("Simulation reset")

    # spawning
    def start_spawning(self):
        if not self.is_running: return
        spawned = self.vehicle_manager.spawn_vehicle()
        if spawned:
            self.total_var.set(self.vehicle_manager.vehicle_count)
        rate = int(self.spawn_rate_var.get())
        self.spawn_id = self.root.after(rate, self.start_spawning)

    # animation
    def start_animation(self):
        if not self.is_running: return
        self.vehicle_manager.update_vehicles(self.controller.signals, self.speed_var.get())
        self.update_queue_visualization()  # Update queue visualization
        self.animation_id = self.root.after(ANIM_INTERVAL, self.start_animation)

    # emergency spawn
    def spawn_emergency_vehicle(self, direction: str, vehicle_type: str):
        ok = self.vehicle_manager.spawn_vehicle(direction, vehicle_type)
        if ok:
            self.controller.add_emergency(direction, vehicle_type)
            self.log_event(f"Spawned {vehicle_type.upper()} from {direction.upper()}")
            if not self.is_running:
                self.start_simulation()
        else:
            self.log_event(f"Could not spawn {vehicle_type} at {direction} (too close)")

# -------------------------
# main
# -------------------------
def main():
    root = tk.Tk()
    app = TrafficUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()