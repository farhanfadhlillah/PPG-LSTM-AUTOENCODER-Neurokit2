"""
====================================================================
EKSTRAKSI FITUR PPG → HRV UNTUK KLASIFIKASI 3 TINGKAT KELELAHAN
Versi   : 3.2 (Critical Bug Fix & Kontradiksi Resolution)
====================================================================

CHANGELOG v3.2 (vs v3.1):
[BUG CRITIS] Hapus parameter `peak_distance=0.35` dari nk.ppg_peaks()
    saat menggunakan method="charlton". Parameter ini TIDAK DIKENALI
    oleh algoritma MSPTD (Charlton et al., 2025) yang menggunakan
    Local Maxima Scalogram, bukan threshold + refractory period.
    Memberikan peak_distance ke charlton menyebabkan error silent
    atau diabaikan — membuat tuning sia-sia.

[BUG] Ent_Sample range (0.0, 3.0) terlalu ketat → dinaikkan ke 5.0.
    Sample entropy antropy bisa > 3.0 untuk sinyal kompleks.

[BUG] HRV_LFHF max 10.0 terlalu ketat → dinaikkan ke 20.0.
    Rasio LF/HF bisa mencapai 15-20 pada kelelahan ekstrem/stres berat.
    Ambang lama justru menolak window "Sangat Lelah" yang ingin dideteksi.

[IMPROVEMENT] MIN_PEAKS_PER_WINDOW diturunkan 250 → 200.
    Aman untuk subjek dengan HR rendah (atlet, 50 bpm = 250 detak/5min).

[IMPROVEMENT] Fallback otomatis ke "elgendi" jika "charlton" gagal.
    Pipeline tidak berhenti total jika ada bug di metode charlton.

[IMPROVEMENT] Guard tambahan di check_and_fix_polarity untuk array pendek.
    stats.skew() error jika array < 3 elemen.

[IMPROVEMENT] Logging eksplisit metode peak detection yang dipakai.

ARSITEKTUR PIPELINE:
1. Baca sinyal PPG mentah per subjek per kondisi
2. Sliding window (5 menit, overlap 4 menit)
3. Per window:
   a. Auto-polarity check (sensor PPG reflektif bisa terbalik)
   b. Bandpass filtering + cleaning (NeuroKit2)
   c. Deteksi puncak (Charlton/MSPTDfast, fallback ke Elgendi)
   d. Validasi fisiologis NN-interval (40-180 BPM) sebagai QA gate
   e. Ekstraksi 6 fitur survivor dari peak_locs ASLI
   f. Sanity-check fisiologis multi-layer
4. Normalisasi Z-score per subjek (baseline = Waspada)
5. Filter outlier IQR
6. Simpan Train_Features_Filtered.csv & Test_Features_Filtered.csv

6 FITUR SURVIVOR (non-redundan, fisiologis independen):
1. HRV_MeanNN     → Detak jantung dasar
2. HRV_RMSSD      → Variabilitas parasimpatis (jangka pendek)
3. HRV_SDNN       → Variabilitas keseluruhan
4. HRV_LFHF       → Keseimbangan simpatis-vagal
5. HRV_DFA_alpha1 → Korelasi fraktal (non-linear)
6. Ent_Sample     → Kompleksitas sistem saraf (entropy)

PRASYARAT:
    pip install neurokit2 antropy pandas numpy scipy
====================================================================
"""

import os
import glob
import traceback
import warnings
import pandas as pd
import numpy as np
import neurokit2 as nk
from datetime import timedelta
import antropy as ant
from scipy import stats

# Redam warning yang tidak relevan
warnings.filterwarnings("ignore", message=".*DFA.*")
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


# ==========================================================
# 1. KONFIGURASI GLOBAL
# ==========================================================
BASE_DIR = r"c:\Users\farha\Documents\Tugas Akhir\program\Feature Extraction & Model"

# --- Windowing ---
WINDOW_SIZE_MIN = 5
STEP_SIZE_MIN = 1
TRAIN_SPLIT_MIN = 20

# --- Sampling ---
TARGET_FS = 400
FS_TOLERANCE_HZ = 15

