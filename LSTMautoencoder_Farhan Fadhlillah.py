"""
LSTM DENOISING AUTOENCODER — UNSUPERVISED CLASSIFICATION
Klasifikasi 3 Tingkat Kelelahan (Waspada / Lelah / Sangat Lelah)
Berdasarkan Fitur HRV dari Sinyal PPG

SINKRONISASI DENGAN Feature_ExtractionV3.py (v3.2):
✅ Data SUDAH dinormalisasi Z-score per subjek (baseline = Waspada)
✅ Data SUDAH difilter outlier IQR
✅ Null% = 0% → SimpleImputer TIDAK DIPERLUKAN (dihapus)
✅ RobustScaler TIDAK DIPERLUKAN (double scaling merusak distribusi)
✅ Filter subjek TANPA BASELINE dideteksi DINAMIS dari CSV
✅ Urutan fitur DIJAMIN konsisten dengan SURVIVOR_FEATURES di v3.2

PENDEKATAN:
LSTM Autoencoder dilatih MURNI unsupervised (loss = MSE rekonstruksi)
Representasi laten (bottleneck, dim=12) diekstrak
Clustering (KMeans/GMM) di ruang laten → 3 kelompok
Label asli HANYA untuk alignment (Hungarian algorithm) & evaluasi

PRASYARAT INSTALASI:
pip install tensorflow scikit-learn pandas numpy matplotlib seaborn
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import warnings

from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import (
    confusion_matrix, classification_report,
    adjusted_rand_score, normalized_mutual_info_score, silhouette_score
)
from sklearn.manifold import TSNE
from scipy.optimize import linear_sum_assignment

from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, LSTM, RepeatVector, Dense, Dropout,
    BatchNormalization, GaussianNoise
)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
import tensorflow as tf

# ============================================================================
# 0. REPRODUCIBILITY
# ============================================================================
SEED = 42
np.random.seed(SEED)
tf.random.set_seed(SEED)
# Redam warning yang tidak relevan agar log bersih
warnings.filterwarnings("ignore", message=".*DFA_alpha2.*")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ============================================================================
# 1. KONFIGURASI GLOBAL (SINKRON DENGAN Feature_ExtractionV3.py v3.2)
# ============================================================================
BASE_DIR = r"c:\Users\farha\Documents\Tugas Akhir\program\Feature Extraction & Model"

# [ATURAN 4] Urutan fitur HARUS SAMA persis dengan SURVIVOR_FEATURES di v3.2
SURVIVOR_FEATURES = [
    'HRV_MeanNN',
    'HRV_RMSSD',
    'HRV_SDNN',
    'HRV_LFHF',
    'HRV_DFA_alpha1',
    'Ent_Sample',
]

# [ATURAN 2] Label mapping EKSPLISIT (tidak bergantung pada LabelEncoder)
LABEL_MAP = {
    'Waspada': 0,
    'Lelah': 1,
    'Sangat Lelah': 2,
}
LABEL_NAMES = {v: k for k, v in LABEL_MAP.items()}  # {0: 'Waspada', 1: 'Lelah', 2: 'Sangat Lelah'}
N_CLASSES = len(LABEL_MAP)

# Arsitektur LSTM Autoencoder
SEQ_LENGTH = 4           # 3 timestep berturut-turut
LSTM_UNITS_1 = 64        # Kapasitas encoder layer 1
LATENT_DIM = 8          # Dimensi bottleneck (ruang laten)
DENOISING_STD = 0.15     # Std Gaussian noise (denoising autoencoder)
LEARNING_RATE_AE = 0.001
BATCH_SIZE = 16
EPOCHS = 200
PATIENCE = 20
N_CLUSTERS = N_CLASSES   # 3 cluster = 3 tingkat kelelahan
MIN_BASELINE_WINDOWS = 3 # Minimum window Waspada agar subjek tidak di-skip

# ============================================================================
# 2. FUNGSI DETEKSI SUBJEK TANPA BASELINE (DINAMIS)
# ============================================================================
def detect_subjects_without_baseline(df, min_windows=MIN_BASELINE_WINDOWS):
    """
    [ATURAN 3] Deteksi DINAMIS subjek yang tidak memiliki baseline Waspada cukup.
    Menghindari hardcoding daftar subjek yang di-skip.
    """
    subjects_to_skip = []
    for subject in df['subject'].unique():
        baseline_count = len(df[
            (df['subject'] == subject) & 
            (df['label'] == 'Waspada')
        ])
        if baseline_count < min_windows:
            subjects_to_skip.append(subject)
    return sorted(subjects_to_skip)

# ============================================================================
# 3. PERSIAPAN DATA (SINKRON DENGAN Feature_ExtractionV3.py v3.2)
# ============================================================================
print("=" * 70)
print("MEMUAT DAN MEMPROSES DATA...")
print("=" * 70)

train_path = os.path.join(BASE_DIR, "Train_Features_Filtered.csv")
test_path = os.path.join(BASE_DIR, "Test_Features_Filtered.csv")

# Cek file ada
for path in [train_path, test_path]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File tidak ditemukan: {path}")

train_df = pd.read_csv(train_path)
test_df = pd.read_csv(test_path)

print(f"[INFO] Train loaded: {train_df.shape[0]} baris × {train_df.shape[1]} kolom")
print(f"[INFO] Test  loaded: {test_df.shape[0]} baris × {test_df.shape[1]} kolom")

# Verifikasi fitur survivor ada di CSV
missing_features = [f for f in SURVIVOR_FEATURES if f not in train_df.columns]
if missing_features:
    raise ValueError(f"Fitur survivor tidak lengkap di CSV: {missing_features}\nPastikan Feature_ExtractionV3.py v3.2 sudah dijalankan dengan benar.")

# [ATURAN 3] Deteksi dinamis subjek tanpa baseline
print(f"\n[INFO] Mendeteksi subjek tanpa baseline Waspada cukup (min {MIN_BASELINE_WINDOWS} window)...")
skip_train = detect_subjects_without_baseline(train_df)
skip_test = detect_subjects_without_baseline(test_df)
print(f"  Train di-skip ({len(skip_train)}): {skip_train}")
print(f"  Test  di-skip ({len(skip_test)}): {skip_test}")

# Filter subjek tanpa baseline
if skip_train:
    train_df = train_df[~train_df['subject'].isin(skip_train)].copy()
if skip_test:
    test_df = test_df[~test_df['subject'].isin(skip_test)].copy()
print(f"[INFO] Setelah filter → Train: {len(train_df)} baris, Test: {len(test_df)} baris")

# [PERBAIKAN BUG 4] Handle infinity (jaga-jaga)
for name, df in [('TRAIN', train_df), ('TEST', test_df)]:
    inf_mask = np.isinf(df[SURVIVOR_FEATURES].values)
    if inf_mask.sum() > 0:
        print(f"[PERINGATAN] {name}: {inf_mask.sum()} nilai infinity → dikonversi ke NaN")
        df[SURVIVOR_FEATURES] = df[SURVIVOR_FEATURES].replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=SURVIVOR_FEATURES)

# [ATURAN 2] Encode label EKSPLISIT (tidak pakai LabelEncoder)
for name, df in [('TRAIN', train_df), ('TEST', test_df)]:
    unknown_labels = set(df['label'].unique()) - set(LABEL_MAP.keys())
    if unknown_labels:
        raise ValueError(f"{name}: Label tidak dikenal: {unknown_labels}")
    df['label_encoded'] = df['label'].map(LABEL_MAP)
print(f"[INFO] Mapping label: {LABEL_MAP}")

# [ATURAN 1] TIDAK ADA SCALING
# Komentar WHY: Data sudah Z-score normalized di Feature Extraction v3.2. 
# Melakukan scaling ulang (RobustScaler/MinMax) akan merusak distribusi data (double scaling).
print(f"\n[INFO] ✅ TIDAK ada scaling ulang (data sudah Z-score normalized di v3.2)")
print(f"[INFO] Rentang data train (seharusnya mean≈0, std≈1):")
for col in SURVIVOR_FEATURES:
    print(f"  {col}: mean={train_df[col].mean():+.3f}, std={train_df[col].std():.3f}")

# ============================================================================
# 4. PEMBUATAN SEQUENCE (DENGAN FIX TYPEERROR)
# ============================================================================
def create_sequences(df, features, seq_len, label_col='label_encoded',
                     group_cols=('subject', 'label'), dataset_name="dataset"):
    """
    Membuat sequence temporal dari DataFrame.
    Group by (subject, label) → sliding window dengan step=1.
    """
    X, y, groups_meta = [], [], []
    skipped = []
    
    for key, group in df.groupby(list(group_cols)):
        group_sorted = group.sort_index()
        data_x = group_sorted[features].values
        data_y = group_sorted[label_col].values
        
        if len(data_x) < seq_len:
            skipped.append((key, len(data_x)))
            continue
        
        for i in range(len(data_x) - seq_len + 1):
            X.append(data_x[i: i + seq_len])
            y.append(data_y[i + seq_len - 1])
            groups_meta.append(key)
            
    if skipped:
        print(f"\n[PERINGATAN] {dataset_name}: {len(skipped)} grup dilewati (< {seq_len} baris):")
        # [PERBAIKAN BUG 2] Print langsung key tanpa indexing ke label_encoder.classes_
        # karena 'lbl' dari groupby key adalah string (misal: 'Waspada'), bukan integer.
        for (subj, lbl), n in skipped:
            print(f"   - subject={subj}, label={lbl}: {n} baris")
            
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32), groups_meta

print(f"\n{'='*70}")
print(f"MEMBENTUK SEQUENCE (SEQ_LENGTH={SEQ_LENGTH})...")
print(f"{'='*70}")

X_train, y_train_true, train_groups = create_sequences(
    train_df, SURVIVOR_FEATURES, SEQ_LENGTH, dataset_name="TRAIN"
)
X_test, y_test_true, test_groups = create_sequences(
    test_df, SURVIVOR_FEATURES, SEQ_LENGTH, dataset_name="TEST"
)

if X_train.shape[0] == 0 or X_test.shape[0] == 0:
    raise RuntimeError("Hasil sequencing kosong — cek SEQ_LENGTH vs jumlah baris per grup.\n" f"Train: {X_train.shape}, Test: {X_test.shape}")

timesteps = X_train.shape[1]
n_features = X_train.shape[2]
print(f"[INFO] Bentuk Input Train: {X_train.shape} | Test: {X_test.shape}")
print(f"       (samples, timesteps={timesteps}, features={n_features})")

# Cek coverage subjek di test
test_subjects = sorted(set(g[0] for g in test_groups))
missing_subjects = sorted(set(test_df['subject'].unique()) - set(test_subjects))
if missing_subjects:
    print(f"[PERHATIAN] Subjek tidak tercakup di test: {missing_subjects}")
else:
    print(f"[INFO] Semua subjek test tercakup ({len(test_subjects)} subjek)")

# ============================================================================
# 5. ARSITEKTUR LSTM DENOISING AUTOENCODER
# ============================================================================
print(f"\n{'='*70}")
print("MEMBANGUN LSTM DENOISING AUTOENCODER...")
print(f"{'='*70}")

# Input layer
inputs = Input(shape=(timesteps, n_features), name="Input_Layer")

# Denoising: Gaussian noise HANYA aktif saat training
noisy_inputs = GaussianNoise(DENOISING_STD, name="Denoising_Noise")(inputs)

# Encoder
enc_1 = LSTM(LSTM_UNITS_1, activation='tanh', return_sequences=True, name="Enc_LSTM_1")(noisy_inputs)
enc_1 = BatchNormalization(name="Enc_BN_1")(enc_1)
enc_1 = Dropout(0.2, name="Enc_Dropout_1")(enc_1)

# Bottleneck (ruang laten)
latent = LSTM(LATENT_DIM, activation='tanh', return_sequences=False, name="Latent_Bottleneck")(enc_1)

# Decoder: ulangi vektor laten
bottleneck_repeated = RepeatVector(timesteps, name="Repeat_Latent")(latent)

dec_1 = LSTM(LATENT_DIM, activation='tanh', return_sequences=True, name="Dec_LSTM_1")(bottleneck_repeated)
dec_1 = BatchNormalization(name="Dec_BN_1")(dec_1)
dec_2 = LSTM(LSTM_UNITS_1, activation='tanh', return_sequences=True, name="Dec_LSTM_2")(dec_1)

# Output: rekonstruksi fitur
outputs = Dense(n_features, name="Reconstruction_Output")(dec_2)

# Build model autoencoder dan encoder terpisah
autoencoder = Model(inputs, outputs, name="LSTM_Denoising_Autoencoder")
encoder = Model(inputs, latent, name="Encoder_Only")

autoencoder.compile(
    optimizer=Adam(learning_rate=LEARNING_RATE_AE),
    loss='mse',
    metrics=['mae']
)

print("\n[ARSITEKTUR AUTOENCODER]")
autoencoder.summary(print_fn=lambda x: print(f"  {x}") if 'Total params' not in x else None)

# Callbacks
early_stop = EarlyStopping(
    monitor='val_loss', patience=PATIENCE,
    restore_best_weights=True, verbose=1
)
reduce_lr = ReduceLROnPlateau(
    monitor='val_loss', factor=0.5,
    patience=8, min_lr=1e-6, verbose=1
)

# Shuffle sebelum training agar validation_split representatif
shuffle_idx = np.random.RandomState(SEED).permutation(len(X_train))
X_train_shuffled = X_train[shuffle_idx]

# ============================================================================
# 6. TRAINING (UNSUPERVISED MURNI)
# ============================================================================
print(f"\n{'='*70}")
print("MELATIH AUTOENCODER (TANPA MELIHAT LABEL)...")
print(f"{'='*70}")

history = autoencoder.fit(
    X_train_shuffled, X_train_shuffled,  # input = output (rekonstruksi)
    epochs=EPOCHS,
    batch_size=BATCH_SIZE,
    validation_split=0.2,
    callbacks=[early_stop, reduce_lr],
    verbose=1
)

n_epochs_trained = len(history.history['loss'])
best_val_loss = min(history.history['val_loss'])
print(f"\n[INFO] Training selesai di epoch {n_epochs_trained}/{EPOCHS}")
print(f"[INFO] Best validation loss: {best_val_loss:.6f}")

# ============================================================================
# 7. EKSTRAKSI REPRESENTASI LATEN
# ============================================================================
print(f"\n{'='*70}")
print("MENGEKSTRAK REPRESENTASI LATEN...")
print(f"{'='*70}")

# Encoder.predict otomatis menonaktifkan GaussianNoise (training=False)
Z_train = encoder.predict(X_train, verbose=0)
Z_test = encoder.predict(X_test, verbose=0)

print(f"[INFO] Bentuk laten train: {Z_train.shape} | test: {Z_test.shape}")
print(f"       (samples, LATENT_DIM={LATENT_DIM})")

# ============================================================================
# 8. CLUSTERING DI RUANG LATEN (TIDAK MENGGUNAKAN LABEL)
# ============================================================================
print(f"\n{'='*70}")
print(f"CLUSTERING LATEN MENJADI {N_CLUSTERS} KELOMPOK...")
print(f"{'='*70}")

# KMeans
kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=SEED, n_init=20)
cluster_train_kmeans = kmeans.fit_predict(Z_train)
cluster_test_kmeans = kmeans.predict(Z_test)

# GMM
gmm = GaussianMixture(
    n_components=N_CLUSTERS, random_state=SEED,
    n_init=10, covariance_type='full'
)
cluster_train_gmm = gmm.fit_predict(Z_train)
cluster_test_gmm = gmm.predict(Z_test)

# Silhouette score (evaluasi internal, tanpa label)
sil_kmeans = silhouette_score(Z_train, cluster_train_kmeans)
sil_gmm = silhouette_score(Z_train, cluster_train_gmm)

print(f"\n[INFO] Silhouette score (internal, train):")
print(f"  KMeans: {sil_kmeans:.4f}")
print(f"  GMM   : {sil_gmm:.4f}")
print(f"  (mendekati 1 = cluster rapat & terpisah)")

# Pilih metode terbaik
if sil_gmm >= sil_kmeans:
    chosen_name = "GMM"
    cluster_train, cluster_test = cluster_train_gmm, cluster_test_gmm
else:
    chosen_name = "KMeans"
    cluster_train, cluster_test = cluster_train_kmeans, cluster_test_kmeans

print(f"\n[INFO] Metode terpilih: {chosen_name}")

# ============================================================================
# 9. EVALUASI: ALIGNMENT CLUSTER → LABEL (Hungarian Algorithm)
# ============================================================================
print(f"\n{'='*70}")
print("EVALUASI: ALIGNMENT CLUSTER → LABEL...")
print(f"{'='*70}")

def align_clusters_to_labels(y_true, cluster_pred, n_classes):
    """
    Hungarian algorithm untuk mencari pemetaan optimal cluster → label.
    """
    cm = confusion_matrix(y_true, cluster_pred, labels=list(range(n_classes)))
    row_ind, col_ind = linear_sum_assignment(-cm)  # maksimalkan kecocokan
    mapping = {col: row for row, col in zip(row_ind, col_ind)}
    aligned_pred = np.array([mapping.get(c, c) for c in cluster_pred])
    return aligned_pred, mapping

y_test_aligned, cluster_to_label_map = align_clusters_to_labels(
    y_test_true, cluster_test, N_CLASSES
)

print(f"\n[INFO] Pemetaan cluster → label:")
for cluster_id, true_label in sorted(cluster_to_label_map.items()):
    print(f"  Cluster {cluster_id} → {LABEL_NAMES[true_label]}")

# Metrik evaluasi
accuracy = np.mean(y_test_aligned == y_test_true) * 100
ari = adjusted_rand_score(y_test_true, cluster_test)
nmi = normalized_mutual_info_score(y_test_true, cluster_test)

print(f"\n{'─'*70}")
print(f"  HASIL EVALUASI — Metode: {chosen_name}")
print(f"{'─'*70}")
print(f"  Accuracy (setelah alignment) : {accuracy:.2f}%")
print(f"  Adjusted Rand Index (ARI)    : {ari:.4f}  (1.0 = sempurna, 0.0 = acak)")
print(f"  Normalized Mutual Info (NMI) : {nmi:.4f}  (1.0 = sempurna, 0.0 = tidak ada info)")
print(f"{'─'*70}")

# Interpretasi ARI
print(f"\n[INTERPRETASI ARI]:")
if ari >= 0.7:
    print(f"  ARI = {ari:.4f} → Clustering SANGAT BAIK")
elif ari >= 0.4:
    print(f"  ARI = {ari:.4f} → Clustering BAIK")
elif ari >= 0.1:
    print(f"  ARI = {ari:.4f} → Clustering SEDANG")
else:
    print(f"  ARI = {ari:.4f} → Clustering BURUK (hampir setara acak)")
    print(f"  Kemungkinan penyebab:")
    print(f"    (a) Kelelahan adalah spektrum gradual, bukan cluster alami")
    print(f"    (b) Dataset terlalu kecil untuk unsupervised clustering stabil")
    print(f"    (c) Pertimbangkan supervised learning (LSTM Classifier) untuk hasil lebih baik")

# Classification report
print(f"\n[CLASSIFICATION REPORT] (setelah alignment):")
print(classification_report(
    y_test_true, y_test_aligned,
    labels=list(range(N_CLASSES)),
    target_names=list(LABEL_NAMES.values()),
    zero_division=0
))

# ============================================================================
# 10. VISUALISASI
# ============================================================================
print(f"\n{'='*70}")
print("VISUALISASI...")
print(f"{'='*70}")

sns.set_theme(style="whitegrid", font_scale=1.1)
kelas_target = list(LABEL_NAMES.values())

# 1. Kurva Loss & MAE
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
axes[0].plot(history.history['loss'], label='Train Loss (MSE)', linewidth=2)
axes[0].plot(history.history['val_loss'], label='Val Loss (MSE)', linewidth=2)
axes[0].set_title('Reconstruction Loss — LSTM Denoising Autoencoder', fontsize=13)
axes[0].set_xlabel('Epoch', fontsize=11)
axes[0].set_ylabel('MSE', fontsize=11)
axes[0].legend(fontsize=10)
axes[0].grid(True, alpha=0.3)

# [PERBAIKAN BUG 1] Typo Plotting: Pastikan menggunakan 'val_mae', BUKAN 'val*_mae'
axes[1].plot(history.history['mae'], label='Train MAE', linewidth=2)
axes[1].plot(history.history['val_mae'], label='Val MAE', linewidth=2)
axes[1].set_title('Mean Absolute Error', fontsize=13)
axes[1].set_xlabel('Epoch', fontsize=11)
axes[1].set_ylabel('MAE', fontsize=11)
axes[1].legend(fontsize=10)
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, "training_history.png"), dpi=150, bbox_inches='tight')
plt.show()

# 2. Confusion Matrix
plt.figure(figsize=(7, 6))
cm = confusion_matrix(
    y_test_true, y_test_aligned,
    labels=list(range(N_CLASSES))
)
sns.heatmap(
    cm, annot=True, fmt='d', cmap='Blues',
    xticklabels=kelas_target, yticklabels=kelas_target
)
plt.title(f'Confusion Matrix: {chosen_name} (setelah Hungarian Alignment)', fontsize=12)
plt.ylabel('Ground Truth', fontsize=11)
plt.xlabel('Cluster Prediction', fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, "confusion_matrix.png"), dpi=150, bbox_inches='tight')
plt.show()

# 3. t-SNE di Ruang Laten
n_test_samples = Z_test.shape[0]
safe_perplexity = min(30, max(2, n_test_samples - 1))

if n_test_samples >= 4:
    tsne = TSNE(
        n_components=2, random_state=SEED,
        perplexity=safe_perplexity, init='pca', learning_rate='auto'
    )
    Z_tsne = tsne.fit_transform(Z_test)
    
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    
    # Subplot 1: Ground Truth
    scatter1 = axes[0].scatter(
        Z_tsne[:, 0], Z_tsne[:, 1],
        c=y_test_true, cmap='viridis', alpha=0.7, edgecolors='k', linewidth=0.5
    )
    axes[0].set_title('t-SNE Ruang Laten — Ground Truth', fontsize=12)
    axes[0].set_xlabel('t-SNE Dim 1')
    axes[0].set_ylabel('t-SNE Dim 2')
    
    # [PERBAIKAN BUG 3] Error Legend t-SNE: Jangan campur positional *args dengan keyword labels=
    handles1, _ = scatter1.legend_elements()
    legend1 = axes[0].legend(handles1, kelas_target, title="Kondisi")
    axes[0].add_artist(legend1)
    
    # Subplot 2: Cluster Prediction
    scatter2 = axes[1].scatter(
        Z_tsne[:, 0], Z_tsne[:, 1],
        c=cluster_test, cmap='tab10', alpha=0.7, edgecolors='k', linewidth=0.5
    )
    axes[1].set_title(f't-SNE Ruang Laten — {chosen_name} Clusters', fontsize=12)
    axes[1].set_xlabel('t-SNE Dim 1')
    axes[1].set_ylabel('t-SNE Dim 2')
    
    handles2, _ = scatter2.legend_elements()
    legend2 = axes[1].legend(
        handles2,
        [f'Cluster {i}' for i in range(N_CLUSTERS)],
        title="Cluster"
    )
    axes[1].add_artist(legend2)
    
    plt.tight_layout()
    plt.savefig(os.path.join(BASE_DIR, "tsne_latent_space.png"), dpi=150, bbox_inches='tight')
    plt.show()
else:
    print("[INFO] Sampel test terlalu sedikit untuk t-SNE — dilewati")

# 4. Distribusi Reconstruction Error
X_test_pred = autoencoder.predict(X_test, verbose=0)
test_mse = np.mean(np.square(X_test - X_test_pred), axis=(1, 2))

plt.figure(figsize=(10, 5))
colors = ['#2ecc71', '#f39c12', '#e74c3c']  # hijau, oranye, merah
for i, label_name in enumerate(kelas_target):
    subset = test_mse[y_test_true == i]
    if len(subset) == 0:
        continue
    sns.histplot(
        subset,
        bins=min(30, max(5, len(subset))),
        color=colors[i % len(colors)],
        label=label_name,
        kde=(len(subset) > 2),
        stat="density",
        alpha=0.5
    )
plt.title('Distribusi Reconstruction Error (MSE) per Kondisi', fontsize=13)
plt.xlabel('MSE', fontsize=11)
plt.ylabel('Density', fontsize=11)
plt.legend(fontsize=10)
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, "reconstruction_error.png"), dpi=150, bbox_inches='tight')
plt.show()

# 5. Silhouette Comparison
plt.figure(figsize=(6, 5))
methods = ['KMeans', 'GMM']
scores = [sil_kmeans, sil_gmm]
colors_bar = ['#3498db', '#e74c3c']

bars = plt.bar(methods, scores, color=colors_bar, width=0.5, edgecolor='k')
plt.axhline(0, color='black', linewidth=0.8)

for bar, score in zip(bars, scores):
    plt.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.005,
        f'{score:.4f}',
        ha='center', va='bottom', fontsize=11, fontweight='bold'
    )

plt.title('Perbandingan Silhouette Score (Internal, Train)', fontsize=12)
plt.ylabel('Silhouette Score', fontsize=11)
plt.ylim(min(0, min(scores) - 0.05), max(scores) + 0.05)
plt.grid(True, alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(os.path.join(BASE_DIR, "silhouette_comparison.png"), dpi=150, bbox_inches='tight')
plt.show()

# ============================================================================
# 11. RINGKASAN FINAL
# ============================================================================
print(f"\n{'='*70}")
print("RINGKASAN HASIL AKHIR")
print(f"{'='*70}")
print(f"  Metode Clustering Terpilih : {chosen_name}")
print(f"  Accuracy (aligned)         : {accuracy:.2f}%")
print(f"  Adjusted Rand Index (ARI)  : {ari:.4f}")
print(f"  Normalized Mutual Info     : {nmi:.4f}")
print(f"  Silhouette Score           : {sil_kmeans:.4f} (KMeans) / {sil_gmm:.4f} (GMM)")
print(f"  Epoch Trained              : {n_epochs_trained}/{EPOCHS}")
print(f"  Best Val Loss              : {best_val_loss:.6f}")
print(f"  Train Sequences            : {X_train.shape[0]}")
print(f"  Test Sequences             : {X_test.shape[0]}")
print(f"  Label Mapping              : {cluster_to_label_map}")
print(f"{'='*70}")
print(f"  Semua plot tersimpan di: {BASE_DIR}")
print(f"{'='*70}")

# ============================================================================
# 12. CATATAN KRITIS UNTUK PENGEMBANGAN SELANJUTNYA
# ============================================================================
print(f"\n{'='*70}")
print("CATATAN KRITIS")
print(f"{'='*70}")
print(f"""
SUBJEK TANPA BASELINE:
  {len(skip_train)} subjek di train dan {len(skip_test)} di test di-skip
  Penyebab: window Waspada rusak 100% atau < {MIN_BASELINE_WINDOWS} window lolos
  Solusi: perbaiki kualitas akuisisi data di subjek tersebut

KERUSAKAN WINDOW DI Feature_ExtractionV3.py:
  Jika > 30%, pertimbangkan turunkan MIN_PCT_VALID_NN dari 0.90 ke 0.80
  Atau turunkan MIN_PEAKS_PER_WINDOW dari 200 ke 150

IMBALANCE KELAS:
  Waspada biasanya 50%, Lelah 25%, Sangat Lelah 25%
  Jika akurasi rendah, pertimbangkan class_weight atau oversampling

PARADIGMA UNSUPERVISED:
  Jika ARI < 0.1, ini BUKAN berarti kode salah
  Ini berarti kelelahan adalah spektrum gradual, bukan cluster alami
  Pertimbangkan supervised learning (LSTM Classifier) untuk hasil lebih baik

DOUBLE SCALING — SUDAH DIHAPUS:
  Data SUDAH Z-score normalized di Feature Extraction v3.2
  RobustScaler di LSTM TIDAK DIPERLUKAN (sudah dihapus di kode ini)
""")