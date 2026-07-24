import sys
import os
import json
import sqlite3
import random
import math
from datetime import datetime, timedelta
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QPushButton, QGridLayout, 
                              QStackedWidget, QGraphicsDropShadowEffect,
                              QFrame, QSizePolicy, QDialog, QListWidget, 
                              QListWidgetItem, QDateEdit, QProgressBar,
                              QMessageBox)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QDate, QRectF, QPointF
from PyQt6.QtGui import (QFont, QColor, QPainter, QPen, QBrush, QFontDatabase)

# ============================================================================
# KONFIGURASI
# ============================================================================
CONFIG = {
    'APP_TITLE': 'HRV Monitor',
    'DB_FILE': str(Path.home() / 'hrv_monitor.db'),
    'BLE_SCAN_TIMEOUT': 5000,
}

COLORS = {
    'bg_primary': '#F5F7FA',
    'bg_secondary': '#FFFFFF',
    'bg_card': '#FFFFFF',
    'accent_primary': '#4A90E2',
    'accent_secondary': '#5BA3F5',
    'accent_dark': '#2C5F8A',
    'accent_success': '#50C878',
    'accent_warning': '#FFA500',
    'accent_danger': '#FF6B6B',
    'text_primary': '#2C3E50',
    'text_secondary': '#7F8C8D',
    'text_muted': '#BDC3C7',
    'text_placeholder': '#A0AEC0',
    'border_light': '#E8ECF1',
    'border_medium': '#D5DBE3',
    'gray_out': '#D5D8DC',
    'signal_excellent': '#50C878',
    'signal_good': '#5BA3F5',
    'signal_poor': '#FFA500',
    'signal_lost': '#FF6B6B',
}

FATIGUE_LEVELS = {
    0: ("Segar", COLORS['accent_success']),
    1: ("Sedang", COLORS['accent_warning']),
    2: ("Lelah", COLORS['accent_danger']),
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def add_shadow(widget, blur_radius=15, offset_x=0, offset_y=4, color_alpha=25):
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur_radius)
    shadow.setColor(QColor(0, 0, 0, color_alpha))
    shadow.setOffset(offset_x, offset_y)
    widget.setGraphicsEffect(shadow)

def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good Morning!"
    elif 12 <= hour < 17:
        return "Good Afternoon!"
    elif 17 <= hour < 21:
        return "Good Evening!"
    else:
        return "Good Night!"

def calculate_signal_quality(ppg_data):
    if not ppg_data or len(ppg_data) < 10:
        return 3, "Lost", COLORS['signal_lost']
    
    try:
        mean_val = sum(ppg_data) / len(ppg_data)
        variance = sum((x - mean_val) ** 2 for x in ppg_data) / len(ppg_data)
        std_dev = math.sqrt(variance)
        
        max_val = max(ppg_data)
        min_val = min(ppg_data)
        amplitude = max_val - min_val
        
        if amplitude < 0.1:
            return 3, "Lost", COLORS['signal_lost']
        
        quality_score = min(100, (amplitude * 50 + std_dev * 100))
        
        if quality_score >= 70:
            return 0, "Excellent", COLORS['signal_excellent']
        elif quality_score >= 40:
            return 1, "Good", COLORS['signal_good']
        elif quality_score >= 20:
            return 2, "Poor", COLORS['signal_poor']
        else:
            return 3, "Lost", COLORS['signal_lost']
            
    except Exception as e:
        print(f"Error calculating signal quality: {e}")
        return 3, "Lost", COLORS['signal_lost']

# ============================================================================
# SIGNAL QUALITY INDICATOR WIDGET
# ============================================================================
class SignalQualityIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.quality_level = 3
        self.quality_text = "Lost"
        self.setFixedSize(120, 40)
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        
        self.signal_icon = QLabel()
        self.signal_icon.setFixedSize(24, 24)
        layout.addWidget(self.signal_icon)
        
        self.quality_label = QLabel("Lost")
        self.quality_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.quality_label.setStyleSheet(f"color: {COLORS['signal_lost']}; background: transparent; border: none;")
        layout.addWidget(self.quality_label)
        
        layout.addStretch()
        self.update_display()
    
    def update_quality(self, level, text, color):
        self.quality_level = level
        self.quality_text = text
        self.update_display()
    
    def update_display(self):
        color = [COLORS['signal_excellent'], COLORS['signal_good'], 
                 COLORS['signal_poor'], COLORS['signal_lost']][self.quality_level]
        
        self.quality_label.setText(self.quality_text)
        self.quality_label.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent; border: none;")
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        color = [COLORS['signal_excellent'], COLORS['signal_good'], 
                 COLORS['signal_poor'], COLORS['signal_lost']][self.quality_level]
        
        bar_width = 4
        bar_spacing = 3
        max_height = 18
        start_x = 8
        start_y = 11
        
        num_bars = 4 - self.quality_level
        
        for i in range(4):
            x = start_x + i * (bar_width + bar_spacing)
            height = max_height * (i + 1) / 4
            
            if i < num_bars:
                painter.setBrush(QBrush(QColor(color)))
                painter.setPen(QPen(QColor(color), 1))
            else:
                painter.setBrush(QBrush(QColor(COLORS['border_medium'])))
                painter.setPen(QPen(QColor(COLORS['border_medium']), 1))
            
            painter.drawRoundedRect(
                QRectF(x, start_y + (max_height - height), bar_width, height),
                2, 2
            )