# --- Filter Kualitas Sinyal ---
MIN_QUALITY = 0.50
MIN_PEAKS_PER_WINDOW = 150        # [v3.2] Turun dari 250 → 200 (aman untuk HR 40 bpm)
MIN_BPM_VALID, MAX_BPM_VALID = 40, 180

# --- Filter Validitas NN-Interval (QA Gate) ---
MIN_PCT_VALID_NN = 0.80

# --- Sanity-Check Fisiologis ---
PHYSIO_CHECKS = {
    "HRV_MeanNN":     (333.0, 1500.0),   # 40-180 BPM
    "HRV_SDNN":       (5.0, 500.0),      # ms (normal: 20-200)
    "HRV_RMSSD":      (2.0, 500.0),      # ms (normal: 10-150)
    "HRV_LFHF":       (0.01, 20.0),      # [v3.2] Naik dari 10.0 → 20.0 (LF/HF bisa tinggi saat lelah ekstrem)
    "HRV_DFA_alpha1": (0.3, 1.8),        # eksponen fraktal
    "Ent_Sample":     (0.0, 5.0),        # [v3.2] Naik dari 3.0 → 5.0 (entropy bisa > 3 untuk sinyal kompleks)
}

# --- Label Mapping ---
LABEL_MAP = {
    'A': 'Waspada',
    'B': 'Lelah',
    'C': 'Sangat Lelah'
}

# --- 6 Fitur Survivor ---
SURVIVOR_FEATURES = [
    'HRV_MeanNN',
    'HRV_RMSSD',
    'HRV_SDNN',
    'HRV_LFHF',
    'HRV_DFA_alpha1',
    'Ent_Sample',
]

# --- Kolom Diagnostik ---
DIAGNOSTIC_COLS = ['_n_peaks', '_pct_valid_nn', '_signal_quality', '_polarity', '_peak_method']

# --- Opsi Pipeline ---
ENABLE_SUBJECT_NORMALIZATION = True
ENABLE_IQR_OUTLIER_REMOVAL = True
IQR_FACTOR = 1.5

# [v3.2] Konfigurasi metode peak detection
PRIMARY_PEAK_METHOD = "charlton"     # Metode utama: MSPTDfastv2 (Charlton et al., 2025)
FALLBACK_PEAK_METHOD = "elgendi"     # Fallback jika charlton gagal


# ==========================================================
# 2. AUTO POLARITY CHECK
# ==========================================================
def check_and_fix_polarity(signal, fs, tag=""):
    """
    Deteksi polaritas sinyal PPG terbalik via skewness.
    [v3.2] Guard diperkuat: handle array kosong, array < 3 elemen,
    dan array dengan variance nol.
    """
    sig = np.asarray(signal, dtype=float)
    
    # Guard 1: cek apakah ada nilai non-NaN
    valid_mask = ~np.isnan(sig)
    valid_sig = sig[valid_mask]
    
    if len(valid_sig) < 3:
        return sig, "NORMAL"  # Array terlalu pendek untuk skewness
    
    # Guard 2: cek variance (skewness undefined jika semua nilai sama)
    if np.std(valid_sig) < 1e-8:
        return sig, "NORMAL"
    
    skew = float(stats.skew(valid_sig))
    
    # Sinyal PPG normal: puncak tajam (sistolik) → skewness positif
    if skew < -0.5:
        return -sig, "FLIPPED"
    return sig, "NORMAL"


# ==========================================================
# 3. VALIDASI FISIOLOGIS MULTI-LAYER
# ==========================================================
def validate_features(feat_dict):
    """
    Validasi bahwa setiap fitur berada dalam rentang fisiologis wajar.
    Mengembalikan (is_valid: bool, reason: str).
    """
    for fname, (lo, hi) in PHYSIO_CHECKS.items():
        val = feat_dict.get(fname)
        if val is None:
            return False, f"{fname} = None (ekstraksi gagal)"
        if not np.isfinite(val):
            return False, f"{fname} = {val} (NaN/Inf)"
        if val < lo or val > hi:
            return False, f"{fname} = {val:.4f} di luar [{lo}, {hi}]"
    
    return True, "OK"


