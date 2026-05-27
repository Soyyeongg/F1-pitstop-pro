"""
Custom telemetry widgets for Pit-Stop Racer Pro.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QProgressBar
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QLinearGradient


class SpeedGauge(QWidget):
    """Circular speed gauge widget."""
    
    def __init__(self):
        super().__init__()
        self.speed = 0.0
        self.max_speed = 2.5  # m/s
        self.setMinimumSize(280, 280)
    
    def set_speed(self, speed):
        self.speed = speed
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        size = min(w, h) - 40
        x = (w - size) / 2
        y = (h - size) / 2
        
        rect = QRectF(x, y, size, size)
        
        # Outer ring (background)
        painter.setPen(QPen(QColor("#333333"), 12))
        painter.drawArc(rect, 225 * 16, -270 * 16)
        
        # Progress arc (speed indicator)
        ratio = min(1.0, self.speed / self.max_speed)
        if ratio > 0.7:
            color = QColor("#e10600")  # Red - fast
        elif ratio > 0.4:
            color = QColor("#ffaa00")  # Orange - medium
        else:
            color = QColor("#00cc66")  # Green - slow
        
        painter.setPen(QPen(color, 12))
        painter.drawArc(rect, 225 * 16, int(-270 * 16 * ratio))
        
        # Speed text
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Arial", 42, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, f"{self.speed:.2f}")
        
        # Unit text
        painter.setFont(QFont("Arial", 14))
        painter.setPen(QColor("#888888"))
        unit_rect = QRectF(x, y + size / 2 + 35, size, 30)
        painter.drawText(unit_rect, Qt.AlignCenter, "m/s")
        
        # SPEED label
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.setPen(QColor("#e10600"))
        label_rect = QRectF(x, y + size - 30, size, 20)
        painter.drawText(label_rect, Qt.AlignCenter, "SPEED")


class ResourceBar(QWidget):
    """Resource bar widget for fuel, battery, tire wear."""
    
    def __init__(self, label, icon, color="#00cc66", inverse=False):
        super().__init__()
        self.label = label
        self.icon = icon
        self.color = color
        self.inverse = inverse  # True for tire_wear (higher is worse)
        self.value = 100.0 if not inverse else 0.0
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Label row
        label_layout = QHBoxLayout()
        
        self.title_label = QLabel(f"{self.icon}  {self.label}")
        self.title_label.setStyleSheet(
            "color: white; font-size: 14px; font-weight: bold; background: transparent;"
        )
        label_layout.addWidget(self.title_label)
        
        label_layout.addStretch()
        
        self.value_label = QLabel("100%")
        self.value_label.setStyleSheet(
            f"color: {self.color}; font-size: 18px; font-weight: bold; background: transparent;"
        )
        label_layout.addWidget(self.value_label)
        
        layout.addLayout(label_layout)
        
        # Progress bar
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if not self.inverse else 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(24)
        self.update_bar_style()
        layout.addWidget(self.bar)
    
    def set_value(self, value):
        self.value = value
        self.bar.setValue(int(value))
        self.value_label.setText(f"{value:.1f}%")
        self.update_bar_style()
    
    def update_bar_style(self):
        # Determine color based on value
        if self.inverse:
            # For tire wear: high = bad
            if self.value > 70:
                color = "#ff4444"
            elif self.value > 40:
                color = "#ffaa00"
            else:
                color = "#00cc66"
        else:
            # For fuel/battery: low = bad
            if self.value < 20:
                color = "#ff4444"
            elif self.value < 50:
                color = "#ffaa00"
            else:
                color = self.color
        
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: bold; background: transparent;"
        )
        
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)


class StatusIndicator(QFrame):
    """Status indicator widget showing current driving status."""
    
    STATUS_CONFIG = {
        'racing': ('🏁 RACING', '#00cc66'),
        'pitting': ('🔧 PITTING', '#ffaa00'),
        'avoiding': ('⚠️ AVOIDING', '#ff4444'),
        'rain': ('🌧️ RAIN MODE', '#0066cc'),
    }
    
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("DRIVING STATUS")
        title.setStyleSheet("color: #e10600; font-size: 12px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        self.status_label = QLabel("🏁 RACING")
        self.status_label.setStyleSheet(
            "color: #00cc66; font-size: 22px; font-weight: bold; background: transparent;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
    
    def set_status(self, status):
        text, color = self.STATUS_CONFIG.get(status, ('UNKNOWN', '#ffffff'))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: bold; background: transparent;"
        )


class WeatherDisplay(QFrame):
    """Weather display widget."""
    
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("WEATHER CONDITION")
        title.setStyleSheet("color: #e10600; font-size: 12px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        # Weather icon and text
        self.weather_label = QLabel("☀️ DRY")
        self.weather_label.setStyleSheet(
            "color: #ffaa00; font-size: 28px; font-weight: bold; background: transparent;"
        )
        self.weather_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.weather_label)
        
        # Description
        self.description_label = QLabel("Optimal racing conditions")
        self.description_label.setStyleSheet(
            "color: #cccccc; font-size: 12px; background: transparent;"
        )
        self.description_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.description_label)
    
    def set_weather(self, weather):
        if weather == "rain":
            self.weather_label.setText("🌧️ RAIN")
            self.weather_label.setStyleSheet(
                "color: #0080ff; font-size: 28px; font-weight: bold; background: transparent;"
            )
            self.description_label.setText("Wet track - reduced grip")
        else:
            self.weather_label.setText("☀️ DRY")
            self.weather_label.setStyleSheet(
                "color: #ffaa00; font-size: 28px; font-weight: bold; background: transparent;"
            )
            self.description_label.setText("Optimal racing conditions")