# ============================================================================
# BATTERY INDICATOR WIDGET
# ============================================================================
class BatteryIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.battery_level = 0
        self.is_charging = False
        self.setFixedSize(80, 32)
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        self.battery_icon = QLabel()
        self.battery_icon.setFixedSize(28, 16)
        layout.addWidget(self.battery_icon)
        
        self.percentage_label = QLabel("0%")
        self.percentage_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.percentage_label.setStyleSheet(f"color: {COLORS['text_primary']}; background: transparent; border: none;")
        layout.addWidget(self.percentage_label)
        
        layout.addStretch()
        self.update_display()
    
    def update_battery(self, level, is_charging=False):
        self.battery_level = max(0, min(100, level))
        self.is_charging = is_charging
        self.update_display()
    
    def update_display(self):
        self.percentage_label.setText(f"{self.battery_level}%")
        
        if self.battery_level > 60:
            color = COLORS['accent_success']
        elif self.battery_level > 20:
            color = COLORS['accent_warning']
        else:
            color = COLORS['accent_danger']
        
        self.percentage_label.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent; border: none;")
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        if self.battery_level > 60:
            color = COLORS['accent_success']
        elif self.battery_level > 20:
            color = COLORS['accent_warning']
        else:
            color = COLORS['accent_danger']
        
        battery_rect = QRectF(2, 4, 20, 12)
        painter.setPen(QPen(QColor(COLORS['text_secondary']), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(battery_rect, 2, 2)
        
        painter.setPen(QPen(QColor(COLORS['text_secondary']), 1.5))
        painter.drawLine(QPointF(22, 8), QPointF(22, 12))
        
        if self.battery_level > 0:
            fill_width = (self.battery_level / 100) * 18
            fill_rect = QRectF(3, 5, fill_width, 10)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(fill_rect, 1, 1)
        
        if self.is_charging:
            painter.setPen(QPen(QColor(COLORS['accent_warning']), 2))
            painter.drawLine(QPointF(8, 10), QPointF(12, 6))
            painter.drawLine(QPointF(12, 6), QPointF(10, 10))
            painter.drawLine(QPointF(10, 10), QPointF(14, 14))

# ============================================================================
# DATABASE MANAGER
# ============================================================================
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_database()
        self.migrate_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                bpm INTEGER,
                hrv INTEGER,
                fatigue_level INTEGER,
                signal_quality INTEGER,
                battery_level INTEGER,
                waveform_sample TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                avg_bpm REAL,
                avg_hrv REAL,
                max_bpm INTEGER,
                min_bpm INTEGER,
                total_readings INTEGER,
                fresh_count INTEGER,
                moderate_count INTEGER,
                fatigued_count INTEGER,
                minute_data TEXT,
                session_start TEXT,
                session_end TEXT,
                avg_signal_quality REAL,
                avg_battery_level REAL
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON readings(date)')
        conn.commit()
        conn.close()
    
    def migrate_database(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA table_info(readings)")
            readings_columns = [col[1] for col in cursor.fetchall()]
            
            if 'signal_quality' not in readings_columns:
                cursor.execute("ALTER TABLE readings ADD COLUMN signal_quality INTEGER DEFAULT 0")
            
            if 'battery_level' not in readings_columns:
                cursor.execute("ALTER TABLE readings ADD COLUMN battery_level INTEGER DEFAULT 0")
            
            cursor.execute("PRAGMA table_info(daily_summary)")
            summary_columns = [col[1] for col in cursor.fetchall()]
            
            if 'avg_signal_quality' not in summary_columns:
                cursor.execute("ALTER TABLE daily_summary ADD COLUMN avg_signal_quality REAL DEFAULT 0")
            
            if 'avg_battery_level' not in summary_columns:
                cursor.execute("ALTER TABLE daily_summary ADD COLUMN avg_battery_level REAL DEFAULT 0")
            
            conn.commit()
        except Exception as e:
            print(f"Migration error: {e}")
        finally:
            conn.close()
    
    def save_reading(self, timestamp, bpm, hrv, fatigue_level, signal_quality, 
                     battery_level, waveform_sample=None):
        date = timestamp.strftime('%Y-%m-%d')
        hour = timestamp.hour
        minute = timestamp.minute
        waveform_json = json.dumps(waveform_sample) if waveform_sample else None
        
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO readings (timestamp, date, hour, minute, bpm, hrv, 
                                  fatigue_level, signal_quality, battery_level, waveform_sample)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp.strftime('%Y-%m-%d %H:%M:%S'), date, hour, minute, 
              bpm, hrv, fatigue_level, signal_quality, battery_level, waveform_json))
        conn.commit()
        conn.close()
    
    def update_daily_summary(self, date):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                AVG(bpm), AVG(hrv), MAX(bpm), MIN(bpm), COUNT(*),
                SUM(CASE WHEN fatigue_level = 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN fatigue_level = 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN fatigue_level = 2 THEN 1 ELSE 0 END),
                MIN(timestamp), MAX(timestamp),
                AVG(signal_quality), AVG(battery_level)
            FROM readings WHERE date = ?
        ''', (date,))
        
        result = cursor.fetchone()
        if not result or result[4] == 0:
            conn.close()
            return
        
        (avg_bpm, avg_hrv, max_bpm, min_bpm, total, fresh, moderate, fatigued, 
         session_start, session_end, avg_signal, avg_battery) = result
        
        cursor.execute('''
            SELECT hour, minute, fatigue_level, COUNT(*) as count
            FROM readings WHERE date = ?
            GROUP BY hour, minute, fatigue_level
        ''', (date,))
        
        minute_data = {}
        for hour, minute, level, count in cursor.fetchall():
            time_key = f"{hour:02d}:{minute:02d}"
            if time_key not in minute_data:
                minute_data[time_key] = {0: 0, 1: 0, 2: 0}
            minute_data[time_key][level] = count
        
        minute_percentage = {}
        for time_key, levels in minute_data.items():
            total_time = sum(levels.values())
            minute_percentage[time_key] = {
                str(level): (count / total_time * 100) if total_time > 0 else 0
                for level, count in levels.items()
            }
        
        cursor.execute('''
            INSERT OR REPLACE INTO daily_summary 
            (date, avg_bpm, avg_hrv, max_bpm, min_bpm, total_readings, 
             fresh_count, moderate_count, fatigued_count, minute_data, 
             session_start, session_end, avg_signal_quality, avg_battery_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date, avg_bpm, avg_hrv, max_bpm, min_bpm, total, 
              fresh, moderate, fatigued, json.dumps(minute_percentage), 
              session_start, session_end, avg_signal, avg_battery))
        
        conn.commit()
        conn.close()
    
    def get_available_dates(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT date FROM daily_summary')
        dates = set(row[0] for row in cursor.fetchall())
        conn.close()
        return dates
    
    def get_daily_summary(self, date):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM daily_summary WHERE date = ?', (date,))
        result = cursor.fetchone()
        conn.close()
        
        if not result or len(result) < 10:
            return None
        
        return {
            'date': result[0],
            'avg_bpm': result[1] or 0,
            'avg_hrv': result[2] or 0,
            'max_bpm': result[3] or 0,
            'min_bpm': result[4] or 0,
            'total_readings': result[5] or 0,
            'fresh_count': result[6] or 0,
            'moderate_count': result[7] or 0,
            'fatigued_count': result[8] or 0,
            'minute_data': json.loads(result[9]) if result[9] else {},
            'session_start': result[10],
            'session_end': result[11],
            'avg_signal_quality': result[12] if len(result) > 12 else 0,
            'avg_battery_level': result[13] if len(result) > 13 else 0
        }
    
    def get_adaptive_time_data(self, date):
        summary = self.get_daily_summary(date)
        if not summary:
            return [], "hour"
        
        minute_data = summary['minute_data']
        if not minute_data:
            return [], "hour"
        
        return self._get_hourly_data(minute_data), "hour"
    
    def _get_hourly_data(self, minute_data):
        try:
            hourly_data = {}
            
            for time_key, levels in minute_data.items():
                hour = time_key.split(':')[0]
                if hour not in hourly_data:
                    hourly_data[hour] = {'0': 0, '1': 0, '2': 0}
                
                for level, count in levels.items():
                    hourly_data[hour][str(level)] = hourly_data[hour].get(str(level), 0) + count
            
            result = []
            for hour in sorted(hourly_data.keys()):
                levels = hourly_data[hour]
                total = sum(levels.values())
                
                result.append({
                    'time': f"{hour}:00",
                    'fresh': (levels.get('0', 0) / total * 100) if total > 0 else 0,
                    'moderate': (levels.get('1', 0) / total * 100) if total > 0 else 0,
                    'fatigued': (levels.get('2', 0) / total * 100) if total > 0 else 0
                })
            
            return result
        except Exception as e:
            print(f"Error hourly data: {e}")
            return []
    
    def clear_all_data(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM readings')
        cursor.execute('DELETE FROM daily_summary')
        conn.commit()
        conn.close()
    
    def get_database_size(self):
        if os.path.exists(self.db_file):
            return os.path.getsize(self.db_file)
        return 0

# ============================================================================
# BLE SCANNER DIALOG
# ============================================================================
class BLEScannerDialog(QDialog):
    device_selected = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan Bluetooth BLE")
        self.resize(500, 400)
        self.scanned_devices = []
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        header = QLabel("Pilih Device ESP32")
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(header)
        
        info = QLabel("Klik 'Scan' untuk mencari device BLE di sekitar")
        info.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent; border: none;")
        layout.addWidget(info)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.device_list = QListWidget()
        self.device_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border_light']};
                border-radius: 8px;
                padding: 5px;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent_primary']};
                color: white;
            }}
        """)
        layout.addWidget(self.device_list)
        
        btn_layout = QHBoxLayout()
        
        self.scan_btn = QPushButton("Scan BLE Devices")
        self.scan_btn.setFixedHeight(44)
        self.scan_btn.clicked.connect(self.start_scan)
        btn_layout.addWidget(self.scan_btn)
        
        self.simulate_btn = QPushButton("Simulasi Device")
        self.simulate_btn.setFixedHeight(44)
        self.simulate_btn.clicked.connect(self.show_simulated_devices)
        btn_layout.addWidget(self.simulate_btn)
        
        btn_layout.addStretch()
        
        self.connect_btn = QPushButton("Hubungkan")
        self.connect_btn.setFixedHeight(44)
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self.connect_selected)
        btn_layout.addWidget(self.connect_btn)
        
        layout.addLayout(btn_layout)
        self.device_list.itemSelectionChanged.connect(self.on_device_selected)
    
    def start_scan(self):
        self.scan_btn.setEnabled(False)
        self.simulate_btn.setEnabled(False)
        self.device_list.clear()
        self.progress_bar.setVisible(True)
        QTimer.singleShot(3000, self.finish_scan)
    
    def finish_scan(self):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.simulate_btn.setEnabled(True)
        
        simulated_devices = [
            {'name': 'ESP32-S3-PPG-001', 'address': 'AA:BB:CC:DD:EE:01', 'rssi': -45, 'battery': 85},
            {'name': 'ESP32-S3-PPG-002', 'address': 'AA:BB:CC:DD:EE:02', 'rssi': -62, 'battery': 62},
        ]
        
        self.scanned_devices = simulated_devices
        
        for device in simulated_devices:
            item = QListWidgetItem(f"{device['name']}\n{device['address']} | RSSI: {device['rssi']} dBm | Battery: {device['battery']}%")
            item.setData(Qt.ItemDataRole.UserRole, device)
            self.device_list.addItem(item)
    
    def show_simulated_devices(self):
        self.device_list.clear()
        simulated_devices = [
            {'name': 'ESP32-S3-PPG-001', 'address': 'AA:BB:CC:DD:EE:01', 'rssi': -45, 'battery': 85},
        ]
        self.scanned_devices = simulated_devices
        
        for device in simulated_devices:
            item = QListWidgetItem(f"{device['name']}\n{device['address']} | RSSI: {device['rssi']} dBm | Battery: {device['battery']}%")
            item.setData(Qt.ItemDataRole.UserRole, device)
            self.device_list.addItem(item)
    
    def on_device_selected(self):
        self.connect_btn.setEnabled(len(self.device_list.selectedItems()) > 0)
    
    def connect_selected(self):
        selected = self.device_list.selectedItems()
        if selected:
            device = selected[0].data(Qt.ItemDataRole.UserRole)
            self.device_selected.emit(device)
            self.accept()

# ============================================================================
# GLASS CARD - DIPERBAIKI
# ============================================================================
class GlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)  # Hapus frame shape
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-radius: 20px;
                border: none;
            }}
        """)
        add_shadow(self, blur_radius=25, offset_x=0, offset_y=6, color_alpha=20)

