# main.py (Improved with continuous vehicle flow and performance optimizations)
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk
import random, time, math, threading, sys, os
from collections import deque
from typing import Optional, List, Dict, Tuple

# Audio imports
USE_PYGAME = False
try:
    import pygame
    USE_PYGAME = True
    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
except Exception:
    USE_PYGAME = False
    if sys.platform.startswith("win"):
        import winsound

# -------------------------
# Configuration
# -------------------------
CANVAS_W = 1000
CANVAS_H = 700

GREEN_TIME = 8
YELLOW_TIME = 2
EMERGENCY_TIME = 8
CHECK_INTERVAL = 200
ANIM_INTERVAL = 16  # ~60 FPS for smoother animation

# Vehicle speeds (in pixels per frame)
CAR_BASE_SPEED = 2.5
AMB_BASE_SPEED = 4.0
FIRE_BASE_SPEED = 3.5

# Distances
STOP_DIST = 70
VEHICLE_SPAWN_DIST = 150  # Distance from intersection to spawn
VEHICLE_DESPAWN_DIST = 300  # Distance from intersection to despawn
MIN_SPACING = 40  # Minimum space between vehicles

# Colors
ROAD_COLOR = "#333"
CENTER_COLOR = "#222"
BG_COLOR = "#e9eaec"
PANEL_BG = "#f7f9fb"

# -------------------------
# Audio Manager
# -------------------------
class AudioManager:
    def __init__(self):
        self.sounds = {}
        self.load_sounds()
        
    def load_sounds(self):
        """Load all sound files"""
        ASSET_SND_PATH = "./assets/"
        sound_files = {
            "car_horn": "car_horn.wav",
            "ambulance_siren": "ambulance_siren.wav",
            "firetruck_siren": "firetruck_siren.wav",
            "engine": "engine.wav",
        }
        
        for name, filename in sound_files.items():
            full_path = os.path.join(ASSET_SND_PATH, filename)
            if os.path.exists(full_path):
                if USE_PYGAME:
                    try:
                        self.sounds[name] = pygame.mixer.Sound(full_path)
                    except:
                        self.sounds[name] = None
                else:
                    self.sounds[name] = full_path
            else:
                self.sounds[name] = None
    
    def play_sound(self, name, loop=False):
        """Play a sound by name"""
        sound = self.sounds.get(name)
        if not sound:
            return None
            
        if USE_PYGAME:
            try:
                if loop:
                    channel = pygame.mixer.find_channel()
                    if channel:
                        channel.play(sound, loops=-1)
                        return channel
                else:
                    sound.play()
            except:
                pass
        elif sys.platform.startswith("win"):
            try:
                if loop:
                    winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
                else:
                    winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except:
                pass
        return None
    
    def stop_sound(self, channel_or_handle):
        """Stop a playing sound"""
        if channel_or_handle and USE_PYGAME:
            try:
                channel_or_handle.stop()
            except:
                pass
        elif sys.platform.startswith("win"):
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except:
                pass

