"""
JetRacer ROS AI Full Kit Bridge
Connects to JetRacer's ROS2 topics to receive real-time telemetry data.

JetRacer ROS AI Full Kit publishes the following topics:
- /jetracer/odom (nav_msgs/Odometry) - position and velocity
- /jetracer/imu (sensor_msgs/Imu) - orientation
- /jetracer/battery (sensor_msgs/BatteryState) - battery status
- /jetracer/cmd_vel (geometry_msgs/Twist) - velocity commands
- /jetracer/scan (sensor_msgs/LaserScan) - lidar (if equipped)

This bridge subscribes to these topics and converts the data into the format
expected by the Pit-Stop Racer Pro dashboard.

Usage:
    from src.jetracer_bridge import JetRacerBridge
    
    bridge = JetRacerBridge()
    bridge.start()
    
    # In your render loop:
    telemetry = bridge.get_telemetry()
    # telemetry has: speed, fuel, battery, tire_wear, status, weather, x, y
"""

import threading
import time
import math
from typing import Optional, Dict, Any


class JetRacerBridge:
    """
    Bridge between JetRacer ROS AI Full Kit and the Pit-Stop Racer Pro dashboard.
    
    Subscribes to ROS2 topics and provides telemetry data in real-time.
    Falls back to simulated data if ROS2 is not available.
    """
    
    def __init__(self,
                 odom_topic: str = "/jetracer/odom",
                 imu_topic: str = "/jetracer/imu",
                 battery_topic: str = "/jetracer/battery",
                 cmd_vel_topic: str = "/jetracer/cmd_vel",
                 # Coordinate transformation parameters
                 # JetRacer track origin (start line) → maps to (track_origin_x, track_origin_y) in world coordinates
                 track_origin_x: float = 0.0,
                 track_origin_y: float = 0.0,
                 # Scale factor: 1 meter in real world → scale_factor units in track world
                 # (since Monza is 5793m long and our internal track is ~scaled)
                 scale_factor: float = 1.0,
                 # Rotation in degrees applied to incoming positions
                 rotation_deg: float = 0.0):
        
        self.odom_topic = odom_topic
        self.imu_topic = imu_topic
        self.battery_topic = battery_topic
        self.cmd_vel_topic = cmd_vel_topic
        
        self.track_origin_x = track_origin_x
        self.track_origin_y = track_origin_y
        self.scale_factor = scale_factor
        self.rotation_rad = math.radians(rotation_deg)
        
        # Latest telemetry data (thread-safe via lock)
        self._lock = threading.Lock()
        self._latest_data = {
            'x': 0.0,
            'y': 0.0,
            'speed': 0.0,           # m/s
            'fuel': 100.0,          # % (simulated, not from JetRacer)
            'battery': 100.0,       # % (from JetRacer's battery state)
            'tire_wear': 0.0,       # % (simulated)
            'status': 'racing',     # racing/pitting/avoiding/rain
            'weather': 'dry',
            'strategy': 'BALANCED',
            'connected': False,     # True if ROS connection is active
            'last_update': 0.0,
        }
        
        # Simulated values (not provided by JetRacer)
        self._fuel = 100.0
        self._tire_wear = 0.0
        self._weather = 'dry'
        self._status = 'racing'
        self._strategy = 'BALANCED'
        
        # Event states
        self._accident_active = False
        self._rain_active = False
        
        # ROS2 components
        self._ros_node = None
        self._ros_thread = None
        self._running = False
    
    def start(self):
        """Start the ROS2 subscriber in a background thread."""
        self._running = True
        self._ros_thread = threading.Thread(target=self._run_ros_node, daemon=True)
        self._ros_thread.start()
        print("🤖 JetRacer Bridge started (ROS2 subscriber thread)")
    
    def stop(self):
        """Stop the ROS2 subscriber."""
        self._running = False
        if self._ros_node is not None:
            try:
                self._ros_node.destroy_node()
            except Exception:
                pass
        print("🤖 JetRacer Bridge stopped")
    
    def _run_ros_node(self):
        """Run ROS2 node in background thread."""
        try:
            import rclpy
            from rclpy.node import Node
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import Imu, BatteryState
            from geometry_msgs.msg import Twist
        except ImportError as e:
            print(f"⚠ ROS2 not available: {e}")
            print("⚠ Install ROS2 Humble + rclpy: 'pip install rclpy'")
            print("⚠ Bridge will return last known values only")
            return
        
        try:
            rclpy.init()
            
            class JetRacerSubscriber(Node):
                def __init__(self, bridge):
                    super().__init__('pit_stop_racer_bridge')
                    self.bridge = bridge
                    
                    # Subscribe to JetRacer topics
                    self.odom_sub = self.create_subscription(
                        Odometry, bridge.odom_topic,
                        self.odom_callback, 10
                    )
                    self.battery_sub = self.create_subscription(
                        BatteryState, bridge.battery_topic,
                        self.battery_callback, 10
                    )
                    self.cmd_vel_sub = self.create_subscription(
                        Twist, bridge.cmd_vel_topic,
                        self.cmd_vel_callback, 10
                    )
                    print(f"✓ Subscribed to {bridge.odom_topic}, {bridge.battery_topic}, {bridge.cmd_vel_topic}")
                
                def odom_callback(self, msg):
                    """Handle odometry messages from JetRacer."""
                    # Extract position
                    x_raw = msg.pose.pose.position.x
                    y_raw = msg.pose.pose.position.y
                    
                    # Apply coordinate transformation
                    cos_r = math.cos(self.bridge.rotation_rad)
                    sin_r = math.sin(self.bridge.rotation_rad)
                    x_rot = x_raw * cos_r - y_raw * sin_r
                    y_rot = x_raw * sin_r + y_raw * cos_r
                    
                    x_world = self.bridge.track_origin_x + x_rot * self.bridge.scale_factor
                    y_world = self.bridge.track_origin_y + y_rot * self.bridge.scale_factor
                    
                    # Extract velocity (linear speed in m/s)
                    vx = msg.twist.twist.linear.x
                    vy = msg.twist.twist.linear.y
                    speed = math.sqrt(vx * vx + vy * vy)
                    
                    with self.bridge._lock:
                        self.bridge._latest_data['x'] = x_world
                        self.bridge._latest_data['y'] = y_world
                        self.bridge._latest_data['speed'] = speed
                        self.bridge._latest_data['connected'] = True
                        self.bridge._latest_data['last_update'] = time.time()
                
                def battery_callback(self, msg):
                    """Handle battery state messages."""
                    # battery_percentage in [0, 1] from BatteryState
                    if msg.percentage > 0:
                        battery_pct = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage
                    else:
                        # Estimate from voltage (typical Li-Po: 3.0V empty, 4.2V full)
                        battery_pct = max(0, min(100, (msg.voltage - 3.0) / (4.2 - 3.0) * 100))
                    
                    with self.bridge._lock:
                        self.bridge._latest_data['battery'] = battery_pct
                
                def cmd_vel_callback(self, msg):
                    """Handle velocity commands (for status detection)."""
                    speed = abs(msg.linear.x)
                    with self.bridge._lock:
                        # If commanded speed is very low, might be pitting
                        if speed < 0.1 and self.bridge._latest_data['status'] == 'racing':
                            pass  # Could detect pit stop here
            
            self._ros_node = JetRacerSubscriber(self)
            
            while self._running:
                rclpy.spin_once(self._ros_node, timeout_sec=0.1)
            
            self._ros_node.destroy_node()
            rclpy.shutdown()
            
        except Exception as e:
            print(f"⚠ ROS2 bridge error: {e}")
            with self._lock:
                self._latest_data['connected'] = False
    
    def get_telemetry(self) -> Dict[str, Any]:
        """
        Get current telemetry snapshot.
        Returns combined real (from JetRacer) + simulated data.
        """
        with self._lock:
            data = dict(self._latest_data)
        
        # Update simulated values based on speed/conditions
        speed = data.get('speed', 0.0)
        speed_factor = min(1.0, speed / 2.0)
        
        # Fuel decreases over time (faster = more)
        if data['status'] != 'pitting':
            self._fuel = max(0.0, self._fuel - (0.05 + speed_factor * 0.1) * 0.1)
        else:
            self._fuel = min(100.0, self._fuel + 5.0 * 0.1)
        
        # Tire wear increases over time
        wear_rate = 0.04 + speed_factor * 0.1
        if self._weather == 'rain':
            wear_rate *= 0.5
        if data['status'] != 'pitting':
            self._tire_wear = min(100.0, self._tire_wear + wear_rate * 0.1)
        else:
            self._tire_wear = max(0.0, self._tire_wear - 8.0 * 0.1)
        
        # Update strategy
        if self._weather == 'rain':
            self._strategy = 'RELIABILITY'
        elif self._fuel < 30 or data['battery'] < 30:
            self._strategy = 'SUSTAINABILITY'
        elif self._tire_wear > 60:
            self._strategy = 'RELIABILITY'
        elif self._fuel > 70 and self._tire_wear < 30:
            self._strategy = 'PERFORMANCE'
        else:
            self._strategy = 'BALANCED'
        
        # Update status
        if self._accident_active:
            self._status = 'avoiding'
        elif self._rain_active:
            self._status = 'rain'
        elif self._fuel < 15 or self._tire_wear > 85 or data['battery'] < 15:
            self._status = 'pitting'
        elif self._status == 'pitting' and self._fuel > 90 and self._tire_wear < 10:
            self._status = 'racing'
        else:
            if self._status not in ('avoiding', 'rain', 'pitting'):
                self._status = 'racing'
        
        data['fuel'] = round(self._fuel, 1)
        data['tire_wear'] = round(self._tire_wear, 1)
        data['weather'] = self._weather
        data['status'] = self._status
        data['strategy'] = self._strategy
        data['speed'] = round(data['speed'], 2)
        return data
    
    def trigger_accident(self, distance: int = 20):
        """Trigger an accident event."""
        self._accident_active = True
        threading.Timer(10.0, lambda: setattr(self, '_accident_active', False)).start()
    
    def trigger_rain(self, delay: int = 0):
        """Trigger rain mode."""
        def activate():
            self._rain_active = True
            self._weather = 'rain'
            threading.Timer(60.0, self._clear_rain).start()
        if delay > 0:
            threading.Timer(float(delay), activate).start()
        else:
            activate()
    
    def _clear_rain(self):
        self._rain_active = False
        self._weather = 'dry'
    
    def reset(self):
        """Reset all event states."""
        self._accident_active = False
        self._rain_active = False
        self._weather = 'dry'
        self._status = 'racing'
    
    def is_connected(self) -> bool:
        """Check if ROS2 connection is active."""
        with self._lock:
            return self._latest_data.get('connected', False)
