import sys
import os
import json
import csv
import sqlite3
import asyncio
import struct
import math
import statistics
import time
import threading
import queue
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import neurokit2 as nk
import antropy as ant
from scipy.signal import butter, filtfilt, find_peaks
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QStackedWidget, QGraphicsDropShadowEffect,
    QFrame, QSizePolicy, QDialog, QListWidget,
    QListWidgetItem, QDateEdit, QProgressBar,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QObject, QDate, QRectF, QPointF
from PyQt6.QtGui import (QFont, QColor, QPainter, QPen, QBrush, QFontDatabase)

try:
    from bleak import BleakScanner, BleakClient
    from ai_edge_litert.interpreter import Interpreter
except ImportError as e:
    print(f"[ERROR] Import gagal: {e}")
    print("Install: pip install bleak ai-edge-litert neurokit2 antropy scipy")
    sys.exit(1)

# ============================================================================
# KONFIGURASI
# ============================================================================
CONFIG = {
    'APP_TITLE': 'HRV Monitor',
    'DB_FILE': str(Path.home() / 'hrv_monitor.db'),
    'BLE_SERVICE_UUID': "12345678-1234-1234-1234-1234567890ab",
    'BLE_CHAR_UUID': "abcd1234-5678-1234-5678-1234567890ab",
    'DEVICE_NAME': "PPG_FATIGUE",
    'SAMPLE_RATE': 400,
    'WINDOW_SIZE_SEC': 300,      # 5 menit - untuk fatigue (slow pipeline)
    'STRIDE_SIZE_SEC': 60,       # 1 menit stride
    'SEQ_LENGTH': 3,
    'EARLY_WINDOW_SEC': 120,     # 1-2 menit untuk early fatigue score
    'EARLY_UPDATE_SEC': 15,
    'MODEL_DIR': str(Path.home() / "Documents" / "ppg_fatigue_app" / "models"),
    'LOG_DIR': str(Path.home() / "Documents" / "ppg_fatigue_app" / "logs"),
    'FAST_WINDOW_SEC': 8,        # 8 detik - untuk BPM real-time (fast pipeline)
}
# Recommended PPG quality threshold: 0.40 (based on NeuroKit2 examples and literature guidance)
CONFIG['MIN_QUALITY'] = 0.40

COLORS = {
    'bg_primary': '#F5F7FA', 'bg_card': '#FFFFFF',
    'accent_primary': '#4A90E2', 'accent_secondary': '#5BA3F5',
    'accent_dark': '#2C5F8A', 'accent_success': '#50C878',
    'accent_warning': '#FFA500', 'accent_danger': '#FF6B6B',
    'text_primary': "#677482", 'text_secondary': '#7F8C8D',
    'text_muted': '#BDC3C7', 'text_placeholder': '#A0AEC0',
    'border_light': '#E8ECF1', 'border_medium': '#D5DBE3',
    'signal_excellent': '#50C878', 'signal_good': '#5BA3F5',
    'signal_poor': '#FFA500', 'signal_lost': '#FF6B6B',
}

FATIGUE_LEVELS = {
    0: ("Waspada", COLORS['accent_success']),
    1: ("Lelah", COLORS['accent_warning']),
    2: ("Sangat Lelah", COLORS['accent_danger']),
}

SURVIVOR_FEATURES = [
    'HRV_MeanNN', 'HRV_RMSSD', 'HRV_SDNN',
    'HRV_LFHF', 'HRV_DFA_alpha1', 'Ent_Sample'
]

# ============================================================================
# CSV LOGGER
# ============================================================================
class CSVLogger:
    def __init__(self, session_name="session"):
        try:
            os.makedirs(CONFIG['LOG_DIR'], exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session = session_name
            self.flush_count = 0
            self.queue = queue.Queue(maxsize=2000)
            self._stop_event = threading.Event()

            # Raw CSV
            self.raw_path = os.path.join(CONFIG['LOG_DIR'], f"{session_name}_raw_{ts}.csv")
            self.raw_f = open(self.raw_path, 'w', newline='', encoding='utf-8')
            self.raw_w = csv.writer(self.raw_f)
            self.raw_w.writerow(['datetime_pc', 'session', 't_us', 'green', 'blue'])

            # Fast CSV
            self.fast_path = os.path.join(CONFIG['LOG_DIR'], f"{session_name}_fast_{ts}.csv")
            self.fast_f = open(self.fast_path, 'w', newline='', encoding='utf-8')
            self.fast_w = csv.writer(self.fast_f)
            self.fast_w.writerow(['datetime_pc', 'session', 'bpm', 'ibi_ms', 'signal_quality'])

            # Slow CSV
            self.slow_path = os.path.join(CONFIG['LOG_DIR'], f"{session_name}_slow_{ts}.csv")
            self.slow_f = open(self.slow_path, 'w', newline='', encoding='utf-8')
            self.slow_w = csv.writer(self.slow_f)
            self.slow_w.writerow(['datetime_pc', 'session'] + SURVIVOR_FEATURES + ['fatigue_label', 'confidence'])

            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

            print(f"[CSVLogger] Raw: {self.raw_path}")
            print(f"[CSVLogger] Fast: {self.fast_path}")
            print(f"[CSVLogger] Slow: {self.slow_path}")
        except Exception as e:
            print(f"[CSVLogger] Error initializing: {e}")
            self.raw_f = None
            self.fast_f = None
            self.slow_f = None

    def _worker(self):
        flush_count = 0
        while not self._stop_event.is_set() or not self.queue.empty():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                if flush_count > 0:
                    self._flush_files()
                    flush_count = 0
                continue
            if item is None:
                self.queue.task_done()
                break
            typ, payload = item
            try:
                if typ == 'raw':
                    t_us_list, green_list, blue_list = payload
                    now = datetime.now().isoformat(timespec='milliseconds')
                    for t, g, b in zip(t_us_list, green_list, blue_list):
                        self.raw_w.writerow([now, self.session, t, g, b])
                elif typ == 'fast':
                    bpm, ibi_ms, quality = payload
                    now = datetime.now().isoformat(timespec='milliseconds')
                    self.fast_w.writerow([now, self.session,
                                          round(bpm, 2) if bpm else '',
                                          round(ibi_ms, 2) if ibi_ms else '',
                                          quality])
                elif typ == 'slow':
                    features, label, confidence = payload
                    now = datetime.now().isoformat(timespec='milliseconds')
                    row = [now, self.session] + [features.get(f, '') for f in SURVIVOR_FEATURES] + [label, round(confidence, 4)]
                    self.slow_w.writerow(row)
                flush_count += 1
                if flush_count >= 20:
                    self._flush_files()
                    flush_count = 0
            except Exception as e:
                print(f"[CSVLogger] Worker error: {e}")
            finally:
                self.queue.task_done()
        self._flush_files()

    def log_raw(self, t_us_list, green_list, blue_list):
        if not self.raw_f:
            return
        try:
            self.queue.put_nowait(('raw', (t_us_list, green_list, blue_list)))
        except queue.Full:
            print("[CSVLogger] queue full, raw log dropped")

    def log_fast(self, bpm, ibi_ms, quality):
        if not self.fast_f:
            return
        try:
            self.queue.put_nowait(('fast', (bpm, ibi_ms, quality)))
        except queue.Full:
            print("[CSVLogger] queue full, fast log dropped")

    def log_slow(self, features, label, confidence):
        if not self.slow_f:
            return
        try:
            self.queue.put_nowait(('slow', (features, label, confidence)))
        except queue.Full:
            print("[CSVLogger] queue full, slow log dropped")

    def _flush_files(self):
        try:
            if self.raw_f: self.raw_f.flush()
            if self.fast_f: self.fast_f.flush()
            if self.slow_f: self.slow_f.flush()
        except Exception as e:
            print(f"[CSVLogger] Error flush: {e}")

    def stop(self):
        try:
            self._stop_event.set()
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                pass
            self._thread.join(timeout=3)
            if self.raw_f:
                self.raw_f.flush()
                self.raw_f.close()
            if self.fast_f:
                self.fast_f.flush()
                self.fast_f.close()
            if self.slow_f:
                self.slow_f.flush()
                self.slow_f.close()
        except Exception as e:
            print(f"[CSVLogger] Error stop: {e}")

# ============================================================================
# BLE WORKER
# ============================================================================
class BLEWorkerSignals(QObject):
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    raw_samples = pyqtSignal(list)
    raw_full = pyqtSignal(list, list, list)  # t_us, green, blue
    error = pyqtSignal(str)

class BLEWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = BLEWorkerSignals()
        self._running = False
        self._client = None
        self._loop = None

    def run(self):
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main_loop())
        except Exception as e:
            self.signals.error.emit(f"BLE Error: {str(e)}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _main_loop(self):
        while self._running:
            try:
                self.signals.error.emit("Scanning...")
                devices = await BleakScanner.discover(timeout=5.0)
                target = next((d for d in devices if d.name and CONFIG['DEVICE_NAME'] in d.name), None)
                if not target:
                    self.signals.error.emit("Device tidak ditemukan. Retry...")
                    await asyncio.sleep(2)
                    continue
                
                self._client = BleakClient(target.address)
                await self._client.connect()
                self.signals.connected.emit(target.name)
                
                await self._client.start_notify(CONFIG['BLE_CHAR_UUID'], self._notification_handler)
                
                while self._running and self._client.is_connected:
                    await asyncio.sleep(1.0)
                
                if self._client and self._client.is_connected:
                    try:
                        await self._client.stop_notify(CONFIG['BLE_CHAR_UUID'])
                        await self._client.disconnect()
                        print("[BLE] Disconnected cleanly")
                    except Exception as e:
                        print(f"[BLE] Disconnect error: {e}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.signals.error.emit(f"Connection error: {str(e)}")
                await asyncio.sleep(2)

    def _notification_handler(self, sender, data: bytearray):
        """
        PERBAIKAN KRITIS: Parsing interleaved struct {t_us, green, blue}
        Firmware mengirim: t0,g0,b0,t1,g1,b1,...,t9,g9,b9
        """
        if len(data) != 120:
            return
        try:
            green_samples = []
            t_us_list = []
            blue_list = []
            offset = 0
            for _ in range(10):
                t_us, green, blue = struct.unpack_from('<III', data, offset)
                t_us_list.append(t_us)
                green_samples.append(green)
                blue_list.append(blue)
                offset += 12  # 3 × 4 bytes = 12 bytes per sample
            
            self.signals.raw_samples.emit(green_samples)
            self.signals.raw_full.emit(t_us_list, green_samples, blue_list)
        except struct.error:
            pass

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running() and self._client:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._client.disconnect(),
                    self._loop
                )
            except Exception as e:
                print(f"[BLE] Schedule disconnect error: {e}")

class BLEScannerWorker(QThread):
    scan_finished = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def run(self):
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=5.0))
            self.scan_finished.emit(devices)
        except Exception as e:
            self.scan_error.emit(str(e))