# ============================================================================
# SIDEBAR - HANYA 2 TAB
# ============================================================================
class SidebarNavigation(QWidget):
    def __init__(self):
        super().__init__()
        self.current_tab = 0
        self.setFixedWidth(80)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 40, 10, 40)
        layout.setSpacing(20)
        
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_card']};
                border-right: 1.5px solid {COLORS['border_light']};
            }}
        """)
        
        self.nav_buttons = []
        # HANYA 2 TAB: Dashboard dan Riwayat
        nav_items = [("DASH", "Dashboard"), ("HIST", "Riwayat")]
        
        for i, (short, full) in enumerate(nav_items):
            btn = QPushButton(short)
            btn.setFixedSize(60, 60)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            btn.setToolTip(full)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {COLORS['text_secondary']};
                    border: none;
                    border-radius: 14px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_primary']};
                    color: {COLORS['accent_primary']};
                }}
                QPushButton:checked {{
                    background-color: {COLORS['accent_primary']};
                    color: white;
                }}
            """)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda checked, idx=i: self.on_nav_clicked(idx))
            self.nav_buttons.append(btn)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        
        layout.addStretch()
    
    def on_nav_clicked(self, index):
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self.current_tab = index

# ============================================================================
# METRIC CARD
# ============================================================================
class MetricCard(GlassCard):
    def __init__(self, title, value, unit="", color=COLORS['accent_primary']):
        super().__init__()
        self.setMinimumHeight(150)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        title_label.setStyleSheet(f"""
            color: {COLORS['text_placeholder']};
            background: transparent;
            border: none;
            margin: 0;
            padding: 0;
        """)
        layout.addWidget(title_label)
        
        layout.addSpacing(8)
        
        value_layout = QHBoxLayout()
        value_layout.setSpacing(8)
        
        self.value_label = QLabel(str(value))
        self.value_label.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"""
            color: {color};
            background: transparent;
            border: none;
            margin: 0;
            padding: 0;
        """)
        value_layout.addWidget(self.value_label)
        
        if unit:
            unit_label = QLabel(unit)
            unit_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Medium))
            unit_label.setStyleSheet(f"""
                color: {COLORS['text_secondary']};
                background: transparent;
                border: none;
                margin: 0;
                padding: 0;
            """)
            value_layout.addWidget(unit_label)
        
        value_layout.addStretch()
        layout.addLayout(value_layout)

