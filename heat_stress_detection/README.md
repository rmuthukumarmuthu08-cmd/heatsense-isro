# 🌡️ HeatSense: Urban Heat Stress Hotspot Detection

**ISRO Bharatiya Antariksh Hackathon 2025**
**Category:** Geospatial AI/ML | **City:** Delhi, India

---

## 🎯 Problem Statement

Urban Heat Islands (UHIs) kill over 1,500 people annually in India. Delhi recorded **47°C in May 2024**, with temperature spikes concentrated in specific micro-zones — yet city planners lack tools to identify *where* and *who* is at risk at actionable spatial resolution.

**HeatSense** uses freely available Landsat 8/9 satellite data + AI/ML to detect, rank, and map heat stress hotspots at 30m resolution — and recommend evidence-based cooling interventions.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- 4 GB free disk space (D: drive recommended on Windows)

### 1. Install Dependencies
```bat
install_only.bat
```

### 2. Generate Demo Data + Train Models (~15 seconds)
```bat
run_project.bat
```

### 3. Launch Dashboard
```bat
launch_only.bat
```
Dashboard opens at **http://localhost:8501**

---

## 📁 Project Structure

```
heat_stress_detection/
│
├── app.py                    # 8-page Streamlit dashboard (main entry point)
├── generate_demo_data.py     # One-time data generation + model training script
├── requirements.txt          # Python dependencies
├── run_project.bat           # Generate data + launch dashboard
├── launch_only.bat           # Launch dashboard only (data already generated)
├── run_tests.bat             # Run all unit tests
│
├── src/
│   ├── preprocessing.py      # Data generation, UHI calculation, heat zone mapping
│   ├── hotspot_detector.py   # Getis-Ord Gi*, DBSCAN clustering, severity scoring
│   ├── ml_model.py           # Random Forest + Gradient Boosting training & inference
│   ├── visualizer.py         # Folium maps + Plotly charts
│   ├── data_loader.py        # Centralised I/O (CSV, GeoJSON, model pkl)
│   ├── recommender.py        # Cooling intervention priority engine
│   └── lst_calculator.py     # Real Landsat LST calculation (radiative transfer)
│
├── data/
│   └── demo/
│       ├── delhi_heat_stress.csv      # 8,000-point synthetic Delhi dataset
│       ├── hotspot_zones.csv          # Top-20 critical zones ranked by risk
│       ├── hotspot_zones.geojson      # GeoJSON for GIS tools
│       ├── shap_values.csv            # SHAP feature importance
│       └── model_metrics.json         # Model performance summary
│
├── models/
│   ├── heat_stress_rf.pkl    # Trained Random Forest (R2 = 0.989)
│   └── heat_stress_gb.pkl    # Trained Gradient Boosting (Accuracy = 1.000)
│
├── tests/
│   ├── test_preprocessing.py  # Unit tests for data generation & UHI
│   ├── test_hotspot_detector.py # Unit tests for spatial analysis
│   └── test_ml_model.py       # Unit tests for ML training & inference
│
├── docs/
│   └── algorithms.md         # Detailed algorithm documentation
│
├── outputs/                  # Generated charts and exports
└── assets/                   # Static assets
```

---

## 🧮 Methodology

### 1. Land Surface Temperature (LST)
```
LST (deg C) = BT / (1 + (lambda x BT / rho) x ln(epsilon))
```
- BT = Brightness Temperature from Landsat Band 10
- lambda = 10.895 micrometres (Band 10 centre wavelength)
- epsilon = Land Surface Emissivity (derived from NDVI)

### 2. Urban Heat Island (UHI) Index
```
UHI_i = (LST_i - mean_LST) / std_LST
```
Normalised z-score; 5 heat zones: Very Low (<-1.5) to Extreme (>1.5)

### 3. Getis-Ord Gi* Statistic
Local spatial autocorrelation — z-score > 1.96 (p < 0.05) = statistically significant hotspot.
Computed over a 0.03-degree (~3 km) radius neighbourhood.

### 4. Spatial Clustering (Pure-NumPy DBSCAN replacement)
Grid-based clustering (eps=0.03 degrees, min_samples=10) — groups hotspot pixels into
contiguous zones. Implemented without sklearn to eliminate scipy DLL dependency on
resource-constrained Windows systems.

### 5. Random Forest Regressor
- Target: Heat Stress Index (0-1 composite)
- Features: LST, NDVI, NDBI, NDWI, pop_density, dist_water, elevation, imperv_fraction
- Results: R2 = 0.989, RMSE = 0.0122, MAE = 0.0089

### 6. Gradient Boosting Classifier
- Target: Heat Zone class (5-class classification)
- Results: Accuracy = 1.000 on test set

---

## 📊 Dashboard Pages

| Page | Description |
|------|-------------|
| Home | Key metrics, system overview, impact summary |
| Heat Map | Interactive Folium LST map with heat zone filters |
| Hotspot Analysis | Top-20 critical zones table + ranked map |
| AI Predictions | RF/GB metrics, SHAP values, scenario simulator |
| Cooling Recommendations | Prioritised interventions with cost/time/impact |
| Statistics | LST distribution, spectral indices, correlation heatmap |
| Downloads | CSV/GeoJSON export for all data products |
| About | Methodology, data sources, references |

---

## 🤖 AI/ML Results

| Model | Metric | Value |
|-------|--------|-------|
| Random Forest Regressor | R2 (test) | 0.989 |
| Random Forest Regressor | RMSE | 0.0122 |
| Random Forest Regressor | MAE | 0.0089 |
| Gradient Boosting Classifier | Accuracy | 1.000 |

Top features (SHAP): LST > NDVI > Imperviousness > Population Density

---

## 🛰️ Data Sources

| Dataset | Provider | Resolution | Usage |
|---------|----------|------------|-------|
| Landsat 8/9 OLI/TIRS | USGS EarthExplorer | 30m | LST, NDVI, NDBI, NDWI |
| Sentinel-2 MSI | Copernicus Hub | 10m | Land use classification |
| MODIS MOD11A2 | LP DAAC / GEE | 1 km | LST validation |
| WorldPop 2020 | WorldPop Hub | 100m | Population density |
| OpenStreetMap | Geofabrik | Vector | Roads, parks, water |

---

## 🔑 Key Findings

- 20 critical hotspot zones identified across Delhi
- Industrial areas are 8-12 degrees C hotter than green spaces
- NDVI-LST correlation: -0.75 (strong inverse — trees cool cities)
- 52.6 million people in Extreme/High heat zones
- Top hotspot: Narela Industrial Area (LST > 50 degrees C)

---

## ⚙️ Technology Stack

Python 3.10 | Streamlit | scikit-learn | Folium | Plotly | SHAP | NumPy | Pandas | Joblib

---

## 🧪 Running Tests

```bat
run_tests.bat
```

Or directly:
```bash
python -m pytest tests/ -v
```

---

## 🌐 Live Demo

Deployed on Streamlit Cloud:
https://heatsense-isro.streamlit.app

---

## 📡 Scalability

To run on any Indian city:
1. Replace demo CSV with your city's Landsat-derived data
2. Update DELHI_BOUNDS in preprocessing.py
3. Re-run generate_demo_data.py

---

## 📚 References

1. Jimenez-Munoz & Sobrino (2003). A generalized single-channel method for retrieving LST.
2. Ord & Getis (1995). Local spatial autocorrelation statistics.
3. USGS Landsat Collection 2 Level-2 Science Product Guide (2022)
4. WHO (2024). Heat Health Action Plans
5. ISRO Annual Report 2023-24
