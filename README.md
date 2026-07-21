# PPG-Based Fatigue Classification System

A complete system for 3-level fatigue classification (Alert / Fatigued / Severely Fatigued) using Photoplethysmogram (PPG) signals and Heart Rate Variability (HRV) analysis.

## 📋 Overview

This project implements an end-to-end pipeline for fatigue detection:
1. **Data Acquisition**: ESP32-based PPG sensor with BLE connectivity
2. **Feature Extraction**: HRV features from PPG signals using NeuroKit2
3. **Classification**: LSTM Autoencoder with unsupervised clustering

## 🗂️ Project Structure

```
/workspace
├── Feature_ExtractionV3.py              # HRV feature extraction pipeline
├── LSTMautoencoder_Farhan Fadhlillah.py # LSTM autoencoder classifier
├── ppg_ble_max86916_final.ino           # ESP32 firmware for PPG acquisition
├── PPG Libraries/                       # Custom MAX86916 sensor libraries
│   ├── MAX86916_Registers.h
│   ├── MAX86916_cm.cpp
│   ├── MAX86916_cm.h
│   ├── cmFilter.cpp
│   └── cmFilter.h
└── README.md                            # This file
```

## 🔧 Components

### 1. Embedded Firmware (`ppg_ble_max86916_final.ino`)
- **Platform**: Arduino (ESP32)
- **Sensor**: MAX86916 PPG sensor
- **Features**:
  - Bluetooth Low Energy (BLE) data transmission
  - WiFi Access Point mode for connectivity
  - Batch sampling (10 samples per notification)
  - Green and blue LED channels

### 2. Feature Extraction (`Feature_ExtractionV3.py`)
- **Version**: 3.2
- **Pipeline**:
  - Auto-polarity check for reflective PPG sensors
  - Bandpass filtering and signal cleaning (NeuroKit2)
  - Peak detection (Charlton/MSPTD method with Elgendi fallback)
  - Physiological validation (40-180 BPM gate)
  - 5-minute sliding windows with 4-minute overlap
  - Z-score normalization per subject (baseline = Alert state)
  - IQR outlier filtering

- **6 Survivor Features**:
  1. `HRV_MeanNN` - Mean NN interval (heart rate baseline)
  2. `HRV_RMSSD` - Root mean square of successive differences (parasympathetic activity)
  3. `HRV_SDNN` - Standard deviation of NN intervals (overall variability)
  4. `HRV_Pnn50` - Percentage of successive NN intervals > 50ms
  5. `Ent_Sample` - Sample entropy (signal complexity)
  6. `HRV_LFHF` - LF/HF ratio (sympathetic-parasympathetic balance)

### 3. LSTM Autoencoder Classifier (`LSTMautoencoder_Farhan Fadhlillah.py`)
- **Approach**: Unsupervised learning with LSTM autoencoder
- **Architecture**:
  - Encoder: LSTM layers compress input to 12-dimensional latent space
  - Decoder: Reconstructs input from latent representation
  - Training: Minimizes MSE reconstruction loss
- **Clustering**: KMeans/Gaussian Mixture Model in latent space
- **Label Alignment**: Hungarian algorithm for cluster-to-label mapping

## 📦 Installation

### Python Dependencies
```bash
pip install tensorflow scikit-learn pandas numpy matplotlib seaborn neurokit2
```

### Arduino Libraries
- Install custom MAX86916 libraries from `PPG Libraries/` folder
- Requires ESP32 board support in Arduino IDE

## 🚀 Usage

### 1. Data Collection
Upload `ppg_ble_max86916_final.ino` to ESP32 device. The device will:
- Create WiFi AP: `PPG_FATIGUE_AP` (password: `12345678`)
- Broadcast PPG data via BLE

### 2. Feature Extraction
```bash
python Feature_ExtractionV3.py
```
Outputs:
- `Train_Features_Filtered.csv`
- `Test_Features_Filtered.csv`

### 3. Classification
```bash
python "LSTMautoencoder_Farhan Fadhlillah.py"
```
Performs:
- LSTM autoencoder training
- Latent space clustering
- Evaluation with confusion matrix and metrics

## 📊 Key Features

- **Automatic polarity correction** for flexible sensor placement
- **Multi-method peak detection** with automatic fallback
- **Physiological sanity checks** at multiple stages
- **Subject-specific normalization** using baseline (Alert) state
- **Unsupervised classification** - no labeled data required for training
- **Robust outlier handling** with IQR filtering

## 📝 Version History

### Feature_ExtractionV3.py v3.2
- Fixed critical bug: Removed incompatible `peak_distance` parameter from Charlton method
- Extended `Ent_Sample` range: (0.0, 3.0) → (0.0, 5.0)
- Extended `HRV_LFHF` max: 10.0 → 20.0
- Reduced `MIN_PEAKS_PER_WINDOW`: 250 → 200
- Added automatic fallback to Elgendi method if Charlton fails
- Enhanced logging and error handling

## 📄 License

This project is for research and educational purposes.

## 👥 Authors

- **Feature Extraction Pipeline**: Version 3.2
- **LSTM Autoencoder**: Farhan Fadhlillah

## 🤝 Contributing

Contributions welcome! Please ensure compatibility with the existing pipeline architecture.