# ==========================================================
# 4. FUNGSI EKSTRAKSI FITUR (SATU WINDOW)
# ==========================================================
def extract_features(signal_raw, calculated_fs, verbose=True, tag=""):
    """
    Ekstraksi 6 fitur HRV survivor dari satu window sinyal PPG mentah.
    
    [v3.2] PERUBAHAN KRITIS:
    - Hapus parameter `peak_distance` dari nk.ppg_peaks() saat pakai charlton.
      Algoritma MSPTD (Charlton) TIDAK menggunakan peak_distance — ia memakai
      Local Maxima Scalogram. Memberikan parameter ini menyebabkan error.
    - Tambah fallback otomatis ke "elgendi" jika "charlton" gagal.
    - Kontrol jarak antar puncak dilakukan di QA gate (filter BPM 40-180).
    
    Returns:
        dict fitur + diagnostik, atau None jika window ditolak.
    """
    def log(msg):
        if verbose:
            print(f"   [{tag}] {msg}")
    
    try:
        signal_raw = np.asarray(signal_raw, dtype=float)
        
        # --------------------------------------------------
        # TAHAP 0: Validasi panjang minimum (30 detik)
        # --------------------------------------------------
        if len(signal_raw) < calculated_fs * 30:
            log(f"[TOLAK] Terlalu pendek ({len(signal_raw)} sampel)")
            return None
        
        # --------------------------------------------------
        # TAHAP 1: Resampling (hanya jika perlu)
        # --------------------------------------------------
        if abs(calculated_fs - TARGET_FS) > FS_TOLERANCE_HZ:
            try:
                signal_proc = nk.signal_resample(
                    signal_raw,
                    sampling_rate=calculated_fs,
                    desired_sampling_rate=TARGET_FS,
                    method="interpolation",
                )
                current_fs = TARGET_FS
                log(f"Resampled {calculated_fs:.1f} → {TARGET_FS} Hz")
            except Exception as e:
                log(f"[TOLAK] Resampling gagal: {e}")
                return None
        else:
            signal_proc = signal_raw
            current_fs = calculated_fs
        
        # --------------------------------------------------
        # TAHAP 2: Auto Polarity Check
        # --------------------------------------------------
        signal_proc, polarity = check_and_fix_polarity(signal_proc, current_fs, tag)
        if polarity == "FLIPPED":
            log("Polaritas terdeteksi TERBALIK → di-flip")
        
        # --------------------------------------------------
        # TAHAP 3: Cleaning (Bandpass + filter)
        # Catatan: method="elgendi" di ppg_clean masih valid untuk cleaning,
        # tidak ada kontradiksi dengan ppg_peaks(method="charlton").
        # Cleaning dan peak detection adalah dua langkah terpisah.
        # --------------------------------------------------
        try:
            ppg_cleaned = nk.ppg_clean(
                signal_proc, sampling_rate=current_fs, method="elgendi"
            )
        except Exception as e:
            log(f"[TOLAK] ppg_clean error: {e}")
            return None
        
        if not np.all(np.isfinite(ppg_cleaned)):
            log("[TOLAK] Sinyal mengandung NaN/Inf setelah cleaning")
            return None
        
        if np.std(ppg_cleaned) < 1e-8:
            log("[TOLAK] Sinyal flat (sensor lepas / tidak ada sinyal)")
            return None
        
        # --------------------------------------------------
        # TAHAP 4: Penilaian Kualitas Sinyal
        # --------------------------------------------------
        try:
            quality = nk.ppg_quality(
                ppg_cleaned, sampling_rate=current_fs, method="templatematch"
            )
            avg_quality = float(np.nanmean(quality))
        except Exception:
            avg_quality = 0.0
        
        if avg_quality < MIN_QUALITY:
            log(f"[TOLAK] Kualitas sinyal rendah: {avg_quality:.3f} < {MIN_QUALITY}")
            return None
        
        # --------------------------------------------------
        # TAHAP 5: Deteksi Puncak (METODE CHARLTON / MSPTDfast)
        # 
        # [v3.2] PERUBAHAN KRITIS:
        # - HAPUS parameter `peak_distance` karena TIDAK DIKENALI oleh charlton.
        #   Algoritma MSPTD menggunakan multi-scale analysis, bukan threshold.
        # - Tambah FALLBACK ke "elgendi" jika "charlton" error.
        # - Kontrol jarak antar puncak dilakukan di TAHAP 6 (QA gate BPM).
        # --------------------------------------------------
        peak_method_used = PRIMARY_PEAK_METHOD
        signals_df, info = None, None
        
        # Percobaan 1: metode utama (charlton)
        try:
            signals_df, info = nk.ppg_peaks(
                ppg_cleaned,
                sampling_rate=current_fs,
                method=PRIMARY_PEAK_METHOD,
                correct_artifacts=True,
                # [v3.2] TIDAK ADA peak_distance — charlton tidak pakai ini
            )
            log(f"Peak detection: {PRIMARY_PEAK_METHOD} (MSPTDfastv2) berhasil")
        except Exception as e:
            log(f"[WARNING] Metode '{PRIMARY_PEAK_METHOD}' gagal: {e}")
            log(f"[FALLBACK] Mencoba metode '{FALLBACK_PEAK_METHOD}'...")
            
            # Percobaan 2: fallback ke elgendi
            try:
                signals_df, info = nk.ppg_peaks(
                    ppg_cleaned,
                    sampling_rate=current_fs,
                    method=FALLBACK_PEAK_METHOD,
                    correct_artifacts=True,
                )
                peak_method_used = FALLBACK_PEAK_METHOD
                log(f"Peak detection: {FALLBACK_PEAK_METHOD} (fallback) berhasil")
            except Exception as e2:
                log(f"[TOLAK] Kedua metode gagal. Elgendi error: {e2}")
                return None
        
        # Cari kolom puncak
        peak_col = None
        for cand in ("PPG_Peaks", "PPG_peaks"):
            if cand in signals_df.columns:
                peak_col = cand
                break
        
        if peak_col is None:
            log(f"[TOLAK] Kolom puncak tidak ditemukan di output ppg_peaks")
            return None
        
        peak_locs = np.where(signals_df[peak_col].values == 1)[0]
        
        if len(peak_locs) < MIN_PEAKS_PER_WINDOW:
            log(f"[TOLAK] Puncak terlalu sedikit: {len(peak_locs)} < {MIN_PEAKS_PER_WINDOW}")
            return None
        
        # --------------------------------------------------
        # TAHAP 6: Validasi Fisiologis NN-Interval (QA GATE)
        # 
        # [v3.2] Ini adalah tempat yang BENAR untuk mengontrol jarak
        # antar puncak (menggantikan peak_distance yang tidak valid di charlton).
        # Filter BPM 40-180 secara efektif menolak:
        #   - Detak ganda (BPM > 180 → interval < 333ms)
        #   - Detak terlewat (BPM < 40 → interval > 1500ms)
        # --------------------------------------------------
        nn_intervals_ms = np.diff(peak_locs) / current_fs * 1000.0
        bpm_per_beat = 60000.0 / nn_intervals_ms
        valid_mask = (bpm_per_beat >= MIN_BPM_VALID) & (bpm_per_beat <= MAX_BPM_VALID)
        pct_valid = valid_mask.mean() if len(valid_mask) else 0.0
        
        if pct_valid < MIN_PCT_VALID_NN:
            log(f"[TOLAK] NN valid rendah: {pct_valid*100:.1f}% < {MIN_PCT_VALID_NN*100:.0f}%")
            return None
        
        # Gunakan peak_locs ASLI untuk semua ekstraksi (konsisten)
        peaks_binary = np.zeros(len(ppg_cleaned), dtype=int)
        peaks_binary[peak_locs] = 1
        nn_intervals_for_entropy = nn_intervals_ms
        
        # --------------------------------------------------
        # TAHAP 7: Ekstraksi HRV (Time, Frequency, Non-Linear)
        # --------------------------------------------------
        result = {}
        
        # --- Time Domain ---
        try:
            hrv_time = nk.hrv_time(peaks_binary, sampling_rate=current_fs, show=False)
            for col in ['HRV_MeanNN', 'HRV_SDNN', 'HRV_RMSSD']:
                if col in hrv_time.columns:
                    result[col] = float(hrv_time[col].iloc[0])
        except Exception as e:
            log(f"[WARNING] hrv_time gagal: {e}")
        
        # --- Frequency Domain ---
        try:
            hrv_freq = nk.hrv_frequency(peaks_binary, sampling_rate=current_fs, show=False)
            for col in ['HRV_LFHF']:
                if col in hrv_freq.columns:
                    result[col] = float(hrv_freq[col].iloc[0])
        except Exception as e:
            log(f"[WARNING] hrv_frequency gagal: {e}")
        
        # --- Non-Linear Domain ---
        try:
            hrv_nonlin = nk.hrv_nonlinear(peaks_binary, sampling_rate=current_fs, show=False)
            if 'HRV_DFA_alpha1' in hrv_nonlin.columns:
                val = float(hrv_nonlin['HRV_DFA_alpha1'].iloc[0])
                result['HRV_DFA_alpha1'] = val if np.isfinite(val) else np.nan
        except Exception as e:
            log(f"[WARNING] hrv_nonlinear gagal: {e}")
        
        # --- Sample Entropy (antropy) ---
        try:
            ent = ant.sample_entropy(nn_intervals_for_entropy)
            result['Ent_Sample'] = float(ent) if np.isfinite(ent) else np.nan
        except Exception:
            result['Ent_Sample'] = np.nan
        
        # --------------------------------------------------
        # TAHAP 8: Cek kelengkapan fitur
        # --------------------------------------------------
        missing = [f for f in SURVIVOR_FEATURES if f not in result or not np.isfinite(result.get(f, np.nan))]
        if missing:
            log(f"[TOLAK] Fitur tidak lengkap/tidak valid: {missing}")
            return None
        
        # --------------------------------------------------
        # TAHAP 9: Sanity-Check Fisiologis Multi-Layer
        # --------------------------------------------------
        is_valid, reason = validate_features(result)
        if not is_valid:
            log(f"[TOLAK] Validasi fisiologis: {reason}")
            return None
        
        # --------------------------------------------------
        # TAHAP 10: Metadata Diagnostik
        # --------------------------------------------------
        result['_n_peaks'] = len(peak_locs)
        result['_pct_valid_nn'] = round(pct_valid * 100, 1)
        result['_signal_quality'] = round(avg_quality, 3)
        result['_polarity'] = polarity
        result['_peak_method'] = peak_method_used  # [v3.2] Catat metode yang dipakai
        
        return result
    
    except Exception as e:
        log(f"[ERROR FATAL] {type(e).__name__}: {e}")
        if verbose:
            traceback.print_exc()
        return None