# ============================================================================
# FAST PIPELINE (DIPERBAIKI - thread-safe dengan signal)
# ============================================================================
class FastHRVPipelineSignals(QObject):
    hrv_ready = pyqtSignal(float, float, str)  # bpm, ibi_ms, quality
    samples_ready = pyqtSignal(list)  # BARU: untuk thread-safe

class FastHRVPipeline(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = FastHRVPipelineSignals()
        self._running = False
        self.buffer = deque(maxlen=CONFIG['SAMPLE_RATE'] * CONFIG['FAST_WINDOW_SEC'])
        self.last_process_time = 0

    def run(self):
        self._running = True
        # PERBAIKAN: connect signal untuk thread-safe
        self.signals.samples_ready.connect(self.add_samples, Qt.ConnectionType.QueuedConnection)
        self.exec()

    def add_samples(self, samples):
        """Sekarang dipanggil via signal (thread-safe)"""
        if not self._running:
            return
        self.buffer.extend(samples)
        now = time.time()
        # Proses setiap 1 detik
        if now - self.last_process_time >= 1.0 and len(self.buffer) >= CONFIG['SAMPLE_RATE'] * CONFIG['FAST_WINDOW_SEC']:
            self.last_process_time = now
            self._process()

    def _process(self):
        try:
            x = np.asarray(list(self.buffer), dtype=float)
            fs = CONFIG['SAMPLE_RATE']
            
            # Bandpass filter 0.7-3.0 Hz untuk heart rate
            nyq = 0.5 * fs
            b, a = butter(2, [0.7 / nyq, 3.0 / nyq], btype="band")
            y = filtfilt(b, a, x)
            
            sig_std = float(np.std(y))
            prominence = max(sig_std * 0.8, 8.0)
            min_distance = int(0.60 * fs)  # max ~100 bpm
            
            peaks, _ = find_peaks(y, distance=min_distance, prominence=prominence)
            
            if len(peaks) < 3:
                self.signals.hrv_ready.emit(0.0, 0.0, "POOR")
                return
            
            # Hitung IBI
            ibis_s = []
            for i in range(1, len(peaks)):
                dt_s = (peaks[i] - peaks[i-1]) / fs
                if 0.50 <= dt_s <= 1.5:  # 40-120 bpm
                    ibis_s.append(dt_s)
            
            if len(ibis_s) < 2:
                self.signals.hrv_ready.emit(0.0, 0.0, "POOR")
                return
            
            mean_ibi = statistics.mean(ibis_s)
            std_ibi = statistics.pstdev(ibis_s) if len(ibis_s) > 1 else 0.0
            ibi_cv = std_ibi / mean_ibi if mean_ibi > 0 else 999.0
            
            if ibi_cv > 0.20:
                self.signals.hrv_ready.emit(0.0, 0.0, "POOR")
                return
            
            bpm = 60.0 / statistics.median(ibis_s)
            median_ibi_ms = statistics.median(ibis_s) * 1000
            
            if 40 <= bpm <= 120:
                self.signals.hrv_ready.emit(bpm, median_ibi_ms, "GOOD")
            else:
                self.signals.hrv_ready.emit(0.0, 0.0, "POOR")
        except Exception as e:
            print(f"[FastPipeline] Error: {e}")
            self.signals.hrv_ready.emit(0.0, 0.0, "POOR")

    def stop(self):
        self._running = False
        self.quit()

# ============================================================================
# SLOW PIPELINE (untuk fatigue detection - 5 menit window)
# ============================================================================
class HRVPipelineSignals(QObject):
    features_ready = pyqtSignal(dict, list)
    window_rejected = pyqtSignal(str)
    calibration_complete = pyqtSignal()
    progress = pyqtSignal(str, float)
    samples_ready = pyqtSignal(list)

class HRVPipeline(QThread):
    STATE_IDLE = "IDLE"
    STATE_CALIBRATING = "CALIBRATING"
    STATE_MONITORING = "MONITORING"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = HRVPipelineSignals()
        self._running = False
        self._state = self.STATE_IDLE
        self._buffer = deque(maxlen=CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC'])
        self._baseline_stats = None
        self._feature_history = []
        self._last_window_time = None
        self._window_count = 0

    def run(self):
        self._running = True
        self.signals.samples_ready.connect(self.add_samples, Qt.ConnectionType.QueuedConnection)
        timer = QTimer()
        timer.timeout.connect(self._check_window)
        timer.start(10000)
        self.exec()

    def set_state(self, state):
        self._state = state
        if state == self.STATE_IDLE:
            self._buffer = deque(maxlen=CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC'])
            self._feature_history = []
            self._window_count = 0
        elif state == self.STATE_CALIBRATING:
            self._baseline_stats = None
            self._buffer = deque(maxlen=CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC'])

    def add_samples(self, samples):
        if not self._running:
            return
        self._buffer.extend(samples)

    def _check_window(self):
        if self._state == self.STATE_IDLE:
            return
        if len(self._buffer) < CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC']:
            progress = len(self._buffer) / (CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC']) * 100
            self.signals.progress.emit(f"Buffering Fatigue: {progress:.1f}%", progress)
            return
        if self._last_window_time is not None:
            elapsed = (datetime.now() - self._last_window_time).total_seconds()
            if elapsed < CONFIG['STRIDE_SIZE_SEC']:
                return
        self._extract_window()
        self._last_window_time = datetime.now()

    def _extract_window(self):
        buffer_list = list(self._buffer)
        window_samples = buffer_list[-CONFIG['SAMPLE_RATE'] * CONFIG['WINDOW_SIZE_SEC']:]
        if len(window_samples) < CONFIG['SAMPLE_RATE'] * 30:
            return
        features = self._extract_features(window_samples)
        if features is None:
            self._advance_window()
            return
        if self._state == self.STATE_CALIBRATING:
            self._set_baseline(features)
            self.signals.calibration_complete.emit()
            self._state = self.STATE_MONITORING
            self.signals.progress.emit("Kalibrasi selesai!", 100)
            self._advance_window()
        elif self._state == self.STATE_MONITORING:
            normalized = self._normalize_features(features)
            if normalized is None:
                self._advance_window()
                return
            self._feature_history.append(normalized)
            self._window_count += 1
            self.signals.features_ready.emit(normalized, window_samples)
            self._advance_window()

    def _advance_window(self):
        shift_count = CONFIG['SAMPLE_RATE'] * CONFIG['STRIDE_SIZE_SEC']
        for _ in range(min(shift_count, len(self._buffer))):
            self._buffer.popleft()

    def _extract_features(self, signal_raw):
        try:
            self.signals.progress.emit("Ekstraksi: membersihkan sinyal", 10)
            signal_raw = np.asarray(signal_raw, dtype=float)
            # Ensure integer sampling rate and polarity check (from Feature_ExtractionV4)
            current_fs = int(round(CONFIG['SAMPLE_RATE']))
            signal_proc, polarity = check_and_fix_polarity(signal_raw, current_fs)
            if polarity == "FLIPPED":
                self.signals.progress.emit("Polaritas terdeteksi TERBALIK -> membalik sinyal", 5)
            ppg_cleaned = nk.ppg_clean(signal_proc, sampling_rate=current_fs, method="elgendi")
            if not np.all(np.isfinite(ppg_cleaned)) or np.std(ppg_cleaned) < 1e-8:
                self.signals.progress.emit("Ekstraksi gagal: noise terlalu tinggi", 0)
                return None
            self.signals.progress.emit("Ekstraksi: mengecek kualitas PPG", 30)
            quality = nk.ppg_quality(ppg_cleaned, sampling_rate=current_fs, method="templatematch")
            avg_quality = float(np.nanmean(quality))
            if avg_quality < CONFIG.get('MIN_QUALITY', 0.25):
                self.signals.window_rejected.emit(f"Kualitas rendah: {avg_quality:.3f}")
                self.signals.progress.emit("Ekstraksi gagal: kualitas rendah", 0)
                return None
            self.signals.progress.emit("Ekstraksi: deteksi puncak PPG", 55)
            signals_df, info = nk.ppg_peaks(ppg_cleaned, sampling_rate=current_fs,
                                           method="charlton", correct_artifacts=True)
            peak_col = None
            for cand in ("PPG_Peaks", "PPG_peaks"):
                if cand in signals_df.columns:
                    peak_col = cand
                    break
            if peak_col is None:
                self.signals.progress.emit("Ekstraksi gagal: kolom puncak tidak ditemukan", 0)
                return None
            peak_locs = np.where(signals_df[peak_col].values == 1)[0]
            if len(peak_locs) < 150:
                self.signals.window_rejected.emit(f"Puncak terlalu sedikit: {len(peak_locs)}")
                self.signals.progress.emit("Ekstraksi gagal: terlalu sedikit puncak", 0)
                return None
            nn_intervals_ms = np.diff(peak_locs) / current_fs * 1000.0
            bpm_per_beat = 60000.0 / nn_intervals_ms
            valid_mask = (bpm_per_beat >= 40) & (bpm_per_beat <= 180)
            pct_valid = valid_mask.mean() if len(valid_mask) else 0.0
            if pct_valid < 0.80:
                self.signals.window_rejected.emit(f"NN valid rendah: {pct_valid*100:.1f}%")
                self.signals.progress.emit("Ekstraksi gagal: NN valid rendah", 0)
                return None
            self.signals.progress.emit("Ekstraksi: menghitung metrik HRV", 75)
            peaks_binary = np.zeros(len(ppg_cleaned), dtype=int)
            peaks_binary[peak_locs] = 1
            result = {}
            hrv_time = nk.hrv_time(peaks_binary, sampling_rate=current_fs, show=False)
            for col in ['HRV_MeanNN', 'HRV_SDNN', 'HRV_RMSSD']:
                if col in hrv_time.columns:
                    result[col] = float(hrv_time[col].iloc[0])
            hrv_freq = nk.hrv_frequency(peaks_binary, sampling_rate=current_fs, show=False)
            if 'HRV_LFHF' in hrv_freq.columns:
                result['HRV_LFHF'] = float(hrv_freq['HRV_LFHF'].iloc[0])
            hrv_nonlin = nk.hrv_nonlinear(peaks_binary, sampling_rate=current_fs, show=False)
            if 'HRV_DFA_alpha1' in hrv_nonlin.columns:
                val = float(hrv_nonlin['HRV_DFA_alpha1'].iloc[0])
                result['HRV_DFA_alpha1'] = val if np.isfinite(val) else np.nan
            ent = ant.sample_entropy(nn_intervals_ms)
            result['Ent_Sample'] = float(ent) if np.isfinite(ent) else np.nan
            for fname in SURVIVOR_FEATURES:
                val = result.get(fname)
                if val is None or not np.isfinite(val):
                    self.signals.window_rejected.emit(f"Fitur {fname} tidak valid: {val}")
                    self.signals.progress.emit("Ekstraksi gagal: fitur tidak valid", 0)
                    return None
            checks = {
                "HRV_MeanNN": (333.0, 1500.0),
                "HRV_SDNN": (5.0, 500.0),
                "HRV_RMSSD": (2.0, 500.0),
                "HRV_LFHF": (0.01, 20.0),
                "HRV_DFA_alpha1": (0.3, 1.8),
                "Ent_Sample": (0.0, 5.0),
            }
            for fname, (lo, hi) in checks.items():
                val = result.get(fname)
                if val is None or not np.isfinite(val) or val < lo or val > hi:
                    self.signals.progress.emit("Ekstraksi gagal: pemeriksaan nilai akhir", 0)
                    return None
            self.signals.progress.emit("Ekstraksi selesai", 100)
            # Diagnostic metadata
            result['_n_peaks'] = int(len(peak_locs))
            result['_pct_valid_nn'] = round(pct_valid * 100, 1)
            try:
                result['_signal_quality'] = round(float(avg_quality), 3)
            except Exception:
                result['_signal_quality'] = None
            result['_polarity'] = polarity if 'polarity' in locals() else 'UNKNOWN'
            result['_peak_method'] = 'charlton'
            return result
        except Exception as e:
            print(f"[HRV Pipeline] Error: {e}")
            self.signals.progress.emit("Ekstraksi gagal: exception", 0)
            return None

    def _set_baseline(self, features):
        self._baseline_stats = {}
        for fname in SURVIVOR_FEATURES:
            val = features.get(fname)
            if val is not None and np.isfinite(val):
                self._baseline_stats[fname] = {'mean': val, 'std': 1.0}

    def _normalize_features(self, features):
        if self._baseline_stats is None:
            return None
        normalized = {}
        for fname in SURVIVOR_FEATURES:
            val = features.get(fname)
            if val is None or not np.isfinite(val):
                return None
            stats = self._baseline_stats.get(fname)
            if stats is None:
                return None
            mean = stats['mean']
            std = stats['std']
            normalized[fname] = 0.0 if std < 1e-8 else (val - mean) / std
        return normalized

    def stop(self):
        self._running = False
        self.quit()

# ============================================================================
# INFERENCE ENGINE
# ============================================================================
class InferenceEngine:
    def __init__(self, model_dir):
        self.model_dir = Path(model_dir)
        self.interpreter = None
        self.centroids = None
        self.cluster_to_label_map = None
        self.feature_buffer = []
        self._load_model()
        self._load_clustering_params()

    def _load_model(self):
        model_path = self.model_dir / "encoder_only.tflite"
        if not model_path.exists():
            raise FileNotFoundError(f"Model tidak ditemukan: {model_path}")
        self.interpreter = Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

    def _load_clustering_params(self):
        params_path = self.model_dir / "clustering_params.json"
        if not params_path.exists():
            raise FileNotFoundError(f"Clustering params tidak ditemukan: {params_path}")
        with open(params_path, 'r') as f:
            params = json.load(f)
        self.centroids = np.array(params['centroids'])
        # cluster_to_label_map in JSON may map cluster_id -> numeric class index (0/1/2).
        # Convert to human-readable label strings using FATIGUE_LEVELS when needed.
        raw_map = {int(k): v for k, v in params['cluster_to_label_map'].items()}
        mapped = {}
        for cid, v in raw_map.items():
            # if value is an int index, convert to label name from FATIGUE_LEVELS
            try:
                if isinstance(v, int) and v in FATIGUE_LEVELS:
                    mapped[cid] = FATIGUE_LEVELS[v][0]
                else:
                    mapped[cid] = v
            except Exception:
                mapped[cid] = v
        self.cluster_to_label_map = mapped

    def add_features(self, features_dict):
        try:
            feature_vector = []
            for fname in SURVIVOR_FEATURES:
                val = features_dict.get(fname, np.nan)
                if val is None or not np.isfinite(val):
                    print(f"[Inference] Fitur {fname} tidak valid: {val}")
                    return None
                feature_vector.append(val)
            feature_vector = np.array(feature_vector, dtype=np.float32)
            self.feature_buffer.append(feature_vector)
            if len(self.feature_buffer) > CONFIG['SEQ_LENGTH'] * 2:
                self.feature_buffer = self.feature_buffer[-CONFIG['SEQ_LENGTH']:]
            if len(self.feature_buffer) >= CONFIG['SEQ_LENGTH']:
                return self._predict()
            return None
        except Exception as e:
            print(f"[Inference] Error: {e}")
            return None

    def _predict(self):
        sequence = np.array(self.feature_buffer[-CONFIG['SEQ_LENGTH']:], dtype=np.float32)
        sequence = sequence.reshape(1, CONFIG['SEQ_LENGTH'], 6)
        self.interpreter.set_tensor(self.input_details[0]['index'], sequence)
        self.interpreter.invoke()
        latent = self.interpreter.get_tensor(self.output_details[0]['index'])
        distances = np.linalg.norm(self.centroids - latent, axis=1)
        cluster_id = int(np.argmin(distances))
        min_dist = distances[cluster_id]
        other_dists = np.delete(distances, cluster_id)
        if min_dist < 1e-8:
            confidence = 1.0
        else:
            ratio = min_dist / (np.mean(other_dists) + 1e-8)
            confidence = max(0.0, min(1.0, 1.0 - ratio))
        label = self.cluster_to_label_map.get(cluster_id, "Unknown")
        return {
            'label': label,
            'cluster_id': cluster_id,
            'confidence': confidence,
            'distances': distances.tolist()
        }

    def reset(self):
        self.feature_buffer = []

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def add_shadow(widget, blur_radius=15, offset_x=0, offset_y=4, color_alpha=25):
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur_radius)
    shadow.setColor(QColor(0, 0, 0, color_alpha))
    shadow.setOffset(offset_x, offset_y)
    widget.setGraphicsEffect(shadow)


def check_and_fix_polarity(signal, fs, tag=""):
    sig = np.asarray(signal, dtype=float)
    valid_mask = ~np.isnan(sig)
    valid_sig = sig[valid_mask]
    if len(valid_sig) < 3:
        return sig, "NORMAL"
    if np.std(valid_sig) < 1e-8:
        return sig, "NORMAL"
    try:
        from scipy import stats as _stats
        skew = float(_stats.skew(valid_sig))
    except Exception:
        skew = 0.0
    if skew < -0.5:
        return -sig, "FLIPPED"
    return sig, "NORMAL"


def compute_early_fatigue_score(signal_raw, fs):
    try:
        signal = np.asarray(signal_raw, dtype=float)
        if len(signal) < fs * 60:
            return None
        # Filter the short window for pulse detection
        nyq = 0.5 * fs
        b, a = butter(2, [0.7 / nyq, 3.0 / nyq], btype="band")
        filtered = filtfilt(b, a, signal)
        if not np.all(np.isfinite(filtered)):
            return None
        quality, _, _ = calculate_signal_quality(signal.tolist())
        if quality == 3:
            return None
        prominence = max(np.std(filtered) * 0.8, 6.0)
        min_distance = int(0.5 * fs)
        peaks, _ = find_peaks(filtered, distance=min_distance, prominence=prominence)
        if len(peaks) < 10:
            return None
        ibis = np.diff(peaks) / fs
        ibis = ibis[(ibis >= 0.4) & (ibis <= 1.5)]
        if len(ibis) < 5:
            return None
        mean_hr = 60.0 / np.mean(ibis)
        rmssd = np.sqrt(np.mean(np.diff(ibis) ** 2)) * 1000.0
        hr_norm = max(0.0, min(1.0, (120.0 - mean_hr) / 80.0))
        rmssd_norm = max(0.0, min(1.0, (rmssd - 10.0) / 60.0))
        quality_norm = max(0.0, min(1.0, quality / 100.0))
        score = 100.0 * (0.55 * hr_norm + 0.45 * rmssd_norm) * quality_norm
        score = max(0.0, min(100.0, score))
        if score >= 70:
            label = "Waspada"
        elif score >= 40:
            label = "Lelah"
        else:
            label = "Sangat Lelah"
        return score, label
    except Exception:
        return None

def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12: return "Good Morning!"
    elif 12 <= hour < 17: return "Good Afternoon!"
    elif 17 <= hour < 21: return "Good Evening!"
    else: return "Good Night!"

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
        if quality_score >= 70: return 0, "Excellent", COLORS['signal_excellent']
        elif quality_score >= 40: return 1, "Good", COLORS['signal_good']
        elif quality_score >= 20: return 2, "Poor", COLORS['signal_poor']
        else: return 3, "Lost", COLORS['signal_lost']
    except:
        return 3, "Lost", COLORS['signal_lost']

# ============================================================================
# WIDGETS
# ============================================================================
class GlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border-radius: 20px;
                border: none;
            }}
        """)
        add_shadow(self, blur_radius=25, offset_x=0, offset_y=6, color_alpha=20)

class MetricCard(GlassCard):
    def __init__(self, title, value, unit="", color=COLORS['accent_primary']):
        super().__init__()
        self.setMinimumHeight(150)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        title_label.setStyleSheet(f"color: {COLORS['text_placeholder']}; background: transparent; border: none;")
        layout.addWidget(title_label)
        layout.addSpacing(8)
        value_layout = QHBoxLayout()
        value_layout.setSpacing(8)
        self.value_label = QLabel(str(value))
        self.value_label.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        value_layout.addWidget(self.value_label)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Medium))
            unit_label.setStyleSheet(f"color: {COLORS['text_secondary']}; background: transparent;")
            value_layout.addWidget(unit_label)
        value_layout.addStretch()
        layout.addLayout(value_layout)

class WideMetricCard(GlassCard):
    def __init__(self, title, value, color=COLORS['text_muted']):
        super().__init__()
        self.setMinimumHeight(130)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        title_label.setStyleSheet(f"color: {COLORS['text_placeholder']}; background: transparent;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        layout.addSpacing(5)
        self.value_label = QLabel(str(value))
        self.value_label.setFont(QFont("Segoe UI", 44, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"color: {color}; background: transparent;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)
        layout.addStretch()

class SignalQualityIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.quality_level = 3
        self.setFixedSize(120, 40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        self.signal_icon = QLabel()
        self.signal_icon.setFixedSize(24, 24)
        layout.addWidget(self.signal_icon)
        self.quality_label = QLabel("Lost")
        self.quality_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.quality_label.setStyleSheet(f"color: {COLORS['signal_lost']}; background: transparent;")
        layout.addWidget(self.quality_label)
        layout.addStretch()

    def update_quality(self, level, text, color):
        self.quality_level = level
        self.quality_label.setText(text)
        self.quality_label.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent;")
        self.update()

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
        for i in range(0, width, 40): painter.drawLine(i, 0, i, height)
        for i in range(0, height, 40): painter.drawLine(0, i, width, i)
        points = len(self.waveform_data)
        path = []
        margin = 12
        for i, value in enumerate(self.waveform_data):
            x = (i / max(points - 1, 1)) * width
            clamped = max(0.0, min(1.0, value))
            y = margin + (1.0 - clamped) * (height - 2 * margin)
            path.append(QPointF(x, y))
        painter.setPen(QPen(QColor(74, 144, 226, 40), 8, Qt.PenStyle.SolidLine, 
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for i in range(len(path) - 1): painter.drawLine(path[i], path[i+1])
        painter.setPen(QPen(QColor(COLORS['accent_primary']), 2.5, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for i in range(len(path) - 1): painter.drawLine(path[i], path[i+1])

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
            total = time_point.get('fresh', 0) + time_point.get('moderate', 0) + time_point.get('fatigued', 0)
            if total > 0:
                for key, color in [('fresh', colors[0]), ('moderate', colors[1]), ('fatigued', colors[2])]:
                    percentage = time_point.get(key, 0)
                    bar_height = (percentage / 100) * chart_height
                    y_offset -= bar_height
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(color, 1))
                    painter.drawRoundedRect(QRectF(x + 1, y_offset, bar_width - 2, bar_height), 3, 3)
            if num_points <= 10 or i % max(num_points // 10, 1) == 0:
                painter.setPen(QPen(QColor(COLORS['text_muted']), 1))
                painter.setFont(QFont("Segoe UI", 8))
                painter.drawText(int(x), height - margin + 15, time_point.get('time', ''))
        legend_y = 15
        for i, (label, color) in enumerate([("Waspada", COLORS['accent_success']),
                                           ("Lelah", COLORS['accent_warning']),
                                           ("Sangat Lelah", COLORS['accent_danger'])]):
            x = width - margin - (3 - i) * 85
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, legend_y, 16, 16), 4, 4)
            painter.setPen(QPen(QColor(COLORS['text_primary']), 1))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
            painter.drawText(x + 20, legend_y + 12, label)

# ============================================================================
# DATABASE MANAGER
# ============================================================================
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_database()

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
                waveform_sample TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON readings(date)')
        conn.commit()
        conn.close()

    def save_reading(self, timestamp, bpm, hrv, fatigue_level, signal_quality, waveform_sample=None):
        date = timestamp.strftime('%Y-%m-%d')
        hour = timestamp.hour
        minute = timestamp.minute
        waveform_json = json.dumps(waveform_sample) if waveform_sample else None
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO readings (timestamp, date, hour, minute, bpm, hrv,
                                  fatigue_level, signal_quality, waveform_sample)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp.strftime('%Y-%m-%d %H:%M:%S'), date, hour, minute,
              bpm, hrv, fatigue_level, signal_quality, waveform_json))
        conn.commit()
        conn.close()

    def get_daily_summary(self, date):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT AVG(bpm), AVG(hrv), MAX(bpm), MIN(bpm), COUNT(*), fatigue_level FROM readings WHERE date = ? GROUP BY fatigue_level', (date,))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return None
        total = sum(r[4] for r in rows)
        max_bpm = max(r[2] for r in rows if r[2] is not None)
        min_bpm = min(r[3] for r in rows if r[3] is not None)
        return {
            'avg_bpm': sum(r[0] * r[4] for r in rows) / total if total > 0 else 0,
            'avg_hrv': sum(r[1] * r[4] for r in rows) / total if total > 0 else 0,
            'max_bpm': max_bpm,
            'min_bpm': min_bpm,
            'total_readings': total,
            'fresh_count': next((r[4] for r in rows if r[5] == 0), 0),
            'moderate_count': next((r[4] for r in rows if r[5] == 1), 0),
            'fatigued_count': next((r[4] for r in rows if r[5] == 2), 0),
        }

    def get_daily_trend(self, date):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT hour,
                   SUM(CASE WHEN fatigue_level = 0 THEN 1 ELSE 0 END) as fresh,
                   SUM(CASE WHEN fatigue_level = 1 THEN 1 ELSE 0 END) as moderate,
                   SUM(CASE WHEN fatigue_level = 2 THEN 1 ELSE 0 END) as fatigued
            FROM readings
            WHERE date = ?
            GROUP BY hour
            ORDER BY hour
        ''', (date,))
        rows = cursor.fetchall()
        conn.close()
        trend = []
        for hour, fresh, moderate, fatigued in rows:
            total = fresh + moderate + fatigued
            if total == 0:
                continue
            trend.append({
                'time': f"{hour:02d}:00",
                'fresh': fresh * 100.0 / total,
                'moderate': moderate * 100.0 / total,
                'fatigued': fatigued * 100.0 / total,
            })
        return trend

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
        self.scanner_thread = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        header = QLabel("Scan Device BLE")
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(header)
        self.status_label = QLabel("Klik 'Scan' untuk mencari device...")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.status_label)
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
        self.device_list.clear()
        self.status_label.setText("Scanning...")
        self.progress_bar.setVisible(True)
        self.scanner_thread = BLEScannerWorker()
        self.scanner_thread.scan_finished.connect(self.on_scan_finished)
        self.scanner_thread.scan_error.connect(self.on_scan_error)
        self.scanner_thread.finished.connect(self.on_scan_finished_complete)
        self.scanner_thread.start()

    def on_scan_finished(self, devices):
        self.device_list.clear()
        for device in devices:
            if device.name:
                rssi = getattr(device, 'rssi', None)
                rssi_text = f"{rssi} dBm" if rssi is not None else "N/A"
                item = QListWidgetItem(f"{device.name}\n{device.address} | RSSI: {rssi_text}")
                item.setData(Qt.ItemDataRole.UserRole, {
                    'name': device.name,
                    'address': device.address,
                    'rssi': rssi
                })
                self.device_list.addItem(item)
        if self.device_list.count() == 0:
            self.status_label.setText("Tidak ada device ditemukan")
        else:
            self.status_label.setText(f"Ditemukan {self.device_list.count()} device")

    def on_scan_error(self, error):
        self.status_label.setText(f"Error: {error}")

    def on_scan_finished_complete(self):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scanner_thread = None

    def on_device_selected(self):
        self.connect_btn.setEnabled(len(self.device_list.selectedItems()) > 0)

    def connect_selected(self):
        selected = self.device_list.selectedItems()
        if selected:
            device = selected[0].data(Qt.ItemDataRole.UserRole)
            self.device_selected.emit(device)
            self.accept()

# ============================================================================
# SIDEBAR
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
# MAIN WINDOW (DIPERBAIKI - threading benar, waveform real-time)
# ============================================================================
class HRVMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager(CONFIG['DB_FILE'])
        self.is_connected = False
        self.is_monitoring = False
        self.connected_device = None
        self.current_signal_quality = 3
        self.ble_worker = None
        self.fast_pipeline = None
        self.slow_pipeline = None
        self.inference_engine = None
        self.csv_logger = None
        self.pipeline_state = "IDLE"
        self.monitor_start_time = None
        self.early_buffer = deque(maxlen=CONFIG['SAMPLE_RATE'] * CONFIG['EARLY_WINDOW_SEC'])
        self.last_early_calc_ts = None
        self.ble_latency_ms = None
        self.last_device_ts = None
        self.last_arrival_ts = None
        
        # BARU: Buffer untuk waveform real-time
        self.waveform_buffer = deque(maxlen=4000)  # 10 detik × 400 Hz
        self.waveform_update_counter = 0
        self.waveform_pending = False
        # Live Hz monitor: store (timestamp, count) per notification
        self.hz_history = deque()
        self.hz_window_sec = 5
        self.live_hz = 0.0
        self.last_notify_ts = None
        
        self.init_ui()
        
        self.waveform_timer = QTimer(self)
        self.waveform_timer.timeout.connect(self.update_waveform_display)
        self.waveform_timer.start(250)
        
        try:
            self.inference_engine = InferenceEngine(CONFIG['MODEL_DIR'])
            print("[OK] Inference engine initialized")
        except Exception as e:
            print(f"[ERROR] Gagal load inference engine: {e}")
            QMessageBox.critical(self, "Error", f"Gagal load model: {e}")
        
        self.greeting_timer = QTimer()
        self.greeting_timer.timeout.connect(self.update_greeting)
        self.greeting_timer.start(1000)
        # Hz update timer
        self.hz_timer = QTimer(self)
        self.hz_timer.timeout.connect(self.update_hz_display)
        self.hz_timer.start(1000)

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
        self.hz_label = QLabel("Hz: -")
        self.hz_label.setFont(QFont("Segoe UI", 11))
        self.hz_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        indicators_layout.addWidget(self.hz_label)
        self.packet_rate_label = QLabel("Pkt/s: -")
        self.packet_rate_label.setFont(QFont("Segoe UI", 11))
        self.packet_rate_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        indicators_layout.addWidget(self.packet_rate_label)
        self.last_interval_label = QLabel("Last ms: -")
        self.last_interval_label.setFont(QFont("Segoe UI", 11))
        self.last_interval_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        indicators_layout.addWidget(self.last_interval_label)
        self.ble_latency_label = QLabel("BLE Latency: -")
        self.ble_latency_label.setFont(QFont("Segoe UI", 11))
        self.ble_latency_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        indicators_layout.addWidget(self.ble_latency_label)
        header_layout.addLayout(indicators_layout)
        content_layout.addWidget(self.header_widget)
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.create_dashboard_content())
        self.stacked_widget.addWidget(self.create_history_content())
        content_layout.addWidget(self.stacked_widget)
        self.sidebar.nav_buttons[0].clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.sidebar.nav_buttons[1].clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        main_layout.addWidget(content_widget, 1)
        self.update_greeting()

    def update_greeting(self):
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))
        self.greeting_label.setText(get_greeting())
        self.header_widget.setVisible(self.stacked_widget.currentIndex() == 0)

    def append_terminal(self, text):
        try:
            ts = datetime.now().strftime('%H:%M:%S')
            self.terminal_output.appendPlainText(f"[{ts}] {text}")
            # keep terminal scrolled to bottom
            self.terminal_output.verticalScrollBar().setValue(self.terminal_output.verticalScrollBar().maximum())
        except Exception:
            pass

    def on_min_quality_changed(self, value):
        quality = value / 100.0
        CONFIG['MIN_QUALITY'] = quality
        self.min_quality_label.setText(f"Min Quality: {quality:.2f}")
        self.append_terminal(f"MIN_QUALITY set to {quality:.2f}")

    def update_hz_display(self):
        # Compute sum of samples in the window (last hz_window_sec seconds)
        now_ts = time.time()
        cutoff = now_ts - self.hz_window_sec
        total = 0
        # Purge old entries and sum
        while self.hz_history and self.hz_history[0][0] < cutoff:
            self.hz_history.popleft()
        for ts, cnt in self.hz_history:
            if ts >= cutoff:
                total += cnt
        # Avoid division by zero: use actual span (min 0.5s)
        span = self.hz_window_sec
        hz = total / span if span > 0 else 0.0
        self.live_hz = hz
        # Notifications (packets) per second
        notif_count = len(self.hz_history)
        pkt_rate = notif_count / span if span > 0 else 0.0
        # Inter-notification intervals (ms)
        intervals = []
        prev = None
        for ts, _ in self.hz_history:
            if prev is not None:
                intervals.append(ts - prev)
            prev = ts
        if intervals:
            avg_interval_ms = (sum(intervals) / len(intervals)) * 1000.0
            # jitter as std dev
            mean_int = sum(intervals) / len(intervals)
            var = sum((x - mean_int) ** 2 for x in intervals) / len(intervals)
            jitter_ms = math.sqrt(var) * 1000.0
        else:
            avg_interval_ms = None
            jitter_ms = None
        # time since last notification
        if self.last_notify_ts:
            last_since_ms = (now_ts - self.last_notify_ts) * 1000.0
        else:
            last_since_ms = None
        try:
            self.hz_label.setText(f"Hz: {hz:.0f}")
            self.packet_rate_label.setText(f"Pkt/s: {pkt_rate:.1f}")
            if last_since_ms is None:
                self.last_interval_label.setText("Last ms: -")
            else:
                self.last_interval_label.setText(f"Last ms: {last_since_ms:.0f}")
            if self.ble_latency_ms is None:
                self.ble_latency_label.setText("BLE Latency: -")
            else:
                self.ble_latency_label.setText(f"BLE Latency: {self.ble_latency_ms:.0f} ms")
        except Exception:
            pass

    def create_dashboard_content(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(25)
        status_card = GlassCard()
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(25, 20, 25, 20)
        status_info_layout = QVBoxLayout()
        status_info_layout.setSpacing(4)
        self.status_label = QLabel("● Tidak Terhubung")
        self.status_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.status_label.setStyleSheet(f"color: {COLORS['accent_danger']};")
        status_info_layout.addWidget(self.status_label)
        self.pipeline_progress_label = QLabel("Inference: 0/3 | Ekstraksi: 0%")
        self.pipeline_progress_label.setFont(QFont("Segoe UI", 10))
        self.pipeline_progress_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        status_info_layout.addWidget(self.pipeline_progress_label)
        self.fatigue_latency_label = QLabel("Waktu sampai output: -")
        self.fatigue_latency_label.setFont(QFont("Segoe UI", 10))
        self.fatigue_latency_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        status_info_layout.addWidget(self.fatigue_latency_label)
        self.pipeline_progress_bar = QProgressBar()
        self.pipeline_progress_bar.setFixedHeight(16)
        self.pipeline_progress_bar.setRange(0, 100)
        self.pipeline_progress_bar.setValue(0)
        self.pipeline_progress_bar.setTextVisible(False)
        status_info_layout.addWidget(self.pipeline_progress_bar)
        status_layout.addLayout(status_info_layout)
        status_layout.addStretch()
        self.log_checkbox = QPushButton("📊 Aktifkan Logging CSV")
        self.log_checkbox.setCheckable(True)
        self.log_checkbox.setFixedHeight(46)
        self.log_checkbox.setMinimumWidth(180)
        self.log_checkbox.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.log_checkbox.clicked.connect(self.toggle_logging)
        self.log_checkbox.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border_light']};
                border-radius: 10px;
                padding: 0 20px;
            }}
            QPushButton:checked {{
                background-color: {COLORS['accent_success']};
                color: white;
                border: 2px solid {COLORS['accent_success']};
            }}
        """)
        status_layout.addWidget(self.log_checkbox)
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
            QPushButton:hover {{ background-color: {COLORS['accent_dark']}; }}
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
            QPushButton:hover {{ background-color: #43A047; }}
            QPushButton:disabled {{ background-color: {COLORS['text_muted']}; }}
        """)
        status_layout.addWidget(self.start_monitoring_btn)
        # Quality threshold control
        self.min_quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_quality_slider.setRange(20, 60)
        self.min_quality_slider.setValue(int(CONFIG['MIN_QUALITY'] * 100))
        self.min_quality_slider.setFixedWidth(240)
        self.min_quality_slider.valueChanged.connect(self.on_min_quality_changed)
        self.min_quality_label = QLabel(f"Min Quality: {CONFIG['MIN_QUALITY']:.2f}")
        self.min_quality_label.setFont(QFont("Segoe UI", 10))
        self.min_quality_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        quality_layout = QVBoxLayout()
        quality_layout.setSpacing(4)
        quality_layout.addWidget(self.min_quality_label)
        quality_layout.addWidget(self.min_quality_slider)
        status_layout.addLayout(quality_layout)
        layout.addWidget(status_card)
        main_content = QHBoxLayout()
        main_content.setSpacing(25)
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(20)
        row1 = QHBoxLayout()
        row1.setSpacing(20)
        self.bpm_card = MetricCard("BPM (Real-time)", "0", "bpm", COLORS['accent_danger'])
        self.ibi_card = MetricCard("IBI (Real-time)", "0", "ms", COLORS['accent_secondary'])
        row1.addWidget(self.bpm_card)
        row1.addWidget(self.ibi_card)
        metrics_layout.addLayout(row1)
        self.fatigue_card = WideMetricCard("Tingkat Kelelahan (5 Menit)", "-", COLORS['text_muted'])
        metrics_layout.addWidget(self.fatigue_card)
        self.early_fatigue_card = WideMetricCard("Early Fatigue Score (1-2 Menit)", "-", COLORS['accent_secondary'])
        metrics_layout.addWidget(self.early_fatigue_card)
        table_card = GlassCard()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(20, 15, 20, 15)
        table_layout.setSpacing(10)
        table_title = QLabel("📡 Monitoring Data ESP32 → Raspberry Pi (Real-time)")
        table_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        table_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        table_layout.addWidget(table_title)
        self.realtime_table = QTableWidget()
        self.realtime_table.setColumnCount(5)
        self.realtime_table.setHorizontalHeaderLabels(["Waktu", "BPM", "IBI (ms)", "Kualitas", "Sumber"])
        self.realtime_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.realtime_table.setMaximumHeight(180)
        self.realtime_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.realtime_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS['bg_primary']};
                border: 1px solid {COLORS['border_light']};
                border-radius: 8px;
                gridline-color: {COLORS['border_light']};
            }}
            QTableWidget::item {{
                padding: 5px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['accent_primary']};
                color: white;
                padding: 5px;
                border: none;
                font-weight: bold;
            }}
        """)
        table_layout.addWidget(self.realtime_table)
        metrics_layout.addWidget(table_card)
        metrics_layout.addStretch()
        main_content.addWidget(metrics_container, 1)
        waveform_card = GlassCard()
        waveform_layout = QVBoxLayout(waveform_card)
        waveform_layout.setContentsMargins(28, 25, 28, 25)
        waveform_layout.setSpacing(18)
        waveform_title = QLabel("Gelombang PPG Real-Time")
        waveform_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        waveform_title.setStyleSheet(f"color: {COLORS['text_primary']};")
        waveform_layout.addWidget(waveform_title)
        self.waveform_widget = WaveformWidget()
        self.waveform_widget.setMinimumHeight(380)
        waveform_layout.addWidget(self.waveform_widget)
        # Terminal output panel for feature extraction and inference
        from PyQt6.QtWidgets import QPlainTextEdit
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        self.terminal_output.setFixedHeight(140)
        self.terminal_output.setStyleSheet(f"background-color: {COLORS['bg_primary']}; color: {COLORS['text_primary']}; border: 1px solid {COLORS['border_light']};")
        waveform_layout.addWidget(self.terminal_output)
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

    def toggle_logging(self, checked):
        if checked:
            session_name = self.connected_device.replace(" ", "_") if self.connected_device else "session"
            self.csv_logger = CSVLogger(session_name)
            self.status_label.setText("● Logging CSV Aktif")
            self.log_checkbox.setText("📊 Logging CSV Aktif")
            print(f"[CSV] Logging started: {self.csv_logger.raw_path}")
        else:
            if self.csv_logger:
                self.csv_logger.stop()
                self.csv_logger = None
            self.status_label.setText("● Logging CSV Mati")
            self.log_checkbox.setText("📊 Aktifkan Logging CSV")

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

    def toggle_monitoring(self):
        if not self.is_monitoring:
            if not self.is_connected:
                QMessageBox.warning(self, "Koneksi Diperlukan", "Hubungkan ke ESP32 terlebih dahulu.")
                return
            self.is_monitoring = True
            self.monitor_start_time = datetime.now()
            self.fatigue_latency_label.setText("Waktu sampai output: -")
            self.start_monitoring_btn.setText("Hentikan Monitoring")
            self.start_monitoring_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_warning']};
                    color: white;
                    border: none;
                    border-radius: 10px;
                }}
            """)
            
            # Start BLE worker
            self.ble_worker = BLEWorker()
            self.ble_worker.signals.connected.connect(self.on_ble_connected)
            self.ble_worker.signals.disconnected.connect(self.on_ble_disconnected)
            self.ble_worker.signals.raw_samples.connect(self.on_raw_samples)
            self.ble_worker.signals.raw_full.connect(self.on_raw_full)
            self.ble_worker.signals.error.connect(self.on_ble_error)
            self.ble_worker.start()
            
            # Start Fast Pipeline (BPM/IBI real-time)
            self.fast_pipeline = FastHRVPipeline()
            self.fast_pipeline.signals.hrv_ready.connect(self.on_fast_ready)
            self.fast_pipeline.start()
            
            # Start Slow Pipeline (fatigue detection)
            self.slow_pipeline = HRVPipeline()
            self.slow_pipeline.signals.features_ready.connect(self.on_features_ready)
            self.slow_pipeline.signals.window_rejected.connect(self.on_window_rejected)
            self.slow_pipeline.signals.calibration_complete.connect(self.on_calibration_complete)
            self.slow_pipeline.signals.progress.connect(self.on_pipeline_progress)
            self.slow_pipeline.start()
            
            self.pipeline_state = "CALIBRATING"
            self.status_label.setText("● Kalibrasi Baseline: Diam rileks 5 menit...")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_warning']};")
            self.slow_pipeline.set_state(HRVPipeline.STATE_CALIBRATING)
            
        else:
            self.is_monitoring = False
            self.start_monitoring_btn.setText("Mulai Monitoring")
            self.start_monitoring_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_success']};
                    color: white;
                    border: none;
                    border-radius: 10px;
                }}
            """)
            if self.ble_worker:
                self.ble_worker.stop()
                self.ble_worker.wait()
                self.ble_worker = None
            if self.fast_pipeline:
                self.fast_pipeline.stop()
                self.fast_pipeline.wait()
                self.fast_pipeline = None
            if self.slow_pipeline:
                self.slow_pipeline.stop()
                self.slow_pipeline.wait()
                self.slow_pipeline = None
            if self.inference_engine:
                self.inference_engine.reset()
            if self.csv_logger:
                self.csv_logger.stop()
                self.csv_logger = None
                self.log_checkbox.setChecked(False)
                self.log_checkbox.setText("📊 Aktifkan Logging CSV")
            self.pipeline_state = "IDLE"
            self.monitor_start_time = None
            self.last_early_calc_ts = None
            self.early_buffer.clear()
            self.ble_latency_ms = None
            self.last_device_ts = None
            self.last_arrival_ts = None
            self.early_fatigue_card.value_label.setText("-")
            self.early_fatigue_card.value_label.setStyleSheet(f"color: {COLORS['accent_secondary']}; font-size: 44pt; font-weight: bold; background: transparent; border: none;")
            self.fatigue_latency_label.setText("Waktu sampai output: -")
            self.status_label.setText("● Monitoring Dihentikan")
            self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")

    def on_ble_connected(self, device_name):
        print(f"[BLE] Connected to {device_name}")

    def on_ble_disconnected(self):
        print("[BLE] Disconnected")
        if self.is_monitoring:
            self.status_label.setText("● BLE Terputus")

    def on_raw_samples(self, samples):
        """Dipanggil dari BLE worker thread - kirim ke kedua pipeline via signal"""
        if not self.is_monitoring:
            return
        # Record incoming samples for live Hz calculation
        try:
            ts = time.time()
            self.hz_history.append((ts, len(samples)))
            self.last_notify_ts = ts
        except Exception:
            pass

        if self.fast_pipeline:
            self.fast_pipeline.signals.samples_ready.emit(samples)
        if self.slow_pipeline:
            self.slow_pipeline.signals.samples_ready.emit(samples)
        
        self.waveform_buffer.extend(samples)
        self.waveform_pending = True

        self.early_buffer.extend(samples)
        now = time.time()
        if self.last_early_calc_ts is None or (now - self.last_early_calc_ts) >= CONFIG['EARLY_UPDATE_SEC']:
            if len(self.early_buffer) >= CONFIG['SAMPLE_RATE'] * CONFIG['EARLY_WINDOW_SEC']:
                early_result = compute_early_fatigue_score(list(self.early_buffer), CONFIG['SAMPLE_RATE'])
                if early_result is not None:
                    score, label = early_result
                    self.early_fatigue_card.value_label.setText(f"{score:.0f}")
                    self.early_fatigue_card.value_label.setStyleSheet(f"color: {COLORS['accent_secondary']}; font-size: 44pt; font-weight: bold; background: transparent; border: none;")
                    self.append_terminal(f"Early fatigue score: {score:.0f} ({label})")
                self.last_early_calc_ts = now

        if len(samples) >= 10:
            quality, text, color = calculate_signal_quality(samples)
            self.current_signal_quality = quality
            self.signal_indicator.update_quality(quality, text, color)

    def on_raw_full(self, t_us_list, green_list, blue_list):
        if len(t_us_list) > 0:
            try:
                arrival_ts = time.time()
                device_ts = t_us_list[0] / 1_000_000.0
                if self.last_device_ts is not None and self.last_arrival_ts is not None:
                    dt_dev = device_ts - self.last_device_ts
                    dt_arr = arrival_ts - self.last_arrival_ts
                    self.ble_latency_ms = max(0.0, (dt_arr - dt_dev) * 1000.0)
                self.last_device_ts = device_ts
                self.last_arrival_ts = arrival_ts
            except Exception:
                pass
        if self.csv_logger:
            self.csv_logger.log_raw(t_us_list, green_list, blue_list)

    def on_ble_error(self, error_msg):
        print(f"[BLE Error] {error_msg}")
        self.status_label.setText(f"● {error_msg}")
        self.status_label.setStyleSheet(f"color: {COLORS['accent_warning']};")

    def on_fast_ready(self, bpm, ibi_ms, quality):
        """Update UI dari fast pipeline (BPM/IBI real-time)"""
        if bpm > 0:
            self.bpm_card.value_label.setText(f"{bpm:.0f}")
            self.ibi_card.value_label.setText(f"{ibi_ms:.0f}")
        else:
            self.bpm_card.value_label.setText("-")
            self.ibi_card.value_label.setText("-")
        
        if self.csv_logger:
            self.csv_logger.log_fast(bpm, ibi_ms, quality)
        
        now_str = datetime.now().strftime("%H:%M:%S")
        row = self.realtime_table.rowCount()
        if row >= 50:
            self.realtime_table.removeRow(row - 1)
        self.realtime_table.insertRow(0)
        self.realtime_table.setItem(0, 0, QTableWidgetItem(now_str))
        self.realtime_table.setItem(0, 1, QTableWidgetItem(f"{bpm:.0f}" if bpm > 0 else "-"))
        self.realtime_table.setItem(0, 2, QTableWidgetItem(f"{ibi_ms:.0f}" if ibi_ms > 0 else "-"))
        quality_item = QTableWidgetItem(quality)
        if quality == "GOOD":
            quality_item.setForeground(QColor(COLORS['signal_excellent']))
        else:
            quality_item.setForeground(QColor(COLORS['signal_poor']))
        self.realtime_table.setItem(0, 3, quality_item)
        self.realtime_table.setItem(0, 4, QTableWidgetItem("Fast (8s)"))

    def on_features_ready(self, features_dict, raw_window):
        """Update UI dari slow pipeline (fatigue detection)"""
        if not self.inference_engine:
            return
        prediction = self.inference_engine.add_features(features_dict)
        buffer_len = len(self.inference_engine.feature_buffer)
        inference_pct = int(min(100, buffer_len / CONFIG['SEQ_LENGTH'] * 100))
        self.pipeline_progress_label.setText(f"Inference: {buffer_len}/{CONFIG['SEQ_LENGTH']} window | Ekstraksi: 100%")
        self.pipeline_progress_bar.setValue(inference_pct)
        if prediction:
            label = prediction['label']
            confidence = prediction['confidence']
            label_to_level = {'Waspada': 0, 'Lelah': 1, 'Sangat Lelah': 2}
            level = label_to_level.get(label, 0)
            fatigue_text, fatigue_color = FATIGUE_LEVELS[level]
            if self.monitor_start_time:
                elapsed = datetime.now() - self.monitor_start_time
                elapsed_minutes = elapsed.total_seconds() / 60.0
                self.fatigue_latency_label.setText(f"Waktu sampai output: {elapsed_minutes:.2f} menit")
                self.append_terminal(f"Fatigue output tersedia setelah {elapsed_minutes:.2f} menit monitoring")
            self.status_label.setText(f"● {fatigue_text} (Confidence: {confidence:.0%})")
            self.status_label.setStyleSheet(f"color: {fatigue_color};")
            self.pipeline_progress_label.setText(f"Inference selesai: {buffer_len}/{CONFIG['SEQ_LENGTH']} window")
            self.pipeline_progress_bar.setValue(100)
            
            if self.csv_logger:
                self.csv_logger.log_slow(features_dict, label, confidence)
            
            row = self.realtime_table.rowCount()
            if row >= 50:
                self.realtime_table.removeRow(row - 1)
            self.realtime_table.insertRow(0)
            now_str = datetime.now().strftime("%H:%M:%S")
            self.realtime_table.setItem(0, 0, QTableWidgetItem(now_str))
            self.realtime_table.setItem(0, 1, QTableWidgetItem(fatigue_text))
            self.realtime_table.setItem(0, 2, QTableWidgetItem(f"{confidence:.0%}"))
            fatigue_item = QTableWidgetItem(label)
            fatigue_item.setForeground(QColor(fatigue_color))
            self.realtime_table.setItem(0, 3, fatigue_item)
            self.realtime_table.setItem(0, 4, QTableWidgetItem("Slow (5m)"))
            
            # Update waveform (fallback jika real-time update gagal)
            if len(raw_window) > 0:
                step = max(1, len(raw_window) // 100)
                downsampled = raw_window[::step]
                self.waveform_widget.update_waveform(downsampled)
            
            # Save to database
            timestamp = datetime.now()
            bpm_val = int(self.bpm_card.value_label.text()) if self.bpm_card.value_label.text().replace('.', '').replace('-', '').isdigit() else 0
            hrv_val = int(float(self.ibi_card.value_label.text())) if self.ibi_card.value_label.text().replace('.', '').replace('-', '').isdigit() else 0
            self.db_manager.save_reading(timestamp, bpm_val, hrv_val, level, self.current_signal_quality, [])
            
            print(f"[Prediction] {label} (Confidence: {confidence:.0%})")
            # Terminal output: features summary + prediction
            try:
                feats = ", ".join([f"{k}={features_dict.get(k):.2f}" for k in SURVIVOR_FEATURES])
            except Exception:
                feats = str({k: features_dict.get(k) for k in SURVIVOR_FEATURES})
            diag = []
            if '_n_peaks' in features_dict:
                diag.append(f"n_peaks={features_dict.get('_n_peaks')}")
            if '_pct_valid_nn' in features_dict:
                diag.append(f"pct_valid={features_dict.get('_pct_valid_nn')}%")
            if '_signal_quality' in features_dict:
                diag.append(f"q={features_dict.get('_signal_quality')}")
            diag_s = ", ".join(diag)
            self.append_terminal(f"Features: {feats} | {diag_s}  => Prediction: {label} (conf={confidence:.2f})")
        else:
            self.fatigue_card.value_label.setText("Menunggu...")
            self.fatigue_card.value_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 32pt; font-weight: bold; background: transparent; border: none;")
            self.status_label.setText(f"● Menunggu inferensi slow: {buffer_len}/{CONFIG['SEQ_LENGTH']} window")
            self.status_label.setStyleSheet(f"color: {COLORS['accent_secondary']};")
            self.pipeline_progress_label.setText(f"Inference: {buffer_len}/{CONFIG['SEQ_LENGTH']} window | Menunggu prediksi")
            self.pipeline_progress_bar.setValue(int(min(100, buffer_len / CONFIG['SEQ_LENGTH'] * 100)))
            # Terminal info when waiting
            self.append_terminal(f"Extracted features saved. Waiting for {CONFIG['SEQ_LENGTH'] - buffer_len} more windows")

    def on_window_rejected(self, reason):
        print(f"[Pipeline] Window rejected: {reason}")
        self.status_label.setText(f"● Window rejected: {reason}")
        self.status_label.setStyleSheet(f"color: {COLORS['accent_warning']};")
        self.pipeline_progress_label.setText(f"Rejected: {reason}")
        self.pipeline_progress_bar.setValue(0)
        self.append_terminal(f"Window rejected: {reason}")

    def update_waveform_display(self):
        if not self.waveform_pending:
            return
        self.waveform_pending = False
        raw_data = list(self.waveform_buffer)
        if not raw_data:
            return
        min_val = min(raw_data)
        max_val = max(raw_data)
        range_val = max_val - min_val
        if range_val > 0:
            normalized = [(x - min_val) / range_val for x in raw_data]
        else:
            normalized = [0.5] * len(raw_data)
        waveform_data = normalized[::max(1, len(normalized) // 120)]
        self.waveform_widget.update_waveform(waveform_data)

    def on_calibration_complete(self):
        self.pipeline_state = "MONITORING"
        self.status_label.setText("● Monitoring Aktif - Menunggu prediksi pertama...")
        self.status_label.setStyleSheet(f"color: {COLORS['accent_success']};")
        self.pipeline_progress_label.setText("Inference: 0/3 window | Kalibrasi selesai")
        self.pipeline_progress_bar.setValue(0)
        print("[Pipeline] Calibration complete")

    def on_pipeline_progress(self, status, percentage):
        self.status_label.setText(f"● {status}")
        self.pipeline_progress_label.setText(f"Ekstraksi: {int(percentage)}%")
        self.pipeline_progress_bar.setValue(int(percentage))

    def on_date_changed(self, date):
        self.load_history_data()

    def load_history_data(self):
        selected_date = self.date_picker.date().toString('yyyy-MM-dd')
        summary = self.db_manager.get_daily_summary(selected_date)
        trend = self.db_manager.get_daily_trend(selected_date)
        if not summary:
            self.hist_avg_bpm.setText("Rata-rata BPM: -")
            self.hist_avg_hrv.setText("Rata-rata HRV: -")
            self.hist_total.setText("Total: -")
            self.hist_max_bpm.setText("Max BPM: -")
            self.hist_min_bpm.setText("Min BPM: -")
            self.hist_fatigue.setText("Distribusi: -")
            self.adaptive_chart.update_data([], "hour")
            self.chart_title.setText(f"Distribusi Kelelahan {selected_date}")
            return
        self.hist_avg_bpm.setText(f"Rata-rata BPM: {summary['avg_bpm']:.1f}")
        self.hist_avg_hrv.setText(f"Rata-rata HRV: {summary['avg_hrv']:.1f} ms")
        self.hist_total.setText(f"Total: {summary['total_readings']}")
        self.hist_max_bpm.setText(f"Max BPM: {summary['max_bpm']:.0f}")
        self.hist_min_bpm.setText(f"Min BPM: {summary['min_bpm']:.0f}")
        self.hist_fatigue.setText(f"Waspada: {summary['fresh_count']} | Lelah: {summary['moderate_count']} | Sangat Lelah: {summary['fatigued_count']}")
        self.adaptive_chart.update_data(trend, "hour")
        self.chart_title.setText(f"Distribusi Kelelahan {selected_date}")

    def closeEvent(self, event):
        if self.ble_worker:
            self.ble_worker.stop()
            self.ble_worker.wait(3000)
        if self.fast_pipeline:
            self.fast_pipeline.stop()
            self.fast_pipeline.wait(3000)
        if self.slow_pipeline:
            self.slow_pipeline.stop()
            self.slow_pipeline.wait(3000)
        if self.csv_logger:
            self.csv_logger.stop()
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