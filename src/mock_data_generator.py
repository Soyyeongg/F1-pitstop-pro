"""
Mock Data Generator for Pit-Stop Racer Pro
Simulates real-time telemetry data for the JetRacer CPS system.
"""

import random
import math


class MockDataGenerator:
    """Generates realistic mock telemetry data for the racing simulation."""
    
    def __init__(self):
        # Initial state
        self.speed = 1.2  # m/s
        self.fuel = 100.0  # %
        self.battery = 100.0  # %
        self.tire_wear = 0.0  # %
        self.status = "racing"  # racing / pitting / avoiding / rain
        self.weather = "dry"  # dry / rain
        self.humidity = 45.0  # % humidity
        self.strategy = "BALANCED"  # PERFORMANCE / BALANCED / SUSTAINABILITY / RELIABILITY
        
        # Time tracking
        self.elapsed_time = 0.0
        self.tick = 0
        
        # Event states
        self.accident_active = False
        self.accident_distance = 0
        self.accident_timer = 0
        
        self.rain_pending = False
        self.rain_delay = 0
        self.rain_active = False
        self.rain_timer = 0
        
        # Pit stop scheduling
        self.pit_recommended = False  # True when system recommends pit
        self.pit_reason = ""           # Why pit is recommended
        self.pit_in_progress = False   # True during pit stop
        self.pit_timer = 0.0           # Time remaining in pit
        self.pit_duration = 5.0        # Pit stop duration in seconds
    
    def get_telemetry(self):
        """Get the current telemetry snapshot."""
        self.tick += 1
        self.elapsed_time += 0.5  # 500ms per tick
        
        # Update simulated values
        self._update_speed()
        self._update_resources()
        self._update_status()
        self._update_strategy()
        self._update_events()
        
        # Update humidity (oscillates around base value, jumps when raining)
        if self.weather == "rain":
            target_humidity = 85.0 + 5.0 * math.sin(self.tick * 0.05)
        else:
            target_humidity = 45.0 + 10.0 * math.sin(self.tick * 0.02)
        self.humidity += (target_humidity - self.humidity) * 0.05
        self.humidity = max(20.0, min(95.0, self.humidity))
        
        return {
            'speed': round(self.speed, 2),
            'fuel': round(self.fuel, 1),
            'battery': round(self.battery, 1),
            'tire_wear': round(self.tire_wear, 1),
            'humidity': round(self.humidity, 0),
            'status': self.status,
            'weather': self.weather,
            'strategy': self.strategy,
        }
    
    def _update_speed(self):
        """Update speed based on current status and conditions."""
        # Base speed varies sinusoidally to simulate realistic driving
        base_speed = 1.5 + 0.3 * math.sin(self.tick * 0.1)
        
        if self.status == "pitting":
            target = 0.3
        elif self.status == "avoiding":
            target = 0.6
        elif self.status == "rain" or self.weather == "rain":
            target = 0.9 + 0.2 * math.sin(self.tick * 0.15)
        else:  # racing
            target = base_speed
        
        # Smooth transition to target speed
        self.speed += (target - self.speed) * 0.3
        self.speed = max(0.0, min(2.5, self.speed))
    
    def _update_resources(self):
        """Update fuel, battery, and tire wear over time."""
        # Consumption rates depend on speed and status
        speed_factor = self.speed / 2.0
        
        # Fuel consumption (faster = more fuel)
        fuel_rate = 0.05 + (speed_factor * 0.1)
        if self.status == "pitting":
            self.fuel = min(100.0, self.fuel + 5.0)  # Refueling
        else:
            self.fuel = max(0.0, self.fuel - fuel_rate)
        
        # Battery consumption
        battery_rate = 0.03 + (speed_factor * 0.08)
        if self.status == "pitting":
            self.battery = min(100.0, self.battery + 4.0)  # Charging
        else:
            self.battery = max(0.0, self.battery - battery_rate)
        
        # Tire wear (increases over time, more with speed)
        wear_rate = 0.04 + (speed_factor * 0.1)
        if self.weather == "rain":
            wear_rate *= 0.5  # Less wear in rain
        if self.status == "pitting":
            self.tire_wear = max(0.0, self.tire_wear - 8.0)  # New tires
        else:
            self.tire_wear = min(100.0, self.tire_wear + wear_rate)
    
    def _update_status(self):
        """Update racing status based on conditions."""
        # Determine pit stop recommendation
        reasons = []
        if self.fuel < 25:
            reasons.append("LOW FUEL")
        if self.tire_wear > 75:
            reasons.append("WORN TIRES")
        if self.battery < 25:
            reasons.append("LOW BATTERY")
        
        if reasons and not self.pit_in_progress:
            self.pit_recommended = True
            self.pit_reason = " + ".join(reasons)
        else:
            self.pit_recommended = False
            self.pit_reason = ""
        
        # Auto pit-stop trigger when very critical
        if (self.fuel < 15 or self.tire_wear > 88 or self.battery < 15) and self.status == "racing" and not self.pit_in_progress:
            self.start_pit_stop()
        
        # Pit stop in progress - countdown
        if self.pit_in_progress:
            self.pit_timer -= 0.5  # 0.5s per tick
            if self.pit_timer <= 0:
                self._finish_pit_stop()
        
        # Override status with active events
        if self.accident_active:
            self.status = "avoiding"
        elif self.rain_active and not self.pit_in_progress:
            self.status = "rain"
    
    def start_pit_stop(self):
        """Start a pit stop sequence."""
        self.pit_in_progress = True
        self.pit_timer = self.pit_duration
        self.status = "pitting"
        self.pit_recommended = False
        print(f"🔧 Entering pit lane (5 second stop)")
    
    def _finish_pit_stop(self):
        """Complete the pit stop and resume racing."""
        self.pit_in_progress = False
        self.pit_timer = 0.0
        # Restore resources
        self.fuel = 100.0
        self.tire_wear = 0.0
        self.battery = min(100.0, self.battery + 50.0)
        self.status = "racing"
        print(f"🏁 Pit stop complete - resuming race")
    
    def _update_strategy(self):
        """Update racing strategy based on conditions."""
        # Strategy adapts based on resource levels and conditions
        if self.weather == "rain":
            self.strategy = "RELIABILITY"
        elif self.fuel < 30 or self.battery < 30:
            self.strategy = "SUSTAINABILITY"
        elif self.tire_wear > 60:
            self.strategy = "RELIABILITY"
        elif self.fuel > 70 and self.tire_wear < 30:
            self.strategy = "PERFORMANCE"
        else:
            self.strategy = "BALANCED"
    
    def _update_events(self):
        """Handle active events (accident, rain)."""
        # Accident event
        if self.accident_active:
            self.accident_timer -= 0.5
            if self.accident_timer <= 0:
                self.accident_active = False
                if self.status == "avoiding":
                    self.status = "racing"
        
        # Rain event - delay before starting
        if self.rain_pending:
            self.rain_delay -= 0.5
            if self.rain_delay <= 0:
                self.rain_pending = False
                self.rain_active = True
                self.weather = "rain"
                self.rain_timer = 60  # Rain lasts 60 seconds
        
        # Active rain
        if self.rain_active:
            self.rain_timer -= 0.5
            if self.rain_timer <= 0:
                self.rain_active = False
                self.weather = "dry"
                if self.status == "rain":
                    self.status = "racing"
    
    def trigger_accident(self, distance=20):
        """Trigger an accident event."""
        self.accident_active = True
        self.accident_distance = distance
        self.accident_timer = 10  # Avoidance lasts 10 seconds
        self.status = "avoiding"
    
    def trigger_rain(self, delay=120):
        """Trigger a rain event with delay."""
        self.rain_pending = True
        self.rain_delay = delay
    
    def reset(self):
        """Reset all events and return to normal racing."""
        self.accident_active = False
        self.rain_pending = False
        self.rain_active = False
        self.weather = "dry"
        self.status = "racing"