# -------------------------
# Traffic Controller
# -------------------------
class TrafficController:
    def __init__(self, ui):
        self.ui = ui
        self.signals = {
            "north": "red",
            "south": "red", 
            "east": "red",
            "west": "red"
        }
        self.emergency_queue = deque()
        self.cycle_state = "ns_green"
        self.state_timer = GREEN_TIME
        self.override_active = False
        self.override_direction = None
        self.override_timer = 0
        self.running = False
        
    def start(self):
        if not self.running:
            self.running = True
            self.set_ns_green()
            self._tick()
    
    def stop(self):
        self.running = False
    
    def add_emergency(self, direction: str, vehicle_type: str):
        """Add emergency vehicle to queue"""
        emergency = {
            "direction": direction,
            "type": vehicle_type,
            "time": time.time()
        }
        self.emergency_queue.append(emergency)
        self.ui.log_event(f"Emergency queued: {vehicle_type.upper()} from {direction.upper()}")
    
    def get_next_emergency(self):
        """Get highest priority emergency"""
        if not self.emergency_queue:
            return None
            
        # Sort by priority (ambulance > firetruck) and arrival time
        sorted_queue = sorted(self.emergency_queue, 
                            key=lambda x: (0 if x["type"] == "ambulance" else 1, x["time"]))
        return sorted_queue[0]
    
    def serve_emergency(self, emergency):
        """Activate emergency override"""
        if emergency in self.emergency_queue:
            self.emergency_queue.remove(emergency)
        
        self.override_active = True
        self.override_direction = emergency["direction"]
        self.override_timer = EMERGENCY_TIME
        
        # Set appropriate signals green
        if self.override_direction in ("north", "south"):
            self.signals.update({"north": "green", "south": "green", "east": "red", "west": "red"})
        else:
            self.signals.update({"east": "green", "west": "green", "north": "red", "south": "red"})
        
        self.ui.update_signals(self.signals, override=True)
        self.ui.log_event(f"Emergency active: {emergency['type'].upper()} from {emergency['direction'].upper()}")
    
    def end_override(self):
        """End emergency override"""
        self.override_active = False
        self.override_direction = None
        self.override_timer = 0
        
        # Remove all served emergencies for the direction
        if self.override_direction:
            self.emergency_queue = deque(
                e for e in self.emergency_queue 
                if e["direction"] != self.override_direction
            )
        
        # Return to normal cycle
        self.set_ns_green()
        self.ui.log_event("Emergency override ended")
    
    def set_ns_green(self):
        self.cycle_state = "ns_green"
        self.state_timer = GREEN_TIME
        self.signals.update({"north": "green", "south": "green", "east": "red", "west": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("Normal: North-South GREEN")
        self.ui.update_timer(self.state_timer)
    
    def set_ns_yellow(self):
        self.cycle_state = "ns_yellow"
        self.state_timer = YELLOW_TIME
        self.signals.update({"north": "yellow", "south": "yellow", "east": "red", "west": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("North-South YELLOW")
        self.ui.update_timer(self.state_timer)
    
    def set_ew_green(self):
        self.cycle_state = "ew_green"
        self.state_timer = GREEN_TIME
        self.signals.update({"east": "green", "west": "green", "north": "red", "south": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("Normal: East-West GREEN")
        self.ui.update_timer(self.state_timer)
    
    def set_ew_yellow(self):
        self.cycle_state = "ew_yellow"
        self.state_timer = YELLOW_TIME
        self.signals.update({"east": "yellow", "west": "yellow", "north": "red", "south": "red"})
        self.ui.update_signals(self.signals)
        self.ui.set_status("East-West YELLOW")
        self.ui.update_timer(self.state_timer)
    
    def _tick(self):
        if not self.running:
            return
        
        if self.override_active:
            # Handle emergency override
            self.override_timer -= CHECK_INTERVAL / 1000.0
            self.ui.update_timer(max(0, int(self.override_timer)))
            
            if self.override_timer <= 0:
                self.end_override()
        else:
            # Check for emergencies
            emergency = self.get_next_emergency()
            if emergency:
                self.serve_emergency(emergency)
            else:
                # Normal cycle
                self.state_timer -= CHECK_INTERVAL / 1000.0
                
                if self.state_timer <= 0:
                    # Transition to next state
                    if self.cycle_state == "ns_green":
                        self.set_ns_yellow()
                    elif self.cycle_state == "ns_yellow":
                        self.set_ew_green()
                    elif self.cycle_state == "ew_green":
                        self.set_ew_yellow()
                    elif self.cycle_state == "ew_yellow":
                        self.set_ns_green()
                else:
                    self.ui.update_timer(max(0, int(self.state_timer)))
        
        # Schedule next tick
        self.ui.root.after(CHECK_INTERVAL, self._tick)

# -------------------------
# Vehicle Manager
# -------------------------
class VehicleManager:
    def __init__(self, ui, canvas):
        self.ui = ui
        self.canvas = canvas
        self.vehicles = []
        self.vehicle_count = 0
        self.spawn_timer = None
        
        # Spawn points for each direction
        self.spawn_points = {
            "north": (CANVAS_W/2 - 60, -VEHICLE_SPAWN_DIST),
            "south": (CANVAS_W/2 + 60, CANVAS_H + VEHICLE_SPAWN_DIST),
            "west": (-VEHICLE_SPAWN_DIST, CANVAS_H/2 - 40),
            "east": (CANVAS_W + VEHICLE_SPAWN_DIST, CANVAS_H/2 + 40)
        }
        
        # Velocity vectors
        self.velocities = {
            "north": (0, 1),
            "south": (0, -1),
            "west": (1, 0),
            "east": (-1, 0)
        }
        
        # Despawn boundaries
        self.despawn_bounds = {
            "north": lambda y: y > CANVAS_H + VEHICLE_DESPAWN_DIST,
            "south": lambda y: y < -VEHICLE_DESPAWN_DIST,
            "west": lambda x: x > CANVAS_W + VEHICLE_DESPAWN_DIST,
            "east": lambda x: x < -VEHICLE_DESPAWN_DIST
        }
    
    def spawn_vehicle(self, direction: Optional[str] = None, vehicle_type: str = "car"):
        """Spawn a new vehicle"""
        if direction is None:
            direction = random.choice(list(self.spawn_points.keys()))
        
        # Check spacing to avoid collisions
        if not self.can_spawn_at(direction):
            return False
        
        # Create vehicle
        vehicle = Vehicle(
            self.ui, self.canvas, direction, vehicle_type,
            self.velocities[direction], self.spawn_points[direction]
        )
        
        self.vehicles.append(vehicle)
        self.vehicle_count += 1
        self.ui.total_var.set(self.vehicle_count)
        
        # Play appropriate sound
        if vehicle_type == "car":
            threading.Thread(target=lambda: self.ui.audio.play_sound("car_horn"), daemon=True).start()
        elif vehicle_type == "ambulance":
            vehicle.sound_channel = self.ui.audio.play_sound("ambulance_siren", loop=True)
        elif vehicle_type == "firetruck":
            vehicle.sound_channel = self.ui.audio.play_sound("firetruck_siren", loop=True)
        
        return True
    
    def can_spawn_at(self, direction: str) -> bool:
        """Check if there's enough space to spawn a vehicle"""
        spawn_x, spawn_y = self.spawn_points[direction]
        
        for vehicle in self.vehicles:
            if vehicle.direction == direction:
                # Calculate distance from spawn point
                dx = abs(vehicle.x - spawn_x)
                dy = abs(vehicle.y - spawn_y)
                distance = math.sqrt(dx*dx + dy*dy)
                
                if distance < MIN_SPACING:
                    return False
        
        return True
    
    def update_vehicles(self, signals: Dict, speed_multiplier: float):
        """Update all vehicles"""
        for vehicle in self.vehicles[:]:  # Use slice to copy list
            # Check traffic signals
            vehicle.check_stop_signal(signals)
            
            # Update position if not stopped
            if not vehicle.stopped:
                vehicle.move(speed_multiplier)
            
            # Update siren blinking for emergency vehicles
            if vehicle.vehicle_type in ("ambulance", "firetruck"):
                vehicle.update_siren()
            
            # Check if vehicle should be despawned
            if self.should_despawn(vehicle):
                self.remove_vehicle(vehicle)
    
    def should_despawn(self, vehicle) -> bool:
        """Check if vehicle is out of bounds"""
        check_bound = self.despawn_bounds.get(vehicle.direction)
        if check_bound:
            return check_bound(vehicle.x) or check_bound(vehicle.y)
        return False
    
    def remove_vehicle(self, vehicle):
        """Remove vehicle from simulation"""
        if vehicle in self.vehicles:
            # Stop any playing sounds
            if vehicle.sound_channel:
                self.ui.audio.stop_sound(vehicle.sound_channel)
            
            # Update stats if emergency vehicle made it through
            if (vehicle.vehicle_type in ("ambulance", "firetruck") and 
                vehicle.has_passed_intersection):
                if vehicle.vehicle_type == "ambulance":
                    self.ui.amb_served_var.set(self.ui.amb_served_var.get() + 1)
                else:
                    self.ui.fire_served_var.set(self.ui.fire_served_var.get() + 1)
            
            # Remove from canvas
            vehicle.destroy()
            
            # Remove from list
            self.vehicles.remove(vehicle)
    
    def clear_all(self):
        """Remove all vehicles"""
        for vehicle in self.vehicles[:]:
            self.remove_vehicle(vehicle)
        self.vehicles.clear()

# -------------------------
# Vehicle Class
# -------------------------
class Vehicle:
    id_counter = 0
    
    def __init__(self, ui, canvas, direction, vehicle_type, velocity, spawn_point):
        self.ui = ui
        self.canvas = canvas
        self.direction = direction
        self.vehicle_type = vehicle_type
        self.id = Vehicle.id_counter
        Vehicle.id_counter += 1
        
        # Position and movement
        self.x, self.y = spawn_point
        self.vx, self.vy = velocity
        self.base_speed = self._get_base_speed()
        self.speed = self.base_speed
        self.stopped = False
        self.has_passed_intersection = False
        
        # Visual properties
        self.color = self._get_color()
        self.siren_color = self._get_siren_color() if vehicle_type in ("ambulance", "firetruck") else None
        self.width, self.height = self._get_dimensions()
        
        # Canvas items
        self.canvas_id = None
        self.siren_id = None
        self.glow_id = None
        self.tk_image = None
        
        # Sound
        self.sound_channel = None
        
        # Siren animation
        self.blink_state = False
        self.blink_timer = 0
        
        # Create visual representation
        self.create_on_canvas()
    
    def _get_base_speed(self):
        speeds = {
            "car": CAR_BASE_SPEED,
            "ambulance": AMB_BASE_SPEED,
            "firetruck": FIRE_BASE_SPEED
        }
        return speeds.get(self.vehicle_type, CAR_BASE_SPEED)
    
    def _get_color(self):
        if self.vehicle_type == "ambulance":
            return "#ffffff"
        elif self.vehicle_type == "firetruck":
            return "#ff6b00"
        else:
            return random.choice(["#2E86C1", "#1E8449", "#7D3C98", "#F39C12", "#E74C3C"])
    
    def _get_siren_color(self):
        return "#ff0055" if self.vehicle_type == "ambulance" else "#ffcc00"
    
    def _get_dimensions(self):
        if self.direction in ("north", "south"):
            return 28, 16
        else:
            return 16, 28
    
    def create_on_canvas(self):
        """Create vehicle visual on canvas using sprite images"""
        try:
            # Load correct image based on vehicle type
            if self.vehicle_type == "ambulance":
                img = Image.open("assets/ambulance.png")
            elif self.vehicle_type == "firetruck":
                img = Image.open("assets/firetruck.png")
            else:
                # Use car sprites
                img_name = random.choice([
                    "car_green.png",
                    "car_red.png",
                    "car_yellow.png",
                    "car_blue.png"
                ])
                img = Image.open("assets/" + img_name)

            # Resize for simulation scale (smaller than original specification for better fitting)
            img = img.resize((50, 100), Image.Resampling.LANCZOS)

            # Rotate image depending on direction
            angle = {
                "north": 0,
                "south": 180,
                "east": 270,
                "west": 90
            }[self.direction]

            img = img.rotate(angle, expand=True)

            # Convert to Tkinter image
            self.tk_image = ImageTk.PhotoImage(img)

            # Draw sprite on canvas
            self.canvas_id = self.canvas.create_image(self.x, self.y, image=self.tk_image, tags="vehicle")
            
            # Add siren indicator for emergency vehicles
            if self.siren_color:
                self.create_siren_indicator()
                
        except Exception as e:
            print(f"Error loading sprite: {e}")
            # Fallback to rectangle if sprite loading fails
            self.create_fallback_visual()
    
    def create_fallback_visual(self):
        """Create fallback rectangle visual if sprite loading fails"""
        x1, y1 = self.x - self.width/2, self.y - self.height/2
        x2, y2 = self.x + self.width/2, self.y + self.height/2
        self.canvas_id = self.canvas.create_rectangle(
            x1, y1, x2, y2, fill=self.color, outline="#111", width=1, tags="vehicle"
        )
        
        # Add siren for emergency vehicles
        if self.siren_color:
            self.create_siren_indicator()
    
    def create_siren_indicator(self):
        """Create siren light indicator for emergency vehicles"""
        # Calculate siren position based on vehicle direction and type
        if self.vehicle_type == "ambulance":
            # Ambulance siren on top
            siren_x, siren_y = self.x, self.y - 35
            siren_size = 8
        elif self.vehicle_type == "firetruck":
            # Firetruck siren on top
            siren_x, siren_y = self.x, self.y - 40
            siren_size = 10
        else:
            return
            
        # Create siren light
        self.siren_id = self.canvas.create_oval(
            siren_x - siren_size, siren_y - siren_size,
            siren_x + siren_size, siren_y + siren_size,
            fill=self.siren_color, outline="black", width=1, tags="siren"
        )
        
        # Create glow effect
        glow_size = siren_size + 8
        self.glow_id = self.canvas.create_oval(
            siren_x - glow_size, siren_y - glow_size,
            siren_x + glow_size, siren_y + glow_size,
            fill=self.siren_color, outline="", stipple="gray50",
            state="hidden", tags="glow"
        )
    
    def move(self, speed_multiplier: float):
        """Move the vehicle"""
        move_x = self.vx * self.speed * speed_multiplier
        move_y = self.vy * self.speed * speed_multiplier
        
        # Update position
        self.x += move_x
        self.y += move_y
        
        # Move canvas items
        if self.canvas_id:
            self.canvas.move(self.canvas_id, move_x, move_y)
        if self.siren_id:
            self.canvas.move(self.siren_id, move_x, move_y)
        if self.glow_id:
            self.canvas.move(self.glow_id, move_x, move_y)
    
    def check_stop_signal(self, signals):
        """Check if vehicle should stop at intersection"""
        center_x, center_y = CANVAS_W/2, CANVAS_H/2
        
        # Calculate distance to intersection
        if self.direction == "north":
            distance_to_center = center_y - self.y
            should_stop = distance_to_center < STOP_DIST and distance_to_center > -STOP_DIST
            if should_stop:
                self.stopped = signals["north"] != "green"
            else:
                self.stopped = False
                if self.y > center_y + STOP_DIST:
                    self.has_passed_intersection = True
        
        elif self.direction == "south":
            distance_to_center = self.y - center_y
            should_stop = distance_to_center < STOP_DIST and distance_to_center > -STOP_DIST
            if should_stop:
                self.stopped = signals["south"] != "green"
            else:
                self.stopped = False
                if self.y < center_y - STOP_DIST:
                    self.has_passed_intersection = True
        
        elif self.direction == "west":
            distance_to_center = center_x - self.x
            should_stop = distance_to_center < STOP_DIST and distance_to_center > -STOP_DIST
            if should_stop:
                self.stopped = signals["west"] != "green"
            else:
                self.stopped = False
                if self.x > center_x + STOP_DIST:
                    self.has_passed_intersection = True
        
        elif self.direction == "east":
            distance_to_center = self.x - center_x
            should_stop = distance_to_center < STOP_DIST and distance_to_center > -STOP_DIST
            if should_stop:
                self.stopped = signals["east"] != "green"
            else:
                self.stopped = False
                if self.x < center_x - STOP_DIST:
                    self.has_passed_intersection = True
    
    def update_siren(self):
        """Update siren blinking effect"""
        self.blink_timer += 1
        if self.blink_timer >= 10:  # Blink every 10 frames
            self.blink_timer = 0
            self.blink_state = not self.blink_state
            
            if self.siren_id:
                self.canvas.itemconfig(self.siren_id, state="normal" if self.blink_state else "hidden")
            
            # Show glow when siren is on
            if self.glow_id:
                self.canvas.itemconfig(self.glow_id, state="normal" if self.blink_state else "hidden")
    
    def destroy(self):
        """Remove vehicle from canvas"""
        items = [self.canvas_id, self.siren_id, self.glow_id]
        for item in items:
            if item:
                try:
                    self.canvas.delete(item)
                except:
                    pass

# -------------------------
# Main UI
# -------------------------
class TrafficUI:
    def __init__(self, root):
        self.root = root
        root.title("Advanced Traffic Simulation - Continuous Flow")
        root.geometry(f"{CANVAS_W + 320}x{CANVAS_H + 20}")
        root.resizable(False, False)
        
        # Initialize components
        self.audio = AudioManager()
        
        # Create main canvas
        self.canvas = tk.Canvas(root, width=CANVAS_W, height=CANVAS_H, bg=BG_COLOR, highlightthickness=0)
        self.canvas.place(x=0, y=0)
        
        # Create control panel
        self.panel = tk.Frame(root, width=300, height=CANVAS_H, bg=PANEL_BG, relief="ridge")
        self.panel.place(x=CANVAS_W + 10, y=10)
        
        # Initialize managers
        self.vehicle_manager = VehicleManager(self, self.canvas)
        self.controller = TrafficController(self)
        
        # Setup UI
        self.setup_ui()
        self.draw_intersection()
        self.create_traffic_lights()
        
        # Animation variables
        self.animation_id = None
        self.spawn_id = None
        self.is_running = False
        
        # Start with stopped state
        self.set_status("Ready - Click Start")
    
    def setup_ui(self):
        """Setup control panel UI"""
        # Status display
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.panel, text="Status:", background=PANEL_BG, 
                 font=("Arial", 10, "bold")).place(x=12, y=10)
        self.status_label = ttk.Label(self.panel, textvariable=self.status_var, 
                                     background=PANEL_BG, wraplength=270)
        self.status_label.place(x=12, y=32)
        
        # Timer display
        self.timer_var = tk.StringVar(value="Timer: 0s")
        ttk.Label(self.panel, textvariable=self.timer_var, background=PANEL_BG,
                 font=("Arial", 9, "bold")).place(x=180, y=10)
        
        # Control buttons
        ttk.Button(self.panel, text="Start", command=self.start_simulation).place(x=12, y=62, width=80)
        ttk.Button(self.panel, text="Stop", command=self.stop_simulation).place(x=102, y=62, width=80)
        ttk.Button(self.panel, text="Reset", command=self.reset_simulation).place(x=192, y=62, width=90)
        
        # Spawn controls
        ttk.Label(self.panel, text="Spawn Rate (ms):", background=PANEL_BG).place(x=12, y=100)
        self.spawn_rate_var = tk.IntVar(value=1800)
        self.spawn_slider = ttk.Scale(self.panel, from_=400, to=5000, 
                                     orient="horizontal", variable=self.spawn_rate_var)
        self.spawn_slider.place(x=12, y=120, width=270)
        
        # Speed controls
        ttk.Label(self.panel, text="Speed Multiplier:", background=PANEL_BG).place(x=12, y=150)
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_slider = ttk.Scale(self.panel, from_=0.4, to=2.0,
                                     orient="horizontal", variable=self.speed_var)
        self.speed_slider.place(x=12, y=170, width=270)
        
        # Statistics
        self.setup_statistics()
        
        # Emergency spawn buttons
        self.setup_emergency_controls()
        
        # Event log
        self.setup_event_log()
    
    def setup_statistics(self):
        """Setup statistics display"""
        ttk.Label(self.panel, text="Statistics:", background=PANEL_BG,
                 font=("Arial", 10, "bold")).place(x=12, y=210)
        
        # Total vehicles
        self.total_var = tk.IntVar(value=0)
        ttk.Label(self.panel, text="Total Vehicles:", background=PANEL_BG).place(x=12, y=236)
        ttk.Label(self.panel, textvariable=self.total_var, background=PANEL_BG).place(x=200, y=236)
        
        # Ambulances served
        self.amb_served_var = tk.IntVar(value=0)
        ttk.Label(self.panel, text="Ambulances:", background=PANEL_BG).place(x=12, y=262)
        ttk.Label(self.panel, textvariable=self.amb_served_var, background=PANEL_BG).place(x=200, y=262)
        
        # Firetrucks served
        self.fire_served_var = tk.IntVar(value=0)
        ttk.Label(self.panel, text="Firetrucks:", background=PANEL_BG).place(x=12, y=288)
        ttk.Label(self.panel, textvariable=self.fire_served_var, background=PANEL_BG).place(x=200, y=288)
    
    def setup_emergency_controls(self):
        """Setup emergency vehicle spawn buttons"""
        y_base = 330
        ttk.Label(self.panel, text="Spawn Emergency:", background=PANEL_BG,
                 font=("Arial", 10, "bold")).place(x=12, y=y_base)
        
        # Ambulance buttons
        directions = [("N", "north"), ("S", "south"), ("E", "east"), ("W", "west")]
        for i, (label, direction) in enumerate(directions):
            x_pos = 12 + (i * 70)
            ttk.Button(self.panel, text=f"Amb {label}",
                      command=lambda d=direction: self.spawn_emergency_vehicle(d, "ambulance")
                      ).place(x=x_pos, y=y_base + 26, width=60)
        
        # Firetruck buttons
        for i, (label, direction) in enumerate(directions):
            x_pos = 12 + (i * 70)
            ttk.Button(self.panel, text=f"Fire {label}",
                      command=lambda d=direction: self.spawn_emergency_vehicle(d, "firetruck")
                      ).place(x=x_pos, y=y_base + 60, width=60)
    
    def setup_event_log(self):
        """Setup event log display"""
        y_base = 420
        ttk.Label(self.panel, text="Event Log:", background=PANEL_BG,
                 font=("Arial", 10, "bold")).place(x=12, y=y_base)
        
        # Create log listbox with scrollbar
        log_frame = tk.Frame(self.panel, bg=PANEL_BG)
        log_frame.place(x=12, y=y_base + 26, width=270, height=150)
        
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_list = tk.Listbox(log_frame, height=8, width=38,
                                  yscrollcommand=scrollbar.set, bg="white")
        self.log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_list.yview)
        
        # Clear log button
        ttk.Button(self.panel, text="Clear Log", command=self.clear_log).place(x=12, y=y_base + 180, width=270)
    
    def draw_intersection(self):
        """Draw the road intersection"""
        c = self.canvas
        
        # Draw roads
        road_width = 160
        center_x, center_y = CANVAS_W/2, CANVAS_H/2
        
        # Vertical road
        c.create_rectangle(center_x - road_width/2, 0,
                          center_x + road_width/2, CANVAS_H,
                          fill=ROAD_COLOR, outline="")
        
        # Horizontal road
        c.create_rectangle(0, center_y - road_width/2,
                          CANVAS_W, center_y + road_width/2,
                          fill=ROAD_COLOR, outline="")
        
        # Intersection center
        c.create_rectangle(center_x - road_width/2, center_y - road_width/2,
                          center_x + road_width/2, center_y + road_width/2,
                          fill=CENTER_COLOR, outline="")
        
        # Lane markings
        self.draw_lane_markings()
        
        # Direction labels
        self.draw_direction_labels()
    
    def draw_lane_markings(self):
        """Draw lane markings and arrows"""
        c = self.canvas
        center_x, center_y = CANVAS_W/2, CANVAS_H/2
        
        # Dashed center lines
        dash_length = 20
        gap_length = 10
        
        # Vertical dashed line
        for y in range(0, CANVAS_H, dash_length + gap_length):
            c.create_line(center_x, y, center_x, y + dash_length,
                         fill="white", width=2)
        
        # Horizontal dashed line
        for x in range(0, CANVAS_W, dash_length + gap_length):
            c.create_line(x, center_y, x + dash_length, center_y,
                         fill="white", width=2)
    
    def draw_direction_labels(self):
        """Draw direction labels"""
        c = self.canvas
        
        labels = [
            (CANVAS_W/2, 20, "NORTH", "white"),
            (CANVAS_W/2, CANVAS_H - 20, "SOUTH", "white"),
            (20, CANVAS_H/2, "WEST", "white"),
            (CANVAS_W - 20, CANVAS_H/2, "EAST", "white")
        ]
        
        for x, y, text, color in labels:
            c.create_text(x, y, text=text, fill=color,
                         font=("Arial", 12, "bold"))
    
    def create_traffic_lights(self):
        """Create traffic light displays"""
        self.traffic_lights = {}
        
        # Positions for each direction
        positions = {
            "north": (CANVAS_W/2 + 120, 60),
            "south": (CANVAS_W/2 - 120, CANVAS_H - 60),
            "west": (70, CANVAS_H/2 - 120),
            "east": (CANVAS_W - 70, CANVAS_H/2 + 120)
        }
        
        for direction, (x, y) in positions.items():
            self.traffic_lights[direction] = self.create_traffic_light(x, y, direction)
    
    def create_traffic_light(self, x, y, direction):
        """Create a single traffic light"""
        c = self.canvas
        light_ids = {}
        
        # Create light bulbs
        colors = ["red", "yellow", "green"]
        for i, color in enumerate(colors):
            if direction in ("north", "south"):
                # Vertical arrangement
                light_x = x
                light_y = y + (i * 30)
            else:
                # Horizontal arrangement
                light_x = x + (i * 30)
                light_y = y
            
            light_id = c.create_oval(light_x - 12, light_y - 12,
                                    light_x + 12, light_y + 12,
                                    fill="#440000" if color == "red" else 
                                         "#444400" if color == "yellow" else "#004400",
                                    outline="black", width=2)
            light_ids[color] = light_id
        
        # Create glow effect
        glow_id = c.create_oval(x - 20, y - 20, x + 20, y + 20,
                               fill="", outline="", stipple="gray50",
                               state="hidden")
        light_ids["glow"] = glow_id
        
        return light_ids
    
    def update_signals(self, signals, override=False):
        """Update traffic light colors"""
        for direction, state in signals.items():
            lights = self.traffic_lights.get(direction)
            if not lights:
                continue
            
            # Update each light color
            for color in ["red", "yellow", "green"]:
                fill_color = {
                    "red": "#ff0000" if color == "red" and state == "red" else "#440000",
                    "yellow": "#ffff00" if color == "yellow" and state == "yellow" else "#444400",
                    "green": "#00ff00" if color == "green" and state == "green" else "#004400"
                }[color]
                
                self.canvas.itemconfig(lights[color], fill=fill_color)
            
            # Update glow effect for green lights
            if state == "green":
                self.canvas.itemconfig(lights["glow"], 
                                      fill="#00ff66" if not override else "#66ffcc",
                                      state="normal")
            else:
                self.canvas.itemconfig(lights["glow"], state="hidden")
    
    def update_timer(self, seconds):
        """Update timer display"""
        self.timer_var.set(f"Timer: {seconds}s")
    
    def set_status(self, text):
        """Update status display"""
        self.status_var.set(text)
    
    def log_event(self, text):
        """Add event to log"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_list.insert(0, f"[{timestamp}] {text}")
        
        # Limit log size
        if self.log_list.size() > 100:
            self.log_list.delete(100, tk.END)
    
    def clear_log(self):
        """Clear event log"""
        self.log_list.delete(0, tk.END)
    
    def start_simulation(self):
        """Start the simulation"""
        if not self.is_running:
            self.is_running = True
            self.controller.start()
            self.start_spawning()
            self.start_animation()
            self.set_status("Simulation running")
            self.log_event("Simulation started")
    
    def stop_simulation(self):
        """Stop the simulation"""
        if self.is_running:
            self.is_running = False
            self.controller.stop()
            
            # Cancel scheduled tasks
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
                self.animation_id = None
            
            if self.spawn_id:
                self.root.after_cancel(self.spawn_id)
                self.spawn_id = None
            
            self.set_status("Simulation stopped")
            self.log_event("Simulation stopped")
    
    def reset_simulation(self):
        """Reset the simulation"""
        self.stop_simulation()
        
        # Clear all vehicles
        self.vehicle_manager.clear_all()
        
        # Reset statistics
        self.total_var.set(0)
        self.amb_served_var.set(0)
        self.fire_served_var.set(0)
        
        # Reset controller
        self.controller.emergency_queue.clear()
        self.controller.override_active = False
        self.controller.override_direction = None
        self.controller.set_ns_green()
        
        self.set_status("Simulation reset")
        self.log_event("Simulation reset")
    
    def start_spawning(self):
        """Start spawning vehicles"""
        if not self.is_running:
            return
        
        # Spawn a vehicle
        self.vehicle_manager.spawn_vehicle()
        
        # Schedule next spawn
        spawn_rate = self.spawn_rate_var.get()
        self.spawn_id = self.root.after(spawn_rate, self.start_spawning)
    
    def start_animation(self):
        """Start animation loop"""
        if not self.is_running:
            return
        
        # Update vehicles
        self.vehicle_manager.update_vehicles(
            self.controller.signals,
            self.speed_var.get()
        )
        
        # Schedule next animation frame
        self.animation_id = self.root.after(ANIM_INTERVAL, self.start_animation)
    
    def spawn_emergency_vehicle(self, direction, vehicle_type):
        """Spawn an emergency vehicle"""
        if self.vehicle_manager.spawn_vehicle(direction, vehicle_type):
            # Add to controller queue
            self.controller.add_emergency(direction, vehicle_type)
            
            # Log event
            self.log_event(f"Spawned {vehicle_type} from {direction}")
            
            # Ensure simulation is running
            if not self.is_running:
                self.start_simulation()
        else:
            self.log_event(f"Could not spawn {vehicle_type} - traffic too dense")

# -------------------------
# Main Application
# -------------------------
def main():
    # Create main window
    root = tk.Tk()
    
    # Create UI
    app = TrafficUI(root)
    
    # Start application
    root.mainloop()

if __name__ == "__main__":
    main()