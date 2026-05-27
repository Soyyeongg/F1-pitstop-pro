"""
Pit-Stop Racer Pro - Main Monitoring Application
Real-time telemetry dashboard for autonomous JetRacer F1 simulation.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QProgressBar, QGroupBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPalette, QColor, QPainter, QPen, QBrush

from src.mock_data_generator import MockDataGenerator
from src.ui.telemetry_widgets import (
    SpeedGauge, ResourceBar, StatusIndicator, WeatherDisplay
)
from src.ui.event_panel import EventInjectionPanel


class PitStopRacerApp(QMainWindow):
    """Main monitoring application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🏎️ Pit-Stop Racer Pro - Live Monitoring")
        self.setMinimumSize(1280, 800)
        
        # Apply dark theme
        self.apply_dark_theme()
        
        # Initialize mock data generator
        self.data_generator = MockDataGenerator()
        
        # Race state
        self.race_start_time = 0
        self.current_lap = 1
        self.total_laps = 53
        
        # Setup UI
        self.setup_ui()
        
        # Start telemetry update timer (every 500ms = 0.5s as per spec)
        self.telemetry_timer = QTimer()
        self.telemetry_timer.timeout.connect(self.update_telemetry)
        self.telemetry_timer.start(500)
        
        # Live indicator blink timer
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.blink_live_indicator)
        self.blink_timer.start(1000)
        self.live_visible = True
    
    def apply_dark_theme(self):
        """Apply F1-inspired dark theme to the application."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0a0a0a;
            }
            QWidget {
                background-color: #0a0a0a;
                color: #ffffff;
                font-family: 'Arial', sans-serif;
            }
            QGroupBox {
                background-color: #1a1a1a;
                border: 2px solid #e10600;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
                font-size: 14px;
                color: #e10600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #e10600;
            }
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
            QPushButton {
                background-color: #e10600;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #ff1e1e;
            }
            QPushButton:pressed {
                background-color: #b00500;
            }
            QPushButton#rain_button {
                background-color: #0066cc;
            }
            QPushButton#rain_button:hover {
                background-color: #0080ff;
            }
            QPushButton#reset_button {
                background-color: #00a651;
            }
            QPushButton#reset_button:hover {
                background-color: #00cc66;
            }
        """)
    
    def setup_ui(self):
        """Create the main UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Main content area
        content_layout = QHBoxLayout()
        content_layout.setSpacing(15)
        
        # Left panel: Speed & Status
        left_panel = self.create_left_panel()
        content_layout.addWidget(left_panel, 1)
        
        # Center panel: Resources
        center_panel = self.create_center_panel()
        content_layout.addWidget(center_panel, 1)
        
        # Right panel: Weather & Strategy
        right_panel = self.create_right_panel()
        content_layout.addWidget(right_panel, 1)
        
        main_layout.addLayout(content_layout)
        
        # Bottom: Event injection panel
        self.event_panel = EventInjectionPanel()
        self.event_panel.accident_triggered.connect(self.on_accident_triggered)
        self.event_panel.rain_triggered.connect(self.on_rain_triggered)
        self.event_panel.reset_triggered.connect(self.on_reset_triggered)
        main_layout.addWidget(self.event_panel)
    
    def create_header(self):
        """Create the header bar with title and live indicator."""
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 2px solid #e10600;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        header.setFixedHeight(80)
        
        layout = QHBoxLayout(header)
        
        # Title
        title = QLabel("🏎️  PIT-STOP RACER PRO")
        title_font = QFont("Arial", 24, QFont.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #e10600; background-color: transparent; border: none;")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Subtitle
        subtitle = QLabel("Cyber-Physical System | Live Telemetry Dashboard")
        subtitle.setStyleSheet("color: #cccccc; background-color: transparent; border: none; font-size: 14px;")
        layout.addWidget(subtitle)
        
        layout.addStretch()
        
        # Live indicator
        self.live_label = QLabel("● LIVE")
        self.live_label.setStyleSheet("color: #00ff00; background-color: transparent; border: none; font-size: 16px; font-weight: bold;")
        layout.addWidget(self.live_label)
        
        return header
    
    def create_left_panel(self):
        """Create the left panel with speed gauge and status."""
        group = QGroupBox("⚡ SPEED & STATUS")
        layout = QVBoxLayout(group)
        layout.setSpacing(15)
        
        # Speed Gauge
        self.speed_gauge = SpeedGauge()
        layout.addWidget(self.speed_gauge)
        
        # Status Indicator
        self.status_indicator = StatusIndicator()
        layout.addWidget(self.status_indicator)
        
        return group
    
    def create_center_panel(self):
        """Create the center panel with resource bars."""
        group = QGroupBox("🔋 RESOURCES")
        layout = QVBoxLayout(group)
        layout.setSpacing(20)
        
        # Fuel
        self.fuel_bar = ResourceBar("Fuel", "⛽", color="#ffaa00")
        layout.addWidget(self.fuel_bar)
        
        # Battery
        self.battery_bar = ResourceBar("Battery", "🔋", color="#00cc66")
        layout.addWidget(self.battery_bar)
        
        # Tire Wear (inverse - higher is worse)
        self.tire_bar = ResourceBar("Tire Wear", "🛞", color="#e10600", inverse=True)
        layout.addWidget(self.tire_bar)
        
        layout.addStretch()
        
        return group
    
    def create_right_panel(self):
        """Create the right panel with weather and strategy info."""
        group = QGroupBox("🌤️ WEATHER & STRATEGY")
        layout = QVBoxLayout(group)
        layout.setSpacing(15)
        
        # Weather Display
        self.weather_display = WeatherDisplay()
        layout.addWidget(self.weather_display)
        
        # Strategy Info
        strategy_frame = QFrame()
        strategy_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        strategy_layout = QVBoxLayout(strategy_frame)
        
        strategy_title = QLabel("CURRENT STRATEGY")
        strategy_title.setStyleSheet("color: #e10600; font-weight: bold; font-size: 12px; background: transparent;")
        strategy_layout.addWidget(strategy_title)
        
        self.strategy_label = QLabel("BALANCED")
        self.strategy_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold; background: transparent;")
        strategy_layout.addWidget(self.strategy_label)
        
        # Lap counter
        self.lap_label = QLabel(f"Lap: {self.current_lap} / {self.total_laps}")
        self.lap_label.setStyleSheet("color: #cccccc; font-size: 16px; background: transparent; margin-top: 10px;")
        strategy_layout.addWidget(self.lap_label)
        
        # Race time
        self.race_time_label = QLabel("Race Time: 00:00")
        self.race_time_label.setStyleSheet("color: #cccccc; font-size: 16px; background: transparent;")
        strategy_layout.addWidget(self.race_time_label)
        
        # Pit stop recommendation
        self.pit_recommendation = QLabel("✓ No Pit Stop Required")
        self.pit_recommendation.setStyleSheet("color: #00ff00; font-size: 14px; background: transparent; margin-top: 10px;")
        strategy_layout.addWidget(self.pit_recommendation)
        
        layout.addWidget(strategy_frame)
        layout.addStretch()
        
        return group
    
    def update_telemetry(self):
        """Update all telemetry displays with new mock data."""
        # Get new telemetry data
        data = self.data_generator.get_telemetry()
        
        # Update speed gauge
        self.speed_gauge.set_speed(data['speed'])
        
        # Update resource bars
        self.fuel_bar.set_value(data['fuel'])
        self.battery_bar.set_value(data['battery'])
        self.tire_bar.set_value(data['tire_wear'])
        
        # Update status
        self.status_indicator.set_status(data['status'])
        
        # Update weather
        self.weather_display.set_weather(data['weather'])
        
        # Update strategy
        self.strategy_label.setText(data['strategy'].upper())
        strategy_colors = {
            'PERFORMANCE': '#e10600',
            'BALANCED': '#ffaa00',
            'SUSTAINABILITY': '#00cc66',
            'RELIABILITY': '#0066cc'
        }
        color = strategy_colors.get(data['strategy'].upper(), '#ffffff')
        self.strategy_label.setStyleSheet(
            f"color: {color}; font-size: 24px; font-weight: bold; background: transparent;"
        )
        
        # Update race info
        self.race_start_time += 0.5  # 500ms increment
        minutes = int(self.race_start_time // 60)
        seconds = int(self.race_start_time % 60)
        self.race_time_label.setText(f"Race Time: {minutes:02d}:{seconds:02d}")
        
        # Update lap (mock - increment every ~30 seconds)
        new_lap = min(int(self.race_start_time / 30) + 1, self.total_laps)
        if new_lap != self.current_lap:
            self.current_lap = new_lap
        self.lap_label.setText(f"Lap: {self.current_lap} / {self.total_laps}")
        
        # Update pit recommendation based on resources
        if data['fuel'] < 20 or data['tire_wear'] > 80 or data['battery'] < 20:
            self.pit_recommendation.setText("⚠ PIT STOP RECOMMENDED")
            self.pit_recommendation.setStyleSheet(
                "color: #ff4444; font-size: 14px; font-weight: bold; background: transparent; margin-top: 10px;"
            )
        else:
            self.pit_recommendation.setText("✓ No Pit Stop Required")
            self.pit_recommendation.setStyleSheet(
                "color: #00ff00; font-size: 14px; background: transparent; margin-top: 10px;"
            )
    
    def blink_live_indicator(self):
        """Make the LIVE indicator blink."""
        self.live_visible = not self.live_visible
        if self.live_visible:
            self.live_label.setStyleSheet(
                "color: #00ff00; background-color: transparent; border: none; font-size: 16px; font-weight: bold;"
            )
        else:
            self.live_label.setStyleSheet(
                "color: #006600; background-color: transparent; border: none; font-size: 16px; font-weight: bold;"
            )
    
    def on_accident_triggered(self, distance):
        """Handle accident event injection."""
        print(f"🚨 ACCIDENT TRIGGERED at {distance}m ahead!")
        self.data_generator.trigger_accident(distance)
    
    def on_rain_triggered(self, delay):
        """Handle rain event injection."""
        print(f"🌧️ RAIN MODE TRIGGERED - starts in {delay}s")
        self.data_generator.trigger_rain(delay)
    
    def on_reset_triggered(self):
        """Handle reset to normal racing."""
        print("✅ Reset to normal racing conditions")
        self.data_generator.reset()