# ==========================================================
# 5. PROSES PER FILE (WINDOWING + SPLIT TRAIN/TEST)
# ==========================================================
def process_file(filepath, label):
    """
    Membaca satu file CSV subjek, melakukan windowing, ekstraksi fitur,
    dan memisahkan menjadi train (20 menit pertama) dan test (sisanya).
    """
    filename = os.path.basename(filepath)
    print(f"\n{'='*60}")
    print(f"Processing: {filename} ({label})")
    print(f"{'='*60}")
    
    # --- Baca & urutkan data ---
    df = pd.read_csv(filepath)
    df["datetime_pc"] = pd.to_datetime(df["datetime_pc"])
    df = df.sort_values("datetime_pc").reset_index(drop=True)
    
    # --- Hitung sampling rate ---
    duration_sec = (df["datetime_pc"].iloc[-1] - df["datetime_pc"].iloc[0]).total_seconds()
    if duration_sec <= 0:
        print(f"   [ERROR] Durasi file <= 0 detik. Skip.")
        return pd.DataFrame(), pd.DataFrame(), 0, 0
    
    calculated_fs = len(df) / duration_sec
    print(f"   FS: {calculated_fs:.2f} Hz | Durasi: {duration_sec/60:.1f} min | Sampel: {len(df)}")
    print(f"   Peak method: {PRIMARY_PEAK_METHOD} (fallback: {FALLBACK_PEAK_METHOD})")
    
    # --- Split train/test berdasarkan waktu ---
    start_time = df["datetime_pc"].iloc[0]
    split_time = start_time + timedelta(minutes=TRAIN_SPLIT_MIN)
    df_train = df[df["datetime_pc"] < split_time].copy()
    df_test = df[df["datetime_pc"] >= split_time].copy()
    
    def windowing(data, set_type):
        features_list = []
        total_windows = 0
        failed_windows = 0
        
        if data.empty or len(data) < 2:
            return pd.DataFrame(), 0, 0
        
        current_start = data["datetime_pc"].iloc[0]
        end_time = data["datetime_pc"].iloc[-1]
        
        while current_start + timedelta(minutes=WINDOW_SIZE_MIN) <= end_time:
            current_end = current_start + timedelta(minutes=WINDOW_SIZE_MIN)
            window_data = data[
                (data["datetime_pc"] >= current_start) &
                (data["datetime_pc"] < current_end)
            ]
            total_windows += 1
            
            tag = f"{set_type} #{total_windows} {current_start.strftime('%H:%M:%S')}"
            feat = extract_features(
                window_data["green"].values,
                calculated_fs,
                verbose=False,
                tag=tag,
            )
            
            if feat:
                feat["label"] = label
                feat["set"] = set_type
                features_list.append(feat)
            else:
                failed_windows += 1
            
            current_start += timedelta(minutes=STEP_SIZE_MIN)
        
        return pd.DataFrame(features_list), total_windows, failed_windows
    
    train_features, train_tot, train_fail = windowing(df_train, "train")
    test_features, test_tot, test_fail = windowing(df_test, "test")
    
    success = train_tot + test_tot - train_fail - test_fail
    total = train_tot + test_tot
    print(f"   ✓ Berhasil: {success}/{total} window "
          f"(train: {len(train_features)}, test: {len(test_features)})")
    
    return train_features, test_features, total, train_fail + test_fail


