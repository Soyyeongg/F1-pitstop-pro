"""
Event Injection Panel for Pit-Stop Racer Pro.
Allows users to trigger live events (accidents, rain) to test the system.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, 
    QGroupBox, QSpinBox, QFrame
)
from PySide6.QtCore import Signal, Qt


class EventInjectionPanel(QGroupBox):
    """Panel for injecting events into the simulation."""
    
    accident_triggered = Signal(int)  # distance
    rain_triggered = Signal(int)  # delay
    reset_triggered = Signal()
    
    def __init__(self):
        super().__init__("🎮 EVENT INJECTION CONTROL")
        self.setMaximumHeight(200)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 25, 20, 20)
        
        # Accident control
        accident_widget = self.create_accident_control()
        layout.addWidget(accident_widget)
        
        # Separator
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.VLine)
        separator1.setStyleSheet("color: #444444;")
        layout.addWidget(separator1)
        
        # Rain control
        rain_widget = self.create_rain_control()
        layout.addWidget(rain_widget)
        
        # Separator
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet("color: #444444;")
        layout.addWidget(separator2)
        
        # Reset control
        reset_widget = self.create_reset_control()
        layout.addWidget(reset_widget)
    
    def create_accident_control(self):
        """Create accident trigger control."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        title = QLabel("🚨 ACCIDENT")
        title.setStyleSheet("color: #ff4444; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        # Distance input
        distance_layout = QHBoxLayout()
        distance_label = QLabel("Distance:")
        distance_label.setStyleSheet("color: #cccccc; font-size: 12px; background: transparent;")
        distance_layout.addWidget(distance_label)
        
        self.distance_spinbox = QSpinBox()
        self.distance_spinbox.setRange(5, 100)
        self.distance_spinbox.setValue(20)
        self.distance_spinbox.setSuffix(" m")
        self.distance_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
                font-size: 13px;
            }
        """)
        distance_layout.addWidget(self.distance_spinbox)
        distance_layout.addStretch()
        
        layout.addLayout(distance_layout)
        
        # Trigger button
        accident_btn = QPushButton("⚠ TRIGGER ACCIDENT")
        accident_btn.clicked.connect(self.on_accident_clicked)
        layout.addWidget(accident_btn)
        
        # Description
        desc = QLabel("Car will slow down to avoid")
        desc.setStyleSheet("color: #888888; font-size: 11px; background: transparent;")
        layout.addWidget(desc)
        
        return widget
    
    def create_rain_control(self):
        """Create rain trigger control."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        title = QLabel("🌧️ RAIN MODE")
        title.setStyleSheet("color: #0080ff; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        # Delay input
        delay_layout = QHBoxLayout()
        delay_label = QLabel("Starts in:")
        delay_label.setStyleSheet("color: #cccccc; font-size: 12px; background: transparent;")
        delay_layout.addWidget(delay_label)
        
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 600)
        self.delay_spinbox.setValue(10)
        self.delay_spinbox.setSuffix(" s")
        self.delay_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
                font-size: 13px;
            }
        """)
        delay_layout.addWidget(self.delay_spinbox)
        delay_layout.addStretch()
        
        layout.addLayout(delay_layout)
        
        # Trigger button
        rain_btn = QPushButton("☔ TRIGGER RAIN")
        rain_btn.setObjectName("rain_button")
        rain_btn.clicked.connect(self.on_rain_clicked)
        layout.addWidget(rain_btn)
        
        # Description
        desc = QLabel("Reduce speed for wet track")
        desc.setStyleSheet("color: #888888; font-size: 11px; background: transparent;")
        layout.addWidget(desc)
        
        return widget
    
    def create_reset_control(self):
        """Create reset control."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)
        
        title = QLabel("✅ RESET")
        title.setStyleSheet("color: #00cc66; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        spacer = QLabel("Clear all active events")
        spacer.setStyleSheet("color: #cccccc; font-size: 12px; background: transparent;")
        layout.addWidget(spacer)
        
        # Reset button
        reset_btn = QPushButton("🔄 RESET TO NORMAL")
        reset_btn.setObjectName("reset_button")
        reset_btn.clicked.connect(self.on_reset_clicked)
        layout.addWidget(reset_btn)
        
        # Description
        desc = QLabel("Return to normal racing")
        desc.setStyleSheet("color: #888888; font-size: 11px; background: transparent;")
        layout.addWidget(desc)
        
        return widget
    
    def on_accident_clicked(self):
        distance = self.distance_spinbox.value()
        self.accident_triggered.emit(distance)
    
    def on_rain_clicked(self):
        delay = self.delay_spinbox.value()
        self.rain_triggered.emit(delay)
    
    def on_reset_clicked(self):
        self.reset_triggered.emit()