# ============================================================================
# WIDE METRIC CARD
# ============================================================================
class WideMetricCard(GlassCard):
    def __init__(self, title, value, color=COLORS['text_muted']):
        super().__init__()
        self.setMinimumHeight(130)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        title_label.setStyleSheet(f"""
            color: {COLORS['text_placeholder']};
            background: transparent;
            border: none;
            margin: 0;
            padding: 0;
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        layout.addSpacing(5)
        
        self.value_label = QLabel(str(value))
        self.value_label.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"""
            color: {color};
            background: transparent;
            border: none;
            margin: 0;
            padding: 0;
        """)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)
        
        layout.addStretch()

# ============================================================================
# WAVEFORM WIDGET
# ============================================================================
class WaveformWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.waveform_data = []
        self.setMinimumHeight(200)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_primary']};
                border-radius: 14px;
                border: none;
            }}
        """)
    
    def update_waveform(self, data):
        self.waveform_data = data
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        width = self.width()
        height = self.height()
        
        if not self.waveform_data:
            painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Menunggu data...")
            return
        
        painter.setPen(QPen(QColor(COLORS['border_light']), 1, Qt.PenStyle.DotLine))
        for i in range(0, width, 40):
            painter.drawLine(i, 0, i, height)
        for i in range(0, height, 40):
            painter.drawLine(0, i, width, i)
        
        points = len(self.waveform_data)
        path = []
        for i, value in enumerate(self.waveform_data):
            x = (i / max(points - 1, 1)) * width
            y = height - ((value - 0.5) / 1.5) * height
            path.append(QPointF(x, y))
        
        painter.setPen(QPen(QColor(74, 144, 226, 40), 8, Qt.PenStyle.SolidLine, 
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for i in range(len(path) - 1):
            painter.drawLine(path[i], path[i+1])
        
        painter.setPen(QPen(QColor(COLORS['accent_primary']), 2.5, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for i in range(len(path) - 1):
            painter.drawLine(path[i], path[i+1])

# ============================================================================
# ADAPTIVE TIME CHART
# ============================================================================
class AdaptiveTimeChart(QWidget):
    def __init__(self):
        super().__init__()
        self.time_data = []
        self.setMinimumHeight(320)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_primary']};
                border-radius: 14px;
                border: none;
            }}
        """)
    
    def update_data(self, time_data, time_scale="hour"):
        self.time_data = time_data
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        width = self.width()
        height = self.height()
        margin = 50
        chart_height = height - 2 * margin
        
        if not self.time_data:
            painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Tidak ada data")
            return
        
        painter.setPen(QPen(QColor(COLORS['border_light']), 1, Qt.PenStyle.DotLine))
        for i in range(5):
            y = margin + (i * chart_height / 4)
            painter.drawLine(margin, int(y), width - margin, int(y))
            painter.drawText(5, int(y) + 3, f"{100 - i * 25}%")
        
        num_points = len(self.time_data)
        bar_width = (width - 2 * margin) / max(num_points, 1)
        colors = [QColor(COLORS['accent_success']), QColor(COLORS['accent_warning']), QColor(COLORS['accent_danger'])]
        
        for i, time_point in enumerate(self.time_data):
            x = margin + i * bar_width
            y_offset = height - margin
            total = time_point['fresh'] + time_point['moderate'] + time_point['fatigued']
            
            if total > 0:
                for key, color in [('fresh', colors[0]), ('moderate', colors[1]), ('fatigued', colors[2])]:
                    percentage = time_point[key]
                    bar_height = (percentage / 100) * chart_height
                    y_offset -= bar_height
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(color, 1))
                    painter.drawRoundedRect(QRectF(x + 1, y_offset, bar_width - 2, bar_height), 3, 3)
            
            if num_points <= 10 or i % max(num_points // 10, 1) == 0:
                painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
                painter.setFont(QFont("Segoe UI", 8))
                painter.drawText(int(x), height - margin + 15, time_point['time'])
        
        legend_y = 15
        for i, (label, color) in enumerate([("Segar", COLORS['accent_success']), 
                                           ("Sedang", COLORS['accent_warning']), 
                                           ("Lelah", COLORS['accent_danger'])]):
            x = width - margin - (3 - i) * 85
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, legend_y, 16, 16), 4, 4)
            painter.setPen(QPen(QColor(COLORS['text_primary']), 1))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
            painter.drawText(x + 20, legend_y + 12, label)

# ============================================================================
# MAIN WINDOW - HANYA 2 PAGE
# ============================================================================
class HRVMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager(CONFIG['DB_FILE'])
        self.is_connected = False
        self.is_monitoring = False
        self.connected_device = None
        self.current_signal_quality = 3
        self.current_battery_level = 0
        
        self.init_ui()
        
        self.greeting_timer = QTimer()
        self.greeting_timer.timeout.connect(self.update_greeting)
        self.greeting_timer.start(1000)
        
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_statistics)
        self.stats_timer.start(5000)
    
    def init_ui(self):
        self.setWindowTitle(CONFIG['APP_TITLE'])
        self.resize(1600, 1000)
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['bg_primary']};
            }}
            QLabel {{
                color: {COLORS['text_primary']};
                font-family: 'Segoe UI', Arial, sans-serif;
                background: transparent;
                border: none;
            }}
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.sidebar = SidebarNavigation()
        self.sidebar.nav_buttons[0].clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.sidebar.nav_buttons[1].clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        main_layout.addWidget(self.sidebar)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(25)
        
        self.header_widget = QWidget()
        header_layout = QHBoxLayout(self.header_widget)
        
        greeting_layout = QVBoxLayout()
        greeting_layout.setSpacing(5)
        
        self.greeting_label = QLabel(get_greeting())
        self.greeting_label.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        greeting_layout.addWidget(self.greeting_label)
        
        self.time_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        self.time_label.setFont(QFont("Segoe UI", 14))
        self.time_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        greeting_layout.addWidget(self.time_label)
        
        header_layout.addLayout(greeting_layout)
        header_layout.addStretch()
        
        indicators_layout = QHBoxLayout()
        indicators_layout.setSpacing(15)
        
        self.signal_indicator = SignalQualityIndicator()
        indicators_layout.addWidget(self.signal_indicator)
        
        self.battery_indicator = BatteryIndicator()
        indicators_layout.addWidget(self.battery_indicator)
        
        header_layout.addLayout(indicators_layout)
        
        content_layout.addWidget(self.header_widget)
        
        # HANYA 2 PAGE: Dashboard dan History
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_dashboard_content())
        self.stacked_widget.addWidget(self.create_history_content())
        
        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_widget, 1)
        
        self.update_greeting()
    
    def update_greeting(self):
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))
        self.greeting_label.setText(get_greeting())
        self.header_widget.setVisible(self.stacked_widget.currentIndex() == 0)
    
    def create_dashboard_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(25)
        
        # Status bar
        status_card = GlassCard()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(25, 20, 25, 20)
        
        self.status_label = QLabel("● Tidak Terhubung")
        self.status_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']};")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        self.connect_btn = QPushButton("Hubungkan ESP32")
        self.connect_btn.setFixedHeight(46)
        self.connect_btn.setMinimumWidth(160)
        self.connect_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.connect_btn.clicked.connect(self.show_ble_scanner)
        self.connect_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_primary']};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_dark']};
            }}
        """)
        status_layout.addWidget(self.connect_btn)
        
        self.start_monitoring_btn = QPushButton("Mulai Monitoring")
        self.start_monitoring_btn.setFixedHeight(46)
        self.start_monitoring_btn.setMinimumWidth(160)
        self.start_monitoring_btn.setEnabled(False)
        self.start_monitoring_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.start_monitoring_btn.clicked.connect(self.toggle_monitoring)
        self.start_monitoring_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_success']};
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #43A047;
            }}
            QPushButton:disabled {{
                background-color: {COLORS['text_muted']};
            }}
        """)
        status_layout.addWidget(self.start_monitoring_btn)
        
        layout.addWidget(status_card)
        
        # Main content
        main_content = QHBoxLayout()
        main_content.setSpacing(25)
        
        # Kolom kiri: Metrics
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(20)
        
        row1 = QHBoxLayout()
        row1.setSpacing(20)
        self.bpm_card = MetricCard("Heart Rate", "0", "bpm", COLORS['accent_danger'])
        self.hrv_card = MetricCard("HRV", "0", "ms", COLORS['accent_secondary'])
        row1.addWidget(self.bpm_card)
        row1.addWidget(self.hrv_card)
        metrics_layout.addLayout(row1)
        
        self.fatigue_card = WideMetricCard("Tingkat Kelelahan", "-", COLORS['text_muted'])
        metrics_layout.addWidget(self.fatigue_card)
        metrics_layout.addStretch()
        
        main_content.addWidget(metrics_container, 1)
        
        # Kolom kanan: Waveform
        waveform_card = GlassCard()
        waveform_layout = QVBoxLayout(waveform_card)
        waveform_layout.setContentsMargins(28, 25, 28, 25)
        waveform_layout.setSpacing(18)
        
        waveform_title = QLabel("Gelombang HRV Real-Time")
        waveform_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        waveform_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        waveform_layout.addWidget(waveform_title)
        
        self.waveform_widget = WaveformWidget()
        self.waveform_widget.setMinimumHeight(380)
        waveform_layout.addWidget(self.waveform_widget)
        
        main_content.addWidget(waveform_card, 1)
        
        layout.addLayout(main_content)
        layout.addStretch()
        
        return widget
    
    def create_history_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(25)
        
        date_layout = QHBoxLayout()
        
        date_label = QLabel("Pilih Tanggal:")
        date_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        date_layout.addWidget(date_label)
        
        self.date_picker = QDateEdit()
        self.date_picker.setCalendarPopup(True)
        self.date_picker.setDate(QDate.currentDate())
        self.date_picker.setFixedHeight(42)
        self.date_picker.setFont(QFont("Segoe UI", 11))
        self.date_picker.setReadOnly(False)
        self.date_picker.setStyleSheet(f"""
            QDateEdit {{
                background-color: {COLORS['bg_card']};
                border: 1.5px solid {COLORS['border_light']};
                border-radius: 10px;
                padding: 5px 15px;
            }}
            QDateEdit::drop-down {{
                border: none;
                width: 30px;
                border-radius: 8px;
            }}
        """)
        self.date_picker.dateChanged.connect(self.on_date_changed)
        date_layout.addWidget(self.date_picker)
        date_layout.addStretch()
        
        db_size = self.db_manager.get_database_size()
        size_label = QLabel(f"Ukuran Database: {db_size / 1024:.2f} KB")
        size_label.setFont(QFont("Segoe UI", 10))
        size_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        date_layout.addWidget(size_label)
        
        layout.addLayout(date_layout)
        
        main_content = QHBoxLayout()
        main_content.setSpacing(25)
        
        summary_card = GlassCard()
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(28, 25, 28, 25)
        summary_layout.setSpacing(18)
        
        summary_title = QLabel("Ringkasan Harian")
        summary_title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        summary_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        summary_layout.addWidget(summary_title)
        
        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)
        
        self.hist_avg_bpm = QLabel("Rata-rata BPM: -")
        self.hist_avg_hrv = QLabel("Rata-rata HRV: -")
        self.hist_total = QLabel("Total: -")
        self.hist_max_bpm = QLabel("Max BPM: -")
        self.hist_min_bpm = QLabel("Min BPM: -")
        self.hist_fatigue = QLabel("Distribusi: -")
        
        for label in [self.hist_avg_bpm, self.hist_avg_hrv, self.hist_total, 
                      self.hist_max_bpm, self.hist_min_bpm, self.hist_fatigue]:
            label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
            label.setStyleSheet(f"""
                padding: 12px 14px;
                background-color: {COLORS['bg_primary']};
                border-radius: 10px;
            """)
            label.setWordWrap(True)
        
        stats_grid.addWidget(self.hist_avg_bpm, 0, 0)
        stats_grid.addWidget(self.hist_avg_hrv, 0, 1)
        stats_grid.addWidget(self.hist_total, 1, 0)
        stats_grid.addWidget(self.hist_max_bpm, 1, 1)
        stats_grid.addWidget(self.hist_min_bpm, 2, 0)
        stats_grid.addWidget(self.hist_fatigue, 2, 1)
        
        summary_layout.addLayout(stats_grid)
        summary_layout.addStretch()
        main_content.addWidget(summary_card, 1)
        
        chart_card = GlassCard()
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(28, 25, 28, 25)
        chart_layout.setSpacing(18)
        
        self.chart_title = QLabel("Distribusi Kelelahan")
        self.chart_title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        self.chart_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        chart_layout.addWidget(self.chart_title)
        
        self.adaptive_chart = AdaptiveTimeChart()
        self.adaptive_chart.setMinimumHeight(380)
        chart_layout.addWidget(self.adaptive_chart)
        
        main_content.addWidget(chart_card, 2)
        layout.addLayout(main_content)
        layout.addStretch()
        
        self.load_history_data()
        return widget
    
    def show_ble_scanner(self):
        dialog = BLEScannerDialog(self)
        dialog.device_selected.connect(self.on_device_selected)
        dialog.exec()
    
    def on_device_selected(self, device):
        self.connected_device = device
        self.is_connected = True
        self.connect_btn.setText(f"Terhubung: {device['name'][:15]}...")
        self.status_label.setText(f"● Terhubung ke {device['name']}")
        self.status_label.setStyleSheet(f"color: {COLORS['accent_success']};")
        self.start_monitoring_btn.setEnabled(True)
        
        if 'battery' in device:
            self.current_battery_level = device['battery']
            self.battery_indicator.update_battery(self.current_battery_level)
    
    def toggle_monitoring(self):
        if not self.is_monitoring:
            if not self.is_connected:
                QMessageBox.warning(self, "Koneksi Diperlukan", "Hubungkan ke ESP32 terlebih dahulu.")
                return
            
            self.is_monitoring = True
            self.start_monitoring_btn.setText("Hentikan Monitoring")
            self.status_label.setText("● Monitoring Aktif")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_secondary']};")
            self.start_data_simulation()
        else:
            self.is_monitoring = False
            self.start_monitoring_btn.setText("Mulai Monitoring")
            self.status_label.setText(f"● Terhubung ke {self.connected_device['name']}")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_success']};")
            
            if hasattr(self, 'simulation_timer'):
                self.simulation_timer.stop()
            
            today = datetime.now().strftime('%Y-%m-%d')
            self.db_manager.update_daily_summary(today)
            if self.stacked_widget.currentIndex() == 1:
                self.load_history_data()
    
    def start_data_simulation(self):
        self.simulation_timer = QTimer()
        self.simulation_timer.timeout.connect(self.simulate_data)
        self.simulation_timer.start(1000)
    
    def simulate_data(self):
        bpm = 70 + random.randint(-5, 10)
        hrv = 50 + random.randint(-10, 15)
        fatigue_level = 0 if hrv > 55 else (1 if hrv > 40 else 2)
        
        noise_level = random.uniform(0.1, 0.4)
        waveform_sample = [1.0 + noise_level * random.gauss(0, 1) for _ in range(20)]
        
        signal_quality, signal_text, signal_color = calculate_signal_quality(waveform_sample)
        self.current_signal_quality = signal_quality
        
        self.signal_indicator.update_quality(signal_quality, signal_text, signal_color)
        
        if self.current_battery_level > 0:
            self.current_battery_level -= 0.1
        self.battery_indicator.update_battery(int(self.current_battery_level))
        
        if signal_quality >= 2:
            self.status_label.setText(f"⚠️ Sinyal {signal_text} - Periksa sensor!")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_warning']};")
        
        self.bpm_card.value_label.setText(str(bpm))
        self.hrv_card.value_label.setText(f"{hrv} ms")
        
        fatigue_text, fatigue_color = FATIGUE_LEVELS[fatigue_level]
        self.fatigue_card.value_label.setText(fatigue_text)
        self.fatigue_card.value_label.setStyleSheet(f"""
            color: {fatigue_color}; 
            font-size: 44pt; 
            font-weight: bold;
            background: transparent;
            border: none;
        """)
        
        self.waveform_widget.update_waveform(waveform_sample)
        
        timestamp = datetime.now()
        self.db_manager.save_reading(timestamp, bpm, hrv, fatigue_level, 
                                     signal_quality, int(self.current_battery_level), 
                                     waveform_sample)
        
        if random.random() < 0.1:
            self.db_manager.update_daily_summary(timestamp.strftime('%Y-%m-%d'))
    
    def on_date_changed(self, date):
        self.load_history_data()
    
    def load_history_data(self):
        selected_date = self.date_picker.date().toString('yyyy-MM-dd')
        summary = self.db_manager.get_daily_summary(selected_date)
        
        if not summary:
            self.hist_avg_bpm.setText("Rata-rata BPM: -")
            self.hist_avg_hrv.setText("Rata-rata HRV: -")
            self.hist_total.setText("Total: -")
            self.hist_max_bpm.setText("Max BPM: -")
            self.hist_min_bpm.setText("Min BPM: -")
            self.hist_fatigue.setText("Distribusi: -")
            self.adaptive_chart.update_data([], "hour")
            self.chart_title.setText("Distribusi Kelelahan")
            return
        
        self.hist_avg_bpm.setText(f"Rata-rata BPM: {summary['avg_bpm']:.1f}")
        self.hist_avg_hrv.setText(f"Rata-rata HRV: {summary['avg_hrv']:.1f} ms")
        self.hist_total.setText(f"Total: {summary['total_readings']}")
        self.hist_max_bpm.setText(f"Max BPM: {summary['max_bpm']}")
        self.hist_min_bpm.setText(f"Min BPM: {summary['min_bpm']}")
        self.hist_fatigue.setText(f"Segar: {summary['fresh_count']} | Sedang: {summary['moderate_count']} | Lelah: {summary['fatigued_count']}")
        
        time_data, time_scale = self.db_manager.get_adaptive_time_data(selected_date)
        self.chart_title.setText("Distribusi Kelelahan (Per Jam)")
        self.adaptive_chart.update_data(time_data, time_scale)
    
    def update_statistics(self):
        if not self.is_monitoring:
            return
        today = datetime.now().strftime('%Y-%m-%d')
        summary = self.db_manager.get_daily_summary(today)
        if summary:
            self.hist_avg_bpm.setText(f"Rata-rata BPM: {summary['avg_bpm']:.1f}")
            self.hist_avg_hrv.setText(f"Rata-rata HRV: {summary['avg_hrv']:.1f} ms")
            self.hist_total.setText(f"Total: {summary['total_readings']}")
    
    def closeEvent(self, event):
        if self.is_monitoring:
            self.db_manager.update_daily_summary(datetime.now().strftime('%Y-%m-%d'))
        event.accept()

# ============================================================================
# MAIN
# ============================================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont("Segoe UI", 10))
    
    window = HRVMonitorApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()