# ==========================================================
# 6. NORMALISASI SUBJEK-SPESIFIK (Z-SCORE)
# ==========================================================
def normalize_subject_wise(df):
    """
    Normalisasi Z-score per subjek, menggunakan fase 'Waspada' sebagai baseline.
    Rumus: Z = (nilai - mean_baseline) / std_baseline
    """
    if not ENABLE_SUBJECT_NORMALIZATION:
        return df
    
    print("\n[STEP] Normalisasi subjek-spesifik (baseline: Waspada)...")
    normalized_dfs = []
    skipped_subjects = []
    
    for subject_id, group in df.groupby("subject"):
        baseline = group[group["label"] == "Waspada"]
        
        if len(baseline) < 3:
            skipped_subjects.append(subject_id)
            normalized_dfs.append(group)
            continue
        
        normalized_group = group.copy()
        
        for col in SURVIVOR_FEATURES:
            if col not in group.columns:
                continue
            
            mean_val = baseline[col].mean()
            std_val = baseline[col].std()
            
            if std_val > 1e-8 and np.isfinite(mean_val) and np.isfinite(std_val):
                normalized_group[col] = (group[col] - mean_val) / std_val
            else:
                # Fallback: Min-Max scaling jika std = 0
                min_val = baseline[col].min()
                max_val = baseline[col].max()
                rng = max_val - min_val
                if rng > 1e-8:
                    normalized_group[col] = (group[col] - min_val) / rng
                else:
                    normalized_group[col] = 0.0
        
        normalized_dfs.append(normalized_group)
    
    if skipped_subjects:
        print(f"   [WARNING] Subjek tanpa baseline cukup (skip normalisasi): {skipped_subjects}")
    
    return pd.concat(normalized_dfs, ignore_index=True)


# ==========================================================
# 7. FILTER OUTLIER IQR
# ==========================================================
def remove_iqr_outliers(df, factor=IQR_FACTOR):
    """Hapus baris yang memiliki outlier ekstrem pada fitur apapun."""
    if not ENABLE_IQR_OUTLIER_REMOVAL:
        return df
    
    print("\n[STEP] Filter outlier IQR...")
    initial_len = len(df)
    mask = pd.Series(True, index=df.index)
    
    for col in SURVIVOR_FEATURES:
        if col not in df.columns:
            continue
        
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        
        lower = Q1 - factor * IQR
        upper = Q3 + factor * IQR
        
        col_ok = (df[col] >= lower) & (df[col] <= upper) | df[col].isna()
        mask = mask & col_ok
    
    df_filtered = df[mask].copy()
    removed = initial_len - len(df_filtered)
    print(f"   Outlier dihapus: {removed} baris ({removed/max(initial_len,1)*100:.1f}%)")
    
    return df_filtered


# ==========================================================
# 8. STATISTIK QA
# ==========================================================
def print_qa_statistics(df, set_name):
    """Cetak ringkasan QA dataset."""
    print(f"\n{'─'*60}")
    print(f"  STATISTIK QA — {set_name}")
    print(f"{'─'*60}")
    print(f"  Total baris     : {len(df)}")
    print(f"  Subjek unik     : {df['subject'].nunique()}")
    print(f"  Distribusi label:")
    for label, count in df['label'].value_counts().items():
        pct = count / max(len(df), 1) * 100
        print(f"    {label:16s}: {count:4d} ({pct:.1f}%)")
    
    # [v3.2] Statistik metode peak detection yang terpakai
    if '_peak_method' in df.columns:
        print(f"\n  Distribusi metode peak detection:")
        for method, count in df['_peak_method'].value_counts().items():
            pct = count / max(len(df), 1) * 100
            print(f"    {method:16s}: {count:4d} ({pct:.1f}%)")
    
    print(f"\n  {'Fitur':<20s} {'Mean':>10s} {'Std':>10s} {'Min':>10s} {'Max':>10s} {'Null%':>7s}")
    print(f"  {'-'*67}")
    
    for col in SURVIVOR_FEATURES:
        if col not in df.columns:
            continue
        mean_v = df[col].mean()
        std_v = df[col].std()
        min_v = df[col].min()
        max_v = df[col].max()
        null_pct = df[col].isna().mean() * 100
        print(f"  {col:<20s} {mean_v:>10.4f} {std_v:>10.4f} {min_v:>10.4f} {max_v:>10.4f} {null_pct:>6.1f}%")
    
    # Cek keseimbangan kelas
    label_counts = df['label'].value_counts()
    if len(label_counts) >= 2:
        ratio = label_counts.max() / max(label_counts.min(), 1)
        if ratio > 3.0:
            print(f"\n  [WARNING] Imbalance kelas tinggi (rasio {ratio:.1f}x). "
                  f"Pertimbangkan class_weight atau oversampling saat training.")


# ==========================================================
# 9. DROP DIAGNOSTIC COLUMNS
# ==========================================================
def drop_diagnostic_columns(df):
    """Hapus kolom diagnostik yang tidak diperlukan untuk training."""
    cols_to_drop = [c for c in DIAGNOSTIC_COLS if c in df.columns]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
    return df


# ==========================================================
# 10. MAIN FUNCTION
# ==========================================================
def main():
    print("=" * 60)
    print("EKSTRAKSI FITUR HRV — v3.2 (Critical Bug Fix)")
    print(f"Peak method: {PRIMARY_PEAK_METHOD} → fallback: {FALLBACK_PEAK_METHOD}")
    print("=" * 60)
    
    all_train, all_test = [], []
    report_data = []
    
    # --- Cari semua file subjek ---
    search_pattern = os.path.join(BASE_DIR, "S*.csv")
    file_list = sorted(glob.glob(search_pattern))
    
    if not file_list:
        print(f"\n[ERROR] Tidak ada file CSV (S*.csv) di:\n  {BASE_DIR}")
        return
    
    print(f"\nDitemukan {len(file_list)} file:")
    for f in file_list:
        print(f"  • {os.path.basename(f)}")
    
    # --- Proses setiap file ---
    for filepath in file_list:
        filename = os.path.basename(filepath)
        
        # Parse subject_id dan label dari nama file
        try:
            subject_id = filename.split("_")[0]
            suffix = filename.split(".")[0].split("_")[-1]
        except (ValueError, IndexError):
            print(f"\n[SKIP] Nama file tidak sesuai format: {filename}")
            continue
        
        if suffix not in LABEL_MAP:
            print(f"\n[SKIP] Label '{suffix}' tidak dikenal: {filename}")
            continue
        
        label = LABEL_MAP[suffix]
        train_df, test_df, total_win, fail_win = process_file(filepath, label)
        
        fail_rate = (fail_win / total_win * 100) if total_win > 0 else 0
        report_data.append({
            "Subjek": subject_id,
            "Kondisi": label,
            "File": filename,
            "Total Window": total_win,
            "Window Rusak": fail_win,
            "Persentase Rusak (%)": round(fail_rate, 2),
        })
        
        if not train_df.empty:
            train_df.insert(0, "subject", subject_id)
        if not test_df.empty:
            test_df.insert(0, "subject", subject_id)
        
        all_train.append(train_df)
        all_test.append(test_df)
    
    # --- Gabungkan semua data ---
    df_train = pd.concat(all_train, ignore_index=True) if all_train else pd.DataFrame()
    df_test = pd.concat(all_test, ignore_index=True) if all_test else pd.DataFrame()
    
    if df_train.empty:
        print("\n[CRITICAL] Data latih KOSONG! Periksa log [TOLAK] di atas.")
        return
    if df_test.empty:
        print("\n[CRITICAL] Data uji KOSONG! Periksa log [TOLAK] di atas.")
        return
    
    print(f"\n\n{'='*60}")
    print("POST-PROCESSING")
    print(f"{'='*60}")
    
    # --- Normalisasi Subjek-Spesifik ---
    df_train = normalize_subject_wise(df_train)
    df_test = normalize_subject_wise(df_test)
    
    # --- Filter Outlier IQR ---
    df_train = remove_iqr_outliers(df_train)
    df_test = remove_iqr_outliers(df_test)
    
    # --- Drop kolom diagnostik ---
    df_train = drop_diagnostic_columns(df_train)
    df_test = drop_diagnostic_columns(df_test)
    
    # --- Pastikan hanya kolom yang diperlukan yang tersisa ---
    keep_cols = ["subject", "label", "set"] + SURVIVOR_FEATURES
    keep_cols_train = [c for c in keep_cols if c in df_train.columns]
    keep_cols_test = [c for c in keep_cols if c in df_test.columns]
    df_train = df_train[keep_cols_train]
    df_test = df_test[keep_cols_test]
    
    # --- QA Statistics ---
    print_qa_statistics(df_train, "TRAIN")
    print_qa_statistics(df_test, "TEST")
    
    # --- Simpan ---
    output_train = os.path.join(BASE_DIR, "Train_Features_Filtered.csv")
    output_test = os.path.join(BASE_DIR, "Test_Features_Filtered.csv")
    
    df_train.to_csv(output_train, index=False)
    df_test.to_csv(output_test, index=False)
    
    print(f"\n{'='*60}")
    print("PROSES SELESAI")
    print(f"{'='*60}")
    print(f"Train: {len(df_train)} baris × {len(SURVIVOR_FEATURES)} fitur → {output_train}")
    print(f"Test : {len(df_test)} baris × {len(SURVIVOR_FEATURES)} fitur → {output_test}")
    
    # --- Laporan Kerusakan ---
    if report_data:
        report_df = pd.DataFrame(report_data).sort_values(
            by="Persentase Rusak (%)", ascending=False
        )
        total_win = report_df["Total Window"].sum()
        total_fail = report_df["Window Rusak"].sum()
        overall_rate = (total_fail / max(total_win, 1)) * 100
        
        print(f"\n{'='*60}")
        print("LAPORAN KERUSAKAN PER SUBJEK")
        print(f"{'='*60}")
        print(report_df.to_string(index=False))
        print(f"\nTOTAL WINDOW : {total_win}")
        print(f"TOTAL DIBUANG: {total_fail}")
        print(f"RATA-RATA RUSAK: {overall_rate:.2f}%")
        
        if overall_rate > 30:
            print(f"\n[WARNING] Tingkat kerusakan tinggi ({overall_rate:.1f}%).")
            print("  Periksa: (1) Pemasangan sensor, (2) Gerak subjek, (3) Firmware ESP32")


if __name__ == "__main__":
    main()